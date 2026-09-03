# -*- coding: utf-8 -*-
"""
Agent Exécution (paper trading live) — Phase 1.

Lance le moteur de paper trading sur données live (Binance public, sans clé) :
  - mode "step" (défaut) : un pas de traitement puis affichage de l'état ;
  - mode "--loop" : boucle continue (poll périodique).

Aucun ordre réel, aucun capital engagé. L'état est persisté dans data/paper/.
"""

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from paper.engine import PaperEngine  # noqa: E402

STATE_DIR = BASE_DIR / "data" / "paper"


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Agent Exécution : paper trading live.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--fast", type=int, default=50)
    parser.add_argument("--slow", type=int, default=200)
    parser.add_argument("--fee-bps", type=float, default=10.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--loop", action="store_true", help="Boucle continue.")
    parser.add_argument("--poll", type=int, default=300, help="Période de poll (s) en mode loop.")
    args = parser.parse_args(argv)

    engine = PaperEngine(args.symbol, args.interval, STATE_DIR,
                         fast=args.fast, slow=args.slow,
                         fee_bps=args.fee_bps, slippage_bps=args.slippage_bps)

    if args.loop:
        engine.run_loop(args.poll)
        return 0

    status = engine.step()
    print(f"[Paper] État : {json.dumps(status, ensure_ascii=False)}")
    print(f"[Paper] Position : {engine.state['position']} | "
          f"trades : {len(engine.state['trades'])} | kill : {engine.state['killed']}")
    print("[Paper] Derniers événements du journal :")
    for e in engine.state["journal"][-6:]:
        print(f"  {e}")
    print(f"[Paper] État persisté : {engine.state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
