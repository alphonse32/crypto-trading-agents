# -*- coding: utf-8 -*-
"""
Agent Exécution (paper trading) — dry-run de la chaîne d'ordres en simulation.

Simule le flux : signal → validation Risk (check_order) → fill simulé → journal.
Rejoue des données historiques "comme si" elles étaient live. Aucun ordre réel,
aucun capital engagé. C'est le squelette de la Phase 1 (paper trading).

Contrat de l'agent :
  - Autonomie : exécute UNIQUEMENT ce que Risk a validé ;
  - Escalade  : aucun ordre sans validation, aucun capital réel.
"""

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from backtest.strategies import BuyHold, Momentum, SmaCross  # noqa: E402
from risk.limits import RiskLimits  # noqa: E402
from risk.manager import RiskManager  # noqa: E402

CLEAN_DIR = BASE_DIR / "data" / "clean"
REPORT_DIR = BASE_DIR / "data" / "reports"
INITIAL_EQUITY = 10_000.0

STRATEGIES = {"buyhold": BuyHold, "sma": SmaCross, "momentum": Momentum}


def load_csv(path: Path) -> dict:
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


def run_paper(data, strategy, limits, fee_bps, slippage_bps) -> dict:
    fee_rate = fee_bps / 10000.0
    slippage = slippage_bps / 10000.0
    opens = data["open"]
    closes = data["close"]
    times = data["open_time_iso"]
    n = len(closes)

    rm = RiskManager(limits=limits, initial_equity=INITIAL_EQUITY)
    position = 0
    entry_price = 0.0
    entry_equity = 0.0
    equity = INITIAL_EQUITY
    journal = []

    def _mtm(close):
        if position == 1:
            return entry_equity * (close / entry_price)
        if position == -1:
            return entry_equity * (2.0 - close / entry_price)
        return equity

    def _exit(px, ts):
        nonlocal position, equity, entry_price, entry_equity
        realized = ((entry_equity * (px / entry_price)) if position == 1
                    else (entry_equity * (2.0 - px / entry_price))) * (1.0 - fee_rate)
        journal.append({"time": ts, "action": "EXIT", "side": position,
                        "price": round(px, 8), "equity_after": round(realized, 2)})
        equity = realized
        position = 0
        entry_price = 0.0
        entry_equity = 0.0

    def _entry(target, px, ts):
        nonlocal position, entry_price, entry_equity
        fill = px * (1.0 + slippage * target)
        entry_price = fill
        entry_equity = equity * (1.0 - fee_rate)
        position = target
        journal.append({"time": ts, "action": "ENTRY", "side": target,
                        "price": round(fill, 8), "equity_after": round(equity, 2)})

    for i in range(n):
        target = strategy.signal(i - 1) if i >= 1 else strategy.signal(0)
        if target != position:
            check = rm.check_order(target, rm.equity)
            journal.append({"time": times[i], "action": "CHECK", "target": target,
                            "allowed": check["allowed"], "reason": check["reason"]})
            if check["allowed"]:
                px = opens[i]
                if position != 0:
                    exit_px = px * (1.0 - slippage * position)
                    _exit(exit_px, times[i])
                if target != 0:
                    _entry(target, px, times[i])

        mv = _mtm(closes[i])
        rm.update(mv, times[i])
        if rm.killed:
            journal.append({"time": times[i], "action": "KILL_SWITCH",
                            "reason": rm.kill_reason})
            if position != 0:
                _exit(closes[i], times[i])
            break

    return {"journal": journal, "summary": rm.summary(),
            "final_equity": round(equity, 2)}


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Agent Exécution : dry-run paper trading.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--strategy", default="sma", choices=sorted(STRATEGIES))
    parser.add_argument("--fee-bps", type=float, default=10.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    args = parser.parse_args(argv)

    clean_path = CLEAN_DIR / f"{args.symbol}_{args.interval}_clean.csv"
    if not clean_path.exists():
        print(f"[Agent Exécution] Fichier introuvable : {clean_path}", file=sys.stderr)
        return 2

    data = load_csv(clean_path)
    cls = STRATEGIES[args.strategy]
    strategy = cls(data)
    limits = RiskLimits()

    result = run_paper(data, strategy, limits, args.fee_bps, args.slippage_bps)
    s = result["summary"]

    print(f"[Agent Exécution] Stratégie : {strategy.name} (paper dry-run)")
    print(f"[Agent Exécution] Ordres journalisés : {len(result['journal'])}")
    print(f"[Agent Exécution] Equity finale : {result['final_equity']} $ "
          f"({s['total_return_pct']:+.2f} %)")
    print(f"[Agent Exécution] Kill-switch : {s['killed']} ({s['kill_reason'] or '-'})")

    # Journal (derniers événements) + export complet.
    out_dir = REPORT_DIR / args.symbol
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    journal_path = out_dir / f"paper_{args.symbol}_{args.interval}_{strategy.name}_{stamp}.csv"
    with journal_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["time", "action", "target", "side", "allowed",
                                          "reason", "price", "equity_after"])
        w.writeheader()
        for e in result["journal"]:
            w.writerow({k: e.get(k, "") for k in w.fieldnames})
    print(f"[Agent Exécution] Journal : {journal_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
