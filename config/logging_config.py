import logging
import os
import sys

from config.settings import Settings

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_configured: set[str] = set()


def get_logger(name: str, log_dir: str | None = None,  filename: str = "session.log", global_log: bool = True, global_log_dir: str = "./logs",) -> logging.Logger:
    """Logger that always writes to stdout and, when log_dir is given, also
    appends to a per-session log file inside that directory (e.g. the
    recording's tracks output dir), so each session's timeline can be
    inspected on its own.
    """
    logger = logging.getLogger(f"gravai.{name}")

    cache_key = f"{name}:{log_dir}"
    if cache_key in _configured:
        return logger

    settings = Settings() # type: ignore
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    logger.propagate = False

    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)

    if not logger.handlers:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(os.path.join(log_dir, filename))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if global_log:
        os.makedirs(global_log_dir, exist_ok=True)
        global_file_handler = logging.FileHandler(os.path.join(global_log_dir, filename))
        global_file_handler.setFormatter(formatter)
        logger.addHandler(global_file_handler)

    _configured.add(cache_key)
    return logger
