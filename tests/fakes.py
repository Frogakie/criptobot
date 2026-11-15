"""Dobles de prueba: sesión HTTP falsa y cliente de Binance falso."""

from decimal import Decimal
from urllib.parse import urlparse

from criptobot.client import Candle, OrderResult
from criptobot.rules import SymbolRules

BTC_RULES = SymbolRules(
    symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
    step_size=Decimal("0.00001"), min_qty=Decimal("0.00001"),
    max_qty=Decimal("9000"), min_notional=Decimal("5"),
)


class FakeResponse:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.text = str(data)

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code != 200:
            import requests
            raise requests.HTTPError(f"status {self.status_code}")


class FakeSession:
    """Responde según la ruta. `routes` mapea path -> datos o función(params) -> datos."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def _respond(self, method, url, params):
        path = urlparse(url).path
        self.calls.append((method, path, dict(params or {})))
        handler = self.routes[(method, path)] if (method, path) in self.routes else self.routes[path]
        data = handler(params or {}) if callable(handler) else handler
        if isinstance(data, FakeResponse):
            return data
        return FakeResponse(data)

    def get(self, url, params=None, timeout=None, **kw):
        return self._respond("GET", url, params)

    def request(self, method, url, params=None, headers=None, timeout=None, **kw):
        return self._respond(method, url, params)


def make_candles(closes, start=0, step=60_000):
    return [Candle(start + i * step, c, c, c, c, 1.0, start + (i + 1) * step - 1)
            for i, c in enumerate(closes)]


class FakeClient:
    """Imita BinanceClient sin red. `candles` es la lista de velas cerradas actual."""

    def __init__(self, mode="paper", price=100.0, balance=0.0, fee=0.001):
        self.mode = mode
        self.price = price
        self.balance = balance
        self.fee = fee
        self.candles = []
        self.orders = []
        self.fail_next_order = None

    def get_closed_klines(self, symbol, interval, limit=100):
        return self.candles[-limit:]

    def get_symbol_rules(self, symbol):
        return BTC_RULES

    def get_price(self, symbol):
        return self.price

    def get_free_balance(self, asset):
        return self.balance

    def place_market_order(self, rules, side, quantity):
        if self.fail_next_order:
            exc, self.fail_next_order = self.fail_next_order, None
            raise exc
        qty = float(quantity)
        self.orders.append((side, qty))
        quote = qty * self.price
        if side == "BUY":
            self.balance += qty * (1 - self.fee)
            return OrderResult("BUY", qty, quote, self.price, qty * self.fee, 0.0)
        self.balance -= qty
        return OrderResult("SELL", qty, quote, self.price, 0.0, quote * self.fee)
