# -*- coding: utf-8 -*-
"""
RiskManager — le garde-fou. Détecte les franchissements de limites et déclenche
le kill-switch. Indépendant du code de trading (il reçoit l'equity, il ne trade pas).

Usage Phase 0 : on alimente `update()` avec la courbe d'equity d'un backtest
(mark-to-market barre par barre) et on observe où le kill-switch aurait déclenché.

Usage Phase 1 (paper trading) : `check_order()` valide/veto chaque ordre proposé.
"""

from .limits import DEFAULT_LIMITS


class RiskManager:
    def __init__(self, limits=None, initial_equity=10_000.0):
        self.limits = limits or DEFAULT_LIMITS
        self.initial_equity = initial_equity
        self.equity = initial_equity
        self.peak = initial_equity
        self.max_drawdown = 0.0
        self.killed = False
        self.kill_reason = None
        self.kill_time = None
        self.current_day = None
        self.day_start_equity = initial_equity
        self.events = []

    def _kill(self, reason, value_pct, ts):
        self.killed = True
        self.kill_reason = reason
        self.kill_time = ts
        self.events.append({
            "type": "KILL_SWITCH",
            "reason": reason,
            "value_pct": round(value_pct, 3),
            "time": ts,
        })

    def update(self, equity_value, ts=None):
        """Alimente une nouvelle valeur d'equity (mark-to-market). Renvoie un événement ou None."""
        if self.killed:
            return None

        prev_equity = self.equity
        self.equity = equity_value

        if equity_value > self.peak:
            self.peak = equity_value
        dd = (self.peak - equity_value) / self.peak if self.peak > 0 else 0.0
        if dd > self.max_drawdown:
            self.max_drawdown = dd

        total_loss = ((self.initial_equity - equity_value) / self.initial_equity
                      if self.initial_equity > 0 else 0.0)

        # Perte quotidienne : début de journée = clôture de la veille (approx).
        day = ts[:10] if ts else None
        if day != self.current_day:
            self.day_start_equity = prev_equity if self.current_day is not None else self.initial_equity
            self.current_day = day
        daily_loss = ((self.day_start_equity - equity_value) / self.day_start_equity
                      if self.day_start_equity > 0 else 0.0)

        event = None
        if total_loss >= self.limits.max_total_loss_pct / 100.0:
            self._kill("total_loss", total_loss * 100.0, ts)
            event = self.events[-1]
        elif dd >= self.limits.max_drawdown_pct / 100.0:
            self._kill("max_drawdown", dd * 100.0, ts)
            event = self.events[-1]
        elif daily_loss >= self.limits.max_daily_loss_pct / 100.0:
            self._kill("daily_loss", daily_loss * 100.0, ts)
            event = self.events[-1]
        return event

    def check_order(self, target_position, notional):
        """Veto pré-exécution (Phase 1). Renvoie {allowed, reason}."""
        if self.killed:
            return {"allowed": False, "reason": "KILL_SWITCH actif"}
        if abs(target_position) > 1:
            return {"allowed": False, "reason": "position invalide (hors {-1,0,1})"}
        if target_position == 0:
            # Sortir d'une position réduit le risque : toujours autorisé.
            return {"allowed": True, "reason": "OK (réduction du risque)"}
        if self.equity <= 0:
            return {"allowed": False, "reason": "equity nulle ou négative"}
        exposure = notional / self.equity
        if exposure > self.limits.max_exposure + 1e-9:
            return {"allowed": False, "reason": f"exposition {exposure:.2f} > {self.limits.max_exposure:.2f}"}
        return {"allowed": True, "reason": "OK"}

    def summary(self):
        return {
            "initial_equity": round(self.initial_equity, 2),
            "final_equity": round(self.equity, 2),
            "total_return_pct": round((self.equity / self.initial_equity - 1.0) * 100, 3)
                                if self.initial_equity else 0.0,
            "peak_equity": round(self.peak, 2),
            "max_drawdown_pct": round(self.max_drawdown * 100.0, 3),
            "killed": self.killed,
            "kill_reason": self.kill_reason,
            "kill_time": self.kill_time,
            "n_events": len(self.events),
        }
