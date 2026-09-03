# -*- coding: utf-8 -*-
"""
Bibliothèque de stratégies. Chaque stratégie expose `signal(i) -> {-1, 0, +1}`.

`signal(i)` est calculé avec les données jusqu'à la clôture de la barre i INCLUSE.
Le moteur l'utilise pour négocier à l'ouverture de la barre i+1 (pas de look-ahead).

Note (Phase 0) : les stratégies sont "stateless" (le signal ne dépend que des
données passées). Les stratégies de mean-reversion sortent donc dès que la
condition d'entrée disparaît (approximation volontaire, à affiner plus tard).
"""


def sma(values, window):
    """Moyenne mobile simple. Renvoie None tant que la fenêtre n'est pas remplie."""
    out = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= window:
            s -= values[i - window]
        if i >= window - 1:
            out[i] = s / window
    return out


def ema(values, period):
    """Moyenne mobile exponentielle (facteur 2/(period+1))."""
    out = [None] * len(values)
    if not values:
        return out
    k = 2.0 / (period + 1)
    prev = None
    for i, v in enumerate(values):
        if prev is None:
            prev = v  # amorçage sur la première valeur
        else:
            prev = v * k + prev * (1 - k)
        out[i] = prev
    # Les `period` premières valeurs sont peu fiables ; on les laisse None.
    for i in range(min(period - 1, len(out))):
        out[i] = None
    return out


def rsi(values, period=14):
    """RSI de Wilder. Renvoie None tant que le RSI n'est pas calculable."""
    out = [None] * len(values)
    if len(values) <= period:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period + 1, len(values)):
        diff = values[i] - values[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def rolling_mean_std(values, window):
    """Moyenne et écart-type glissants (fenêtre). Renvoie (means, stds) avec None au début."""
    means = [None] * len(values)
    stds = [None] * len(values)
    s = 0.0
    s2 = 0.0
    for i, v in enumerate(values):
        s += v
        s2 += v * v
        if i >= window:
            s -= values[i - window]
            s2 -= values[i - window] * values[i - window]
        if i >= window - 1:
            m = s / window
            var = s2 / window - m * m
            means[i] = m
            stds[i] = var ** 0.5 if var > 0 else 0.0
    return means, stds


def atr(data, period=14):
    """Average True Range (lissage de Wilder). Renvoie None au début."""
    highs = data["high"]
    lows = data["low"]
    closes = data["close"]
    n = len(closes)
    out = [None] * n
    if n == 0:
        return out
    trs = [0.0] * n
    trs[0] = highs[0] - lows[0]
    for i in range(1, n):
        trs[i] = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
    out[period - 1] = sum(trs[:period]) / period
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + trs[i]) / period
    return out


class BuyHold:
    """Benchmark : acheter au début et conserver (position longue permanente)."""

    def __init__(self, data=None):
        self.name = "BUY_HOLD"

    def signal(self, i):
        return 1


class SmaCross:
    """Croisement de moyennes mobiles : long si SMA rapide > SMA lente, sinon flat."""

    def __init__(self, data, fast=20, slow=50):
        self.fast_sma = sma(data["close"], fast)
        self.slow_sma = sma(data["close"], slow)
        self.name = f"SMA_CROSS_{fast}_{slow}"

    def signal(self, i):
        f, s = self.fast_sma[i], self.slow_sma[i]
        if f is None or s is None:
            return 0
        return 1 if f > s else 0


class EmaCross:
    """Croisement de moyennes mobiles exponentielles (tendance)."""

    def __init__(self, data, fast=12, slow=26):
        self.fast_ema = ema(data["close"], fast)
        self.slow_ema = ema(data["close"], slow)
        self.name = f"EMA_CROSS_{fast}_{slow}"

    def signal(self, i):
        f, s = self.fast_ema[i], self.slow_ema[i]
        if f is None or s is None:
            return 0
        return 1 if f > s else 0


class Momentum:
    """Momentum : long si le prix est au-dessus de sa valeur il y a `lookback` barres."""

    def __init__(self, data, lookback=24):
        self.close = data["close"]
        self.lookback = lookback
        self.name = f"MOMENTUM_{lookback}"

    def signal(self, i):
        if i < self.lookback or self.close[i - self.lookback] <= 0:
            return 0
        return 1 if self.close[i] > self.close[i - self.lookback] else 0


class RsiReversion:
    """Mean-reversion : long quand le RSI est en zone de survente (achat de la baisse)."""

    def __init__(self, data, period=14, oversold=30.0):
        self.rsi = rsi(data["close"], period)
        self.oversold = oversold
        self.name = f"RSI_REVERSION_{period}"

    def signal(self, i):
        r = self.rsi[i]
        if r is None:
            return 0
        return 1 if r < self.oversold else 0


class BollingerReversion:
    """Mean-reversion : long quand le prix clôture sous la bande de Bollinger inférieure."""

    def __init__(self, data, period=20, num_std=2.0):
        self.close = data["close"]
        self.means, self.stds = rolling_mean_std(data["close"], period)
        self.num_std = num_std
        self.name = f"BB_REVERSION_{period}"

    def signal(self, i):
        m, s = self.means[i], self.stds[i]
        if m is None or s is None:
            return 0
        lower = m - self.num_std * s
        return 1 if self.close[i] < lower else 0


class DonchianBreakout:
    """Tendance : long sur cassure du plus-haut N barres, sortie sur cassure du plus-bas."""

    def __init__(self, data, period=20):
        self.high = data["high"]
        self.low = data["low"]
        self.close = data["close"]
        self.period = period
        self.name = f"DONCHIAN_BREAKOUT_{period}"

    def signal(self, i):
        if i < self.period:
            return 0
        upper = max(self.high[i - self.period:i])
        lower = min(self.low[i - self.period:i])
        c = self.close[i]
        if c >= upper:
            return 1
        if c <= lower:
            return 0
        mid = (upper + lower) / 2.0
        return 1 if c > mid else 0


# Constructeurs utilisés par les Agents Research/Risk (chacun reçoit le dict de données).
STRATEGY_BUILDERS = [
    ("BuyHold", lambda d: BuyHold(d)),
    ("SmaCross", lambda d: SmaCross(d, fast=20, slow=50)),
    ("SmaCross1030", lambda d: SmaCross(d, fast=10, slow=30)),
    ("SmaCross50200", lambda d: SmaCross(d, fast=50, slow=200)),
    ("EmaCross", lambda d: EmaCross(d, fast=12, slow=26)),
    ("Momentum", lambda d: Momentum(d, lookback=24)),
    ("Momentum72", lambda d: Momentum(d, lookback=72)),
    ("RsiReversion", lambda d: RsiReversion(d, period=14, oversold=30.0)),
    ("BollingerReversion", lambda d: BollingerReversion(d, period=20, num_std=2.0)),
    ("DonchianBreakout", lambda d: DonchianBreakout(d, period=20)),
]
