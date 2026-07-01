from __future__ import annotations

import json
import logging
from typing import Any


def setup_logger(name: str = "cloud_automation") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def log_event(logger: logging.Logger, **kwargs: Any) -> None:
    logger.info(json.dumps(kwargs, ensure_ascii=False))
