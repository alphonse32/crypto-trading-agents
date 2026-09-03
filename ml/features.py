# -*- coding: utf-8 -*-
"""
Ingénierie de caractéristiques pour l'Agent ML.

Chaque caractéristique est calculée avec les données jusqu'à la barre i incluse
(aucune fuite future). Les valeurs manquantes (période d'amorçage) sont remplies
à 0 ; la standardisation est faite par l'Agent ML sur l'ensemble d'entraînement.
"""

from backtest.strategies import rolling_mean_std, rsi, sma  # noqa: E402

FEATURE_NAMES = [
    "ret_1", "ret_3", "ret_6", "ret_12", "ret_24",
    "vol_24", "rsi_14", "sma_ratio_20", "vol_ratio_20", "range_norm",
]


def build_features(data):
    """Renvoie une matrice X (liste de listes), une ligne par barre."""
    closes = data["close"]
    highs = data["high"]
    lows = data["low"]
    volumes = data["volume"]
    n = len(closes)

    rsi_vals = rsi(closes, 14)
    sma20 = sma(closes, 20)
    vol_sma20 = sma(volumes, 20)

    rets = [0.0] * n
    for i in range(1, n):
        rets[i] = closes[i] / closes[i - 1] - 1.0 if closes[i - 1] > 0 else 0.0
    _, vol_stds = rolling_mean_std(rets, 24)

    X = []
    for i in range(n):
        row = []
        # Rendements multi-horizons.
        for k in (1, 3, 6, 12, 24):
            row.append(closes[i] / closes[i - k] - 1.0 if i >= k and closes[i - k] > 0 else 0.0)
        # Volatilité réalisée (écart-type des rendements 1 barre sur 24).
        row.append(vol_stds[i] if vol_stds[i] is not None else 0.0)
        # RSI recentré sur [-1, 1].
        r = rsi_vals[i]
        row.append((r - 50.0) / 50.0 if r is not None else 0.0)
        # Ratio prix / SMA20 - 1 (position dans la tendance).
        s = sma20[i]
        row.append(closes[i] / s - 1.0 if s is not None and s > 0 else 0.0)
        # Ratio volume / SMA20(volume) - 1 (activité anormale).
        vs = vol_sma20[i]
        row.append(volumes[i] / vs - 1.0 if vs is not None and vs > 0 else 0.0)
        # Amplitude intra-barre normalisée.
        row.append((highs[i] - lows[i]) / closes[i] if closes[i] > 0 else 0.0)
        X.append(row)
    return X


def build_target(closes):
    """Cible binaire : 1 si la barre suivante monte (close[i+1] > close[i]), sinon 0."""
    n = len(closes)
    y = [0] * n
    for i in range(n - 1):
        y[i] = 1 if closes[i + 1] > closes[i] else 0
    return y
