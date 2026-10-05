import logging
import sys

from .config import settings

LOGGER_NAME = "worthmytime"


def setup_logging() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(settings.log_level.upper())
    if not logger.handlers:  # create_app bywa wołane wielokrotnie (testy)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s", "%H:%M:%S"))
        logger.addHandler(handler)
        logger.propagate = False
    return logger


def get_logger(suffix: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{suffix}" if suffix else LOGGER_NAME)
