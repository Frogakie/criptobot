"""Descarga de velas históricas de Binance con caché local en CSV."""

import csv
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import requests

from .client import Candle

log = logging.getLogger("bot")

# Los datos de mercado siempre vienen de Binance real (los de testnet no son fiables).
MARKET_DATA_URL = "https://api.binance.com"
MAX_LIMIT = 1000

CSV_HEADER = ["open_time", "open", "high", "low", "close", "volume", "close_time"]


def parse_date(s: str) -> int:
    """'2024-01-31' o '2024-01-31 14:00' (UTC) → milisegundos."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    raise ValueError(f"Fecha inválida: {s!r} (usa AAAA-MM-DD o 'AAAA-MM-DD HH:MM')")


def fmt_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def download_klines(symbol: str, interval: str, start_ms: int, end_ms: int,
                    session: Optional[requests.Session] = None,
                    base_url: str = MARKET_DATA_URL, pause: float = 0.2) -> List[Candle]:
    """Descarga todas las velas CERRADAS entre start_ms y end_ms, paginando de 1000 en 1000."""
    session = session or requests.Session()
    now = int(time.time() * 1000)
    candles: List[Candle] = []
    cursor = start_ms
    while cursor < end_ms:
        r = session.get(f"{base_url}/api/v3/klines", params={
            "symbol": symbol, "interval": interval, "limit": MAX_LIMIT,
            "startTime": cursor, "endTime": end_ms,
        }, timeout=15)
        r.raise_for_status()
        batch = [Candle.from_api(k) for k in r.json()]
        if not batch:
            break
        candles.extend(batch)
        log.info("Descargadas %d velas (hasta %s)", len(candles), fmt_ms(batch[-1].open_time))
        cursor = batch[-1].open_time + 1
        if len(batch) < MAX_LIMIT:
            break
        if pause:
            time.sleep(pause)
    return [c for c in candles if c.close_time < now and c.open_time < end_ms]


def save_csv(path: Path, candles: List[Candle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for c in candles:
            w.writerow([c.open_time, c.open, c.high, c.low, c.close, c.volume, c.close_time])


def load_csv(path: Path) -> List[Candle]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [Candle(int(r["open_time"]), float(r["open"]), float(r["high"]),
                       float(r["low"]), float(r["close"]), float(r["volume"]),
                       int(r["close_time"])) for r in reader]


def load_or_download(symbol: str, interval: str, start_ms: int, end_ms: int,
                     cache_dir: Path, use_cache: bool = True,
                     session: Optional[requests.Session] = None) -> List[Candle]:
    path = cache_dir / f"{symbol}_{interval}_{start_ms}_{end_ms}.csv"
    if use_cache and path.exists():
        log.info("Usando velas en caché: %s", path)
        return load_csv(path)
    candles = download_klines(symbol, interval, start_ms, end_ms, session=session)
    if candles:
        save_csv(path, candles)
    return candles
