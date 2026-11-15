"""Cliente REST de Binance (firmado HMAC-SHA256)."""

import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import requests

from .config import Config

log = logging.getLogger("bot")

ENDPOINTS = {
    "live": "https://api.binance.com",
    "testnet": "https://testnet.binance.vision",
    "paper": "https://api.binance.com",  # paper usa precios reales, órdenes simuladas
}


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
