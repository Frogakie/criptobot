import unittest

from criptobot.strategy import signal_sma_crossover, sma


class TestSMA(unittest.TestCase):
    def test_sma_basic(self):
        self.assertEqual(sma([1, 2, 3, 4], 2), 3.5)

    def test_sma_not_enough_data(self):
        self.assertIsNone(sma([1, 2], 3))


class TestCrossover(unittest.TestCase):
    def test_buy_when_fast_crosses_above(self):
        # Antes: rápida (1.0) <= lenta (1.0); ahora la rápida sube por encima
        closes = [1, 1, 1, 1, 5]
        self.assertEqual(signal_sma_crossover(closes, 2, 4), "BUY")

    def test_sell_when_fast_crosses_below(self):
        closes = [5, 5, 5, 5, 1]
        self.assertEqual(signal_sma_crossover(closes, 2, 4), "SELL")

    def test_no_signal_without_cross(self):
        closes = [1, 2, 3, 4, 5, 6]
        self.assertIsNone(signal_sma_crossover(closes, 2, 4))

    def test_none_with_insufficient_data(self):
        self.assertIsNone(signal_sma_crossover([1, 2, 3], 2, 4))


if __name__ == "__main__":
    unittest.main()
