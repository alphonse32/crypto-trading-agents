# -*- coding: utf-8 -*-
"""
Validation multi-actifs du candidat SMA 50/200 (baseline vs volatility targeting).

Répond à : l'edge tient-il sur d'autres cryptos, ou seulement sur BTC (sur-ajustement) ?
Pour chaque actif : 6 mois de 1h, frais inclus, comparaison avec le buy & hold,
et découpage in-sample / out-of-sample (70/30).
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from agents.data_agent import _ms_to_iso, fetch_klines  # noqa: E402
from backtest.metrics import compute_metrics  # noqa: E402
from backtest.risk_engine import RiskManagedEngine  # noqa: E402
from backtest.strategies import SmaCross, atr  # noqa: E402

INITIAL_EQUITY = 10_000.0
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"]
REPORT_DIR = BASE_DIR / "data" / "reports"


def candles_to_data(candles):
    return {
        "open_time_iso": [_ms_to_iso(c["open_time"]) for c in candles],
        "open_time": [c["open_time"] for c in candles],
        "open": [c["open"] for c in candles],
        "high": [c["high"] for c in candles],
        "low": [c["low"] for c in candles],
        "close": [c["close"] for c in candles],
        "volume": [c["volume"] for c in candles],
    }


def slice_data(data, start, end):
    return {k: v[start:end] for k, v in data.items()}


def buyhold_return(data):
    c = data["close"]
    return (c[-1] / c[0] - 1.0) * 100 if c and c[0] > 0 else 0.0


def run(engine, data):
    strat = SmaCross(data, fast=50, slow=200)
    result = engine.run(data, strat, INITIAL_EQUITY)
    return compute_metrics(result["equity"], result["trades"], "1h", INITIAL_EQUITY)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Validation multi-actifs SMA 50/200.")
    parser.add_argument("--days", type=float, default=180.0)
    args = parser.parse_args(argv)

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - int(args.days * 86_400_000)

    print(f"=== Validation multi-actifs (SMA 50/200, {args.days:.0f} jours, 1h) ===\n")
    print(f"{'Actif':10s} | {'BuyHold%':>8s} | {'SMA base%':>9s} {'Sharpe':>7s} {'DD%':>6s} | "
          f"{'SMA vol0.5%':>11s} {'Sharpe':>7s} {'DD%':>6s} | {'OOS vol0.5%':>10s}")

    rows = []
    for sym in SYMBOLS:
        try:
            candles = fetch_klines(sym, "1h", start_ms, now_ms)
        except Exception as exc:  # noqa: BLE001
            print(f"{sym:10s} | ERREUR fetch: {exc}")
            continue
        if len(candles) < 500:
            print(f"{sym:10s} | données insuffisantes ({len(candles)})")
            continue

        data = candles_to_data(candles)
        atr_vals = atr(data, 14)
        base = RiskManagedEngine(fee_bps=10, slippage_bps=5)
        vol = RiskManagedEngine(fee_bps=10, slippage_bps=5, atr_values=atr_vals,
                                vol_target_pct=0.5, max_size_pct=1.0)

        bh = buyhold_return(data)
        mb = run(base, data)
        mv = run(vol, data)

        # Out-of-sample : dernière 30 % des données.
        n = len(data["close"])
        split = int(n * 0.7)
        oos_data = slice_data(data, split, n)
        oos_atr = atr(oos_data, 14)
        vol_oos = RiskManagedEngine(fee_bps=10, slippage_bps=5, atr_values=oos_atr,
                                    vol_target_pct=0.5, max_size_pct=1.0)
        mo = run(vol_oos, oos_data)

        print(f"{sym:10s} | {bh:+8.1f} | {mb['total_return_pct']:+9.1f} {mb['sharpe']:7.2f} "
              f"{mb['max_drawdown_pct']:6.1f} | {mv['total_return_pct']:+11.1f} "
              f"{mv['sharpe']:7.2f} {mv['max_drawdown_pct']:6.1f} | {mo['total_return_pct']:+10.1f}")

        rows.append({"symbol": sym, "buy_hold_pct": round(bh, 2),
                     "sma_base": mb, "sma_vol05": mv, "oos_vol05": mo})

    # Synthèse.
    n_pos = sum(1 for r in rows if r["sma_vol05"]["total_return_pct"] > 0)
    n_beat_bh = sum(1 for r in rows if r["sma_vol05"]["total_return_pct"] > r["buy_hold_pct"])
    print(f"\nSynthèse : SMA vol0.5 positif sur {n_pos}/{len(rows)} actifs, "
          f"bat le buy&hold sur {n_beat_bh}/{len(rows)} actifs.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = REPORT_DIR / "multi_asset"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"multi_asset_{stamp}.json"
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[Rapport] {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
