"""Bucle principal del bot."""

import logging
import shutil
import sys
import time
from pathlib import Path

import requests

from .client import BinanceClient
from .config import Config
from .logging_setup import setup_logging
from .paths import BASE_DIR, CONFIG_EXAMPLE_PATH, CONFIG_PATH, LOG_PATH
from .rules import adjust_quantity
from .state import Position, load_state, save_state, state_path
from .strategy import signal_sma_crossover, sma

log = logging.getLogger("bot")

# Tolerancia al comparar la posición guardada con el saldo real (redondeos).
BALANCE_TOLERANCE = 0.999


class Bot:
    """Un ciclo de trading por llamada a run_once(). El bucle y las esperas
    están en main(), así run_once() se puede probar sin red ni esperas."""

    def __init__(self, cfg: Config, client: BinanceClient, base_dir: Path, sleep=time.sleep):
        self.cfg = cfg
        self.client = client
        self.base_dir = base_dir
        self._sleep = sleep
        self.mode = None
        self.state = None
        self._state_path = None
        self._reconciled = False
        self._warned_symbol_change = None

    # ------------------------------------------------------------------
    # Estado y modo
    # ------------------------------------------------------------------
    def _save(self):
        save_state(self._state_path, self.state)

    def _activate_mode(self, mode: str):
        if self.mode is not None:
            log.warning("🔀 Cambio de modo: %s → %s", self.mode, mode)
        if mode == "live":
            log.warning("⚠️  MODO LIVE: se operará con DINERO REAL. "
                        "Tienes 10 segundos para cerrar el bot si no era tu intención...")
            self._sleep(10)
        self.mode = mode
        self._state_path = state_path(self.base_dir, mode)
        self.state = load_state(self._state_path)
        self._reconciled = (mode == "paper")
        pos = self.state.position
        if pos:
            log.info("📂 Posición recuperada de %s: %.8f %s a %.8f",
                     self._state_path.name, pos.qty, pos.symbol, pos.entry_price)

    def _reconcile(self):
        """Compara la posición guardada con el saldo real de la cuenta."""
        pos = self.state.position
        symbol = pos.symbol if pos else self.cfg.get("symbol", "BTCUSDT")
        rules = self.client.get_symbol_rules(symbol)
        balance = self.client.get_free_balance(rules.base_asset)

        if pos and balance < pos.qty * BALANCE_TOLERANCE:
            price = self.client.get_price(symbol)
            _, err = adjust_quantity(rules, balance, price)
            if err:
                log.warning("⚠️  El estado dice que hay una posición de %.8f %s, pero el saldo "
                            "libre es %.8f (no vendible: %s). Se da la posición por cerrada.",
                            pos.qty, rules.base_asset, balance, err)
                self.state.position = None
            else:
                log.warning("⚠️  Saldo libre de %s (%.8f) menor que la posición guardada "
                            "(%.8f). Se ajusta la posición al saldo.",
                            rules.base_asset, balance, pos.qty)
                pos.qty = balance
        elif not pos and balance > 0:
            log.info("ℹ️  Tienes %.8f %s en la cuenta. El bot NO los considera parte de su "
                     "posición y no los venderá.", balance, rules.base_asset)

        self._save()
        self._reconciled = True

    # ------------------------------------------------------------------
    # Ciclo
    # ------------------------------------------------------------------
    def run_once(self):
        self.cfg.reload()

        if not self.cfg.get("enabled", True):
            log.info("⏸️  Bot en pausa (enabled=false en config.json). Esperando...")
            return

        mode = self.cfg.get("mode", "paper")
        if mode != self.mode:
            self._activate_mode(mode)
        if not self._reconciled:
            self._reconcile()

        interval = self.cfg.get("interval", "1m")
        fast_p = int(self.cfg.get("sma_fast", 7))
        slow_p = int(self.cfg.get("sma_slow", 25))
        if fast_p >= slow_p:
            log.error("Configuración inválida: sma_fast (%d) debe ser menor que sma_slow (%d).",
                      fast_p, slow_p)
            return

        cfg_symbol = self.cfg.get("symbol", "BTCUSDT")
        pos = self.state.position
        symbol = pos.symbol if pos else cfg_symbol
        if pos and cfg_symbol != pos.symbol and self._warned_symbol_change != cfg_symbol:
            log.warning("Cambiaste symbol a %s, pero hay una posición abierta en %s. "
                        "Se seguirá operando %s hasta cerrarla.", cfg_symbol, pos.symbol, pos.symbol)
            self._warned_symbol_change = cfg_symbol

        candles = self.client.get_closed_klines(symbol, interval, limit=slow_p + 2)
        if len(candles) < slow_p + 1:
            log.warning("Muy pocas velas cerradas (%d) para SMA%d.", len(candles), slow_p)
            return

        last = candles[-1]
        key = f"{symbol}:{interval}"
        if self.state.last_candle.get(key) == last.open_time:
            return  # esta vela ya se evaluó; esperar a que cierre la siguiente

        closes = [c.close for c in candles]
        sig = signal_sma_crossover(closes, fast_p, slow_p)
        log.info("[%s] %s cierre=%.4f SMA%d=%.4f SMA%d=%.4f señal=%s pos=%s",
                 mode.upper(), symbol, last.close, fast_p, sma(closes, fast_p),
                 slow_p, sma(closes, slow_p), sig or "-",
                 f"{pos.qty:.8f}" if pos else "ninguna")

        if sig == "BUY" and not pos:
            self._buy(symbol)
        elif sig == "SELL" and pos:
            self._sell()

        # Solo se marca la vela como procesada si no hubo excepción: si la orden
        # falló por red, se reintenta en el siguiente ciclo.
        self.state.last_candle[key] = last.open_time
        self._save()

    # ------------------------------------------------------------------
    # Órdenes
    # ------------------------------------------------------------------
    def _buy(self, symbol: str):
        rules = self.client.get_symbol_rules(symbol)
        price = self.client.get_price(symbol)
        qty, err = adjust_quantity(rules, self.cfg.get("order_quantity", 0.001), price)
        if err:
            log.error("❌ Orden BUY no enviada: %s. Ajusta order_quantity en config.json.", err)
            return
        res = self.client.place_market_order(rules, "BUY", qty)
        self.state.position = Position(
            symbol=symbol,
            qty=res.net_base_qty,
            entry_price=res.avg_price,
            entry_cost=res.quote_qty + res.commission_quote,
            entry_time=int(time.time() * 1000),
        )
        self._save()

    def _sell(self):
        pos = self.state.position
        rules = self.client.get_symbol_rules(pos.symbol)
        price = self.client.get_price(pos.symbol)
        qty = pos.qty
        if self.mode != "paper":
            balance = self.client.get_free_balance(rules.base_asset)
            if balance < qty:
                log.warning("Saldo libre de %s (%.8f) menor que la posición (%.8f); "
                            "se vende el saldo disponible.", rules.base_asset, balance, qty)
                qty = balance
        q, err = adjust_quantity(rules, qty, price)
        if err:
            log.error("❌ No se puede vender la posición: %s. Se da por cerrada; "
                      "revisa tu saldo en Binance.", err)
            self.state.position = None
            self._save()
            return

        res = self.client.place_market_order(rules, "SELL", q)
        proceeds = res.quote_qty - res.commission_quote
        fraction = min(1.0, res.executed_qty / pos.qty) if pos.qty else 1.0
        pnl = proceeds - pos.entry_cost * fraction
        self.state.realized_pnl += pnl
        self.state.position = None
        self._save()
        log.info("💰 Posición cerrada: PnL %+.4f %s (%+.2f%%) | PnL acumulado %+.4f %s",
                 pnl, rules.quote_asset, 100 * pnl / (pos.entry_cost * fraction or 1),
                 self.state.realized_pnl, rules.quote_asset)


