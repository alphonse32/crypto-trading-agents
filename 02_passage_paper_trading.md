# Passage en paper trading — préparation

> Phase 1. Objectif : valider en conditions quasi-réelles (données live, exécution simulée,
> **0 € risqué**) les stratégies ayant passé le backtest, avant tout capital réel.

---

## 1. Critères de passage (depuis le backtest)

Une stratégie n'entre en paper trading que si **toutes** ces conditions sont réunies :

| Critère | Seuil |
|---|---|
| Sharpe annualisé | > 1,0 |
| Drawdown maximum | < 20 % |
| Profit factor | > 1,3 |
| Robustesse hors-échantillon | dégradation < 30 % vs in-sample |
| Verdict Risk | aucun kill-switch déclenché, limites respectées |
| Volume de données | ≥ 6 mois (≈ 4 000 barres 1h) |

> État actuel : **aucune stratégie ne passe ces seuils** sur BTC/USDT 1h (6 mois).
> On enrichit le portefeuille de stratégies avant de déclencher le paper.

## 2. Ce qui change entre Phase 0 et Phase 1

| Élément | Phase 0 (backtest) | Phase 1 (paper) |
|---|---|---|
| Données | historiques figées | flux live (REST/WebSocket public) |
| Exécution | rétrospective | ordres simulés au fil de l'eau |
| Risk | analyse de la courbe d'equity | `check_order()` par ordre + kill-switch live |
| Monitoring | rapport a posteriori | surveillance continue + alertes |

## 3. Chaîne des ordres en paper

```
Data (live) → Research (signal) → Risk (check_order) → Exécution (paper) → Monitoring → feedback
```

Un ordre ne part **que** si `RiskManager.check_order()` renvoie `allowed=true`.
Tout refus est journalisé avec son motif.

## 4. Spécification de l'Agent Exécution (paper)

- Reçoit des signaux validés `{symbole, position cible, notionnel}`.
- Simule le fill : `prix = marché ± slippage`, frais de taker par côté.
- Maintient positions + PnL mark-to-market, journalise **chaque** décision.
- Aucune clé API réelle, aucun ordre réel, aucun capital engagé.

Un dry-run de référence existe déjà : `agents/execution_agent.py` (rejoue des données
historiques « comme si » elles étaient live, avec validation Risk par ordre).

## 5. Checklist de readiness (avant de démarrer le paper)

- [ ] Au moins **une stratégie** a passé les seuils de backtest ET les limites de risque.
- [ ] Limites de risque figées et **validées par l'humain**.
- [ ] Kill-switch indépendant **testé** (simulation de franchissement).
- [ ] Journalisation de chaque ordre/décision en place et relue.
- [ ] Données live accessibles (API publique) et testées.
- [ ] Alertes configurées (anomalies, franchissements, pannes d'agent).
- [ ] Aucune clé API de compte réel utilisée.
- [ ] Humain dans la boucle pour l'allocation et les décisions majeures.

## 6. Protocole de surveillance et d'arrêt

- **Kill-switch global** : perte totale ≥ seuil, drawdown ≥ seuil.
- **Kill-switch par stratégie** : perte quotidienne ≥ seuil.
- **Arrêt automatique** si N anomalies en T minutes (à paramétrer).
- L'humain est alerté et peut **geler** l'équipe à tout moment.
- Le kill-switch est **indépendant** du code de trading.

## 7. Critères de sortie du paper (→ Phase 2, capital minimal)

- ≥ **4 semaines** de paper trading stable.
- PnL positif **net de frais et slippage**, Sharpe > 1, drawdown < limites.
- Aucun kill-switch déclenché.
- **Revue humaine obligatoire** avant tout capital réel.

## 8. État actuel

- Pipeline Phase 0 : **complet et vérifié** (Data → Research → Risk → Ordonnanceur).
- Stratégies testées : 3 (Buy&Hold, SMA cross, Momentum) — toutes **REJETÉES** sur les données actuelles.
- Prochaine action : enrichir le portefeuille de stratégies jusqu'à en valider une qui passe les seuils.
