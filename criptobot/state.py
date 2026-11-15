"""Estado persistente del bot (posición abierta y última vela procesada).

Se guarda en un archivo por modo (state_paper.json, state_testnet.json,
state_live.json) para que una posición simulada nunca se confunda con una real.
La escritura es atómica: si el PC se apaga a mitad, no queda un archivo corrupto.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger("bot")


@dataclass
class Position:
    symbol: str
    qty: float            # cantidad neta del activo base en posesión
    entry_price: float    # precio medio de entrada
    entry_cost: float     # total gastado en moneda de cotización (incl. comisiones)
    entry_time: int       # ms


@dataclass
class BotState:
    position: Optional[Position] = None
    last_candle: Dict[str, int] = field(default_factory=dict)  # "SYMBOL:interval" -> open_time
    realized_pnl: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "BotState":
        pos = d.get("position")
        return cls(
            position=Position(**pos) if pos else None,
            last_candle=dict(d.get("last_candle", {})),
            realized_pnl=float(d.get("realized_pnl", 0.0)),
        )


def state_path(base_dir: Path, mode: str) -> Path:
    return base_dir / f"state_{mode}.json"


def load_state(path: Path) -> BotState:
    if not path.exists():
        return BotState()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return BotState.from_dict(json.load(f))
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        backup = path.with_suffix(".corrupt.json")
        os.replace(path, backup)
        log.error("El archivo de estado %s estaba dañado (%s). Se movió a %s y se "
                  "empieza sin posición. REVISA tu saldo en Binance.", path, e, backup)
        return BotState()


def save_state(path: Path, state: BotState) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
