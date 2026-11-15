"""Bucle principal del bot."""

import shutil
import sys
import time

import requests

from .client import BinanceClient
from .config import Config
from .logging_setup import setup_logging
from .paths import BASE_DIR, CONFIG_EXAMPLE_PATH, CONFIG_PATH, LOG_PATH
from .strategy import signal_sma_crossover, sma


def _ensure_config(log) -> None:
    """Si no existe config.json, lo crea a partir de config.example.json."""
    if CONFIG_PATH.exists():
        return
    if CONFIG_EXAMPLE_PATH.exists():
        shutil.copy(CONFIG_EXAMPLE_PATH, CONFIG_PATH)
        log.warning("No existía config.json: se creó una copia de config.example.json en %s. "
                    "Revísala y vuelve a iniciar el bot.", CONFIG_PATH)
    else:
        log.error("No se encontró config.json ni config.example.json en %s", BASE_DIR)
    sys.exit(1)


def main():
    log = setup_logging(LOG_PATH)
    log.info("=" * 60)
    log.info("Binance Bot iniciado | directorio: %s", BASE_DIR)
    _ensure_config(log)
    cfg = Config(CONFIG_PATH)
    client = BinanceClient(cfg)
    position_open = False  # estado simple: 1 posición a la vez

    if cfg.get("mode") == "live":
        log.warning("⚠️  MODO LIVE: se operará con DINERO REAL. "
                    "Tienes 10 segundos para cerrar el bot si no era tu intención...")
        time.sleep(10)

    while True:
        try:
            # Hot-reload: detecta cambios en config.json en cada ciclo
            cfg.reload()

            if not cfg.get("enabled", True):
                log.info("⏸️  Bot en pausa (enabled=false en config.json). Esperando...")
                time.sleep(cfg.get("poll_seconds", 30))
                continue

            symbol = cfg.get("symbol", "BTCUSDT")
            interval = cfg.get("interval", "1m")
            qty = cfg.get("order_quantity", 0.001)
            fast_p = cfg.get("sma_fast", 7)
            slow_p = cfg.get("sma_slow", 25)

            closes = client.get_klines(symbol, interval, limit=slow_p + 5)
            price = closes[-1]
            sig = signal_sma_crossover(closes, fast_p, slow_p)

            log.info("[%s] %s precio=%.4f SMA%d=%.4f SMA%d=%.4f señal=%s pos=%s",
                     cfg.get("mode", "paper").upper(), symbol, price,
                     fast_p, sma(closes, fast_p), slow_p, sma(closes, slow_p),
                     sig or "-", "ABIERTA" if position_open else "ninguna")

            if sig == "BUY" and not position_open:
                client.place_order(symbol, "BUY", qty)
                position_open = True
            elif sig == "SELL" and position_open:
                client.place_order(symbol, "SELL", qty)
                position_open = False

        except requests.RequestException as e:
            log.warning("Error de red/API: %s. Reintentando...", e)
        except KeyboardInterrupt:
            log.info("Bot detenido por el usuario.")
            break
        except Exception as e:
            log.exception("Error inesperado: %s", e)

        try:
            time.sleep(cfg.get("poll_seconds", 30))
        except KeyboardInterrupt:
            log.info("Bot detenido por el usuario.")
            break
