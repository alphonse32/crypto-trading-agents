# Équipe d'agents IA — Trading Crypto (Phase Simulation)

> Version 1.0 — Document fondateur. Objectif : générer un profit sur les marchés crypto via une
> équipe d'agents IA spécialisés, en commençant **exclusivement en simulation** (backtest puis
> paper trading) avant tout engagement de capital réel.

---

## 1. Objectif et principes directeurs

**Mission** : concevoir, valider et exploiter des stratégies de trading crypto rentables grâce à
une équipe d'agents spécialisés qui coopèrent.

**Principes non négociables** :

1. **Aucun capital réel avant validation.** Une stratégie doit passer backtest → paper trading →
   revue de risque avant de toucher le moindre euro.
2. **Humain dans la boucle.** L'humain valide l'allocation du capital et les décisions majeures.
   Les agents proposent, exécutent dans leurs limites, et escaladent.
3. **Autonomie bornée.** Chaque agent a un périmètre strict, des limites de risque dures, et ne
   peut pas agir hors de son contrat.
4. **Traçabilité totale.** Chaque décision (signal, ordre, blocage) est journalisée avec son auteur,
   son motif et son horodatage.
5. **Sécurité d'abord.** Aucun secret (clé API, seed) en clair dans le code ou les logs.

---

## 2. Architecture générale

```
                         ┌──────────────────────────┐
                         │  AGENT ORDONNANCEUR      │
                         │  (Chief Orchestrator)    │
                         └────────────┬─────────────┘
        ┌─────────────┬───────────────┼───────────────┬─────────────┐
        ▼             ▼               ▼               ▼             ▼
 ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐
 │ AGENT DATA │ │AGENT RESEA-│ │  AGENT ML  │ │ AGENT RISK │ │  AGENT     │
 │  (marché)  │ │  RCH       │ │ (signaux)  │ │ (contrôle) │ │ MONITORING │
 └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └────────────┘
       │              │              │              │
       └──────────────┴──────┬───────┴──────────────┘
                             ▼
                    ┌────────────────┐
                    │ AGENT EXÉCUTION │  (paper trading en phase simulation)
                    └────────────────┘
```

**Flux logique** : `Data → Signal → Backtest → Validation → Risk → Exécution → Monitoring → feedback`

---

## 3. Les agents (rôles détaillés)

### 3.1 Agent Ordonnanceur (Chief Orchestrator)

- **Mission** : coordonner l'équipe, arbitrer les priorités, décider de l'allocation et des
  stratégies à promouvoir d'une phase à l'autre.
- **Responsabilités** :
  - Répartir les tâches entre agents (ex. "tester une stratégie momentum sur BTC/USDT").
  - Consolider les résultats (métriques de backtest, signaux, alertes risque).
  - Décider quelles stratégies passent au stade suivant (backtest → paper).
  - Tenir le journal de bord de l'équipe.
- **Entrées** : rapports Research, rapports ML, alertes Risk, rapports Monitoring.
- **Sorties** : plan de travail, décisions de promotion/rétrogradation des stratégies, allocation
  proposée à l'humain.
- **Autonomie** : organise et décide **en interne** (priorités, tests). Ne décide **pas** seul de
  l'engagement de capital réel — c'est une escalade à l'humain.
- **KPIs** : nombre de stratégies testées, taux de passage à la phase suivante, clarté des décisions.

### 3.2 Agent Data (marché & données)

