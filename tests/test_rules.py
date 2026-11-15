import unittest
from decimal import Decimal

from criptobot.rules import SymbolRules, adjust_quantity, fmt_qty, round_step
from tests.fakes import BTC_RULES

EXCHANGE_INFO_BTC = {
    "symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT",
    "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
        {"filterType": "LOT_SIZE", "minQty": "0.00001000", "maxQty": "9000.00000000",
         "stepSize": "0.00001000"},
        {"filterType": "MARKET_LOT_SIZE", "minQty": "0.00000000", "maxQty": "120.5",
         "stepSize": "0.00000000"},
        {"filterType": "NOTIONAL", "minNotional": "5.00000000", "applyMinToMarket": True,
         "maxNotional": "9000000.00000000", "applyMaxToMarket": False},
    ],
}


class TestRules(unittest.TestCase):
    def test_parse_exchange_info(self):
        r = SymbolRules.from_exchange_info(EXCHANGE_INFO_BTC)
        self.assertEqual(r.base_asset, "BTC")
        self.assertEqual(r.step_size, Decimal("0.00001"))
        self.assertEqual(r.min_qty, Decimal("0.00001"))
        self.assertEqual(r.max_qty, Decimal("120.5"))   # el más restrictivo
        self.assertEqual(r.min_notional, Decimal("5"))

    def test_legacy_min_notional(self):
        info = dict(EXCHANGE_INFO_BTC, filters=[
            {"filterType": "MIN_NOTIONAL", "minNotional": "10", "applyToMarket": True}])
        self.assertEqual(SymbolRules.from_exchange_info(info).min_notional, Decimal("10"))

    def test_round_step_rounds_down(self):
        self.assertEqual(round_step(0.0012345, Decimal("0.00001")), Decimal("0.00123"))
        self.assertEqual(round_step(0.000999, Decimal("0.00001")), Decimal("0.00099"))

    def test_fmt_qty_no_scientific(self):
        self.assertEqual(fmt_qty(Decimal("0.00001000")), "0.00001")
        self.assertEqual(fmt_qty(Decimal("1E+1")), "10")

    def test_adjust_ok(self):
        q, err = adjust_quantity(BTC_RULES, 0.0012345, 60000)
        self.assertIsNone(err)
        self.assertEqual(q, Decimal("0.00123"))

    def test_adjust_below_min_notional(self):
        _, err = adjust_quantity(BTC_RULES, 0.00005, 60000)  # 3 USDT < 5
        self.assertIn("mínimo", err)

    def test_adjust_zero_after_rounding(self):
        _, err = adjust_quantity(BTC_RULES, 0.000001, 60000)
        self.assertIsNotNone(err)


if __name__ == "__main__":
    unittest.main()
