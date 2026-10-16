from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from salary_web.database import Base


def utc_now() -> datetime:
    """UTC timestamp kept naive for compatibility with the existing SQLite schema."""
    return datetime.now(UTC).replace(tzinfo=None)


class PeriodStatus(str, Enum):
    DRAFT = "draft"
    REPORTS_LOADING = "reports_loading"
    MISSING_REPORTS = "missing_reports"
    REPORT_ERRORS = "report_errors"
    DATA_PARSED = "data_parsed"
    READY_TO_CALCULATE = "ready_to_calculate"
    CALCULATION_CREATED = "calculation_created"
    CLOSED = "closed"


class ReportStatus(str, Enum):
    UPLOADED = "uploaded"
    VALIDATED = "validated"
    PARSED = "parsed"
    ERROR = "error"


class ManualEntryStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"


class Period(Base):
    __tablename__ = "periods"
    __table_args__ = (
        UniqueConstraint("department_id", "year", "month", name="uq_period_department_year_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default=PeriodStatus.DRAFT.value)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
    )

    reports: Mapped[list["UploadedReport"]] = relationship(
        back_populates="period",
        cascade="all, delete-orphan",
    )
    calculations: Mapped[list["Calculation"]] = relationship(
        back_populates="period",
        cascade="all, delete-orphan",
    )
    department: Mapped["Department | None"] = relationship()


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, default=1)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    session_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    is_admin: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    departments: Mapped[list["UserDepartment"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserDepartment(Base):
    __tablename__ = "user_departments"
    __table_args__ = (
        UniqueConstraint("user_id", "department_id", name="uq_user_department"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), nullable=False)

    user: Mapped[User] = relationship(back_populates="departments")
    department: Mapped[Department] = relationship()


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    key_secret: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)

    departments: Mapped[list["ApiKeyDepartment"]] = relationship(
        back_populates="api_key",
        cascade="all, delete-orphan",
    )


class ApiKeyDepartment(Base):
    __tablename__ = "api_key_departments"
    __table_args__ = (
        UniqueConstraint("api_key_id", "department_id", name="uq_api_key_department"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    api_key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"), nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), nullable=False)

    api_key: Mapped[ApiKey] = relationship(back_populates="departments")
    department: Mapped[Department] = relationship()


class UploadedReport(Base):
    __tablename__ = "uploaded_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False)
    report_type: Mapped[str] = mapped_column(String(50), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default=ReportStatus.UPLOADED.value)
    error_message: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    period: Mapped[Period] = relationship(back_populates="reports")


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="manager")
    is_active: Mapped[int] = mapped_column(Integer, default=1)


class Calculation(Base):
    __tablename__ = "calculations"
    __table_args__ = (
        UniqueConstraint("period_id", "employee_id", name="uq_period_employee"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    snapshot_json: Mapped[str | None] = mapped_column(Text)
    pdf_path: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
    )

    period: Mapped[Period] = relationship(back_populates="calculations")
    employee: Mapped[Employee] = relationship()
    additional_payments: Mapped[list["AdditionalPayment"]] = relationship(
        cascade="all, delete-orphan",
    )
    adjustments: Mapped[list["CalculationAdjustment"]] = relationship(
        cascade="all, delete-orphan",
    )


class AdditionalPayment(Base):
    __tablename__ = "additional_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    calculation_id: Mapped[int | None] = mapped_column(ForeignKey("calculations.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0)
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(50),
        default=ManualEntryStatus.DRAFT.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class CalculationAdjustment(Base):
    __tablename__ = "calculation_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    calculation_id: Mapped[int | None] = mapped_column(ForeignKey("calculations.id"))
    section_code: Mapped[str] = mapped_column(String(100), nullable=False)
    field_code: Mapped[str | None] = mapped_column(String(100))
    adjustment_type: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0)
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(50),
        default=ManualEntryStatus.DRAFT.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
