"""Configuración del logging: archivo bot.log + consola."""

import logging
import sys
from pathlib import Path

LOGGER_NAME = "bot"


def setup_logging(log_path: Path) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(LOGGER_NAME)