- **Mission** : fournir des données de marché propres, versionnées et fiables aux autres agents.
- **Responsabilités** :
  - Collecter les données (OHLCV, carnet d'ordres, volumes, funding rates) via API publiques
    (Binance, Bybit, CoinGecko, etc.).
  - Nettoyer : trous, doublons, outliers, fuseaux horaires, cohérence des paires.
  - Versionner les données (snapshots horodatés) et documenter leur schéma.
  - Détecter les problèmes de qualité (suspension de cotation, données manquantes).
- **Entrées** : liste des paires/univers demandé, périodes à couvrir.
- **Sorties** : jeux de données normalisés (Parquet/CSV), dictionnaire de données, rapports qualité.
- **Outils** : scripts de collecte, pipelines de nettoyage, contrôle qualité automatique.
- **Autonomie** : collecte et nettoyage en autonomie. Escalade en cas d'indisponibilité de source
  ou de données suspectes.
- **KPIs** : complétude des données, fraîcheur, taux d'erreurs détectées.

### 3.3 Agent Research (recherche & backtest)

- **Mission** : générer, tester et valider des hypothèses de stratégie via backtest rigoureux.
- **Responsabilités** :
  - Formuler des hypothèses (momentum, mean-reversion, breakout, arbitrage, market making…).
  - Implémenter et backtester avec un moteur intègre (coûts, slippage, frais, latence).
  - Lutter contre les biais : look-ahead, survivorship, sur-optimisation, fuite de données.
  - Produire des rapports de métriques standardisés (voir §6).
  - Test de robustesse : walk-forward, hors-échantillon, sensibilité aux paramètres.
- **Entrées** : données (Agent Data), hypothèses (Ordonnanceur).
- **Sorties** : rapports de backtest, stratégies candidates étiquetées "à promouvoir / à rejeter".
- **Outils** : moteur de backtest, bibliothèque d'indicateurs, outils de visualisation.
- **Autonomie** : rejette seul les stratégies manifestement mauvaises. La promotion vers paper
  exige l'accord Risk + Ordonnanceur.
- **KPIs** : Sharpe, drawdown max, ratio profit/facteur, robustesse hors-échantillon, coûts intégrés.

### 3.4 Agent ML (signaux prédictifs)

- **Mission** : produire des signaux prédictifs (direction, probabilité, volatilité) via machine learning.
- **Responsabilités** :
  - Feature engineering (indicateurs, données on-chain/sentiment si disponibles).
  - Entraîner/valider des modèles (régression, classification, séries temporelles).
  - Prévenir le **surapprentissage** : validation temporelle stricte, walk-forward, ensembles.
  - Quantifier la confiance du modèle (probabilités calibrées, intervalles).
  - Collaborer avec Research : un signal ML n'est qu'une **entrée**, pas une stratégie complète.
- **Entrées** : données (Agent Data), cibles et périmètre (Research/Ordonnanceur).
- **Sorties** : modèles évalués, signaux horodatés, rapports de performance prédictive.
- **Outils** : scikit-learn, TensorFlow/PyTorch, bibliothèques de séries temporelles.
- **Autonomie** : entraîne et évalue seul. Ne fournit **jamais** un signal non validé au Risk.
- **KPIs** : précision/rappel, AUC/Sharpe du signal, stabilité temporelle, calibration.

### 3.5 Agent Risk (contrôle du risque)

- **Mission** : protéger le capital. C'est le **garde-fou** de l'équipe, avec un droit de veto.
- **Responsabilités** :
  - Définir et faire appliquer les limites : taille de position max, perte max par jour/stratégie,
    exposition totale, levier max, concentration.
  - Calculer les métriques de risque (VaR, drawdown, exposition, corrélations entre stratégies).
  - Décider du **kill-switch** : arrêt d'une stratégie ou de toute l'équipe en cas de seuil franchi.
  - Valider chaque stratégie avant passage en phase supérieure.
- **Entrées** : signaux/ordres proposés, positions (Exécution), métriques (Research/ML).
- **Sorties** : décisions "autorisé / refusé / réduit", alertes, limites mises à jour.
- **Autonomie** : **peut bloquer seul** tout ordre ou stratégie hors limites (veto). Ne peut pas
  élargir seul les limites globales — escalade à l'humain.
- **KPIs** : respect des limites, drawdown réel vs. limite, délai de réaction, alertes pertinentes.

### 3.6 Agent Exécution (passage d'ordres)

- **Mission** : exécuter les ordres validés, au meilleur coût, en phase **paper trading** pour l'instant.
- **Responsabilités** :
  - Transformer les signaux validés en ordres (type d'ordre, taille, timing).
  - Simuler l'exécution de façon réaliste (slippage, frais, profondeur de carnet).
  - Suivre les positions ouvertes et les PnL en temps réel.
  - En phase réelle (plus tard) : routage via API broker, gestion des rejets.
- **Entrées** : ordres validés par Risk, données de marché live.
- **Sorties** : exécutions, positions, PnL, rapport de slippage/coûts.
- **Autonomie** : exécute **uniquement** ce que Risk a validé. Aucune décision de trading propre.
- **KPIs** : slippage, frais, taux de remplissage, fidélité à la taille demandée.

### 3.7 Agent Monitoring (surveillance 24/7)

- **Mission** : surveiller l'équipe et le marché en continu, alerter sur toute anomalie.
- **Responsabilités** :
  - Surveiller la santé de tous les agents (pannes, silences anormaux, erreurs).
  - Surveiller le marché (volatilité extrême, haltes, anomalies de prix).
  - Centraliser les logs et produire des rapports périodiques.
  - Alerter immédiatement en cas d'anomalie (à Risk et à l'humain).
- **Entrées** : logs de tous les agents, flux de marché, états de positions.
- **Sorties** : alertes temps réel, tableaux de bord, rapports d'incident.
- **Autonomie** : alerte et journalise en autonomie. Peut demander à Risk un gel des opérations.
- **KPIs** : délai de détection d'anomalie, faux positifs, couverture des logs.

---

## 4. Contrat d'agent (modèle commun)

Chaque agent est défini par le même gabarit, pour garantir cohérence et interchangeabilité :

| Champ | Description |
|---|---|
| **Identité** | nom + identifiant stable |
| **Mission** | une phrase, résultat attendu |
| **Responsabilités** | liste bornée et vérifiable |
| **Entrées / Sorties** | données et livrables explicites |
| **Outils** | ce qu'il peut utiliser |
| **Autonomie** | ce qu'il décide seul |
| **Escalade** | ce qu'il doit remonter |
| **Limites** | ce qu'il ne peut jamais faire |
| **KPIs** | comment on mesure son succès |

---

## 5. Flux de communication

- **Canal de décision** : un ordre ne part en exécution que via la chaîne
  `Research/ML → Risk (validation) → Exécution`.
- **Escalade** : tout dépassement de limite, donnée suspecte ou panne remonte à Risk puis à
  l'Ordonnanceur, et à l'humain si l'enjeu est financier.
- **Journal unique** : chaque événement est horodaté et attribué (agent, action, motif, résultat).
- **Feedback** : les résultats d'exécution et de monitoring nourrissent Research/ML pour améliorer
  les stratégies (boucle fermée, sans fuite de données).

---

## 6. Cadre de gestion du risque (phase simulation)

Métriques de référence à calculer pour **toute** stratégie avant promotion :

| Métrique | Seuil indicatif |
|---|---|
| Sharpe ratio (annualisé) | > 1,0 |
| Drawdown maximum | < 20 % |
| Ratio profit/facteur (Profit Factor) | > 1,3 |
| Taux de réussite | dépend de la stratégie (pas un critère seul) |
| Robustesse hors-échantillon | dégradation < 30 % vs in-sample |
| Coûts intégrés | slippage + frais **obligatoirement** inclus dans le backtest |

Limites dures (à paramétrer) : perte max par jour, par stratégie, exposition totale, levier max,
concentration par actif. **Tout franchissement déclenche le kill-switch automatiquement.**

---

## 7. Stack technique recommandée

- **Langage** : Python (recherche, ML, orchestration), éventuellement un cœur basse latence plus tard.
- **Données** : API publiques (Binance/Bybit/CoinGecko), stockage Parquet/CSV versionné.
- **Backtest** : moteur maison ou `backtrader`/`vectorbt`, avec coûts réalistes.
- **ML** : scikit-learn, PyTorch/TensorFlow, validation temporelle (TimeSeriesSplit, walk-forward).
- **Orchestration** : scripts + journalisation centralisée, planification (cron/scheduler).
- **Sécurité** : variables d'environnement pour les secrets, aucun token en clair.

---

## 8. Roadmap par phases

| Phase | Contenu | Risque financier |
|---|---|---|
| **0. Simulation (backtest)** | Data + Research + ML : stratégies backtestées et validées | 0 € |
| **1. Paper trading** | Exécution simulée sur données live, Risk + Monitoring actifs | 0 € |
| **2. Capital minimal** | Un seul marché, limites serrées, kill-switch, humain dans la boucle | minime |
| **3. Scale** | Élargissement uniquement si rentabilité stable et validée | progressif |

**Nous sommes en Phase 0.**

---

## 9. Règles de sécurité (rappel)

1. Aucun secret en clair (clés API, seeds, mots de passe) dans le code, les logs ou les commits.
2. Tout accès à une API broker réelle est désactivé tant qu'on est en simulation.
3. Journalisation complète et non modifiable des décisions.
4. Le kill-switch et les limites de risque sont **indépendants** du code de trading.

---

## 10. Prochaines étapes

1. ✅ Définir l'équipe d'agents (ce document).
2. ⬜ Construire l'**Agent Data** (collecte + nettoyage sur une paire pilote, ex. BTC/USDT).
3. ⬜ Construire l'**Agent Research** + moteur de backtest avec coûts réalistes.
4. ⬜ Construire le **module Risk** (limites, métriques, kill-switch).
5. ⬜ Assembler le pipeline de simulation end-to-end.
