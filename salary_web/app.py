from contextlib import asynccontextmanager
from pathlib import Path
from shutil import rmtree
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from salary_web.auth import (
    API_KEY_HEADER,
    authenticate_user,
    can_access_department,
    current_user,
    generate_api_key_secret,
    get_or_create_default_department,
    hash_api_key,
    hash_password,
    make_session_token,
    require_api_key_for_department,
    require_admin,
    require_user,
    read_session_user_id,
    SESSION_COOKIE,
    user_department_ids,
)
from salary_web.config import (
    GENERATED_DIR,
    MONTHS,
    REPORT_DESCRIPTIONS,
    REPORT_TYPES,
    UPLOADS_DIR,
    period_storage_dir,
    resolve_service_data_path,
)
from salary_web.calculation_runner import calculate_period
from salary_web.database import get_db, init_db
from salary_web.models import (
    AdditionalPayment,
    ApiKey,
    ApiKeyDepartment,
    Calculation,
    CalculationAdjustment,
    Department,
    ManualEntryStatus,
    Period,
    PeriodStatus,
    User,
    UserDepartment,
)
from salary_web.report_storage import (
    report_completeness,
    save_uploaded_report,
    save_uploaded_reports_batch,
)
from salary_web.report_validation import validate_period_reports
from salary_web.snapshot_presenter import (
    build_final_summary_rows,
    build_snapshot_sections,
    build_summary_rows,
)
from salary_web.snapshot_editor import (
    append_additional_payment,
    append_adjustment,
    append_key_client_profit,
    generate_pdf_for_calculation,
    load_snapshot,
    remove_additional_payment,
    remove_adjustment,
    remove_key_client_profit,
    refresh_calculated_values,
    save_snapshot_text,
    update_additional_payment,
    update_adjustment,
    update_key_client_profit,
    update_debt_large_item_comment,
)
from salary_web.ui_helpers import report_type_label, status_label


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Salary Web", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="salary_web/static"), name="static")
templates = Jinja2Templates(directory="salary_web/templates")
templates.env.filters["status_label"] = status_label
templates.env.filters["report_type_label"] = report_type_label


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers=exc.headers,
        media_type="application/json; charset=utf-8",
    )


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    public_prefixes = ("/login", "/static", "/health", "/api/health", "/api/commands", "/openapi.json")
    if request.url.path == "/" or request.url.path.startswith(public_prefixes):
        return await call_next(request)
    if request.url.path.startswith("/api/departments/"):
        return await call_next(request)
    if not read_session_user_id(request):
        if request.url.path.startswith("/api"):
            return JSONResponse({"detail": "Требуется авторизация"}, status_code=401)
        return RedirectResponse(url="/login", status_code=303)
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health")
def api_health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/commands")
def api_commands() -> dict[str, list[dict[str, object]]]:
    commands = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = sorted(getattr(route, "methods", []) or [])
        if not path.startswith("/api/") or path == "/api/commands":
            continue
        commands.append({
            "path": path,
            "methods": [method for method in methods if method not in {"HEAD", "OPTIONS"}],
            "name": getattr(route, "name", ""),
        })
    return {"commands": commands}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return RedirectResponse(url="/periods", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request, "error": ""},
    )


