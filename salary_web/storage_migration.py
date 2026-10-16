"""Move registered files to the department/year/month layout without overwrites."""
from filecmp import cmp
from shutil import copy2

from salary_web.config import (
    GENERATED_DIR, UPLOADS_DIR, period_storage_dir,
    resolve_service_data_path, stored_service_data_path,
)
from salary_web.models import Calculation, UploadedReport


def reorganize_files(db):
    moved = []
    missing = 0
    for model, field, root in ((UploadedReport, "stored_path", UPLOADS_DIR),
                               (Calculation, "pdf_path", GENERATED_DIR)):
        for row in db.query(model).all():
            stored = getattr(row, field)
            if not stored:
                continue
            source = resolve_service_data_path(stored)
            if not source.is_file():
                missing += 1
                continue
            target = period_storage_dir(root, row.period) / source.name
            if source.resolve() == target.resolve():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if not cmp(source, target, shallow=False):
                    raise ValueError(f"Файл назначения уже существует и отличается: {target}")
            else:
                copy2(source, target)
            setattr(row, field, stored_service_data_path(target))
            moved.append((source, target))
    db.commit()
    # Delete originals only after every new path has been committed successfully.
    for source in {source for source, _ in moved}:
        source.unlink(missing_ok=True)
    return {"moved": len(moved), "missing": missing}
