# -*- coding: utf-8 -*-
"""
Moteur de paper trading (Phase 1).

Boucle : données live (Binance REST) → signal → validation Risk (check_order)
→ exécution simulée (slippage + frais) → kill-switch → journal + état persistants.

Aucun ordre réel, aucun capital engagé. L'état est sauvegardé dans un JSON
pour pouvoir arrêter/relancer sans perdre position, equity ni historique.
"""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from backtest.metrics import compute_metrics  # noqa: E402
from backtest.strategies import SmaCross  # noqa: E402
from risk.limits import RiskLimits  # noqa: E402
from risk.manager import RiskManager  # noqa: E402

KLINE_URL = "https://data-api.binance.vision/api/v3/klines"
INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}


def _ms_to_iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_recent(symbol, interval, limit=300):
    """Récupère les `limit` derniers chandeliers (Binance public, sans clé)."""
    params = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    req = urllib.request.Request(f"{KLINE_URL}?{params}", headers={"User-Agent": "crypto-trading-agents/0.1"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    return [{
        "open_time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
        "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
        "close_time": int(k[6]),
    } for k in rows]


class PaperEngine:
    def __init__(self, symbol, interval, state_dir, fast=50, slow=200,
                 fee_bps=10.0, slippage_bps=5.0, warmup=300):
        self.symbol = symbol
        self.interval = interval
        self.fast = fast
        self.slow = slow
        self.fee_rate = fee_bps / 10000.0
        self.slippage = slippage_bps / 10000.0
        self.warmup = warmup
        self.limits = RiskLimits()
        self.state_path = Path(state_dir) / f"paper_{symbol}_{interval}_state.json"
        self.state = self._load_state()

    # --- état persistant -------------------------------------------------
    def _default_state(self):
        now = int(time.time() * 1000)
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "strategy": f"SMA_CROSS_{self.fast}_{self.slow}",
            "initial_equity": 10_000.0,
            "equity": 10_000.0,          # cash réalisé (hors position)
            "position": 0,               # -1, 0, +1
            "entry_price": 0.0,
            "entry_equity": 0.0,         # capital exposé après frais d'entrée
            "entry_time": None,
            "peak": 10_000.0,
            "max_drawdown": 0.0,
            "killed": False,
            "kill_reason": None,
            "current_day": None,
            "day_start_equity": 10_000.0,
            "trades": [],
            "journal": [],
            "last_processed_time": 0,
            "created_at": _ms_to_iso(now),
            "updated_at": _ms_to_iso(now),
        }

    def _load_state(self):
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return self._default_state()

    def _save_state(self):
        self.state["updated_at"] = _ms_to_iso(int(time.time() * 1000))
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2, ensure_ascii=False),
                                   encoding="utf-8")

    # --- RiskManager reconstruit depuis l'état ---------------------------
    def _make_risk(self):
        rm = RiskManager(self.limits, self.state["initial_equity"])
        rm.equity = self.state["equity"]
        rm.peak = self.state["peak"]
        rm.max_drawdown = self.state["max_drawdown"]
        rm.killed = self.state["killed"]
        rm.kill_reason = self.state["kill_reason"]
        rm.current_day = self.state["current_day"]
        rm.day_start_equity = self.state["day_start_equity"]
        return rm

    def _sync_risk(self, rm):
        self.state["equity"] = rm.equity
        self.state["peak"] = rm.peak
        self.state["max_drawdown"] = rm.max_drawdown
        self.state["killed"] = rm.killed
        self.state["kill_reason"] = rm.kill_reason
        self.state["current_day"] = rm.current_day
        self.state["day_start_equity"] = rm.day_start_equity

    # --- journal ---------------------------------------------------------
    def _journal(self, ts, action, **extra):
        rec = {"time": ts, "action": action}
        rec.update(extra)
        self.state["journal"].append(rec)

    def _mtm(self, close_price):
        p = self.state["position"]
        if p == 1:
            return self.state["entry_equity"] * (close_price / self.state["entry_price"])
        if p == -1:
            return self.state["entry_equity"] * (2.0 - close_price / self.state["entry_price"])
        return self.state["equity"]

    # --- exécution simulée d'un chandelier -------------------------------
    def _process_candle(self, rm, target, close_price, iso_time):
        position = self.state["position"]
        if target != position and not rm.killed:
            check = rm.check_order(target, rm.equity)
            self._journal(iso_time, "CHECK", target=target,
                          allowed=check["allowed"], reason=check["reason"])
            if check["allowed"]:
                if position != 0:
                    exit_side = position
                    exit_px = close_price * (1.0 - self.slippage * position)
                    realized = (self.state["entry_equity"] * (exit_px / self.state["entry_price"])
                                * (1.0 - self.fee_rate))
                    self.state["trades"].append({
                        "entry_time": self.state["entry_time"],
                        "exit_time": iso_time,
                        "side": "LONG" if exit_side == 1 else "SHORT",
                        "entry_price": round(self.state["entry_price"], 8),
                        "exit_price": round(exit_px, 8),
                        "return_pct": realized / self.state["equity"] - 1.0,
                        "pnl": realized - self.state["equity"],
                    })
                    self.state["equity"] = realized
                    self.state["position"] = 0
                    position = 0
                    self._journal(iso_time, "EXIT", side=exit_side,
                                  price=round(exit_px, 8), equity_after=round(realized, 2))
                if target != 0:
                    entry_price = close_price * (1.0 + self.slippage * target)
                    self.state["entry_price"] = entry_price
                    self.state["entry_equity"] = self.state["equity"] * (1.0 - self.fee_rate)
                    self.state["entry_time"] = iso_time
                    self.state["position"] = target
                    position = target
                    self._journal(iso_time, "ENTRY", side=target,
                                  price=round(entry_price, 8),
                                  equity_after=round(self.state["equity"], 2))

        # Mark-to-market + mise à jour du risque (kill-switch).
        mtm = self._mtm(close_price)
        rm.update(mtm, iso_time)
        if rm.killed:
            self._journal(iso_time, "KILL_SWITCH", reason=rm.kill_reason)
            if self.state["position"] != 0:
                self._close_position(close_price, iso_time)
        self._sync_risk(rm)

    def _close_position(self, close_price, iso_time):
        position = self.state["position"]
        if position == 0:
            return
        realized = (self.state["entry_equity"] * (close_price / self.state["entry_price"])
                    * (1.0 - self.fee_rate))
        self.state["trades"].append({
            "entry_time": self.state["entry_time"], "exit_time": iso_time,
            "side": "LONG" if position == 1 else "SHORT",
            "entry_price": round(self.state["entry_price"], 8),
            "exit_price": round(close_price, 8),
            "return_pct": realized / self.state["equity"] - 1.0,
            "pnl": realized - self.state["equity"],
        })
        self.state["equity"] = realized
        self.state["position"] = 0
        self._journal(iso_time, "EXIT", side=position, price=round(close_price, 8),
                      equity_after=round(realized, 2))

    # --- pas de temps ----------------------------------------------------
    def step(self):
        try:
            candles = fetch_recent(self.symbol, self.interval, self.warmup)
        except Exception as exc:  # noqa: BLE001 — erreur réseau : ne pas crasher
            return {"status": "error", "error": f"fetch: {exc}"}
        now_ms = int(time.time() * 1000)
        closed = [c for c in candles if c["close_time"] <= now_ms]
        if not closed:
            return {"status": "no_closed_candle"}

        closes = [c["close"] for c in closed]
        strat = SmaCross({"close": closes}, fast=self.fast, slow=self.slow)
        idx_map = {c["open_time"]: i for i, c in enumerate(closed)}

        if self.state["last_processed_time"] == 0:
            new_candles = closed[-1:]  # premier lancement : on ne traite que la dernière bougie
        else:
            new_candles = [c for c in closed
                           if c["open_time"] > self.state["last_processed_time"]]

        rm = self._make_risk()
        for c in new_candles:
            i = idx_map[c["open_time"]]
            self._process_candle(rm, strat.signal(i), c["close"],
                                 _ms_to_iso(c["open_time"]))

        self.state["last_processed_time"] = closed[-1]["open_time"]
        self.state["last_close"] = closed[-1]["close"]
        self.state["mtm_equity"] = round(self._mtm(closed[-1]["close"]), 2)
        last_idx = len(closed) - 1
        self.state["signal"] = strat.signal(last_idx)
        self.state["sma_fast"] = (round(strat.fast_sma[last_idx], 2)
                                  if strat.fast_sma[last_idx] is not None else None)
        self.state["sma_slow"] = (round(strat.slow_sma[last_idx], 2)
                                  if strat.slow_sma[last_idx] is not None else None)
        self._save_state()
        return self.status()

    def status(self):
        latest = self.state["journal"][-1]["action"] if self.state["journal"] else "init"
        mtm = self.state.get("mtm_equity")
        equity = mtm if mtm is not None else self.state["equity"]
        return {
            "status": "ok",
            "symbol": self.symbol,
            "interval": self.interval,
            "strategy": self.state["strategy"],
            "position": self.state["position"],
            "equity": round(equity, 2),
            "killed": self.state["killed"],
            "n_trades": len(self.state["trades"]),
            "n_journal": len(self.state["journal"]),
            "last_action": latest,
            "last_close": self.state.get("last_close"),
            "signal": self.state.get("signal"),
            "sma_fast": self.state.get("sma_fast"),
            "sma_slow": self.state.get("sma_slow"),
            "updated_at": self.state.get("updated_at"),
        }

    def run_loop(self, poll_seconds=300):
        print(f"[Paper] Boucle démarrée : {self.symbol} {self.interval} "
              f"{self.state['strategy']} (poll {poll_seconds}s). Ctrl-C pour arrêter.")
        try:
            while True:
                s = self.step()
                print(f"[Paper] {s}")
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            print("[Paper] Arrêt demandé, état sauvegardé.")

    def replay(self, n_bars=4320):
        """Rejoue l'historique barre par barre, avec la MÊME logique que le live.

        Signal → validation Risk (check_order) avant chaque ordre → fill simulé
        → kill-switch ACTIF (arrête la stratégie dès qu'une limite est franchie).
        N'altère PAS l'état live persisté (il est restauré à la fin).
        """
        candles = fetch_recent(self.symbol, self.interval, n_bars)
        if not candles:
            return {"error": "aucune donnée récupérée"}

        closes = [c["close"] for c in candles]
        strat = SmaCross({"close": closes}, fast=self.fast, slow=self.slow)

        saved_state = self.state
        self.state = self._default_state()
        rm = self._make_risk()
        equity_curve = []

        for i, c in enumerate(candles):
            target = strat.signal(i)
            self._process_candle(rm, target, c["close"], _ms_to_iso(c["open_time"]))
            equity_curve.append(round(self._mtm(c["close"]), 2))

        metrics = compute_metrics(equity_curve, self.state["trades"],
                                  self.interval, self.state["initial_equity"])
        kill_events = [e for e in self.state["journal"] if e["action"] == "KILL_SWITCH"]

        result = {
            "symbol": self.symbol,
            "interval": self.interval,
            "strategy": self.state["strategy"],
            "n_bars": len(candles),
            "n_trades": len(self.state["trades"]),
            "killed": self.state["killed"],
            "kill_reason": self.state["kill_reason"],
            "kill_events": kill_events,
            "metrics": metrics,
            "trades": self.state["trades"],
        }
        self.state = saved_state
        return result