def _ensure_config() -> None:
    """Si no existe config.json, lo crea a partir de config.example.json."""
    if CONFIG_PATH.exists():
        return
    if CONFIG_EXAMPLE_PATH.exists():
        shutil.copy(CONFIG_EXAMPLE_PATH, CONFIG_PATH)
        log.warning("No existía config.json: se creó una copia de config.example.json en %s. "
                    "Revísala y vuelve a iniciar el bot.", CONFIG_PATH)
    else:
        log.error("No se encontró config.json ni config.example.json en %s", BASE_DIR)
    sys.exit(1)


def main():
    setup_logging(LOG_PATH)
    log.info("=" * 60)
    log.info("Binance Bot iniciado | directorio: %s", BASE_DIR)
    _ensure_config()
    cfg = Config(CONFIG_PATH)
    bot = Bot(cfg, BinanceClient(cfg), BASE_DIR)

    while True:
        try:
            bot.run_once()
        except requests.RequestException as e:
            log.warning("Error de red/API: %s. Reintentando...", e)
        except KeyboardInterrupt:
            log.info("Bot detenido por el usuario.")
            break
        except Exception as e:
            log.exception("Error inesperado: %s", e)

        try:
            time.sleep(cfg.get("poll_seconds", 30))
        except KeyboardInterrupt:
            log.info("Bot detenido por el usuario.")
            break
