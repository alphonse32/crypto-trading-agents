# -*- coding: utf-8 -*-
"""Métriques de performance et de risque (Phase 0)."""

import math

PERIODS_PER_YEAR = {
    "1m": 525_600, "5m": 105_120, "15m": 35_040, "30m": 17_520,
    "1h": 8_760, "4h": 2_190, "1d": 365, "1w": 52,
}


def periods_per_year(interval: str) -> int:
    return PERIODS_PER_YEAR.get(interval, 365)


def max_drawdown(equity) -> float:
    """Drawdown maximum (en fraction de la valeur, entre 0 et 1)."""
    if not equity:
        return 0.0
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > mdd:
                mdd = dd
    return mdd


def compute_metrics(equity, trades, interval, initial_equity) -> dict:
    """Calcule les métriques standard à partir de la courbe d'equity et des trades."""
    n = len(equity)
    returns = [
        equity[i] / equity[i - 1] - 1.0
        for i in range(1, n)
        if equity[i - 1] > 0
    ]

    total_return = equity[-1] / initial_equity - 1.0 if equity else 0.0
    ppy = periods_per_year(interval)

    if n > 1 and equity[0] > 0 and total_return > -1.0:
        ann_return = (equity[-1] / equity[0]) ** (ppy / (n - 1)) - 1.0
    else:
        ann_return = 0.0

    if len(returns) > 1:
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(var)
        sharpe = (mean / std) * math.sqrt(ppy) if std > 0 else 0.0
    else:
        sharpe = 0.0

    mdd = max_drawdown(equity)

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in losses)
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    win_rate = len(wins) / len(trades) if trades else 0.0

    return {
        "total_return_pct": round(total_return * 100, 3),
        "annualized_return_pct": round(ann_return * 100, 3),
        "sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(mdd * 100, 3),
        "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else None,
        "win_rate_pct": round(win_rate * 100, 3),
        "num_trades": len(trades),
        "final_equity": round(equity[-1], 2) if equity else round(initial_equity, 2),
    }
