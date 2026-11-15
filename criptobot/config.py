"""Lectura de config.json con recarga en caliente (hot-reload)."""

import json
import logging
import sys
from pathlib import Path

log = logging.getLogger("bot")


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return "key" in k or "secret" in k


class Config:
    def __init__(self, path: Path):
        self.path = path
        self._mtime = 0.0
        self.data = {}
        self.reload(initial=True)

    def reload(self, initial=False) -> bool:
        """Devuelve True si la config cambió y se recargó."""
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            if initial:
                log.error("No se encontró config.json en %s", self.path)
                sys.exit(1)
            return False

        if mtime == self._mtime:
            return False

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                new_data = json.load(f)
        except json.JSONDecodeError as e:
            log.warning("config.json tiene un error de sintaxis (%s). "
                        "Se mantiene la configuración anterior.", e)
            self._mtime = mtime  # no reintentar hasta el próximo guardado
            return False

        self._mtime = mtime
        old = self.data
        self.data = new_data
        if not initial:
            changed = {k: v for k, v in new_data.items()
                       if old.get(k) != v and not _is_sensitive(k)}
            log.info("🔄 Configuración recargada en caliente. Cambios: %s",
                     changed or "(claves/valores sensibles)")
        return True

    def get(self, key, default=None):
        return self.data.get(key, default)
