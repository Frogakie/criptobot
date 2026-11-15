"""Backtester: simula la estrategia sobre velas históricas.

Supuestos (los mismos que el bot en vivo):
- La señal se calcula al CIERRE de cada vela, solo con velas cerradas.
- La orden se ejecuta a la APERTURA de la vela siguiente, con deslizamiento.
- Comisión como Binance sin BNB: en la compra se descuenta del activo base,
  en la venta de la moneda de cotización.
- Una posición a la vez, usando `position_fraction` del capital disponible.

Uso:
    python -m criptobot.backtest --symbol BTCUSDT --interval 1h --start 2024-01-01
    python -m criptobot.backtest --help
"""

import argparse
import csv
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

from .client import Candle
from .strategy import signal_sma_crossover

log = logging.getLogger("bot")

QUOTE_ASSETS = ("FDUSD", "USDT", "USDC", "TUSD", "EUR", "TRY", "BRL", "BTC", "ETH", "BNB")


@dataclass
class Trade:
    entry_time: int
    entry_price: float
    exit_time: int
    exit_price: float
    qty: float
    cost: float          # moneda de cotización gastada en la compra
    proceeds: float      # moneda de cotización recibida en la venta (neta)
    fees: float          # comisiones totales, en moneda de cotización
    open: bool = False   # True si seguía abierta al final (valorada al último cierre)

    @property
    def pnl(self) -> float:
        return self.proceeds - self.cost

    @property
    def pnl_pct(self) -> float:
        return 100 * self.pnl / self.cost if self.cost else 0.0


@dataclass
class BacktestResult:
    initial_capital: float
    final_equity: float
    buy_hold_equity: float
    max_drawdown_pct: float
    exposure_pct: float
    candles: int
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)

    @property
    def total_return_pct(self) -> float:
        return 100 * (self.final_equity / self.initial_capital - 1)

    @property
    def buy_hold_return_pct(self) -> float:
        return 100 * (self.buy_hold_equity / self.initial_capital - 1)

    @property
    def closed_trades(self) -> List[Trade]:
        return [t for t in self.trades if not t.open]

    @property
    def win_rate_pct(self) -> float:
        closed = self.closed_trades
        return 100 * sum(t.pnl > 0 for t in closed) / len(closed) if closed else 0.0

    @property
    def profit_factor(self) -> Optional[float]:
        gains = sum(t.pnl for t in self.closed_trades if t.pnl > 0)
        losses = -sum(t.pnl for t in self.closed_trades if t.pnl < 0)
        if losses == 0:
            return None if gains == 0 else float("inf")
        return gains / losses

    @property
    def avg_trade_pct(self) -> float:
        closed = self.closed_trades
        return sum(t.pnl_pct for t in closed) / len(closed) if closed else 0.0

    @property
    def total_fees(self) -> float:
        return sum(t.fees for t in self.trades)


def max_drawdown_pct(equity: List[float]) -> float:
    """Mayor caída desde un máximo previo, en % (número positivo)."""
    peak, mdd = float("-inf"), 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak)
    return 100 * mdd


