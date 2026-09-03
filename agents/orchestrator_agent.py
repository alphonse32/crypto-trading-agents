# -*- coding: utf-8 -*-
"""
Agent Ordonnanceur — coordonne le pipeline de simulation de bout en bout.

Chaîne : Data → Research → Risk, puis consolidation des verdicts dans un
rapport de mission unique.

Contrat de l'agent :
  - Autonomie : organise et décide en interne (priorités, enchaînement) ;
  - Escalade  : aucune décision d'engagement de capital réel sans l'humain.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from agents import data_agent, research_agent, risk_agent  # noqa: E402

REPORT_DIR = BASE_DIR / "data" / "reports"


def latest_json(symbol: str, prefix: str) -> Path | None:
    out_dir = REPORT_DIR / symbol
    if not out_dir.exists():
        return None
    candidates = sorted(out_dir.glob(f"{prefix}_{symbol}_*.json"),
                        key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def consolidate(args) -> str | None:
    bt_path = latest_json(args.symbol, "backtest")
    rk_path = latest_json(args.symbol, "risk")
    if bt_path is None or rk_path is None:
        return None

    bt = json.loads(bt_path.read_text(encoding="utf-8"))
    rk = json.loads(rk_path.read_text(encoding="utf-8"))

    lines = [
        f"# Rapport de mission — {args.symbol} {args.interval}",
        f"- Généré le : {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "- Pipeline : **Data → Research → Risk** (simulation, 0 € risqué)",
        f"- Source backtest : `{bt_path.name}`",
        f"- Source risque   : `{rk_path.name}`",
        "",
        "| Stratégie | Retour % | Sharpe | DD % | Verdict backtest | Verdict risque |",
        "|---|---|---|---|---|---|",
    ]

    promoted = []
    for name, entry in bt["strategies"].items():
        m = entry["full"]
        rk_verdict = rk["strategies"].get(name, {}).get("verdict", "-")
        lines.append(
            f"| {name} | {m['total_return_pct']:+.2f} | {m['sharpe']:.2f} "
            f"| {m['max_drawdown_pct']:.2f} | {m.get('verdict', '-')} | {rk_verdict} |"
        )
        if m.get("verdict") == "PROMOUVOIR" and "APPROUVÉ" in rk_verdict:
            promoted.append(name)

    lines.append("")
    if promoted:
        lines.append(f"## Décision : PROMOUVOIR vers paper trading → {', '.join(promoted)}")
    else:
        lines.append("## Décision : aucune stratégie à promouvoir (Phase 0).")
        lines.append("Aucune stratégie ne satisfait à la fois les seuils de backtest (§6) "
                     "et les limites de risque. On reste en simulation.")
    return "\n".join(lines)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Agent Ordonnanceur : pipeline de simulation end-to-end.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--days", type=float, default=180.0, help="Profondeur d'historique (jours).")
    args = parser.parse_args(argv)

    print("=== PIPELINE DE SIMULATION ===")
    print(f"[1/3] Agent Data ...")
    rc1 = data_agent.main(["--symbol", args.symbol, "--interval", args.interval,
                           "--days", str(args.days)])
    print(f"[2/3] Agent Research ...")
    rc2 = research_agent.main(["--symbol", args.symbol, "--interval", args.interval])
    print(f"[3/3] Agent Risk ...")
    rc3 = risk_agent.main(["--symbol", args.symbol, "--interval", args.interval])

    report = consolidate(args)
    if report is None:
        print("[Ordonnanceur] Impossible de consolider : rapports manquants.", file=sys.stderr)
        return 2

    out_dir = REPORT_DIR / args.symbol
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    md_path = out_dir / f"mission_{args.symbol}_{args.interval}_{stamp}.md"
    md_path.write_text(report, encoding="utf-8")
    print(f"[Ordonnanceur] Rapport de mission : {md_path}")
    print(f"[Ordonnanceur] Codes de sortie → Data:{rc1} Research:{rc2} Risk:{rc3}")
    return 0 if (rc1 == 0 and rc2 == 0 and rc3 == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
