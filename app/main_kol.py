from __future__ import annotations

from app.logger import log_event, setup_logger
from app.services.kol_service import KolService
from app.settings import load_settings


def main() -> int:
    logger = setup_logger("kol")
    settings = load_settings()
    service = KolService(settings, logger)
    result = service.run_daily_report()
    log_event(logger, job="kol_report", stage="completed", status="success", file=str(result["report_path"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
