"""Cliente REST de Binance (firmado HMAC-SHA256)."""

import hashlib
import hmac
import logging
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlencode

import requests

from .config import Config
from .rules import SymbolRules, fmt_qty

log = logging.getLogger("bot")

ENDPOINTS = {
    "live": "https://api.binance.com",
    "testnet": "https://testnet.binance.vision",
    "paper": "https://api.binance.com",  # paper usa precios reales, órdenes simuladas
}

TIME_RESYNC_SECONDS = 30 * 60
ERR_TIMESTAMP = -1021  # "Timestamp for this request is outside of the recvWindow"


@dataclass(frozen=True)
class Candle:
    open_time: int    # ms
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int   # ms

    @classmethod
    def from_api(cls, k) -> "Candle":
        return cls(int(k[0]), float(k[1]), float(k[2]), float(k[3]),
                   float(k[4]), float(k[5]), int(k[6]))


@dataclass
class OrderResult:
    side: str
    executed_qty: float      # cantidad ejecutada (bruta)
    quote_qty: float         # total en moneda de cotización (USDT)
    avg_price: float
    commission_base: float   # comisión cobrada en el activo base (p. ej. BTC)
    commission_quote: float  # comisión cobrada en la moneda de cotización
    order_id: Optional[int] = None
    client_order_id: Optional[str] = None
    simulated: bool = False

    @property
    def net_base_qty(self) -> float:
        """Cantidad del activo base que realmente queda tras la comisión."""
        return self.executed_qty - self.commission_base


class BinanceAPIError(requests.HTTPError):
    """Error devuelto por la API de Binance (incluye el código de error)."""

    def __init__(self, code, msg, response=None):
        super().__init__(f"Binance error {code}: {msg}", response=response)
        self.code = code
        self.msg = msg


