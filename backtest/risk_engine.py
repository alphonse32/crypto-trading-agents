# -*- coding: utf-8 -*-
"""
Moteur de backtest avec gestion du risque (améliorations Phase 0).

Fonctionnalités :
  - sizing fractionnaire fixe (position_size_pct) ;
  - volatility targeting : taille ∝ vol_cible / vol_réalisée (ATR/prix) ;
  - stop-loss / take-profit fixes ou basés ATR (vérifiés intra-barre) ;
  - filtre de marché « quand ne pas trader » (trade_filter) ;
  - positions long ET short (signal -1/0/1) ;
  - cooldown après une sortie perdante (cooldown_bars).

Modèle : equity = réserve + capital exposé × facteur de rendement.
"""

from backtest.strategies import sma  # noqa: E402


class RiskManagedEngine:
    def __init__(self, fee_bps=10.0, slippage_bps=5.0, position_size_pct=1.0,
                 stop_loss_pct=None, take_profit_pct=None,
                 atr_stop_mult=None, atr_tp_mult=None, atr_values=None,
                 trade_filter=None, vol_target_pct=None, max_size_pct=1.0,
                 cooldown_bars=0):
        self.fee_rate = fee_bps / 10000.0
        self.slippage = slippage_bps / 10000.0
        self.position_size_pct = position_size_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.atr_stop_mult = atr_stop_mult
        self.atr_tp_mult = atr_tp_mult
        self.atr_values = atr_values
        self.trade_filter = trade_filter
        self.vol_target_pct = vol_target_pct
        self.max_size_pct = max_size_pct
        self.cooldown_bars = cooldown_bars

    def _size_fraction(self, price, i):
        if self.vol_target_pct is not None and self.atr_values is not None:
            a = self.atr_values[i]
            if a is not None and price > 0 and a > 0:
                frac = (self.vol_target_pct / 100.0) / (a / price)
                return max(0.0, min(self.max_size_pct, frac))
        return self.position_size_pct

    def run(self, data, strategy, initial_equity=10_000.0):
        opens = data["open"]
        highs = data["high"]
        lows = data["low"]
        closes = data["close"]
        times = data.get("open_time_iso") or [str(i) for i in range(len(closes))]
        n = len(closes)

        equity = initial_equity
        position = 0          # -1 (short), 0 (flat), +1 (long)
        entry_price = 0.0
        entry_equity = 0.0    # capital exposé (après frais d'entrée)
        reserve = 0.0         # cash non engagé
        equity_at_entry = initial_equity
        stop_price = None
        tp_price = None
        entry_time = None
        cooldown_until = -1
        equity_curve = []
        trades = []

        def close_position(exit_px, exit_time, reason):
            nonlocal equity, position, entry_price, entry_equity, reserve
            nonlocal stop_price, tp_price, entry_time
            gross = (entry_equity * (exit_px / entry_price) if position == 1
                     else entry_equity * (2.0 - exit_px / entry_price))
            realized = reserve + gross * (1.0 - self.fee_rate)
            pnl = realized - equity_at_entry
            trades.append({
                "entry_time": entry_time, "exit_time": exit_time,
                "side": "LONG" if position == 1 else "SHORT",
                "entry_price": round(entry_price, 8),
                "exit_price": round(exit_px, 8),
                "reason": reason,
                "return_pct": pnl / equity_at_entry if equity_at_entry else 0.0,
                "pnl": pnl,
            })
            equity = realized
            position = 0
            entry_price = 0.0
            entry_equity = 0.0
            reserve = 0.0
            stop_price = tp_price = None
            entry_time = None
            return pnl

        for i in range(n):
            target = strategy.signal(i - 1) if i >= 1 else strategy.signal(0)
            allowed = self.trade_filter is None or self.trade_filter(max(0, i - 1))
            allowed = allowed and i >= cooldown_until

            # Fermeture (sortie plate OU retournement de position).
            if position != 0 and (target == 0 or target != position):
                if close_position(opens[i], times[i], "signal") < 0:
                    cooldown_until = i + self.cooldown_bars

            # Ouverture (long ou short).
            if position == 0 and target != 0 and allowed:
                entry_price = opens[i] * (1.0 + self.slippage * target)
                fraction = self._size_fraction(entry_price, i)
                equity_at_entry = equity
                entry_equity = equity * fraction * (1.0 - self.fee_rate)
                reserve = equity - equity * fraction
                position = target
                entry_time = times[i]
                stop_price = tp_price = None
                a = self.atr_values[i] if self.atr_values is not None else None
                if self.atr_stop_mult is not None and a is not None:
                    stop_price = entry_price - target * self.atr_stop_mult * a
                elif self.stop_loss_pct is not None:
                    stop_price = entry_price * (1.0 - target * self.stop_loss_pct)
                if self.atr_tp_mult is not None and a is not None:
                    tp_price = entry_price + target * self.atr_tp_mult * a
                elif self.take_profit_pct is not None:
                    tp_price = entry_price * (1.0 + target * self.take_profit_pct)

            # Stop / take-profit intra-barre.
            if position == 1:
                if stop_price is not None and lows[i] <= stop_price:
                    if close_position(stop_price, times[i], "stop_loss") < 0:
                        cooldown_until = i + self.cooldown_bars
                elif tp_price is not None and highs[i] >= tp_price:
                    close_position(tp_price, times[i], "take_profit")
            elif position == -1:
                if stop_price is not None and highs[i] >= stop_price:
                    if close_position(stop_price, times[i], "stop_loss") < 0:
                        cooldown_until = i + self.cooldown_bars
                elif tp_price is not None and lows[i] <= tp_price:
                    close_position(tp_price, times[i], "take_profit")

            # Mark-to-market.
            if position == 1:
                equity = reserve + entry_equity * (closes[i] / entry_price)
            elif position == -1:
                equity = reserve + entry_equity * (2.0 - closes[i] / entry_price)

            equity_curve.append(equity)

        if position != 0:
            close_position(closes[-1], times[-1] if n else None, "end")

        return {"equity": equity_curve, "trades": trades, "final_equity": equity}


class VolatilityFilter:
    """Bloque les entrées si l'ATR est anormalement élevé vs sa moyenne récente."""

    def __init__(self, atr_values, lookback=100, max_ratio=2.0):
        self.atr_values = atr_values
        self.lookback = lookback
        self.max_ratio = max_ratio

    def __call__(self, i):
        a = self.atr_values[i]
        if a is None or i < self.lookback:
            return True
        recent = [x for x in self.atr_values[i - self.lookback:i] if x is not None]
        if not recent:
            return True
        mean = sum(recent) / len(recent)
        return a <= self.max_ratio * mean


class TrendStrengthFilter:
    """« Quand ne pas trader » : n'autorise l'entrée que si la séparation
    SMA_fast / SMA_slow est significative par rapport au bruit (ATR)."""

    def __init__(self, data, fast=50, slow=200, atr_values=None, threshold=0.3):
        self.fast_sma = sma(data["close"], fast)
        self.slow_sma = sma(data["close"], slow)
        self.atr_values = atr_values
        self.threshold = threshold

    def __call__(self, i):
        f = self.fast_sma[i]
        s = self.slow_sma[i]
        a = self.atr_values[i] if self.atr_values is not None else None
        if f is None or s is None or a is None or a <= 0:
            return False
        return abs(f - s) / a > self.threshold