def run_backtest(candles: List[Candle], fast: int, slow: int,
                 fee_rate: float = 0.001, slippage: float = 0.0005,
                 initial_capital: float = 1000.0, position_fraction: float = 1.0) -> BacktestResult:
    if fast >= slow:
        raise ValueError(f"fast ({fast}) debe ser menor que slow ({slow})")
    if len(candles) < slow + 2:
        raise ValueError(f"Se necesitan al menos {slow + 2} velas; hay {len(candles)}")

    closes = [c.close for c in candles]
    cash = initial_capital
    qty = 0.0
    entry = None   # dict con datos de la compra en curso
    trades: List[Trade] = []
    equity_curve: List[float] = []
    candles_in_market = 0
    start = slow  # primera vela con datos suficientes para calcular el cruce

    for i in range(start, len(candles)):
        # 1) Ejecutar la orden decidida al cierre de la vela anterior, a la apertura de esta.
        if i > start:
            window = closes[i - 1 - slow: i]   # slow+1 cierres que terminan en la vela i-1
            sig = signal_sma_crossover(window, fast, slow)
            c = candles[i]
            if sig == "BUY" and qty == 0:
                price = c.open * (1 + slippage)
                spend = cash * position_fraction
                gross = spend / price
                qty = gross * (1 - fee_rate)
                cash -= spend
                entry = {"time": c.open_time, "price": price, "cost": spend,
                         "fee": gross * fee_rate * price}
            elif sig == "SELL" and qty > 0:
                price = c.open * (1 - slippage)
                gross = qty * price
                fee = gross * fee_rate
                cash += gross - fee
                trades.append(Trade(entry["time"], entry["price"], c.open_time, price,
                                    qty, entry["cost"], gross - fee, entry["fee"] + fee))
                qty, entry = 0.0, None

        # 2) Valorar la cartera al cierre de la vela.
        if qty > 0:
            candles_in_market += 1
        equity_curve.append(cash + qty * candles[i].close)

    last = candles[-1]
    if qty > 0:
        trades.append(Trade(entry["time"], entry["price"], last.close_time, last.close,
                            qty, entry["cost"], qty * last.close, entry["fee"], open=True))

    # Comprar y mantener desde la misma vela en que empieza la estrategia (con comisiones).
    bh_price = candles[start + 1].open * (1 + slippage) if start + 1 < len(candles) else last.close
    bh_qty = initial_capital / bh_price * (1 - fee_rate)
    buy_hold = bh_qty * last.close * (1 - fee_rate)

    return BacktestResult(
        initial_capital=initial_capital,
        final_equity=equity_curve[-1],
        buy_hold_equity=buy_hold,
        max_drawdown_pct=max_drawdown_pct(equity_curve),
        exposure_pct=100 * candles_in_market / len(equity_curve),
        candles=len(equity_curve),
        trades=trades,
        equity_curve=equity_curve,
    )


# ----------------------------------------------------------------------
# Informe y CLI
# ----------------------------------------------------------------------
def format_report(r: BacktestResult, quote: str = "USDT") -> str:
    pf = r.profit_factor
    pf_txt = "—" if pf is None else ("∞" if pf == float("inf") else f"{pf:.2f}")
    open_trades = [t for t in r.trades if t.open]
    lines = [
        "",
        "═" * 52,
        " RESULTADO DEL BACKTEST",
        "═" * 52,
        f" Capital inicial        {r.initial_capital:>14,.2f} {quote}",
        f" Capital final          {r.final_equity:>14,.2f} {quote}",
        f" Rentabilidad           {r.total_return_pct:>+13.2f} %",
        f" Comprar y mantener     {r.buy_hold_return_pct:>+13.2f} %",
        f" Caída máxima           {-r.max_drawdown_pct:>13.2f} %",
        "─" * 52,
        f" Operaciones cerradas   {len(r.closed_trades):>14}",
        f" % ganadoras            {r.win_rate_pct:>13.1f} %",
        f" Media por operación    {r.avg_trade_pct:>+13.2f} %",
        f" Profit factor          {pf_txt:>14}",
        f" Comisiones pagadas     {r.total_fees:>14,.2f} {quote}",
        f" Tiempo en mercado      {r.exposure_pct:>13.1f} %",
        f" Velas analizadas       {r.candles:>14,}",
    ]
    if open_trades:
        t = open_trades[0]
        lines.append(f" Posición abierta al final ({t.pnl_pct:+.2f} %), valorada al último cierre")
    lines.append("═" * 52)
    if len(r.closed_trades) < 30:
        lines.append(" ⚠️  Menos de 30 operaciones: el resultado no es estadísticamente fiable.")
    if r.total_return_pct < r.buy_hold_return_pct:
        lines.append(" ℹ️  La estrategia rinde menos que comprar y mantener en este periodo.")
    return "\n".join(lines)


