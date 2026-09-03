# -*- coding: utf-8 -*-
"""
Agent Research — génère, backteste et évalue des stratégies (Phase 0, simulation).

Périmètre :
  - charger les données nettoyées produites par l'Agent Data ;
  - backtester plusieurs stratégies avec coûts réalistes (frais + slippage) ;
  - calculer les métriques (Sharpe, drawdown, profit factor, win rate) ;
  - évaluer en échantillon / hors échantillon (dégradation) ;
  - produire un rapport JSON + Markdown.

Contrat de l'agent :
  - Autonomie : rejette seul les stratégies manifestement mauvaises ;
  - Escalade  : aucune promotion vers paper trading sans accord Risk + Ordonnanceur.
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
from backtest.metrics import compute_metrics  # noqa: E402
from backtest.strategies import STRATEGY_BUILDERS  # noqa: E402

CLEAN_DIR = BASE_DIR / "data" / "clean"
REPORT_DIR = BASE_DIR / "data" / "reports"

INITIAL_EQUITY = 10_000.0
# Nombre minimal de barres pour qu'une décision de promotion ait un sens
# (~6 mois de chandeliers 1h). En dessous, la décision est "INSUFFISANT".
MIN_BARS_FOR_PROMOTION = 4_000


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


def slice_data(data: dict, start: int, end: int) -> dict:
    return {k: v[start:end] for k, v in data.items()}


def evaluate(engine, data, interval, builder) -> dict:
    strat = builder(data)
    result = engine.run(data, strat, INITIAL_EQUITY)
    metrics = compute_metrics(result["equity"], result["trades"], interval, INITIAL_EQUITY)
    return {"name": strat.name, "metrics": metrics}


def classify(metrics: dict, n_bars: int) -> str:
    """Décision de promotion fondée sur les seuils du §6 du document d'équipe."""
    if n_bars < MIN_BARS_FOR_PROMOTION:
        return "INSUFFISANT (données)"
    if (metrics["sharpe"] > 1.0
            and metrics["max_drawdown_pct"] < 20.0
            and (metrics["profit_factor"] is None or metrics["profit_factor"] > 1.3)):
        return "PROMOUVOIR"
    return "REJETER"


def build_report(args, data, results, interval) -> dict:
    n = len(data["close"])
    span_days = (data["open_time"][-1] - data["open_time"][0]) / 86_400_000 if n else 0
    report = {
        "symbol": args.symbol,
        "interval": interval,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fee_bps": args.fee_bps,
        "slippage_bps": args.slippage_bps,
        "initial_equity": INITIAL_EQUITY,
        "n_bars": n,
        "span_days": round(span_days, 2),
        "start": data["open_time_iso"][0] if n else None,
        "end": data["open_time_iso"][-1] if n else None,
        "strategies": results,
    }
    return report


def write_report(report: dict) -> tuple:
    symbol = report["symbol"]
    out_dir = REPORT_DIR / symbol
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    interval = report["interval"]

    json_path = out_dir / f"backtest_{symbol}_{interval}_{stamp}.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    md_path = out_dir / f"backtest_{symbol}_{interval}_{stamp}.md"
    md = render_markdown(report)
    md_path.write_text(md, encoding="utf-8")

    return json_path, md_path


