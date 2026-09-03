# -*- coding: utf-8 -*-
"""
Limites de risque (config du garde-fou).

Tous les seuils sont en pourcentage (ex. 20.0 = 20 %). Ils correspondent au §6
du document d'équipe et sont DURS : tout franchissement déclenche le kill-switch.
"""


class RiskLimits:
    def __init__(self,
                 max_drawdown_pct=20.0,     # drawdown depuis le pic → kill
                 max_daily_loss_pct=5.0,    # perte sur un jour calendaire → kill
                 max_total_loss_pct=30.0,   # perte depuis le capital initial → kill global
                 max_exposure=1.0,          # fraction max du capital exposée (1.0 = tout)
                 max_leverage=1.0,          # pas de levier en Phase 0
                 max_concentration=1.0):    # fraction max sur un seul actif
        self.max_drawdown_pct = max_drawdown_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_total_loss_pct = max_total_loss_pct
        self.max_exposure = max_exposure
        self.max_leverage = max_leverage
        self.max_concentration = max_concentration

    def to_dict(self):
        return {
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_total_loss_pct": self.max_total_loss_pct,
            "max_exposure": self.max_exposure,
            "max_leverage": self.max_leverage,
            "max_concentration": self.max_concentration,
        }


DEFAULT_LIMITS = RiskLimits()