def save_trades_csv(path: Path, trades: List[Trade]) -> None:
    from .data import fmt_ms
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["entrada", "precio_entrada", "salida", "precio_salida", "cantidad",
                    "coste", "ingreso", "comisiones", "pnl", "pnl_pct", "abierta"])
        for t in trades:
            w.writerow([fmt_ms(t.entry_time), f"{t.entry_price:.8f}", fmt_ms(t.exit_time),
                        f"{t.exit_price:.8f}", f"{t.qty:.8f}", f"{t.cost:.4f}",
                        f"{t.proceeds:.4f}", f"{t.fees:.4f}", f"{t.pnl:.4f}",
                        f"{t.pnl_pct:.2f}", "sí" if t.open else "no"])


def _load_defaults(config_path: Path) -> dict:
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def build_parser(defaults: dict) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m criptobot.backtest",
        description="Backtest de la estrategia SMA crossover con datos históricos de Binance. "
                    "Los valores por defecto se toman de config.json.")
    p.add_argument("--symbol", default=defaults.get("symbol", "BTCUSDT"))
    p.add_argument("--interval", default=defaults.get("interval", "1h"),
                   help="1m, 5m, 15m, 1h, 4h, 1d… (por defecto: el de config.json)")
    p.add_argument("--start", required=True, help="Fecha inicial UTC: AAAA-MM-DD")
    p.add_argument("--end", help="Fecha final UTC: AAAA-MM-DD (por defecto: ahora)")
    p.add_argument("--fast", type=int, default=defaults.get("sma_fast", 7))
    p.add_argument("--slow", type=int, default=defaults.get("sma_slow", 25))
    p.add_argument("--fee", type=float, default=100 * float(defaults.get("fee_rate", 0.001)),
                   help="Comisión por operación en %% (por defecto 0.1)")
    p.add_argument("--slippage", type=float, default=0.05,
                   help="Deslizamiento de precio en %% (por defecto 0.05)")
    p.add_argument("--capital", type=float, default=1000.0, help="Capital inicial")
    p.add_argument("--fraction", type=float, default=1.0,
                   help="Fracción del capital usada en cada compra (0-1, por defecto 1)")
    p.add_argument("--csv", type=Path, help="Usar velas de un CSV local en vez de descargarlas")
    p.add_argument("--trades-out", type=Path, help="Guardar las operaciones en este CSV")
    p.add_argument("--no-cache", action="store_true", help="Descargar de nuevo aunque haya caché")
    return p


def main(argv=None):
    from .data import fmt_ms, load_csv, load_or_download, parse_date
    from .paths import BASE_DIR, CONFIG_PATH

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    args = build_parser(_load_defaults(CONFIG_PATH)).parse_args(argv)

    start_ms = parse_date(args.start)
    if args.csv:
        candles = [c for c in load_csv(args.csv) if c.open_time >= start_ms]
        if args.end:
            candles = [c for c in candles if c.open_time < parse_date(args.end)]
    else:
        import time
        end_ms = parse_date(args.end) if args.end else int(time.time() * 1000)
        candles = load_or_download(args.symbol, args.interval, start_ms, end_ms,
                                   cache_dir=BASE_DIR / "data", use_cache=not args.no_cache)
    if not candles:
        log.error("No hay velas para ese rango.")
        return 1

    log.info("%s %s | %s → %s | SMA %d/%d | comisión %.3f%% | deslizamiento %.3f%%",
             args.symbol, args.interval, fmt_ms(candles[0].open_time),
             fmt_ms(candles[-1].close_time), args.fast, args.slow, args.fee, args.slippage)
    try:
        result = run_backtest(candles, args.fast, args.slow,
                              fee_rate=args.fee / 100, slippage=args.slippage / 100,
                              initial_capital=args.capital, position_fraction=args.fraction)
    except ValueError as e:
        log.error("Error: %s", e)
        return 1

    quote = next((q for q in QUOTE_ASSETS if args.symbol.endswith(q)), "")
    print(format_report(result, quote))
    if args.trades_out:
        save_trades_csv(args.trades_out, result.trades)
        print(f" Operaciones guardadas en {args.trades_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
