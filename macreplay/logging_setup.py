import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(log_dir):
    logger = logging.getLogger("MacReplay")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    os.makedirs(log_dir, exist_ok=True)

    log_file_path = os.path.join(log_dir, "MacReplay.log")
    file_handler = RotatingFileHandler(
        log_file_path, maxBytes=5 * 1024 * 1024, backupCount=5
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(console_handler)

    return logger
