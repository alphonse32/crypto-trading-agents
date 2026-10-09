# -*- coding: utf-8 -*-
"""Rapport quotidien du portefeuille (6 actifs) — envoyé via ntfy."""
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
STATE_DIR = BASE_DIR / "data" / "paper"
TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"]
INITIAL = 10_000.0


def send(title, message, priority="default", tags=None):
    if not TOPIC:
        print("[rapport] NTFY_TOPIC absent — skip")
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
    rows = []
    total = 0.0
    n_long = 0
    n_killed = 0

    for sym in SYMBOLS:
        path = STATE_DIR / f"paper_{sym}_1h_state.json"
        if not path.exists():
            continue
        s = json.loads(path.read_text(encoding="utf-8"))
        mtm = s.get("mtm_equity", s.get("equity"))
        total += mtm
        pos = s.get("position")
        killed = s.get("killed")
        ret = (mtm / INITIAL - 1.0) * 100.0
        if pos == 1:
            n_long += 1
        if killed:
            n_killed += 1
        rows.append((sym, pos, mtm, ret, killed))

    rows.sort(key=lambda r: r[3], reverse=True)

    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    total_ret = (total / 60_000.0 - 1.0) * 100.0

    lines = [f"Rapport {today} — Total {total:,.0f} $ ({total_ret:+.1f} %)", ""]
    for sym, pos, mtm, ret, killed in rows:
        pos_str = "LONG" if pos == 1 else ("SHORT" if pos == -1 else "flat")
        mark = " [KILL]" if killed else (" *" if ret > 0 else "")
        lines.append(f"{sym} : {pos_str} · {mtm:,.0f} $ ({ret:+.1f} %){mark}")

    lines.append("")
    lines.append(f"Positions long : {n_long}/{len(rows)} · kill-switch : {n_killed}")

    msg = "\n".join(lines)
    ok = send("Rapport trading quotidien", msg, priority="default", tags="bar_chart")
    print(f"[rapport] envoyé={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
