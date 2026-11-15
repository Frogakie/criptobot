import logging
import tempfile
import unittest
from pathlib import Path

import requests

from criptobot.runner import Bot
from criptobot.state import BotState, Position, load_state, save_state, state_path
from tests.fakes import FakeClient, make_candles

logging.getLogger("bot").setLevel(logging.CRITICAL)

# Con SMA 2/4: compra al añadir el 5 (índice 5) y vende al llegar al segundo 0.1 (índice 7).
CLOSES = [1, 1, 1, 1, 1, 5, 0.1, 0.1]
BUY_AT, SELL_AT = 6, 8   # nº de velas cerradas cuando aparece cada señal


class FakeCfg:
    def __init__(self, **data):
        self.data = {"mode": "paper", "symbol": "BTCUSDT", "interval": "1m",
                     "order_quantity": 0.1, "sma_fast": 2, "sma_slow": 4, **data}

    def reload(self):
        return False

    def get(self, k, d=None):
        return self.data.get(k, d)


class TestBot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.all_candles = make_candles(CLOSES)

    def tearDown(self):
        self.tmp.cleanup()

    def _bot(self, client, **cfg):
        return Bot(FakeCfg(**cfg), client, self.dir, sleep=lambda s: None)

    def _advance(self, bot, client, n):
        client.candles = self.all_candles[:n]
        bot.run_once()

    def test_buy_then_sell_with_pnl(self):
        client = FakeClient()
        bot = self._bot(client)
        for n in range(5, SELL_AT + 1):
            self._advance(bot, client, n)
        self.assertEqual([o[0] for o in client.orders], ["BUY", "SELL"])
        self.assertEqual(client.orders[0], ("BUY", 0.1))
        # Vende la cantidad NETA tras la comisión (0.1 - 0.1%), redondeada al step.
        self.assertAlmostEqual(client.orders[1][1], 0.0999)
        self.assertIsNone(bot.state.position)
        self.assertAlmostEqual(bot.state.realized_pnl, 0.0999 * 100 * 0.999 - 10, places=6)

    def test_same_candle_is_evaluated_once(self):
        client = FakeClient()
        bot = self._bot(client)
        client.candles = self.all_candles[:BUY_AT]
        bot.run_once()
        bot.state.position = None   # aunque se "olvide" la posición...
        bot.run_once()              # ...la misma vela no vuelve a generar orden
        self.assertEqual(len(client.orders), 1)

    def test_position_survives_restart(self):
        client = FakeClient()
        bot = self._bot(client)
        self._advance(bot, client, BUY_AT)
        self.assertIsNotNone(bot.state.position)

        bot2 = self._bot(client)   # "reinicio"
        self._advance(bot2, client, SELL_AT - 1)
        self.assertIsNotNone(bot2.state.position)
        self._advance(bot2, client, SELL_AT)
        self.assertEqual([o[0] for o in client.orders], ["BUY", "SELL"])

    def test_failed_order_is_retried_next_cycle(self):
        client = FakeClient()
        client.fail_next_order = requests.ConnectionError("sin red")
        bot = self._bot(client)
        client.candles = self.all_candles[:BUY_AT]
        with self.assertRaises(requests.ConnectionError):
            bot.run_once()
        bot.run_once()
        self.assertEqual(client.orders, [("BUY", 0.1)])

    def test_order_below_minimum_is_not_sent(self):
        client = FakeClient()
        bot = self._bot(client, order_quantity=0.00001)  # 0.001 USDT < mínimo 5
        self._advance(bot, client, BUY_AT)
        self.assertEqual(client.orders, [])
        self.assertIsNone(bot.state.position)

    def test_live_reconcile_clears_position_without_balance(self):
        save_state(state_path(self.dir, "live"), BotState(
            position=Position("BTCUSDT", 0.1, 100, 10, 0)))
        client = FakeClient(mode="live", balance=0.0)
        bot = self._bot(client, mode="live")
        client.candles = self.all_candles[:5]
        bot.run_once()
        self.assertIsNone(bot.state.position)
        self.assertIsNone(load_state(state_path(self.dir, "live")).position)

    def test_live_reconcile_adjusts_to_smaller_balance(self):
        save_state(state_path(self.dir, "live"), BotState(
            position=Position("BTCUSDT", 0.1, 100, 10, 0)))
        client = FakeClient(mode="live", balance=0.08)
        bot = self._bot(client, mode="live")
        client.candles = self.all_candles[:5]
        bot.run_once()
        self.assertAlmostEqual(bot.state.position.qty, 0.08)

    def test_modes_use_separate_state_files(self):
        client = FakeClient()
        bot = self._bot(client)
        self._advance(bot, client, BUY_AT)
        self.assertTrue(state_path(self.dir, "paper").exists())
        self.assertFalse(state_path(self.dir, "live").exists())

    def test_symbol_change_keeps_managing_open_position(self):
        client = FakeClient()
        bot = self._bot(client)
        self._advance(bot, client, BUY_AT)
        bot.cfg.data["symbol"] = "ETHUSDT"
        self._advance(bot, client, SELL_AT - 1)
        self._advance(bot, client, SELL_AT)
        self.assertEqual([o[0] for o in client.orders], ["BUY", "SELL"])

    def test_invalid_sma_config_does_nothing(self):
        client = FakeClient()
        bot = self._bot(client, sma_fast=10, sma_slow=5)
        self._advance(bot, client, BUY_AT)
        self.assertEqual(client.orders, [])


class TestState(unittest.TestCase):
    def test_roundtrip_and_corrupt_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state_paper.json"
            st = BotState(position=Position("BTCUSDT", 0.5, 100, 50, 123),
                          last_candle={"BTCUSDT:1m": 99}, realized_pnl=1.5)
            save_state(p, st)
            self.assertEqual(load_state(p), st)
            p.write_text("{roto", encoding="utf-8")
            self.assertIsNone(load_state(p).position)
            self.assertTrue((Path(d) / "state_paper.corrupt.json").exists())


if __name__ == "__main__":
    unittest.main()