class BinanceClient:
    def __init__(self, cfg: Config, session: Optional[requests.Session] = None):
        self.cfg = cfg
        self.session = session or requests.Session()
        self._time_offset_ms = 0
        self._last_time_sync = 0.0
        self._time_synced_url = None
        self._rules_cache = {}

    # ------------------------------------------------------------------
    # Básicos
    # ------------------------------------------------------------------
    @property
    def mode(self):
        return self.cfg.get("mode", "paper")

    @property
    def base_url(self):
        return ENDPOINTS.get(self.mode, ENDPOINTS["paper"])

    def _headers(self):
        return {"X-MBX-APIKEY": self.cfg.get("api_key", "")}

    def _check(self, r: requests.Response):
        if r.status_code == 200:
            return r.json()
        try:
            body = r.json()
            code, msg = body.get("code"), body.get("msg")
        except ValueError:
            code, msg = r.status_code, r.text
        raise BinanceAPIError(code, msg, response=r)

    def _public_get(self, path: str, params: Optional[dict] = None):
        r = self.session.get(f"{self.base_url}{path}", params=params or {}, timeout=10)
        return self._check(r)

    # ------------------------------------------------------------------
    # Sincronización de hora con el servidor
    # ------------------------------------------------------------------
    def sync_time(self):
        t0 = time.time() * 1000
        server = self._public_get("/api/v3/time")["serverTime"]
        t1 = time.time() * 1000
        self._time_offset_ms = int(server - (t0 + t1) / 2)
        self._last_time_sync = time.time()
        self._time_synced_url = self.base_url
        if abs(self._time_offset_ms) > 1000:
            log.warning("⏱️  El reloj local difiere %d ms del servidor de Binance; "
                        "se compensa automáticamente.", self._time_offset_ms)

    def _maybe_sync_time(self):
        if (self._time_synced_url != self.base_url
                or time.time() - self._last_time_sync > TIME_RESYNC_SECONDS):
            self.sync_time()

    def server_time_ms(self) -> int:
        self._maybe_sync_time()
        return int(time.time() * 1000) + self._time_offset_ms

    # ------------------------------------------------------------------
    # Peticiones firmadas
    # ------------------------------------------------------------------
    def _signed_params(self, params: dict) -> dict:
        params = dict(params)
        params["timestamp"] = self.server_time_ms()
        params["recvWindow"] = 5000
        query = urlencode(params)
        secret = self.cfg.get("api_secret", "").encode()
        params["signature"] = hmac.new(secret, query.encode(), hashlib.sha256).hexdigest()
        return params

    def _signed_request(self, method: str, path: str, params: dict, _retry=True):
        r = self.session.request(
            method, f"{self.base_url}{path}",
            params=self._signed_params(params), headers=self._headers(), timeout=10,
        )
        try:
            return self._check(r)
        except BinanceAPIError as e:
            if e.code == ERR_TIMESTAMP and _retry:
                log.warning("Desfase de hora con Binance; resincronizando y reintentando...")
                self.sync_time()
                return self._signed_request(method, path, params, _retry=False)
            raise

    # ------------------------------------------------------------------
    # Datos de mercado (públicos, sin firma)
    # ------------------------------------------------------------------
    def get_klines(self, symbol: str, interval: str, limit: int = 100,
                   start_time: Optional[int] = None, end_time: Optional[int] = None) -> List[Candle]:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        return [Candle.from_api(k) for k in self._public_get("/api/v3/klines", params)]

    def get_closed_klines(self, symbol: str, interval: str, limit: int = 100) -> List[Candle]:
        """Velas CERRADAS. Binance devuelve la vela en curso como última; se descarta
        para que la señal no cambie dentro de la misma vela."""
        candles = self.get_klines(symbol, interval, limit=limit + 1)
        now = self.server_time_ms()
        closed = [c for c in candles if c.close_time < now]
        return closed[-limit:]

    def get_price(self, symbol: str) -> float:
        return float(self._public_get("/api/v3/ticker/price", {"symbol": symbol})["price"])

    def get_symbol_rules(self, symbol: str) -> SymbolRules:
        key = (self.base_url, symbol)
        if key not in self._rules_cache:
            data = self._public_get("/api/v3/exchangeInfo", {"symbol": symbol})
            self._rules_cache[key] = SymbolRules.from_exchange_info(data["symbols"][0])
        return self._rules_cache[key]

    # ------------------------------------------------------------------
    # Cuenta (firmado)
    # ------------------------------------------------------------------
    def get_free_balance(self, asset: str) -> float:
        data = self._signed_request("GET", "/api/v3/account", {"omitZeroBalances": "true"})
        for b in data.get("balances", []):
            if b["asset"] == asset:
                return float(b["free"])
        return 0.0

    # ------------------------------------------------------------------
    # Órdenes
    # ------------------------------------------------------------------
    def place_market_order(self, rules: SymbolRules, side: str, quantity) -> OrderResult:
        """Envía una orden de mercado. `quantity` ya debe estar ajustada a las reglas."""
        if self.mode == "paper":
            return self._paper_order(rules, side, float(quantity))

        client_id = f"cb_{uuid.uuid4().hex[:20]}"
        params = {
            "symbol": rules.symbol,
            "side": side,               # BUY / SELL
            "type": "MARKET",
            "quantity": fmt_qty(quantity),
            "newClientOrderId": client_id,
            "newOrderRespType": "FULL",
        }
        try:
            data = self._signed_request("POST", "/api/v3/order", params)
        except (requests.ConnectionError, requests.Timeout) as e:
            # No sabemos si la orden llegó: la buscamos por su ID antes de rendirnos.
            log.warning("Sin respuesta al enviar la orden (%s). Comprobando si se ejecutó...", e)
            data = self._recover_order(rules.symbol, client_id)
            if data is None:
                raise
        result = self._parse_order(rules, data)
        log.info("✅ [%s] Orden ejecutada: %s %.8f %s @ %.8f | id=%s",
                 self.mode.upper(), side, result.executed_qty, rules.symbol,
                 result.avg_price, result.order_id)
        return result

    def _recover_order(self, symbol: str, client_id: str, attempts: int = 3):
        for i in range(attempts):
            time.sleep(2 * (i + 1))
            try:
                data = self._signed_request("GET", "/api/v3/order",
                                            {"symbol": symbol, "origClientOrderId": client_id})
            except BinanceAPIError as e:
                if e.code == -2013:  # la orden no existe: nunca llegó
                    log.warning("La orden %s no llegó a Binance.", client_id)
                    return None
                raise
            except (requests.ConnectionError, requests.Timeout):
                continue
            if data.get("status") in ("FILLED", "PARTIALLY_FILLED", "EXPIRED", "CANCELED") \
                    and float(data.get("executedQty", 0)) > 0:
                log.info("La orden %s sí se ejecutó (estado %s).", client_id, data["status"])
                return data
            if data.get("status") in ("REJECTED", "EXPIRED", "CANCELED"):
                return None
        return None

    @staticmethod
    def _parse_order(rules: SymbolRules, data: dict) -> OrderResult:
        executed = float(data.get("executedQty", 0))
        quote = float(data.get("cummulativeQuoteQty", 0))
        commission_base = commission_quote = 0.0
        for fill in data.get("fills", []):
            if fill.get("commissionAsset") == rules.base_asset:
                commission_base += float(fill["commission"])
            elif fill.get("commissionAsset") == rules.quote_asset:
                commission_quote += float(fill["commission"])
        avg = quote / executed if executed else 0.0
        return OrderResult(
            side=data.get("side", ""), executed_qty=executed, quote_qty=quote,
            avg_price=avg, commission_base=commission_base,
            commission_quote=commission_quote, order_id=data.get("orderId"),
            client_order_id=data.get("clientOrderId"),
        )

    def _paper_order(self, rules: SymbolRules, side: str, qty: float) -> OrderResult:
        price = self.get_price(rules.symbol)
        fee = float(self.cfg.get("fee_rate", 0.001))
        quote = qty * price
        # Igual que Binance sin BNB: en BUY la comisión se cobra en el activo base,
        # en SELL en la moneda de cotización.
        commission_base = qty * fee if side == "BUY" else 0.0
        commission_quote = quote * fee if side == "SELL" else 0.0
        log.info("📝 [PAPER] Orden simulada: %s %.8f %s @ %.8f", side, qty, rules.symbol, price)
        return OrderResult(side=side, executed_qty=qty, quote_qty=quote, avg_price=price,
                           commission_base=commission_base, commission_quote=commission_quote,
                           simulated=True)
