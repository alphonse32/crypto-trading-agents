# -*- coding: utf-8 -*-
"""
Moteur de backtest — exécution barre par barre, coûts réalistes, sans look-ahead.

Modèle (Phase 0) :
  - mono-actif, position tout-ou-rien {-1, 0, +1} (long / flat / short) ;
  - frais de taker par côté (fee_bps) et slippage (slippage_bps) ;
  - anti-look-ahead : le signal est calculé à la clôture de la barre t,
    l'ordre est exécuté à l'OUVERTURE de la barre t+1.

Limites assumées (documentées, à améliorer en Phase 1) :
  - pas de gestion de levier ni de marge ;
  - position "all-in" sur le capital courant ;
  - slippage modélisé comme un coût fixe proportionnel (pas de vraie profondeur de carnet).
"""


class BacktestEngine:
    def __init__(self, fee_bps=10.0, slippage_bps=5.0):
        self.fee_rate = fee_bps / 10000.0       # ex. 10 bps = 0,10 %
        self.slippage = slippage_bps / 10000.0  # ex. 5 bps = 0,05 %

    def run(self, data, strategy, initial_equity=10000.0):
        opens = data["open"]
        closes = data["close"]
        times = (data.get("open_time_iso")
                 or data.get("open_time")
                 or [str(i) for i in range(len(closes))])
        n = len(closes)

        if n == 0:
            return {"equity": [initial_equity], "trades": [], "final_equity": initial_equity}

        position = 0           # -1, 0, +1
        entry_price = 0.0
        entry_notional = 0.0   # cash avant frais d'entrée
        entry_equity = 0.0     # cash exposé après frais d'entrée
        entry_time = times[0]
        equity = initial_equity
        equity_curve = []
        trades = []

        def _mtm(close):
            if position == 1:
                return entry_equity * (close / entry_price)
            if position == -1:
                return entry_equity * (2.0 - close / entry_price)
            return equity

        def _exit(exit_px, exit_time):
            nonlocal position, equity, entry_price, entry_notional, entry_equity
            gross = (entry_equity * (exit_px / entry_price) if position == 1
                     else entry_equity * (2.0 - exit_px / entry_price))
            realized = gross * (1.0 - self.fee_rate)
            trades.append({
                "entry_time": entry_time,
                "exit_time": exit_time,
                "side": "LONG" if position == 1 else "SHORT",
                "entry_price": round(entry_price, 8),
                "exit_price": round(exit_px, 8),
                "return_pct": realized / entry_notional - 1.0,
                "pnl": realized - entry_notional,
            })
            equity = realized
            position = 0
            entry_price = 0.0
            entry_notional = 0.0
            entry_equity = 0.0

        # Entrée initiale à l'ouverture de la barre 0 (benchmark équitable).
        sig = strategy.signal(0)
        if sig != 0:
            position = sig
            entry_price = opens[0] * (1.0 + self.slippage * sig)
            entry_notional = equity
            entry_equity = entry_notional * (1.0 - self.fee_rate)
            entry_time = times[0]

        equity_curve.append(_mtm(closes[0]))

        for i in range(1, n):
            sig = strategy.signal(i - 1)
            if sig != position:
                if position != 0:
                    exit_px = opens[i] * (1.0 - self.slippage * position)
                    _exit(exit_px, times[i])
                if sig != 0:
                    position = sig
                    entry_price = opens[i] * (1.0 + self.slippage * sig)
                    entry_notional = equity
                    entry_equity = entry_notional * (1.0 - self.fee_rate)
                    entry_time = times[i]
            equity_curve.append(_mtm(closes[i]))

        # Clôture de la position restante à la dernière clôture.
        if position != 0:
            _exit(closes[-1], times[-1])
            equity_curve[-1] = equity

        return {"equity": equity_curve, "trades": trades, "final_equity": equity}
