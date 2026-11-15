import time
import unittest
from unittest import mock

import requests

from criptobot.client import BinanceAPIError, BinanceClient
from tests.fakes import BTC_RULES, FakeResponse, FakeSession


class FakeCfg:
    def __init__(self, **data):
        self.data = {"mode": "testnet", "api_key": "k", "api_secret": "s", **data}

    def get(self, k, d=None):
        return self.data.get(k, d)


def now_ms():
    return int(time.time() * 1000)


class TestClient(unittest.TestCase):
    def test_closed_klines_drop_current_candle(self):
        t = now_ms()
        klines = [
            [t - 180_000, "1", "1", "1", "10", "1", t - 120_001],
            [t - 120_000, "1", "1", "1", "11", "1", t - 60_001],
            [t - 60_000, "1", "1", "1", "12", "1", t - 1],
            [t, "1", "1", "1", "13", "1", t + 59_999],   # vela en curso
        ]
        s = FakeSession({"/api/v3/time": {"serverTime": t}, "/api/v3/klines": klines})
        c = BinanceClient(FakeCfg(), session=s)
        closes = [k.close for k in c.get_closed_klines("BTCUSDT", "1m", limit=3)]
        self.assertEqual(closes, [10.0, 11.0, 12.0])

    def test_time_offset_used_in_signature(self):
        server = now_ms() + 5_000  # el servidor va 5 s por delante
        s = FakeSession({"/api/v3/time": lambda p: {"serverTime": server},
                         "/api/v3/account": {"balances": [{"asset": "BTC", "free": "0.5"}]}})
        c = BinanceClient(FakeCfg(), session=s)
        self.assertEqual(c.get_free_balance("BTC"), 0.5)
        ts = s.calls[-1][2]["timestamp"]
        self.assertAlmostEqual(ts, server, delta=1_000)
        self.assertIn("signature", s.calls[-1][2])

    def test_resync_on_timestamp_error(self):
        responses = [FakeResponse({"code": -1021, "msg": "Timestamp outside recvWindow"}, 400),
                     {"balances": []}]
        s = FakeSession({"/api/v3/time": lambda p: {"serverTime": now_ms()},
                         "/api/v3/account": lambda p: responses.pop(0)})
        c = BinanceClient(FakeCfg(), session=s)
        self.assertEqual(c.get_free_balance("BTC"), 0.0)
        self.assertEqual(sum(1 for call in s.calls if call[1] == "/api/v3/time"), 2)

    def test_api_error_has_code(self):
        s = FakeSession({"/api/v3/time": {"serverTime": now_ms()},
                         "/api/v3/order": FakeResponse({"code": -2010, "msg": "insufficient"}, 400)})
        c = BinanceClient(FakeCfg(), session=s)
        with self.assertRaises(BinanceAPIError) as ctx:
            c.place_market_order(BTC_RULES, "BUY", "0.001")
        self.assertEqual(ctx.exception.code, -2010)
        self.assertIsInstance(ctx.exception, requests.RequestException)

    def test_order_parses_fills_and_base_commission(self):
        order = {"orderId": 1, "clientOrderId": "x", "side": "BUY", "status": "FILLED",
                 "executedQty": "0.00100000", "cummulativeQuoteQty": "60.00",
                 "fills": [{"price": "60000", "qty": "0.001", "commission": "0.000001",
                            "commissionAsset": "BTC"}]}
        s = FakeSession({"/api/v3/time": {"serverTime": now_ms()}, "/api/v3/order": order})
        c = BinanceClient(FakeCfg(), session=s)
        res = c.place_market_order(BTC_RULES, "BUY", "0.001")
        self.assertAlmostEqual(res.net_base_qty, 0.000999)
        self.assertAlmostEqual(res.avg_price, 60000)
        sent = [call for call in s.calls if call[1] == "/api/v3/order"][0][2]
        self.assertEqual(sent["quantity"], "0.001")
        self.assertTrue(sent["newClientOrderId"].startswith("cb_"))

    def test_order_recovered_after_timeout(self):
        filled = {"orderId": 7, "side": "BUY", "status": "FILLED",
                  "executedQty": "0.001", "cummulativeQuoteQty": "60"}

        def order(params):
            if "origClientOrderId" in params:
                return filled
            raise requests.Timeout("timeout")

        s = FakeSession({"/api/v3/time": {"serverTime": now_ms()},
                         ("POST", "/api/v3/order"): order, ("GET", "/api/v3/order"): order})
        c = BinanceClient(FakeCfg(), session=s)
        with mock.patch("criptobot.client.time.sleep"):
            res = c.place_market_order(BTC_RULES, "BUY", "0.001")
        self.assertEqual(res.order_id, 7)

    def test_paper_order_does_not_hit_order_endpoint(self):
        s = FakeSession({"/api/v3/ticker/price": {"price": "50000"}})
        c = BinanceClient(FakeCfg(mode="paper", fee_rate=0.001), session=s)
        res = c.place_market_order(BTC_RULES, "BUY", "0.002")
        self.assertTrue(res.simulated)
        self.assertAlmostEqual(res.net_base_qty, 0.002 * 0.999)
        self.assertFalse(any(call[1] == "/api/v3/order" for call in s.calls))


if __name__ == "__main__":
    unittest.main()
