# -*- coding: utf-8 -*-
"""
Notifications ntfy.sh pour le paper trading.

Détecte les NOUVEAUX événements notables (kill-switch, entrée, sortie) dans les
journaux d'état, envoie une notification ntfy.sh, et mémorise l'horodatage dans
data/notified.json pour ne pas re-notifier les mêmes événements.

Topic ntfy : variable d'environnement NTFY_TOPIC (stockée en secret GitHub).
"""

import json
import os
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
STATE_DIR = BASE_DIR / "data" / "paper"
NOTIFIED_PATH = BASE_DIR / "data" / "notified.json"
TOPIC = os.environ.get("NTFY_TOPIC", "").strip()

NOTABLE = {"ENTRY", "EXIT", "KILL_SWITCH"}


def load_notified():
    if NOTIFIED_PATH.exists():
        return json.loads(NOTIFIED_PATH.read_text(encoding="utf-8"))
    return {}


def save_notified(notified):
    NOTIFIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTIFIED_PATH.write_text(json.dumps(notified, indent=2, ensure_ascii=False),
                             encoding="utf-8")


def send(title, message, priority="default", tags=None):
    if not TOPIC:
        print("[notify] NTFY_TOPIC absent — skip")
        return False
    headers = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = tags
    req = urllib.request.Request(
        f"https://ntfy.sh/{TOPIC}",
        data=message.encode("utf-8"),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status == 200


def main():
    notified = load_notified()
    new_notified = dict(notified)
    events = []

    for f in sorted(STATE_DIR.glob("paper_*_state.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        sym = s.get("symbol", f.stem)
        last = notified.get(sym)  # None si l'actif n'a jamais été notifié
        max_t = last or ""
        for e in s.get("journal", []):
            t = e.get("time", "")
            if e.get("action") in NOTABLE:
                if t > max_t:
                    max_t = t
                # On ne notifie QUE les événements postérieurs à la baseline
                # (évite de rejouer tout l'historique au premier lancement).
                if last is not None and t > last:
                    events.append((sym, e, t))
        new_notified[sym] = max_t

    if not events:
        save_notified(new_notified)
        print("[notify] baseline enregistrée, aucun événement à notifier")
        return 0

    for sym, e, t in events:
        action = e.get("action")
        if action == "KILL_SWITCH":
            send(f"⛔ Kill-switch — {sym}", f"Raison : {e.get('reason')} à {t}",
                 priority="high", tags="rotating_light")
        elif action == "ENTRY":
            send(f"🟢 Entrée — {sym}", f"{e.get('side', '?')} à {t} · prix {e.get('price', '?')}",
                 priority="default", tags="chart_with_upwards_trend")
        elif action == "EXIT":
            send(f"🔴 Sortie — {sym}", f"{e.get('side', '?')} à {t} · equity {e.get('equity_after', '?')}",
                 priority="default", tags="chart_with_downwards_trend")

    save_notified(new_notified)
    print(f"[notify] {len(events)} événement(s) notifié(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