@app.post("/login")
def login_form(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, username, password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "error": "Неверный логин или пароль"},
            status_code=401,
        )
    response = RedirectResponse(url="/periods", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(user.id),
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/logout")
def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> RedirectResponse:
    if not read_session_user_id(request):
        return RedirectResponse(url="/login", status_code=303)
    return RedirectResponse(url="/periods", status_code=303)


@app.get("/periods", response_class=HTMLResponse)
def periods_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    periods = periods_query_for_user(db, user).order_by(Period.year.desc(), Period.month.desc()).all()
    departments = departments_for_user(db, user)
    default_department_id = default_department_for_period_form(db, user, departments)
    return templates.TemplateResponse(
        request,
        "periods.html",
        template_context(request, db, {
            "periods": periods,
            "months": MONTHS,
            "departments": departments,
            "default_department_id": default_department_id,
        }),
    )


@app.get("/api-docs", response_class=HTMLResponse)
def api_docs_page(request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    return templates.TemplateResponse(
        request,
        "api_docs.html",
        template_context(request, db, {
            "api_base_url": str(request.base_url).rstrip("/"),
            "report_types": REPORT_TYPES,
        }),
    )


@app.post("/periods")
def create_period_form(
    request: Request,
    year: int = Form(...),
    month: int = Form(...),
    department_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    period = create_period(db, year, month, user, department_id)
    return RedirectResponse(url=period_url(period), status_code=303)


@app.post("/periods/{period_id}/delete")
def delete_period_form(
    period_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    period = get_period_or_404(db, period_id)
    delete_period(db, period)
    db.commit()
    return RedirectResponse(url="/periods", status_code=303)


@app.get("/periods/{year}/{month}", response_class=HTMLResponse)
def period_page(year: int, month: int, request: Request, db: Session = Depends(get_db)):
    period = get_period_by_date_or_404(db, year, month)
    ensure_period_access(request, db, period)
    completeness = report_completeness(period)
    return templates.TemplateResponse(
        request,
        "period_detail.html",
        template_context(request, db, {
            "period": period,
            "report_types": REPORT_TYPES,
            "report_descriptions": REPORT_DESCRIPTIONS,
            "completeness": completeness,
            "reports_by_type": reports_by_type(period),
        }),
    )


@app.get("/periods/{period_id}", response_class=HTMLResponse)
def legacy_period_page(period_id: int, request: Request, db: Session = Depends(get_db)):
    period = get_period_or_404(db, period_id)
    ensure_period_access(request, db, period)
    return RedirectResponse(url=period_url(period), status_code=303)


@app.post("/periods/{year}/{month}/reports")
def upload_report_form(
    year: int,
    month: int,
    request: Request,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    period = get_period_by_date_or_404(db, year, month)
    ensure_period_access(request, db, period)
    try:
        saved_reports = save_uploaded_reports_batch(db, period, files)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if saved_reports:
        remove_period_calculations(db, period)
    if report_completeness(period)["complete"]:
        validate_period_reports(db, period)
    db.commit()
    return RedirectResponse(url=period_url(period), status_code=303)


@app.post("/periods/{year}/{month}/validate")
def validate_period_form(year: int, month: int, request: Request, db: Session = Depends(get_db)):
    period = get_period_by_date_or_404(db, year, month)
    ensure_period_access(request, db, period)
    validate_period_reports(db, period)
    db.commit()
    return RedirectResponse(url=period_url(period), status_code=303)


@app.post("/periods/{year}/{month}/calculate")
def calculate_period_form(year: int, month: int, request: Request, db: Session = Depends(get_db)):
    period = get_period_by_date_or_404(db, year, month)
    ensure_period_access(request, db, period)
    try:
        calculate_period(db, period)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return RedirectResponse(url=period_url(period), status_code=303)


@app.post("/periods/{year}/{month}/pdf")
def generate_period_pdfs_form(year: int, month: int, request: Request, db: Session = Depends(get_db)):
    period = get_period_by_date_or_404(db, year, month)
    ensure_period_access(request, db, period)
    try:
        calculations = calculate_period(db, period)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    for calculation in calculations:
        if calculation.snapshot_json:
            generate_pdf_for_calculation(db, calculation)
    db.commit()
    return RedirectResponse(url=f"{period_url(period)}#calculations", status_code=303)


@app.post("/periods/{year}/{month}/calculations/delete")
def delete_period_calculations_form(year: int, month: int, request: Request, db: Session = Depends(get_db)):
    period = get_period_by_date_or_404(db, year, month)
    ensure_period_access(request, db, period)
    remove_period_calculations(db, period)
    db.commit()
    return RedirectResponse(url=f"{period_url(period)}#calculations", status_code=303)


@app.get("/calculations/{calculation_id}", response_class=HTMLResponse)
def calculation_page(
    calculation_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    calculation = get_calculation_or_404(db, calculation_id)
    ensure_period_access(request, db, calculation.period)
    if calculation.snapshot_json and refresh_calculated_values(calculation):
        db.commit()
    snapshot = load_snapshot(calculation) if calculation.snapshot_json else {}
    return templates.TemplateResponse(
        request,
        "calculation_detail.html",
        template_context(request, db, {
            "calculation": calculation,
            "snapshot": snapshot,
            "final_summary_rows": build_final_summary_rows(snapshot),
            "summary_rows": build_summary_rows(snapshot),
            "sections": build_snapshot_sections(snapshot),
            "snapshot_text": calculation.snapshot_json or "",
            "months": MONTHS,
        }),
    )


@app.post("/calculations/{calculation_id}/snapshot")
def update_calculation_snapshot(
    calculation_id: int,
    request: Request,
    snapshot_json: str = Form(...),
    db: Session = Depends(get_db),
):
    calculation = get_calculation_or_404(db, calculation_id)
    ensure_period_access(request, db, calculation.period)
    try:
        save_snapshot_text(calculation, snapshot_json)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return RedirectResponse(url=f"/calculations/{calculation.id}", status_code=303)


@app.post("/calculations/{calculation_id}/additional-payments")
def add_calculation_payment(
    calculation_id: int,
    request: Request,
    title: str = Form(...),
    amount: float = Form(...),
    comment: str = Form(""),
    return_to: str = Form(""),
    db: Session = Depends(get_db),
):
    calculation = get_calculation_or_404(db, calculation_id)
    ensure_period_access(request, db, calculation.period)
    payment = AdditionalPayment(
        period_id=calculation.period_id,
        employee_id=calculation.employee_id,
        calculation_id=calculation.id,
        title=title,
        amount=amount,
        comment=comment,
        status=ManualEntryStatus.APPROVED.value,
    )
    db.add(payment)
    append_additional_payment(calculation, payment_description(title, comment), amount)
    db.commit()
    return RedirectResponse(
        url=with_saved_notice(return_to or f"/calculations/{calculation.id}#additional-payment-form"),
        status_code=303,
    )


@app.post("/calculations/{calculation_id}/additional-payments/{payment_id}/update")
def update_calculation_payment(
    calculation_id: int,
    payment_id: int,
    request: Request,
    title: str = Form(...),
    amount: float = Form(...),
    comment: str = Form(""),
    db: Session = Depends(get_db),
):
    calculation = get_calculation_or_404(db, calculation_id)
    ensure_period_access(request, db, calculation.period)
    payment = get_payment_or_404(db, calculation, payment_id)
    old_description = payment_description(payment.title, payment.comment)
    old_amount = payment.amount
    payment.title = title
    payment.amount = amount
    payment.comment = comment
    payment.status = ManualEntryStatus.APPROVED.value
    update_additional_payment(
        calculation,
        old_description,
        old_amount,
        payment_description(title, comment),
        amount,
    )
    db.commit()
    return RedirectResponse(
        url=f"/calculations/{calculation.id}#manual-entries",
        status_code=303,
    )


@app.post("/calculations/{calculation_id}/debt-large-items/{item_index}/comment")
def update_debt_large_item_comment_form(
    calculation_id: int,
    item_index: int,
    request: Request,
    comment: str = Form(""),
    db: Session = Depends(get_db),
):
    calculation = get_calculation_or_404(db, calculation_id)
    ensure_period_access(request, db, calculation.period)
    try:
        update_debt_large_item_comment(calculation, item_index, comment)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    db.commit()
    return RedirectResponse(
        url=with_saved_notice(f"/calculations/{calculation.id}#debt-large-items"),
        status_code=303,
    )


@app.post("/calculations/{calculation_id}/additional-payments/{payment_id}/delete")
def delete_calculation_payment(
    calculation_id: int,
    payment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    calculation = get_calculation_or_404(db, calculation_id)
    ensure_period_access(request, db, calculation.period)
    payment = get_payment_or_404(db, calculation, payment_id)
    remove_additional_payment(
        calculation,
        payment_description(payment.title, payment.comment),
        payment.amount,
    )
    db.delete(payment)
    db.commit()
    return RedirectResponse(
        url=f"/calculations/{calculation.id}#manual-entries",
        status_code=303,
    )


@app.post("/calculations/{calculation_id}/adjustments")
def add_calculation_adjustment(
    calculation_id: int,
    request: Request,
    section_code: str = Form(...),
    adjustment_type: str = Form(...),
    amount: float = Form(0),
    comment: str = Form(""),
    client: str = Form(""),
    profit: float | None = Form(None),
    return_to: str = Form(""),
    db: Session = Depends(get_db),
):
    calculation = get_calculation_or_404(db, calculation_id)
    ensure_period_access(request, db, calculation.period)
    is_key_client = section_code == "key_clients_profit" and load_snapshot(calculation).get("report_type") == "chief"
    if is_key_client:
        client = client.strip()
        if not client:
            raise HTTPException(status_code=400, detail="Укажите наименование клиента")
        if profit is None:
            raise HTTPException(status_code=400, detail="Укажите размер прибыли")
        adjustment_type = "key_client_profit"
        amount = profit
        comment = client

    adjustment = CalculationAdjustment(
        period_id=calculation.period_id,
        employee_id=calculation.employee_id,
        calculation_id=calculation.id,
        section_code=section_code,
        field_code=client if is_key_client else None,
        adjustment_type=adjustment_type,
        amount=amount,
        comment=comment,
        status=ManualEntryStatus.APPROVED.value,
    )
    db.add(adjustment)
    if is_key_client:
        append_key_client_profit(calculation, client, amount)
    else:
        append_adjustment(calculation, section_code, adjustment_type, amount, comment)
    db.commit()
    return RedirectResponse(
        url=with_saved_notice(return_to or f"/calculations/{calculation.id}#section-{section_code}"),
        status_code=303,
    )


@app.post("/calculations/{calculation_id}/adjustments/{adjustment_id}/update")
def update_calculation_adjustment(
    calculation_id: int,
    adjustment_id: int,
    request: Request,
    amount: float = Form(0),
    comment: str = Form(""),
    db: Session = Depends(get_db),
):
    calculation = get_calculation_or_404(db, calculation_id)
    ensure_period_access(request, db, calculation.period)
    adjustment = get_adjustment_or_404(db, calculation, adjustment_id)
    old_section_code = adjustment.section_code
    old_adjustment_type = adjustment.adjustment_type
    old_amount = adjustment.amount
    old_comment = adjustment.comment or ""
    if adjustment.section_code == "key_clients_profit":
        old_client = adjustment.field_code or old_comment
        new_client = comment.strip()
        if not new_client:
            raise HTTPException(status_code=400, detail="Укажите наименование клиента")
        if adjustment.adjustment_type == "key_client_profit":
            update_key_client_profit(calculation, old_client, old_amount, new_client, amount)
        else:
            remove_adjustment(
                calculation,
                old_section_code,
                old_adjustment_type,
                old_amount,
                old_comment,
            )
            append_key_client_profit(calculation, new_client, amount)
        adjustment.field_code = new_client
        adjustment.adjustment_type = "key_client_profit"
        adjustment.amount = amount
        adjustment.comment = new_client
        adjustment.status = ManualEntryStatus.APPROVED.value
        db.commit()
        return RedirectResponse(
            url=f"/calculations/{calculation.id}#section-key_clients_profit",
            status_code=303,
        )
    adjustment.amount = amount
    adjustment.comment = comment
    adjustment.status = ManualEntryStatus.APPROVED.value
    update_adjustment(
        calculation,
        old_section_code,
        old_adjustment_type,
        old_amount,
        old_comment,
        adjustment.section_code,
        adjustment.adjustment_type,
        amount,
        comment,
    )
    db.commit()
    return RedirectResponse(
        url=f"/calculations/{calculation.id}#manual-entries",
        status_code=303,
    )


@app.post("/calculations/{calculation_id}/adjustments/{adjustment_id}/delete")
def delete_calculation_adjustment(
    calculation_id: int,
    adjustment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    calculation = get_calculation_or_404(db, calculation_id)
    ensure_period_access(request, db, calculation.period)
    adjustment = get_adjustment_or_404(db, calculation, adjustment_id)
    if adjustment.section_code == "key_clients_profit" and adjustment.adjustment_type == "key_client_profit":
        remove_key_client_profit(
            calculation,
            adjustment.field_code or adjustment.comment or "",
            adjustment.amount,
        )
    else:
        remove_adjustment(
            calculation,
            adjustment.section_code,
            adjustment.adjustment_type,
            adjustment.amount,
            adjustment.comment or "",
        )
    db.delete(adjustment)
    db.commit()
    return RedirectResponse(
        url=f"/calculations/{calculation.id}#manual-entries",
        status_code=303,
    )


@app.post("/calculations/{calculation_id}/pdf")
def generate_calculation_pdf(
    calculation_id: int,
    request: Request,
    return_to: str = Form(""),
    db: Session = Depends(get_db),
):
    calculation = get_calculation_or_404(db, calculation_id)
    ensure_period_access(request, db, calculation.period)
    try:
        generate_pdf_for_calculation(db, calculation)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    redirect_url = return_to or f"/calculations/{calculation.id}"
    return RedirectResponse(url=redirect_url, status_code=303)


@app.get("/calculations/{calculation_id}/pdf/download")
def download_calculation_pdf(calculation_id: int, request: Request, db: Session = Depends(get_db)):
    calculation = get_calculation_or_404(db, calculation_id)
    ensure_period_access(request, db, calculation.period)
    return calculation_pdf_response(calculation)


def calculation_pdf_response(calculation: Calculation) -> FileResponse:
    if not calculation.pdf_path:
        raise HTTPException(status_code=404, detail="PDF еще не сформирован")
    pdf_path = resolve_service_data_path(calculation.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Файл PDF не найден")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name,
    )


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    users = db.query(User).order_by(User.username).all()
    departments = db.query(Department).order_by(Department.name).all()
    api_keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "admin.html",
        template_context(request, db, {
            "users": users,
            "departments": departments,
            "api_keys": api_keys,
            "generated_api_key": "",
            "error": "",
        }),
    )


@app.post("/admin/departments")
def create_department_form(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    department = Department(code=code.strip(), name=name.strip(), is_active=1)
    db.add(department)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Отдел с таким кодом уже существует")
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/users")
def create_user_form(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
    is_admin: int = Form(0),
    department_ids: list[int] = Form([]),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    user = User(
        username=username.strip(),
        password_hash=hash_password(password),
        full_name=full_name.strip() or None,
        is_admin=1 if is_admin else 0,
        is_active=1,
    )
    db.add(user)
    try:
        db.flush()
        _set_user_departments(db, user, department_ids)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Пользователь с таким логином уже существует")
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/users/{user_id}/password")
def change_user_password_form(
    user_id: int,
    request: Request,
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.password_hash = hash_password(password)
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/users/{user_id}/profile")
def update_user_profile_form(
    user_id: int,
    request: Request,
    username: str = Form(...),
    full_name: str = Form(""),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.username = username.strip()
    user.full_name = full_name.strip() or None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Пользователь с таким логином уже существует")
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/users/{user_id}/departments")
def update_user_departments_form(
    user_id: int,
    request: Request,
    department_ids: list[int] = Form([]),
    is_admin: int = Form(0),
    is_active: int = Form(0),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.id == admin.id and (not is_admin or not is_active):
        raise HTTPException(status_code=400, detail="Нельзя снять права администратора или отключить самого себя")
    user.is_admin = 1 if is_admin else 0
    user.is_active = 1 if is_active else 0
    _set_user_departments(db, user, department_ids)
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/users/{user_id}/delete")
def delete_user_form(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить самого себя")
    db.delete(user)
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/api-keys")
def create_api_key_form(
    request: Request,
    name: str = Form(...),
    department_ids: list[int] = Form([]),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    secret = generate_api_key_secret()
    api_key = ApiKey(
        name=name.strip(),
        key_hash=hash_api_key(secret),
        key_secret=secret,
        is_active=1,
    )
    db.add(api_key)
    db.flush()
    _set_api_key_departments(db, api_key, department_ids)
    db.commit()
    db.refresh(api_key)

    users = db.query(User).order_by(User.username).all()
    departments = db.query(Department).order_by(Department.name).all()
    api_keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "admin.html",
        template_context(request, db, {
            "users": users,
            "departments": departments,
            "api_keys": api_keys,
            "generated_api_key": secret,
            "error": "",
        }),
    )


@app.post("/admin/api-keys/{api_key_id}/rights")
def update_api_key_form(
    api_key_id: int,
    request: Request,
    name: str = Form(...),
    department_ids: list[int] = Form([]),
    is_active: int = Form(0),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    api_key = db.get(ApiKey, api_key_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail="API-ключ не найден")
    api_key.name = name.strip()
    api_key.is_active = 1 if is_active else 0
    _set_api_key_departments(db, api_key, department_ids)
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/api-keys/{api_key_id}/delete")
def delete_api_key_form(
    api_key_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    api_key = db.get(ApiKey, api_key_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail="API-ключ не найден")
    db.delete(api_key)
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/api/periods")
def create_period_api(
    year: int = Form(...),
    month: int = Form(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    period = create_period(db, year, month)
    return serialize_period(period)


@app.get("/api/periods/{period_id}")
def period_api(period_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    period = get_period_or_404(db, period_id)
    return serialize_period(period)


@app.get("/api/periods/{period_id}/validation")
def validate_period_api(period_id: int, db: Session = Depends(get_db)):
    period = get_period_or_404(db, period_id)
    return report_completeness(period)


@app.post("/api/periods/{period_id}/validate")
def validate_period_reports_api(period_id: int, db: Session = Depends(get_db)):
    period = get_period_or_404(db, period_id)
    result = validate_period_reports(db, period)
    db.commit()
    return result


@app.post("/api/periods/{period_id}/reports/{report_type}")
def upload_report_api(
    period_id: int,
    report_type: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    period = get_period_or_404(db, period_id)
    return upload_report_to_period_api(db, period, report_type, file)


def upload_report_to_period_api(
    db: Session,
    period: Period,
    report_type: str,
    file: UploadFile,
) -> dict[str, object]:
    try:
        report = save_uploaded_report(db, period, report_type, file)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    remove_period_calculations(db, period)
    if report_completeness(period)["complete"]:
        validate_period_reports(db, period)
    db.commit()
    return {
        "id": report.id,
        "period_id": period.id,
        "department_code": period.department.code if period.department else None,
        "report_type": report.report_type,
        "filename": report.original_filename,
        "file_hash": report.file_hash,
        "period_status": period.status,
    }


@app.post("/api/periods/{period_id}/calculate")
def calculate_period_api(
    period_id: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    period = get_period_or_404(db, period_id)
    return calculate_period_response(db, period)


def calculate_period_response(db: Session, period: Period) -> dict[str, object]:
    try:
        calculations = calculate_period(db, period)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return {
        "period_id": period.id,
        "department_code": period.department.code if period.department else None,
        "status": period.status,
        "calculations_created": len(calculations),
    }


@app.post("/api/periods/{period_id}/pdf")
def generate_period_pdfs_api(
    period_id: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    period = get_period_or_404(db, period_id)
    return generate_period_pdfs_response(db, period)


@app.post("/api/periods/{year}/{month}")
def create_period_by_date_api(
    year: int,
    month: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    period = create_period(db, year, month)
    return serialize_period(period)


@app.get("/api/periods/{year}/{month}")
def period_by_date_api(year: int, month: int, db: Session = Depends(get_db)) -> dict[str, object]:
    period = get_period_by_date_or_404(db, year, month)
    return serialize_period(period)


@app.get("/api/periods/{year}/{month}/validation")
def validate_period_by_date_api(year: int, month: int, db: Session = Depends(get_db)):
    period = get_period_by_date_or_404(db, year, month)
    return report_completeness(period)


@app.post("/api/periods/{year}/{month}/validate")
def validate_period_reports_by_date_api(year: int, month: int, db: Session = Depends(get_db)):
    period = get_period_by_date_or_404(db, year, month)
    result = validate_period_reports(db, period)
    db.commit()
    return result


@app.post("/api/periods/{year}/{month}/reports/{report_type}")
def upload_report_by_date_api(
    year: int,
    month: int,
    report_type: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    period = get_period_by_date_or_404(db, year, month)
    return upload_report_to_period_api(db, period, report_type, file)


@app.post("/api/periods/{year}/{month}/calculate")
def calculate_period_by_date_api(
    year: int,
    month: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    period = get_period_by_date_or_404(db, year, month)
    return calculate_period_response(db, period)


@app.post("/api/periods/{year}/{month}/pdf")
def generate_period_pdfs_by_date_api(
    year: int,
    month: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    period = get_period_by_date_or_404(db, year, month)
    return generate_period_pdfs_response(db, period)


@app.get("/api/periods/{year}/{month}/calculations")
def period_calculations_by_date_api(
    year: int,
    month: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    period = get_period_by_date_or_404(db, year, month)
    return {
        "period_id": period.id,
        "year": period.year,
        "month": period.month,
        "calculations": [
            serialize_calculation_summary(period, calculation)
            for calculation in period.calculations
        ],
    }


@app.get("/api/periods/{year}/{month}/calculations/{calculation_id}")
def period_calculation_by_date_api(
    year: int,
    month: int,
    calculation_id: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    period = get_period_by_date_or_404(db, year, month)
    calculation = get_period_calculation_or_404(db, period, calculation_id)
    return serialize_calculation(calculation)


@app.post("/api/periods/{year}/{month}/calculations/{calculation_id}/pdf")
def generate_period_calculation_pdf_by_date_api(
    year: int,
    month: int,
    calculation_id: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    period = get_period_by_date_or_404(db, year, month)
    calculation = get_period_calculation_or_404(db, period, calculation_id)
    try:
        pdf_path = generate_pdf_for_calculation(db, calculation)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return serialize_pdf_result(period, calculation, pdf_path)


@app.get("/api/periods/{year}/{month}/calculations/{calculation_id}/pdf/download")
def download_period_calculation_pdf_by_date_api(
    year: int,
    month: int,
    calculation_id: int,
    db: Session = Depends(get_db),
):
    period = get_period_by_date_or_404(db, year, month)
    calculation = get_period_calculation_or_404(db, period, calculation_id)
    return calculation_pdf_response(calculation)


@app.post("/api/departments/{department_code}/periods/{year}/{month}")
def create_department_period_api(
    department_code: str,
    year: int,
    month: int,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    department = get_department_by_code_or_404(db, department_code)
    require_api_key_for_department(request, db, department)
    period = create_period(db, year, month, department_id=department.id)
    return serialize_period(period)


@app.get("/api/departments/{department_code}/periods/{year}/{month}")
def department_period_api(
    department_code: str,
    year: int,
    month: int,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    department = get_department_by_code_or_404(db, department_code)
    require_api_key_for_department(request, db, department)
    period = get_period_by_department_date_or_404(db, department, year, month)
    return serialize_period(period)


@app.get("/api/departments/{department_code}/periods/{year}/{month}/validation")
def validate_department_period_api(
    department_code: str,
    year: int,
    month: int,
    request: Request,
    db: Session = Depends(get_db),
):
    department = get_department_by_code_or_404(db, department_code)
    require_api_key_for_department(request, db, department)
    period = get_period_by_department_date_or_404(db, department, year, month)
    return report_completeness(period)


@app.post("/api/departments/{department_code}/periods/{year}/{month}/validate")
def validate_department_period_reports_api(
    department_code: str,
    year: int,
    month: int,
    request: Request,
    db: Session = Depends(get_db),
):
    department = get_department_by_code_or_404(db, department_code)
    require_api_key_for_department(request, db, department)
    period = get_period_by_department_date_or_404(db, department, year, month)
    result = validate_period_reports(db, period)
    db.commit()
    return result


@app.post("/api/departments/{department_code}/periods/{year}/{month}/reports/{report_type}")
def upload_department_report_api(
    department_code: str,
    year: int,
    month: int,
    report_type: str,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    department = get_department_by_code_or_404(db, department_code)
    require_api_key_for_department(request, db, department)
    period = create_period(db, year, month, department_id=department.id)
    return upload_report_to_period_api(db, period, report_type, file)


@app.post("/api/departments/{department_code}/periods/{year}/{month}/calculate")
def calculate_department_period_api(
    department_code: str,
    year: int,
    month: int,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    department = get_department_by_code_or_404(db, department_code)
    require_api_key_for_department(request, db, department)
    period = get_period_by_department_date_or_404(db, department, year, month)
    return calculate_period_response(db, period)


@app.post("/api/departments/{department_code}/periods/{year}/{month}/pdf")
def generate_department_period_pdfs_api(
    department_code: str,
    year: int,
    month: int,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    department = get_department_by_code_or_404(db, department_code)
    require_api_key_for_department(request, db, department)
    period = get_period_by_department_date_or_404(db, department, year, month)
    return generate_period_pdfs_response(db, period, department_code=department.code)


@app.get("/api/departments/{department_code}/periods/{year}/{month}/calculations")
def department_period_calculations_api(
    department_code: str,
    year: int,
    month: int,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    department = get_department_by_code_or_404(db, department_code)
    require_api_key_for_department(request, db, department)
    period = get_period_by_department_date_or_404(db, department, year, month)
    return {
        "period_id": period.id,
        "department_code": department.code,
        "year": period.year,
        "month": period.month,
        "calculations": [
            serialize_calculation_summary(period, calculation, department_code=department.code)
            for calculation in period.calculations
        ],
    }


@app.get("/api/departments/{department_code}/periods/{year}/{month}/calculations/{calculation_id}")
def department_period_calculation_api(
    department_code: str,
    year: int,
    month: int,
    calculation_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    department = get_department_by_code_or_404(db, department_code)
    require_api_key_for_department(request, db, department)
    period = get_period_by_department_date_or_404(db, department, year, month)
    calculation = get_period_calculation_or_404(db, period, calculation_id)
    return serialize_calculation(calculation, department_code=department.code)


@app.post("/api/departments/{department_code}/periods/{year}/{month}/calculations/{calculation_id}/pdf")
def generate_department_calculation_pdf_api(
    department_code: str,
    year: int,
    month: int,
    calculation_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    department = get_department_by_code_or_404(db, department_code)
    require_api_key_for_department(request, db, department)
    period = get_period_by_department_date_or_404(db, department, year, month)
    calculation = get_period_calculation_or_404(db, period, calculation_id)
    try:
        pdf_path = generate_pdf_for_calculation(db, calculation)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return serialize_pdf_result(period, calculation, pdf_path, department_code=department.code)


@app.get("/api/departments/{department_code}/periods/{year}/{month}/calculations/{calculation_id}/pdf/download")
def download_department_calculation_pdf_api(
    department_code: str,
    year: int,
    month: int,
    calculation_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    department = get_department_by_code_or_404(db, department_code)
    require_api_key_for_department(request, db, department)
    period = get_period_by_department_date_or_404(db, department, year, month)
    calculation = get_period_calculation_or_404(db, period, calculation_id)
    return calculation_pdf_response(calculation)


def generate_period_pdfs_response(
    db: Session,
    period: Period,
    department_code: str | None = None,
) -> dict[str, object]:
    try:
        calculations = calculate_period(db, period)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    pdfs = []
    for calculation in calculations:
        if not calculation.snapshot_json:
            continue
        pdf_path = generate_pdf_for_calculation(db, calculation)
        pdfs.append(serialize_pdf_result(period, calculation, pdf_path, department_code))
    db.commit()
    result = {
        "period_id": period.id,
        "department_code": department_code or (period.department.code if period.department else None),
        "year": period.year,
        "month": period.month,
        "pdfs_created": len(pdfs),
        "pdfs": pdfs,
    }
    if department_code:
        result["department_code"] = department_code
    return result


@app.get("/api/calculations/{calculation_id}")
def calculation_api(calculation_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    calculation = get_calculation_or_404(db, calculation_id)
    return serialize_calculation(calculation)


@app.post("/api/calculations/{calculation_id}/pdf")
def generate_calculation_pdf_api(
    calculation_id: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    calculation = get_calculation_or_404(db, calculation_id)
    try:
        pdf_path = generate_pdf_for_calculation(db, calculation)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return serialize_pdf_result(calculation.period, calculation, pdf_path)


@app.get("/api/calculations/{calculation_id}/pdf/download")
def download_calculation_pdf_api(calculation_id: int, db: Session = Depends(get_db)):
    calculation = get_calculation_or_404(db, calculation_id)
    return calculation_pdf_response(calculation)


def create_period(
    db: Session,
    year: int,
    month: int,
    user: User | None = None,
    department_id: int | None = None,
) -> Period:
    if not 1 <= month <= 12:
        raise HTTPException(status_code=400, detail="Месяц должен быть от 1 до 12")

    if department_id is None:
        department = get_or_create_default_department(db)
    else:
        department = db.get(Department, department_id)
        if department is None:
            raise HTTPException(status_code=404, detail="Отдел не найден")
    if user is not None and not can_access_department(user, department.id):
        raise HTTPException(status_code=403, detail="Нет доступа к отделу")

    period = Period(year=year, month=month, department_id=department.id)
    db.add(period)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        period = (
            db.query(Period)
            .filter(
                Period.department_id == department.id,
                Period.year == year,
                Period.month == month,
            )
            .one()
        )
    db.refresh(period)
    return period


def get_period_or_404(db: Session, period_id: int) -> Period:
    period = db.get(Period, period_id)
    if period is None:
        raise HTTPException(status_code=404, detail="Период не найден")
    return period


def get_period_by_date_or_404(db: Session, year: int, month: int) -> Period:
    period = (
        db.query(Period)
        .filter(Period.year == year, Period.month == month)
        .order_by(Period.id)
        .first()
    )
    if period is None:
        raise HTTPException(status_code=404, detail="Период не найден")
    return period


def get_department_by_code_or_404(db: Session, department_code: str) -> Department:
    department = (
        db.query(Department)
        .filter(Department.code == department_code, Department.is_active == 1)
        .one_or_none()
    )
    if department is None:
        raise HTTPException(status_code=404, detail="Подразделение не найдено")
    return department


def get_period_by_department_date_or_404(
    db: Session,
    department: Department,
    year: int,
    month: int,
) -> Period:
    period = (
        db.query(Period)
        .filter(
            Period.department_id == department.id,
            Period.year == year,
            Period.month == month,
        )
        .one_or_none()
    )
    if period is None:
        raise HTTPException(status_code=404, detail="Период не найден")
    return period


def period_url(period: Period) -> str:
    return f"/periods/{period.year}/{period.month:02d}"


def get_calculation_or_404(db: Session, calculation_id: int) -> Calculation:
    calculation = db.get(Calculation, calculation_id)
    if calculation is None:
        raise HTTPException(status_code=404, detail="Расчет не найден")
    return calculation


def get_period_calculation_or_404(
    db: Session,
    period: Period,
    calculation_id: int,
) -> Calculation:
    calculation = get_calculation_or_404(db, calculation_id)
    if calculation.period_id != period.id:
        raise HTTPException(status_code=404, detail="Расчет не найден в указанном периоде")
    return calculation


def ensure_period_access(request: Request, db: Session, period: Period) -> User:
    user = require_user(request, db)
    if not can_access_department(user, period.department_id):
        raise HTTPException(status_code=403, detail="Нет доступа к периоду")
    return user


def periods_query_for_user(db: Session, user: User):
    query = db.query(Period)
    if user.is_admin:
        return query
    department_ids = user_department_ids(user)
    if not department_ids:
        return query.filter(Period.id == -1)
    return query.filter(Period.department_id.in_(department_ids))


def departments_for_user(db: Session, user: User) -> list[Department]:
    if user.is_admin:
        return db.query(Department).filter(Department.is_active == 1).order_by(Department.name).all()
    ids = user_department_ids(user)
    if not ids:
        return []
    return (
        db.query(Department)
        .filter(Department.id.in_(ids), Department.is_active == 1)
        .order_by(Department.name)
        .all()
    )


def default_department_for_period_form(
    db: Session,
    user: User,
    departments: list[Department],
) -> int | None:
    if not departments:
        return None

    available_department_ids = {department.id for department in departments}
    last_period_with_calculations = (
        periods_query_for_user(db, user)
        .join(Calculation, Calculation.period_id == Period.id)
        .order_by(Period.year.desc(), Period.month.desc(), Period.updated_at.desc())
        .first()
    )
    if (
        last_period_with_calculations is not None
        and last_period_with_calculations.department_id in available_department_ids
    ):
        return last_period_with_calculations.department_id
    return departments[0].id


def template_context(request: Request, db: Session, context: dict | None = None) -> dict:
    result = {"request": request, "current_user": current_user(request, db)}
    if context:
        result.update(context)
    return result


def _set_user_departments(db: Session, user: User, department_ids: list[int]) -> None:
    db.query(UserDepartment).filter(UserDepartment.user_id == user.id).delete()
    for department_id in department_ids:
        if db.get(Department, department_id) is not None:
            db.add(UserDepartment(user_id=user.id, department_id=department_id))


def _set_api_key_departments(db: Session, api_key: ApiKey, department_ids: list[int]) -> None:
    db.query(ApiKeyDepartment).filter(ApiKeyDepartment.api_key_id == api_key.id).delete()
    for department_id in department_ids:
        if db.get(Department, department_id) is not None:
            db.add(ApiKeyDepartment(api_key_id=api_key.id, department_id=department_id))


def get_payment_or_404(
    db: Session,
    calculation: Calculation,
    payment_id: int,
) -> AdditionalPayment:
    payment = db.get(AdditionalPayment, payment_id)
    if payment is None or payment.calculation_id != calculation.id:
        raise HTTPException(status_code=404, detail="Дополнительная выплата не найдена")
    return payment


def get_adjustment_or_404(
    db: Session,
    calculation: Calculation,
    adjustment_id: int,
) -> CalculationAdjustment:
    adjustment = db.get(CalculationAdjustment, adjustment_id)
    if adjustment is None or adjustment.calculation_id != calculation.id:
        raise HTTPException(status_code=404, detail="Корректировка не найдена")
    return adjustment


def payment_description(title: str, comment: str | None) -> str:
    return title if not comment else f"{title}. {comment}"


def serialize_pdf_result(
    period: Period,
    calculation: Calculation,
    pdf_path: Path,
    department_code: str | None = None,
) -> dict[str, object]:
    if department_code:
        api_base = f"/api/departments/{department_code}/periods/{period.year}/{period.month}"
    else:
        api_base = f"/api/periods/{period.year}/{period.month}"
    return {
        "calculation_id": calculation.id,
        "employee": calculation.employee.full_name,
        "pdf_path": str(pdf_path),
        "api_download_url": f"{api_base}/calculations/{calculation.id}/pdf/download",
        "web_download_url": f"/calculations/{calculation.id}/pdf/download",
    }


def serialize_calculation_summary(
    period: Period,
    calculation: Calculation,
    department_code: str | None = None,
) -> dict[str, object]:
    if department_code:
        api_base = f"/api/departments/{department_code}/periods/{period.year}/{period.month}"
    else:
        api_base = f"/api/periods/{period.year}/{period.month}"
    result = {
        "id": calculation.id,
        "employee": calculation.employee.full_name,
        "status": calculation.status,
        "has_snapshot": bool(calculation.snapshot_json),
        "has_pdf": bool(calculation.pdf_path),
        "data_url": f"{api_base}/calculations/{calculation.id}",
        "api_pdf_url": f"{api_base}/calculations/{calculation.id}/pdf",
    }
    if calculation.pdf_path:
        result["api_download_url"] = f"{api_base}/calculations/{calculation.id}/pdf/download"
    return result


def serialize_calculation(
    calculation: Calculation,
    department_code: str | None = None,
) -> dict[str, object]:
    snapshot = load_snapshot(calculation) if calculation.snapshot_json else {}
    period = calculation.period
    if department_code:
        api_base = f"/api/departments/{department_code}/periods/{period.year}/{period.month}"
    else:
        api_base = f"/api/periods/{period.year}/{period.month}"
    return {
        "id": calculation.id,
        "period_id": calculation.period_id,
        "department_code": department_code or (period.department.code if period.department else None),
        "year": period.year,
        "month": period.month,
        "employee": calculation.employee.full_name,
        "status": calculation.status,
        "report_type": snapshot.get("report_type"),
        "total_bonus": snapshot.get("total_bonus"),
        "salary_total": snapshot.get("salary_total"),
        "pdf_path": calculation.pdf_path,
        "data_url": f"{api_base}/calculations/{calculation.id}",
        "api_pdf_url": f"{api_base}/calculations/{calculation.id}/pdf",
        "api_download_url": (
            f"{api_base}/calculations/{calculation.id}/pdf/download"
            if calculation.pdf_path
            else None
        ),
        "additional_payments": [
            {
                "title": payment.title,
                "amount": payment.amount,
                "comment": payment.comment,
                "status": payment.status,
            }
            for payment in calculation.additional_payments
        ],
        "adjustments": [
            {
                "section_code": adjustment.section_code,
                "adjustment_type": adjustment.adjustment_type,
                "amount": adjustment.amount,
                "comment": adjustment.comment,
                "status": adjustment.status,
            }
            for adjustment in calculation.adjustments
        ],
    }


def serialize_period(period: Period) -> dict[str, object]:
    return {
        "id": period.id,
        "department_code": period.department.code if period.department else None,
        "department": period.department.name if period.department else None,
        "year": period.year,
        "month": period.month,
        "status": period.status,
        "reports": [
            {
                "id": report.id,
                "report_type": report.report_type,
                "filename": report.original_filename,
                "status": report.status,
            }
            for report in period.reports
        ],
        "calculations": [
            {
                "id": calculation.id,
                "employee": calculation.employee.full_name,
                "status": calculation.status,
                "has_snapshot": bool(calculation.snapshot_json),
                "has_pdf": bool(calculation.pdf_path),
            }
            for calculation in period.calculations
        ],
        "validation": report_completeness(period),
    }


def reports_by_type(period: Period) -> dict[str, list]:
    grouped = {report_type: [] for report_type in REPORT_TYPES}
    for report in period.reports:
        grouped.setdefault(report.report_type, []).append(report)
    return grouped


def with_saved_notice(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["saved"] = "1"
    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        urlencode(query),
        parts.fragment,
    ))


def remove_period_calculations(db: Session, period: Period) -> None:
    for calculation in list(period.calculations):
        if calculation.pdf_path:
            pdf_path = resolve_service_data_path(calculation.pdf_path)
            try:
                if pdf_path.is_file():
                    pdf_path.unlink()
                    _remove_empty_parents(pdf_path.parent)
            except OSError:
                pass
        db.delete(calculation)
    db.flush()

    output_dir = period_storage_dir(GENERATED_DIR, period)
    if output_dir.exists():
        rmtree(output_dir)

    completeness = report_completeness(period)
    period.status = (
        PeriodStatus.DATA_PARSED.value
        if completeness["validated"]
        else PeriodStatus.REPORT_ERRORS.value
        if completeness["errors"]
        else PeriodStatus.READY_TO_CALCULATE.value
        if completeness["complete"]
        else PeriodStatus.MISSING_REPORTS.value
    )
    db.flush()


def delete_period(db: Session, period: Period) -> None:
    paths_to_delete = []
    for report in period.reports:
        if report.stored_path:
            paths_to_delete.append(resolve_service_data_path(report.stored_path))
    for calculation in period.calculations:
        if calculation.pdf_path:
            paths_to_delete.append(resolve_service_data_path(calculation.pdf_path))

    for path in paths_to_delete:
        try:
            if path.exists() and path.is_file():
                path.unlink()
                _remove_empty_parents(path.parent)
        except OSError:
            pass

    db.query(AdditionalPayment).filter(AdditionalPayment.period_id == period.id).delete(
        synchronize_session=False
    )
    db.query(CalculationAdjustment).filter(CalculationAdjustment.period_id == period.id).delete(
        synchronize_session=False
    )
    db.delete(period)
    db.flush()


def _remove_empty_parents(path: Path) -> None:
    stop_dirs = {GENERATED_DIR.resolve(), UPLOADS_DIR.resolve(), GENERATED_DIR.parent.resolve()}
    current = path
    while current.exists():
        try:
            resolved = current.resolve()
            if resolved in stop_dirs:
                return
            current.rmdir()
        except OSError:
            return
        current = current.parent
