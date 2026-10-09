# -*- coding: utf-8 -*-
"""
Test long/short + cooldown sur 3 ans × 6 actifs (données déjà téléchargées).

Compare :
  1. Long-only (référence actuelle)
  2. Long/short (short quand SMA50 < SMA200)
  3. Long/short + cooldown 5 jours après une sortie perdante
  4. Long-only + cooldown 5 jours
"""

import csv
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from backtest.metrics import compute_metrics  # noqa: E402
from backtest.risk_engine import RiskManagedEngine  # noqa: E402
from backtest.strategies import SmaCross, SmaCrossLongShort  # noqa: E402

CLEAN_DIR = BASE_DIR / "data" / "clean"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"]
INITIAL_EQUITY = 10_000.0


def load_csv(path):
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {
        "open_time_iso": [r["open_time_iso"] for r in rows],
        "open_time": [int(r["open_time"]) for r in rows],
        "open": [float(r["open"]) for r in rows],
        "high": [float(r["high"]) for r in rows],
        "low": [float(r["low"]) for r in rows],
        "close": [float(r["close"]) for r in rows],
        "volume": [float(r["volume"]) for r in rows],
    }


def run(engine, data, strat_cls):
    strat = strat_cls(data, fast=50, slow=200)
    r = engine.run(data, strat, INITIAL_EQUITY)
    return compute_metrics(r["equity"], r["trades"], "1h", INITIAL_EQUITY)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    configs = [
        ("Long-only (réf)", SmaCross, RiskManagedEngine(fee_bps=10, slippage_bps=5)),
        ("Long/short", SmaCrossLongShort, RiskManagedEngine(fee_bps=10, slippage_bps=5)),
        ("Long/short + cooldown 5j", SmaCrossLongShort,
         RiskManagedEngine(fee_bps=10, slippage_bps=5, cooldown_bars=120)),
        ("Long-only + cooldown 5j", SmaCross,
         RiskManagedEngine(fee_bps=10, slippage_bps=5, cooldown_bars=120)),
    ]

    print("=== Long/short + cooldown sur 3 ans (moyenne sur 6 actifs) ===\n")
    for label, strat_cls, engine in configs:
        rets, sharpes, dds = [], [], []
        for sym in SYMBOLS:
            path = CLEAN_DIR / f"{sym}_1h_clean.csv"
            if not path.exists():
                print(f"  {sym}: données absentes, skip")
                continue
            m = run(engine, load_csv(path), strat_cls)
            rets.append(m["total_return_pct"])
            sharpes.append(m["sharpe"])
            dds.append(m["max_drawdown_pct"])
        if not rets:
            continue
        n_pos = sum(1 for r in rets if r > 0)
        print(f"{label:26s} | retour moyen {sum(rets)/len(rets):+7.2f}% | "
              f"Sharpe moy {sum(sharpes)/len(sharpes):5.2f} | "
              f"DD moy {sum(dds)/len(dds):5.2f}% | positifs {n_pos}/{len(rets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
