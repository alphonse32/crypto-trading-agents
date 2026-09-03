# -*- coding: utf-8 -*-
"""
Agent Data — collecte et nettoyage des données de marché crypto.

Périmètre (Phase 0, simulation) :
  1. Collecter les chandeliers OHLCV depuis l'API publique Binance (aucune clé requise).
  2. Nettoyer : doublons, tri, trous temporels, incohérences OHLC, valeurs aberrantes.
  3. Sauvegarder les données brutes et nettoyées, et produire un rapport de qualité.

Contrat de l'agent (résumé) :
  - Autonomie : collecte + nettoyage + contrôle qualité.
  - Escalade  : source indisponible ou données massivement suspectes.
  - Sorties   : CSV bruts/clean + rapport JSON + rapport lisible.

Dépendances : bibliothèque standard uniquement (urllib, csv, json, statistics).
"""

import argparse
import csv
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
CLEAN_DIR = DATA_DIR / "clean"
REPORT_DIR = DATA_DIR / "reports"

KLINE_URL = "https://api.binance.com/api/v3/klines"
SERVER_TIME_URL = "https://api.binance.com/api/v3/time"

# Durée d'un intervalle en millisecondes (intervalles Binance supportés).
INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}

# Colonnes du chandelier Binance (ordre officiel de l'API).
KLINE_FIELDS = [
    "open_time",       # ms (epoch)
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",      # ms
    "quote_volume",
    "num_trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]


# ---------------------------------------------------------------------------
# Collecte
# ---------------------------------------------------------------------------

def _get_json(url: str, timeout: int = 15) -> object:
    """Requête GET simple renvoyant le JSON parsé (urllib standard)."""
    req = urllib.request.Request(url, headers={"User-Agent": "crypto-trading-agents/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ms_to_iso(ms: int) -> str:
    """Convertit un timestamp epoch (ms) en chaîne ISO 8601 UTC."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int,
                 pause: float = 0.15) -> list:
    """
    Récupère les chandeliers par pagination (max 1000 par requête).

    Renvoie une liste de lignes normalisées (dicts), triées par open_time.
    """
    if interval not in INTERVAL_MS:
        raise ValueError(f"Intervalle non supporté : {interval} (choix : {sorted(INTERVAL_MS)})")

    rows = []
    cursor = start_ms
    while cursor < end_ms:
        params = urllib.parse.urlencode({
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": 1000,
        })
        batch = _get_json(f"{KLINE_URL}?{params}")

        if not batch:
            break

        for k in batch:
            rows.append({
                "open_time": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": int(k[6]),
                "quote_volume": float(k[7]),
                "num_trades": int(k[8]),
                "taker_buy_base": float(k[9]),
                "taker_buy_quote": float(k[10]),
            })

        # Prochaine page : juste après le dernier chandelier reçu.
        next_cursor = int(batch[-1][0]) + 1
        if next_cursor <= cursor:
            break  # sécurité anti-boucle infinie
        cursor = next_cursor
        time.sleep(pause)  # courtoisie vis-à-vis des limites de débit

    # Déduplication + tri par open_time (défensif).
    seen = set()
    deduped = []
    for row in sorted(rows, key=lambda r: r["open_time"]):
        if row["open_time"] not in seen:
            seen.add(row["open_time"])
            deduped.append(row)
    return deduped


# ---------------------------------------------------------------------------
# Nettoyage et contrôle qualité
# ---------------------------------------------------------------------------

def clean_klines(rows: list, interval: str) -> dict:
    """
    Nettoie les chandeliers et produit un rapport de qualité.

    Retourne {"clean": [...], "report": {...}}.
    Vérifications : doublons, tri, trous temporels, incohérences OHLC,
    volumes négatifs, et barres aberrantes (rendement extrême).
    """
    step = INTERVAL_MS[interval]
    clean = sorted(rows, key=lambda r: r["open_time"])

    issues = {
        "duplicates": 0,
        "ohlc_inconsistent": [],
        "negative_volume": [],
        "gaps": [],
        "extreme_bars": [],
    }

    # 1) Incohérences OHLC et volumes négatifs.
    for r in clean:
        h, l = r["high"], r["low"]
        o, c = r["open"], r["close"]
        if h < max(o, c) - 1e-12 or l > min(o, c) + 1e-12 or h < l:
            issues["ohlc_inconsistent"].append(r["open_time"])
        if r["volume"] < 0:
            issues["negative_volume"].append(r["open_time"])

    # 2) Trous temporels (chandeliers manquants) + barres aberrantes.
    for prev, cur in zip(clean, clean[1:]):
        delta = cur["open_time"] - prev["open_time"]
        if delta > step:
            issues["gaps"].append({
                "after": prev["open_time"],
                "missing": (delta // step) - 1,
            })
        # Rendement de clôture entre deux barres, hors barres à prix nul.
        if prev["close"] > 0:
            ret = abs(cur["close"] / prev["close"] - 1)
            if ret > 0.20:  # saut > 20 % entre deux chandeliers 1h → suspect
                issues["extreme_bars"].append({
                    "open_time": cur["open_time"],
                    "return_pct": round(ret * 100, 2),
                })

    # 3) Statistiques descriptives utiles au rapport.
    closes = [r["close"] for r in clean]
    volumes = [r["volume"] for r in clean]

    report = {
        "symbol": None,  # renseigné par l'appelant
        "interval": interval,
        "generated_at": _ms_to_iso(int(time.time() * 1000)),
        "count": len(clean),
        "span": {
            "start": _ms_to_iso(clean[0]["open_time"]) if clean else None,
            "end": _ms_to_iso(clean[-1]["open_time"]) if clean else None,
        },
        "price": {
            "min": round(min(closes), 4) if closes else None,
            "max": round(max(closes), 4) if closes else None,
            "mean": round(statistics.fmean(closes), 4) if closes else None,
            "stdev": round(statistics.stdev(closes), 4) if len(closes) > 1 else None,
        },
        "volume_total": round(sum(volumes), 4) if volumes else 0,
        "issues": {
            "ohlc_inconsistent": len(issues["ohlc_inconsistent"]),
            "negative_volume": len(issues["negative_volume"]),
            "gaps": len(issues["gaps"]),
            "extreme_bars": len(issues["extreme_bars"]),
        },
        "detail": issues,
        "verdict": None,  # calculé ci-dessous
    }

    # Verdict qualité : OK / DÉGRADÉ / REJETÉ.
    n_bad = report["issues"]["ohlc_inconsistent"] + report["issues"]["negative_volume"]
    if n_bad == 0 and report["issues"]["gaps"] == 0:
        report["verdict"] = "OK"
    elif n_bad == 0:
        report["verdict"] = "DÉGRADÉ (trous temporels)"
    else:
        report["verdict"] = "REJETÉ (incohérences OHLC ou volumes négatifs)"

    return {"clean": clean, "report": report}


# ---------------------------------------------------------------------------
# Sauvegarde
# ---------------------------------------------------------------------------

def write_csv(path: Path, rows: list) -> None:
    """Écrit les chandeliers en CSV avec open_time lisible + epoch."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "open_time_iso", "open_time", "open", "high", "low", "close",
            "volume", "close_time", "quote_volume", "num_trades",
            "taker_buy_base", "taker_buy_quote",
        ])
        for r in rows:
            writer.writerow([
                _ms_to_iso(r["open_time"]),
                r["open_time"],
                f"{r['open']:.8f}", f"{r['high']:.8f}", f"{r['low']:.8f}", f"{r['close']:.8f}",
                f"{r['volume']:.8f}", r["close_time"], f"{r['quote_volume']:.8f}",
                r["num_trades"], f"{r['taker_buy_base']:.8f}", f"{r['taker_buy_quote']:.8f}",
            ])


def write_report(report: dict) -> None:
    """Écrit le rapport de qualité en JSON et une synthèse lisible."""
    report_dir = REPORT_DIR / report["symbol"]
    report_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = report_dir / f"quality_{report['symbol']}_{report['interval']}_{stamp}.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Synthèse lisible (Markdown).
    md = []
    md.append(f"# Rapport qualité — {report['symbol']} {report['interval']}")
    md.append(f"- Généré le : {report['generated_at']}")
    md.append(f"- Chandeliers : {report['count']}")
    md.append(f"- Période : {report['span']['start']} → {report['span']['end']}")
    md.append(f"- Prix min/max/moyen : {report['price']['min']} / {report['price']['max']} / {report['price']['mean']}")
    md.append(f"- Volume total : {report['volume_total']}")
    md.append(f"- **Verdict : {report['verdict']}**")
    md.append("")
    md.append("## Problèmes détectés")
    for k, v in report["issues"].items():
        md.append(f"- {k} : {v}")
    md_path = report_dir / f"quality_{report['symbol']}_{report['interval']}_{stamp}.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    return json_path, md_path


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    # Forcer l'UTF-8 sur la console Windows (évite UnicodeEncodeError avec cp1252).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Agent Data : collecte + nettoyage de chandeliers crypto (Binance, sans clé)."
    )
    parser.add_argument("--symbol", default="BTCUSDT", help="Paire (ex. BTCUSDT).")
    parser.add_argument("--interval", default="1h", choices=sorted(INTERVAL_MS),
                        help="Intervalle de chandelier.")
    parser.add_argument("--days", type=float, default=30.0,
                        help="Profondeur d'historique en jours (depuis maintenant).")
    parser.add_argument("--start", default=None, help="Début ISO (ex. 2025-01-01). Ignore --days.")
    parser.add_argument("--end", default=None, help="Fin ISO. Défaut : maintenant.")
    args = parser.parse_args(argv)

    # Bornes temporelles.
    now_ms = int(time.time() * 1000)
    if args.start:
        start_ms = int(datetime.fromisoformat(args.start).replace(
            tzinfo=timezone.utc).timestamp() * 1000)
    else:
        start_ms = now_ms - int(args.days * 86_400_000)
    end_ms = (int(datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc).timestamp() * 1000)
              if args.end else now_ms)

    print(f"[Agent Data] Collecte {args.symbol} {args.interval} "
          f"({_ms_to_iso(start_ms)} → {_ms_to_iso(end_ms)}) ...")

    try:
        raw = fetch_klines(args.symbol, args.interval, start_ms, end_ms)
    except Exception as exc:  # noqa: BLE001 — escalade explicite
        print(f"[Agent Data] ERREUR source indisponible : {exc}", file=sys.stderr)
        return 2

    if not raw:
        print("[Agent Data] Aucune donnée reçue.", file=sys.stderr)
        return 2

    result = clean_klines(raw, args.interval)
    clean = result["clean"]
    report = result["report"]
    report["symbol"] = args.symbol

    # Sauvegarde.
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{args.symbol}_{args.interval}_raw.csv"
    clean_path = CLEAN_DIR / f"{args.symbol}_{args.interval}_clean.csv"
    write_csv(raw_path, raw)
    write_csv(clean_path, clean)
    json_path, md_path = write_report(report)

    print(f"[Agent Data] Brut : {raw_path} ({len(raw)} barres)")
    print(f"[Agent Data] Clean : {clean_path} ({len(clean)} barres)")
    print(f"[Agent Data] Rapport : {json_path}")
    print(f"[Agent Data] Verdict qualité : {report['verdict']}")
    print(f"[Agent Data] Problèmes : {report['issues']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
