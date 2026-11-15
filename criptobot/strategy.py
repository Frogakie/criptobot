"""Estrategia: cruce de medias móviles simples (SMA crossover)."""


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def signal_sma_crossover(closes, fast_p, slow_p):
    """Devuelve 'BUY', 'SELL' o None según el cruce de SMAs."""
    fast_now, slow_now = sma(closes, fast_p), sma(closes, slow_p)
    fast_prev, slow_prev = sma(closes[:-1], fast_p), sma(closes[:-1], slow_p)
    if None in (fast_now, slow_now, fast_prev, slow_prev):
        return None
    if fast_prev <= slow_prev and fast_now > slow_now:
        return "BUY"
    if fast_prev >= slow_prev and fast_now < slow_now:
        return "SELL"
    return None
