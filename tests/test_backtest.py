import csv
import tempfile
import unittest
from pathlib import Path

from criptobot.backtest import main as backtest_main, max_drawdown_pct, run_backtest
from criptobot.data import download_klines, load_csv, parse_date, save_csv
from tests.fakes import FakeSession, make_candles

# SMA 2/4: señal BUY al cierre del índice 5 → compra a la apertura del 6 (precio 5).
#          señal SELL al cierre del índice 8 → venta a la apertura del 9 (precio 2).
CLOSES = [1, 1, 1, 1, 1, 5, 5, 6, 0.1, 2, 2]


class TestBacktest(unittest.TestCase):
    def test_trade_executes_on_next_open_without_costs(self):
        r = run_backtest(make_candles(CLOSES), 2, 4, fee_rate=0, slippage=0, initial_capital=100)
        self.assertEqual(len(r.closed_trades), 1)
        t = r.trades[0]
        self.assertEqual((t.entry_price, t.exit_price), (5, 2))
        self.assertAlmostEqual(r.final_equity, 40.0)
        self.assertAlmostEqual(r.total_return_pct, -60.0)
        self.assertAlmostEqual(r.win_rate_pct, 0.0)

    def test_fees_and_slippage_reduce_result(self):
        free = run_backtest(make_candles(CLOSES), 2, 4, fee_rate=0, slippage=0)
        costly = run_backtest(make_candles(CLOSES), 2, 4, fee_rate=0.001, slippage=0.001)
        self.assertLess(costly.final_equity, free.final_equity)
        self.assertGreater(costly.total_fees, 0)

    def test_no_lookahead(self):
        # Cambiar velas FUTURAS no debe alterar operaciones ya ejecutadas.
        a = run_backtest(make_candles(CLOSES), 2, 4, fee_rate=0, slippage=0)
        b = run_backtest(make_candles(CLOSES[:-1] + [999]), 2, 4, fee_rate=0, slippage=0)
        self.assertEqual(a.trades[0].entry_price, b.trades[0].entry_price)
        self.assertEqual(a.trades[0].exit_price, b.trades[0].exit_price)

    def test_open_position_at_end(self):
        r = run_backtest(make_candles([1, 1, 1, 1, 1, 5, 6, 7]), 2, 4, fee_rate=0, slippage=0,
                         initial_capital=100)
        self.assertTrue(r.trades[-1].open)
        self.assertAlmostEqual(r.final_equity, 100 / 6 * 7)

    def test_max_drawdown(self):
        self.assertAlmostEqual(max_drawdown_pct([100, 120, 90, 130, 65]), 50.0)

    def test_invalid_params(self):
        with self.assertRaises(ValueError):
            run_backtest(make_candles(CLOSES), 5, 3)
        with self.assertRaises(ValueError):
            run_backtest(make_candles(CLOSES[:4]), 2, 4)

    def test_cli_with_local_csv(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "velas.csv"
            out = Path(d) / "ops.csv"
            save_csv(src, make_candles(CLOSES, start=parse_date("2024-01-01")))
            code = backtest_main(["--csv", str(src), "--start", "2024-01-01", "--fast", "2",
                                  "--slow", "4", "--trades-out", str(out)])
            self.assertEqual(code, 0)
            with open(out, encoding="utf-8") as f:
                rows = list(csv.reader(f))
            self.assertEqual(len(rows), 2)  # cabecera + 1 operación


class TestData(unittest.TestCase):
    def test_download_paginates(self):
        start = parse_date("2024-01-01")
        all_k = [[start + i * 60_000, "1", "1", "1", str(i), "1", start + (i + 1) * 60_000 - 1]
                 for i in range(2500)]

        def klines(params):
            i0 = next(i for i, k in enumerate(all_k) if k[0] >= params["startTime"])
            return all_k[i0:i0 + params["limit"]]

        s = FakeSession({"/api/v3/klines": klines})
        candles = download_klines("BTCUSDT", "1m", start, start + 2500 * 60_000,
                                  session=s, pause=0)
        self.assertEqual(len(candles), 2500)
        self.assertEqual(len(s.calls), 3)
        self.assertEqual(candles[-1].close, 2499.0)

    def test_csv_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.csv"
            c = make_candles([1.5, 2.5])
            save_csv(p, c)
            self.assertEqual(load_csv(p), c)


if __name__ == "__main__":
    unittest.main()
