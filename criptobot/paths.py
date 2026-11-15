"""Rutas de archivos del bot.

Cuando está empaquetado con PyInstaller, config.json y bot.log viven junto al
.exe; si se ejecuta como script, en la raíz del proyecto (junto a bot.py).
"""

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

CONFIG_PATH = BASE_DIR / "config.json"
CONFIG_EXAMPLE_PATH = BASE_DIR / "config.example.json"
LOG_PATH = BASE_DIR / "bot.log"
