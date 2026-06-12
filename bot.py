#!/usr/bin/env python3
"""
Binance Trading Bot con configuración en caliente (hot-reload).

- Lee config.json (junto al .exe / script). Si editas y guardas el archivo
  mientras el bot corre, los cambios se aplican automáticamente.
- Tres modos: "paper" (simulado, por defecto), "testnet" (Binance Testnet),
  "live" (dinero real - úsalo bajo tu propio riesgo).
- Estrategia incluida: cruce de medias móviles (SMA crossover), configurable.

ADVERTENCIA: El trading de criptomonedas es de alto riesgo. Este software se
entrega tal cual, sin garantías. Prueba SIEMPRE en paper/testnet primero.
"""

import hashlib
import hmac
import json
import logging
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

# ----------------------------------------------------------------------------
# Rutas: cuando está empaquetado con PyInstaller, el config vive junto al .exe
# ----------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "bot.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("bot")

ENDPOINTS = {
    "live": "https://api.binance.com",
    "testnet": "https://testnet.binance.vision",
    "paper": "https://api.binance.com",  # paper usa precios reales, órdenes simuladas
}


# ----------------------------------------------------------------------------
# Configuración con hot-reload
# ----------------------------------------------------------------------------
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
                       if old.get(k) != v and "key" not in k.lower() and "secret" not in k.lower()}
            log.info("🔄 Configuración recargada en caliente. Cambios: %s", changed or "(claves/valores sensibles)")
        return True

    def get(self, key, default=None):
        return self.data.get(key, default)


# ----------------------------------------------------------------------------
# Cliente Binance (REST, firmado HMAC-SHA256)
# ----------------------------------------------------------------------------
class BinanceClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.session = requests.Session()

    @property
    def mode(self):
        return self.cfg.get("mode", "paper")

    @property
    def base_url(self):
        return ENDPOINTS.get(self.mode, ENDPOINTS["paper"])

    def _headers(self):
        return {"X-MBX-APIKEY": self.cfg.get("api_key", "")}

    def _signed_params(self, params: dict) -> dict:
        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 5000
        query = urlencode(params)
        secret = self.cfg.get("api_secret", "").encode()
        params["signature"] = hmac.new(secret, query.encode(), hashlib.sha256).hexdigest()
        return params

    # ---- Datos de mercado (públicos, sin firma) ----
    def get_klines(self, symbol: str, interval: str, limit: int = 100):
        r = self.session.get(
            f"{self.base_url}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10,
        )
        r.raise_for_status()
        return [float(k[4]) for k in r.json()]  # precios de cierre

    def get_price(self, symbol: str) -> float:
        r = self.session.get(
            f"{self.base_url}/api/v3/ticker/price",
            params={"symbol": symbol}, timeout=10,
        )
        r.raise_for_status()
        return float(r.json()["price"])

    # ---- Órdenes (firmadas) ----
    def place_order(self, symbol: str, side: str, quantity: float):
        if self.mode == "paper":
            price = self.get_price(symbol)
            log.info("📝 [PAPER] Orden simulada: %s %s %s @ %.8f", side, quantity, symbol, price)
            return {"simulated": True, "side": side, "qty": quantity, "price": price}

        params = self._signed_params({
            "symbol": symbol,
            "side": side,           # BUY / SELL
            "type": "MARKET",
            "quantity": quantity,
        })
        r = self.session.post(
            f"{self.base_url}/api/v3/order",
            params=params, headers=self._headers(), timeout=10,
        )
        if r.status_code != 200:
            log.error("Error en orden: %s", r.text)
            r.raise_for_status()
        data = r.json()
        log.info("✅ [%s] Orden ejecutada: %s %s %s | id=%s",
                 self.mode.upper(), side, quantity, symbol, data.get("orderId"))
        return data


# ----------------------------------------------------------------------------
# Estrategia: cruce de medias móviles simples
# ----------------------------------------------------------------------------
def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def signal_sma_crossover(closes, fast_p, slow_p):
    """Devuelve 'BUY', 'SELL' o None según el cruce de SMAs."""
    fast_now, slow_now = sma(closes, fast_p), sma(closes, slow_p)
    fast_prev, slow_prev = sma(closes[:-1], fast_p), sma(closes[:-1], slow_p)
    if None in (fast_now, slow_now, fast_prev, slow_prev):
        return None
    if fast_prev <= slow_prev and fast_now > slow_now:
        return "BUY"
    if fast_prev >= slow_prev and fast_now < slow_now:
        return "SELL"
    return None


# ----------------------------------------------------------------------------
# Bucle principal
# ----------------------------------------------------------------------------
def main():
    log.info("=" * 60)
    log.info("Binance Bot iniciado | directorio: %s", BASE_DIR)
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

        time.sleep(cfg.get("poll_seconds", 30))


if __name__ == "__main__":
    main()
