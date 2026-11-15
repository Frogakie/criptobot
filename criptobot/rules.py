"""Reglas de cada par en Binance (filtros de exchangeInfo) y ajuste de órdenes.

Binance rechaza las órdenes que no respetan los filtros del símbolo:
- LOT_SIZE / MARKET_LOT_SIZE: cantidad mínima, máxima y múltiplo (stepSize).
- MIN_NOTIONAL / NOTIONAL: valor mínimo de la orden (cantidad × precio).
Este módulo redondea la cantidad y valida la orden ANTES de enviarla.
"""

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Optional, Tuple


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    base_asset: str
    quote_asset: str
    step_size: Decimal
    min_qty: Decimal
    max_qty: Decimal          # 0 = sin límite
    min_notional: Decimal     # 0 = sin límite

    @classmethod
    def from_exchange_info(cls, info: dict) -> "SymbolRules":
        """Construye las reglas a partir de un elemento de exchangeInfo['symbols']."""
        filters = {f["filterType"]: f for f in info.get("filters", [])}

        step = Decimal("0")
        min_qty = Decimal("0")
        max_qty = Decimal("0")
        for name in ("LOT_SIZE", "MARKET_LOT_SIZE"):
            f = filters.get(name)
            if not f:
                continue
            f_step = Decimal(f.get("stepSize", "0"))
            f_min = Decimal(f.get("minQty", "0"))
            f_max = Decimal(f.get("maxQty", "0"))
            step = max(step, f_step)
            min_qty = max(min_qty, f_min)
            if f_max > 0:
                max_qty = f_max if max_qty == 0 else min(max_qty, f_max)

        min_notional = Decimal("0")
        if "NOTIONAL" in filters:
            f = filters["NOTIONAL"]
            if f.get("applyMinToMarket", True):
                min_notional = Decimal(f.get("minNotional", "0"))
        elif "MIN_NOTIONAL" in filters:
            f = filters["MIN_NOTIONAL"]
            if f.get("applyToMarket", True):
                min_notional = Decimal(f.get("minNotional", "0"))

        return cls(
            symbol=info["symbol"],
            base_asset=info["baseAsset"],
            quote_asset=info["quoteAsset"],
            step_size=step,
            min_qty=min_qty,
            max_qty=max_qty,
            min_notional=min_notional,
        )


def round_step(qty, step: Decimal) -> Decimal:
    """Redondea la cantidad HACIA ABAJO al múltiplo de step más cercano."""
    q = Decimal(str(qty))
    if step <= 0:
        return q
    return (q / step).to_integral_value(rounding=ROUND_DOWN) * step


def fmt_qty(qty) -> str:
    """Formatea sin notación científica ni ceros sobrantes (lo que espera la API)."""
    s = format(Decimal(str(qty)).normalize(), "f")
    return s if s else "0"


def adjust_quantity(rules: SymbolRules, qty, price: float) -> Tuple[Decimal, Optional[str]]:
    """Ajusta la cantidad a las reglas del par.

    Devuelve (cantidad_ajustada, error). Si error no es None, la orden no es válida
    y NO debe enviarse.
    """
    q = round_step(qty, rules.step_size)
    if q <= 0:
        return q, f"cantidad {qty} queda en 0 tras redondear a stepSize {rules.step_size}"
    if q < rules.min_qty:
        return q, f"cantidad {fmt_qty(q)} menor que el mínimo del par ({fmt_qty(rules.min_qty)})"
    if rules.max_qty > 0 and q > rules.max_qty:
        return q, f"cantidad {fmt_qty(q)} mayor que el máximo del par ({fmt_qty(rules.max_qty)})"
    notional = q * Decimal(str(price))
    if rules.min_notional > 0 and notional < rules.min_notional:
        return q, (f"valor de la orden {notional:.2f} {rules.quote_asset} menor que el "
                   f"mínimo del par ({rules.min_notional} {rules.quote_asset})")
    return q, None
