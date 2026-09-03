# -*- coding: utf-8 -*-
"""
Agent Risk — contrôle du risque et kill-switch (Phase 0, simulation).

Périmètre :
  - re-exécute les backtests de façon indépendante (re-joue le moteur) ;
  - alimente le RiskManager avec chaque courbe d'equity barre par barre ;
  - détecte les franchissements de limites et le déclenchement du kill-switch ;
  - produit un rapport de risque avec verdict par stratégie.

Contrat de l'agent :
  - Autonomie : droit de veto — peut REJETER seule toute stratégie hors limites ;
  - Escalade  : l'élargissement des limites globales remonte à l'humain.
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from backtest.engine import BacktestEngine  # noqa: E402
from backtest.strategies import STRATEGY_BUILDERS  # noqa: E402
from risk.limits import RiskLimits  # noqa: E402
from risk.manager import RiskManager  # noqa: E402

CLEAN_DIR = BASE_DIR / "data" / "clean"
REPORT_DIR = BASE_DIR / "data" / "reports"
INITIAL_EQUITY = 10_000.0


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


def verdict(rm: RiskManager) -> str:
    if rm.killed:
        return f"KILL-SWITCH ({rm.kill_reason})"
    if rm.summary()["total_return_pct"] < 0:
        return "REJETÉ (perte)"
    return "APPROUVÉ (limites respectées)"


def evaluate_risk(engine, data, limits, builder) -> dict:
    strat = builder(data)
    result = engine.run(data, strat, INITIAL_EQUITY)
    equity = result["equity"]
    times = data["open_time_iso"]

    rm = RiskManager(limits=limits, initial_equity=INITIAL_EQUITY)
    for i, v in enumerate(equity):
        ts = times[i] if i < len(times) else None
        rm.update(v, ts)

    return {
        "name": strat.name,
        "summary": rm.summary(),
        "verdict": verdict(rm),
        "kill_events": rm.events,
    }


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Agent Risk : limites + kill-switch.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--fee-bps", type=float, default=10.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--max-dd", type=float, default=20.0, help="Drawdown max (%%).")
    parser.add_argument("--max-daily-loss", type=float, default=5.0, help="Perte quotidienne max (%%).")
    parser.add_argument("--max-total-loss", type=float, default=30.0, help="Perte totale max (%%).")
    args = parser.parse_args(argv)

    clean_path = CLEAN_DIR / f"{args.symbol}_{args.interval}_clean.csv"
    if not clean_path.exists():
        print(f"[Agent Risk] Fichier introuvable : {clean_path}", file=sys.stderr)
        print("[Agent Risk] Lance d'abord l'Agent Data.", file=sys.stderr)
        return 2

    data = load_csv(clean_path)
    limits = RiskLimits(max_drawdown_pct=args.max_dd,
                        max_daily_loss_pct=args.max_daily_loss,
                        max_total_loss_pct=args.max_total_loss)
    engine = BacktestEngine(fee_bps=args.fee_bps, slippage_bps=args.slippage_bps)

    strategies = {}
    for key, builder in STRATEGY_BUILDERS:
        r = evaluate_risk(engine, data, limits, builder)
        strategies[r["name"]] = r
        print(f"[Agent Risk] {r['name']:20s} → verdict {r['verdict']:35s} "
              f"| DD max {r['summary']['max_drawdown_pct']:.2f}% "
              f"| kill={r['summary']['killed']}")

    report = {
        "symbol": args.symbol,
        "interval": args.interval,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "initial_equity": INITIAL_EQUITY,
        "limits": limits.to_dict(),
        "n_bars": len(data["close"]),
        "start": data["open_time_iso"][0] if data["close"] else None,
        "end": data["open_time_iso"][-1] if data["close"] else None,
        "strategies": strategies,
    }

    out_dir = REPORT_DIR / args.symbol
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"risk_{args.symbol}_{args.interval}_{stamp}.json"
    md_path = out_dir / f"risk_{args.symbol}_{args.interval}_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    print(f"[Agent Risk] Rapport JSON : {json_path}")
    print(f"[Agent Risk] Rapport MD   : {md_path}")
    return 0


def render_markdown(report: dict) -> str:
    lines = []
    lines.append(f"# Rapport de risque — {report['symbol']} {report['interval']}")
    lines.append(f"- Généré le : {report['generated_at']}")
    lines.append(f"- Barres : {report['n_bars']} — {report['start']} → {report['end']}")
    lines.append("- Limites : "
                 f"drawdown {report['limits']['max_drawdown_pct']}% · "
                 f"perte/jour {report['limits']['max_daily_loss_pct']}% · "
                 f"perte totale {report['limits']['max_total_loss_pct']}%")
    lines.append("")
    lines.append("| Stratégie | Retour % | DD max % | Kill-switch | Verdict |")
    lines.append("|---|---|---|---|---|")
    for name, r in report["strategies"].items():
        s = r["summary"]
        lines.append(f"| {name} | {s['total_return_pct']:+.2f} | {s['max_drawdown_pct']:.2f} "
                     f"| {'OUI' if s['killed'] else 'non'} | {r['verdict']} |")
    lines.append("")
    lines.append("> Le kill-switch est **indépendant** du code de trading : il bloque toute stratégie "
                 "dès qu'une limite est franchie. En Phase 0, il est simulé sur les backtests.")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
