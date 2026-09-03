# -*- coding: utf-8 -*-
"""
Validation empirique des recommandations (volatility targeting + filtre de tendance)
sur le candidat SMA 50/200.
"""

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from backtest.metrics import compute_metrics  # noqa: E402
from backtest.risk_engine import RiskManagedEngine, TrendStrengthFilter  # noqa: E402
from backtest.strategies import SmaCross, atr  # noqa: E402

CLEAN_DIR = BASE_DIR / "data" / "clean"
REPORT_DIR = BASE_DIR / "data" / "reports"
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


def run_config(engine, data, label):
    strat = SmaCross(data, fast=50, slow=200)
    result = engine.run(data, strat, INITIAL_EQUITY)
    m = compute_metrics(result["equity"], result["trades"], "1h", INITIAL_EQUITY)
    m["label"] = label
    m["reasons"] = dict(Counter(t["reason"] for t in result["trades"]))
    m["avg_trade_pct"] = round(sum(t["return_pct"] for t in result["trades"]) / len(result["trades"]) * 100, 3) \
        if result["trades"] else 0.0
    return m


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Validation empirique des améliorations.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    args = parser.parse_args(argv)

    clean_path = CLEAN_DIR / f"{args.symbol}_{args.interval}_clean.csv"
    if not clean_path.exists():
        print(f"[Améliorations] Fichier introuvable : {clean_path}", file=sys.stderr)
        return 2

    data = load_csv(clean_path)
    atr_vals = atr(data, 14)

    configs = [
        ("Baseline (tout-ou-rien)",
         RiskManagedEngine(fee_bps=10, slippage_bps=5)),

        ("Filtre force tendance 0.3",
         RiskManagedEngine(fee_bps=10, slippage_bps=5,
                           trade_filter=TrendStrengthFilter(data, fast=50, slow=200,
                                                            atr_values=atr_vals, threshold=0.3))),

        ("Volatility targeting 1%",
         RiskManagedEngine(fee_bps=10, slippage_bps=5, atr_values=atr_vals,
                           vol_target_pct=1.0, max_size_pct=1.0)),

        ("Volatility targeting 0.75%",
         RiskManagedEngine(fee_bps=10, slippage_bps=5, atr_values=atr_vals,
                           vol_target_pct=0.75, max_size_pct=1.0)),

        ("Volatility targeting 0.5%",
         RiskManagedEngine(fee_bps=10, slippage_bps=5, atr_values=atr_vals,
                           vol_target_pct=0.5, max_size_pct=1.0)),

        ("Vol target 1% + force tendance 0.3",
         RiskManagedEngine(fee_bps=10, slippage_bps=5, atr_values=atr_vals,
                           vol_target_pct=1.0, max_size_pct=1.0,
                           trade_filter=TrendStrengthFilter(data, fast=50, slow=200,
                                                            atr_values=atr_vals, threshold=0.3))),
    ]

    print(f"=== Validation empirique sur {args.symbol} {args.interval} (SMA 50/200) ===\n")
    results = []
    for label, engine in configs:
        m = run_config(engine, data, label)
        results.append(m)
        print(f"{label:34s} | retour {m['total_return_pct']:+8.2f}% | Sharpe {m['sharpe']:6.2f} "
              f"| DD {m['max_drawdown_pct']:6.2f}% | PF {str(m['profit_factor']):>5} "
              f"| trades {m['num_trades']:3d} | {m['reasons']}")

    out_dir = REPORT_DIR / args.symbol
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"improvements_{args.symbol}_{args.interval}_{stamp}.json"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[Améliorations] Rapport : {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
