from __future__ import annotations

import os
import sys

from loguru import logger

from .config import get_settings


def setup_logging() -> None:
    settings = get_settings()
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )
    if settings.log_file:
        os.makedirs(os.path.dirname(settings.log_file), exist_ok=True)
        logger.add(
            settings.log_file,
            level=settings.log_level,
            rotation=settings.log_rotation,
            retention=settings.log_retention,
            enqueue=True,
        )