def render_markdown(report: dict) -> str:
    lines = []
    lines.append(f"# Rapport de backtest — {report['symbol']} {report['interval']}")
    lines.append(f"- Généré le : {report['generated_at']}")
    lines.append(f"- Barres : {report['n_bars']} ({report['span_days']} jours) — {report['start']} → {report['end']}")
    lines.append(f"- Frais : {report['fee_bps']} bps/côté · Slippage : {report['slippage_bps']} bps/côté")
    lines.append(f"- Capital initial : {report['initial_equity']:,.0f} $ (simulation)")
    lines.append("")
    lines.append("| Stratégie | Période | Retour % | Sharpe | Drawdown % | PF | Win % | Trades | Verdict |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    for name, periods in report["strategies"].items():
        for period, m in periods.items():
            if m is None:
                continue
            verdict = m.pop("verdict", "-") if isinstance(m, dict) else "-"
            pf = m.get("profit_factor")
            pf_s = "-" if pf is None else f"{pf:.2f}"
            lines.append(
                f"| {name} | {period} | {m['total_return_pct']:+.2f} | {m['sharpe']:.2f} "
                f"| {m['max_drawdown_pct']:.2f} | {pf_s} | {m['win_rate_pct']:.0f} "
                f"| {m['num_trades']} | {verdict} |"
            )

    lines.append("")
    if report["n_bars"] < MIN_BARS_FOR_PROMOTION:
        lines.append(f"> **Note** : {report['n_bars']} barres < {MIN_BARS_FOR_PROMOTION} barres → "
                     "données insuffisantes pour toute décision de promotion. Le rapport valide le "
                     "pipeline, pas une décision de trading.")
    else:
        lines.append(f"> **Note** : {report['n_bars']} barres >= {MIN_BARS_FOR_PROMOTION} barres → "
                     "les verdicts sont calculés selon les seuils du §6 (Sharpe > 1, "
                     "drawdown < 20 %, profit factor > 1,3). Aucune promotion sans accord Risk + Ordonnanceur.")
    return "\n".join(lines)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Agent Research : backtest et évaluation de stratégies crypto."
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--fee-bps", type=float, default=10.0, help="Frais taker par côté en bps (10 = 0,10%%).")
    parser.add_argument("--slippage-bps", type=float, default=5.0, help="Slippage par côté en bps (5 = 0,05%%).")
    parser.add_argument("--split", type=float, default=0.7, help="Part in-sample (défaut 0.7).")
    args = parser.parse_args(argv)

    clean_path = CLEAN_DIR / f"{args.symbol}_{args.interval}_clean.csv"
    if not clean_path.exists():
        print(f"[Agent Research] Fichier introuvable : {clean_path}", file=sys.stderr)
        print("[Agent Research] Lance d'abord l'Agent Data : python agents\\data_agent.py "
              f"--symbol {args.symbol} --interval {args.interval}", file=sys.stderr)
        return 2

    data = load_csv(clean_path)
    n = len(data["close"])
    if n < 30:
        print("[Agent Research] Trop peu de barres pour un backtest significatif.", file=sys.stderr)
        return 2

    engine = BacktestEngine(fee_bps=args.fee_bps, slippage_bps=args.slippage_bps)

    results = {}
    for key, builder in STRATEGY_BUILDERS:
        full = evaluate(engine, data, args.interval, builder)
        entry = {"full": full["metrics"]}
        entry["full"]["verdict"] = classify(full["metrics"], n)

        # Évaluation hors échantillon (split temporel, sans mélange).
        split_idx = int(n * args.split)
        if split_idx > 30 and n - split_idx > 30:
            is_data = slice_data(data, 0, split_idx)
            oos_data = slice_data(data, split_idx, n)
            entry["in_sample"] = evaluate(engine, is_data, args.interval, builder)["metrics"]
            entry["out_of_sample"] = evaluate(engine, oos_data, args.interval, builder)["metrics"]
        else:
            entry["in_sample"] = None
            entry["out_of_sample"] = None

        results[full["name"]] = entry
        print(f"[Agent Research] {full['name']:20s} → retour {full['metrics']['total_return_pct']:+8.3f}% "
              f"| Sharpe {full['metrics']['sharpe']:.2f} | DD {full['metrics']['max_drawdown_pct']:.2f}% "
              f"| trades {full['metrics']['num_trades']}")

    report = build_report(args, data, results, args.interval)
    json_path, md_path = write_report(report)
    print(f"[Agent Research] Rapport JSON : {json_path}")
    print(f"[Agent Research] Rapport MD   : {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
