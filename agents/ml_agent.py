# -*- coding: utf-8 -*-
"""
Agent ML — signaux prédictifs avec scikit-learn (Phase 0, simulation).

Pipeline strictement anti-fuite :
  1. Ingénierie de caractéristiques (jusqu'à la barre i incluse) ;
  2. Cible binaire : la barre suivante monte ou baisse ;
  3. Walk-forward (fenêtre croissante, ré-entraînement périodique) :
     on n'entraîne que sur le passé, on prédit uniquement le futur ;
  4. Le signal prédit hors-échantillon est backtesté avec coûts réels.

Modèles : Random Forest (régularisé) + Régression Logistique (comparaison).

Contrat de l'agent :
  - Autonomie : entraîne et évalue seul ;
  - Escalade  : ne fournit jamais un signal non validé au Risk.
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from backtest.engine import BacktestEngine  # noqa: E402
from backtest.metrics import compute_metrics  # noqa: E402
from ml.features import FEATURE_NAMES, build_features, build_target  # noqa: E402

CLEAN_DIR = BASE_DIR / "data" / "clean"
REPORT_DIR = BASE_DIR / "data" / "reports"
INITIAL_EQUITY = 10_000.0

MIN_TRAIN = 1500      # barres minimales avant la première prédiction
RETRAIN_EVERY = 750   # ré-entraînement périodique (fenêtre croissante)


def load_csv(path):
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


def make_rf():
    """Random Forest régularisée pour éviter le surapprentissage."""
    return RandomForestClassifier(n_estimators=200, max_depth=6, min_samples_leaf=20,
                                  random_state=42, n_jobs=1)


def make_lr():
    """Régression logistique avec standardisation (pipeline anti-fuite)."""
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.1))


def walk_forward(X, y, n, make_model):
    """Prédictions hors-échantillon par fenêtre croissante. Renvoie (preds, probs, model)."""
    preds = [None] * n
    probs = [None] * n
    model = None
    t0 = time.time()
    for t in range(MIN_TRAIN, n - 1):
        if t == MIN_TRAIN or (t - MIN_TRAIN) % RETRAIN_EVERY == 0:
            Xtr = np.asarray(X[:t], dtype=float)
            ytr = np.asarray(y[:t])
            model = make_model()
            model.fit(Xtr, ytr)
            print(f"  [Agent ML] ré-entraînement à t={t} ({t} éch., {time.time() - t0:.1f}s)")
        xt = np.asarray([X[t]], dtype=float)
        preds[t] = int(model.predict(xt)[0])
        try:
            probs[t] = float(model.predict_proba(xt)[0, 1])
        except Exception:
            probs[t] = float(preds[t])
    return preds, probs, model


class MLStrategy:
    """Enveloppe le signal ML pour le moteur de backtest (signal(i) -> 0/1)."""

    def __init__(self, preds, name="ML"):
        self.preds = preds
        self.name = name

    def signal(self, i):
        p = self.preds[i]
        return p if p is not None else 0


def classification_metrics(preds, y, start):
    tp = fp = tn = fn = 0
    n = 0
    for i in range(start, len(y) - 1):
        p = preds[i]
        if p is None:
            continue
        n += 1
        if p == 1 and y[i] == 1:
            tp += 1
        elif p == 1 and y[i] == 0:
            fp += 1
        elif p == 0 and y[i] == 0:
            tn += 1
        else:
            fn += 1
    if n == 0:
        return {"n": 0}
    ups = sum(1 for i in range(start, len(y) - 1) if y[i] == 1)
    downs = (len(y) - 1 - start) - ups
    baseline = max(ups, downs) / (len(y) - 1 - start)
    return {
        "n": n,
        "accuracy": round((tp + tn) / n, 4),
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else 0.0,
        "recall": round(tp / (tp + fn), 4) if (tp + fn) else 0.0,
        "baseline_majority": round(baseline, 4),
    }


def evaluate(data, X, y, n, name, make_model):
    preds, _probs, model = walk_forward(X, y, n, make_model)
    cls = classification_metrics(preds, y, MIN_TRAIN)
    strat = MLStrategy(preds, name=name)
    engine = BacktestEngine(fee_bps=10.0, slippage_bps=5.0)
    result = engine.run(data, strat, INITIAL_EQUITY)
    metrics = compute_metrics(result["equity"], result["trades"], "1h", INITIAL_EQUITY)
    out = {"classification": cls, "backtest": metrics}
    if hasattr(model, "feature_importances_"):
        out["feature_importances"] = dict(
            zip(FEATURE_NAMES, [round(float(v), 4) for v in model.feature_importances_])
        )
    return out, preds


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Agent ML : signaux prédictifs (scikit-learn).")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    args = parser.parse_args(argv)

    clean_path = CLEAN_DIR / f"{args.symbol}_{args.interval}_clean.csv"
    if not clean_path.exists():
        print(f"[Agent ML] Fichier introuvable : {clean_path}", file=sys.stderr)
        return 2

    data = load_csv(clean_path)
    n = len(data["close"])
    if n < MIN_TRAIN + 100:
        print(f"[Agent ML] Données insuffisantes : {n} barres < {MIN_TRAIN + 100}.", file=sys.stderr)
        return 2

    X = build_features(data)
    y = build_target(data["close"])
    print(f"[Agent ML] {n} barres, {len(FEATURE_NAMES)} caractéristiques, "
          f"min_train={MIN_TRAIN}, retrain_every={RETRAIN_EVERY}")

    report = {
        "symbol": args.symbol,
        "interval": args.interval,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "features": FEATURE_NAMES,
        "min_train": MIN_TRAIN,
        "retrain_every": RETRAIN_EVERY,
        "n_bars": n,
        "models": {},
    }

    for name, make_model in [("RandomForest", make_rf), ("LogisticRegression", make_lr)]:
        print(f"[Agent ML] === {name} ===")
        res, _ = evaluate(data, X, y, n, f"ML_{name.upper()}", make_model)
        cls = res["classification"]
        bt = res["backtest"]
        print(f"[Agent ML]   classification : {cls}")
        print(f"[Agent ML]   backtest : retour {bt['total_return_pct']:+.2f}% | "
              f"Sharpe {bt['sharpe']:.2f} | DD {bt['max_drawdown_pct']:.2f}% | "
              f"trades {bt['num_trades']}")
        report["models"][name] = res

    out_dir = REPORT_DIR / args.symbol
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"ml_{args.symbol}_{args.interval}_{stamp}.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[Agent ML] Rapport : {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
