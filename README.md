# Équipe d'agents IA — Trading Crypto (simulation)

Équipe d'agents IA spécialisés pour générer un profit sur les marchés crypto, en commençant
**exclusivement en simulation** (backtest + paper trading) avant tout engagement de capital réel.

> **État : Phase 0 (simulation). Aucun capital engagé. 1 candidat au paper trading.**

## Les agents

| Agent | Fichier | Rôle |
|---|---|---|
| 🎯 Ordonnanceur | `agents/orchestrator_agent.py` | Enchaîne le pipeline et consolide le rapport de mission |
| 📊 Data | `agents/data_agent.py` | Collecte + nettoie les chandeliers (Binance, sans clé) |
| 🔬 Research | `agents/research_agent.py` | Backteste et évalue les stratégies (coûts réels) |
| 🤖 ML | `agents/ml_agent.py` | Signaux prédictifs (scikit-learn : Random Forest + logit, walk-forward) |
| 🛡️ Risk | `agents/risk_agent.py` | Limites dures + kill-switch indépendant |
| ⚡ Exécution | `agents/execution_agent.py` | Dry-run paper trading (signal → Risk → fill simulé) |

Documentation : [`01_equipe_agents.md`](01_equipe_agents.md) (rôles & contrats) ·
[`02_passage_paper_trading.md`](02_passage_paper_trading.md) (préparation Phase 1).

## Lancer le pipeline complet

```powershell
cd crypto-trading-agents
python agents\orchestrator_agent.py --symbol BTCUSDT --interval 1h --days 180
```

Enchaîne : Data → Research → Risk, puis écrit `data/reports/BTCUSDT/mission_*.md`.

## Lancer un agent seul

```powershell
# Collecte + nettoyage (ex. 6 mois de BTC/USDT 1h)
python agents\data_agent.py --symbol BTCUSDT --interval 1h --days 180

# Backtest (frais + slippage paramétrables)
python agents\research_agent.py --symbol BTCUSDT --interval 1h --fee-bps 10 --slippage-bps 5

# Signal ML (scikit-learn, validation walk-forward)
python agents\ml_agent.py --symbol BTCUSDT --interval 1h

# Contrôle du risque (limites paramétrables)
python agents\risk_agent.py --symbol BTCUSDT --interval 1h --max-dd 20 --max-daily-loss 5

# Dry-run paper trading (chaîne signal → Risk → fill simulé)
python agents\execution_agent.py --symbol BTCUSDT --interval 1h --strategy sma
```

## Structure

```
crypto-trading-agents/
├── 01_equipe_agents.md            # rôles & contrats
├── 02_passage_paper_trading.md    # préparation Phase 1
├── agents/                        # Data, Research, ML, Risk, Exécution, Ordonnanceur
├── backtest/                      # moteur + métriques + stratégies (10 stratégies)
├── ml/                            # features + modèles scikit-learn
├── risk/                          # limites + RiskManager (kill-switch)
└── data/                          # CSV bruts/clean + rapports
```

## Résultats actuels (BTC/USDT 1h, 6 mois, frais 0,10 % + slippage 0,05 %)

**10 stratégies** testées. Une seule passe les deux verrous (backtest §6 + limites de risque) :

| Stratégie | Retour | Sharpe | Drawdown | Verdict |
|---|---|---|---|---|
| **SMA 50/200** | **+19,5 %** | **1,47** | **13,5 %** | ✅ **CANDIDAT paper** |
| Buy & Hold | +18 % | 0,96 | 29 % | ❌ REJETER (drawdown) |
| SMA 20/50 | +0,3 % | 0,16 | 22 % | ❌ REJETER |
| Momentum 24 | −32 % | −2,6 | 43 % | ❌ REJETER |
| … (6 autres) | — | — | — | ❌ REJETER / kill-switch |

> ⚠️ **SMA_CROSS_50_200** n'a que **12 trades** (dont 4 hors-échantillon) sur 6 mois :
> candidat sérieux mais à **valider en paper trading** (≥ 4 semaines) avant tout capital réel.

**Agent ML (scikit-learn)** : Random Forest 52,7 % de précision hors-échantillon (base 50,3 %),
mais **non rentable après coûts** (−70 %, 414 trades). Le signal ML brut n'est pas exploitable
seul → à améliorer (features, modèle, filtrage par le Risk) avant d'entrer au portefeuille.

## Sécurité

- Aucun secret (clé API, seed) en clair dans le code, les logs ou les commits.
- Aucune API broker réelle tant qu'on est en simulation.
- Le kill-switch et les limites de risque sont **indépendants** du code de trading.
- Python standard uniquement (aucune dépendance externe requise).

## Prérequis

- Python 3.10+ (testé sur 3.14). Agent ML : numpy, pandas, scikit-learn.
- Accès réseau à `data-api.binance.vision` (données publiques Binance, sans restriction géographique).
