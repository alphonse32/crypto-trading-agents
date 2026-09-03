# -*- coding: utf-8 -*-
"""
Test de résistance multi-régimes : 3 ans × 6 actifs, SMA 50/200 + volatility targeting.

Répond à : l'edge survit-il à un bear market et à des phases de range, ou
s'agit-il simplement d'un artefact de 6 mois de marché haussier ?
Pour chaque actif : full période + rentabilité annuelle, frais inclus.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from agents.data_agent import _ms_to_iso, fetch_klines, write_csv  # noqa: E402
from backtest.metrics import compute_metrics  # noqa: E402
from backtest.risk_engine import RiskManagedEngine  # noqa: E402
from backtest.strategies import SmaCross, atr  # noqa: E402

INITIAL_EQUITY = 10_000.0
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"]
CLEAN_DIR = BASE_DIR / "data" / "clean"
REPORT_DIR = BASE_DIR / "data" / "reports" / "multi_asset"


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


def _year(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).year


def run(data, engine):
    strat = SmaCross(data, fast=50, slow=200)
    r = engine.run(data, strat, INITIAL_EQUITY)
    return compute_metrics(r["equity"], r["trades"], "1h", INITIAL_EQUITY)


def yearly_returns(data):
    years = sorted({_year(t) for t in data["open_time"]})
    out = {}
    for y in years:
        idx = [i for i, t in enumerate(data["open_time"]) if _year(t) == y]
        if len(idx) < 500:
            continue
        sub = {k: [v[i] for i in idx] for k, v in data.items()}
        eng = RiskManagedEngine(fee_bps=10, slippage_bps=5, atr_values=atr(sub, 14),
                                vol_target_pct=0.5, max_size_pct=1.0)
        out[y] = round(run(sub, eng)["total_return_pct"], 1)
    return out


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Test multi-régimes SMA 50/200.")
    parser.add_argument("--years", type=float, default=3.0)
    args = parser.parse_args(argv)

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - int(args.years * 365 * 86_400_000)
    print(f"=== Test multi-régimes : {args.years:.0f} ans × {len(SYMBOLS)} actifs (SMA 50/200) ===\n")

    results = []
    print(f"{'Actif':9s} | {'BuyHold%':>8s} | {'Base%':>8s} {'Sh':>6s} {'DD%':>6s} | "
          f"{'Vol0.5%':>8s} {'Sh':>6s} {'DD%':>6s} | Rentabilité annuelle vol0.5")

    for sym in SYMBOLS:
        try:
            candles = fetch_klines(sym, "1h", start_ms, now_ms)
        except Exception as exc:  # noqa: BLE001
            print(f"{sym:9s} | ERREUR fetch : {exc}")
            continue
        if len(candles) < 3000:
            print(f"{sym:9s} | données insuffisantes ({len(candles)})")
            continue

        write_csv(CLEAN_DIR / f"{sym}_1h_clean.csv", candles)
        data = candles_to_data(candles)
        bh = (data["close"][-1] / data["close"][0] - 1) * 100 if data["close"][0] > 0 else 0.0

        base_eng = RiskManagedEngine(fee_bps=10, slippage_bps=5)
        vol_eng = RiskManagedEngine(fee_bps=10, slippage_bps=5, atr_values=atr(data, 14),
                                    vol_target_pct=0.5, max_size_pct=1.0)
        mb = run(data, base_eng)
        mv = run(data, vol_eng)
        yr = yearly_returns(data)
        yr_str = "  ".join(f"{y}:{v:+.0f}%" for y, v in yr.items())

        print(f"{sym:9s} | {bh:+8.1f} | {mb['total_return_pct']:+8.1f} {mb['sharpe']:6.2f} "
              f"{mb['max_drawdown_pct']:6.1f} | {mv['total_return_pct']:+8.1f} {mv['sharpe']:6.2f} "
              f"{mv['max_drawdown_pct']:6.1f} | {yr_str}")

        results.append({"symbol": sym, "n_bars": len(candles), "buy_hold_pct": round(bh, 2),
                        "base": mb, "vol05": mv, "yearly_vol05": yr})

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / f"multi_regime_{stamp}.json"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[Rapport] {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
