# Saxo Readonly

[English](README.md) · [Configuration](docs/configuration.md) · [Intégration OpenClaw](docs/openclaw.md) · [Contribuer](CONTRIBUTING.md)

Connecteur Python local en **lecture seule pour Saxo Bank OpenAPI**, utilisable en ligne de commande, en bibliothèque Python ou avec un skill OpenClaw facultatif. Il consulte les portefeuilles, conserve des relevés SQLite et produit des rapports et alertes locaux. Son fonctionnement ne nécessite aucune bibliothèque Python externe.

Projet communautaire indépendant, sans affiliation officielle avec Saxo. La version **0.1.0** refactorise l'archive `saxo-openclaw-readonly-v1.0.zip` : consulter le [guide de migration](docs/migration.md).

## Fonctions

- Consultation des comptes, du solde consolidé, des positions individuelles et des positions nettes en SIM ou LIVE.
- Authentification OAuth par code, PKCE S256, renouvellement et rotation des jetons.
- Relevés horodatés dans SQLite ; historique et rapports consultables hors ligne.
- Alertes sur les écarts de valorisation entre relevés comparables et sur les variations journalières des instruments lorsque Saxo les fournit.
- Connecteur indépendant d'OpenClaw, accompagné d'un [SKILL.md](skills/saxo-readonly/SKILL.md) facultatif.

**La lecture seule est imposée par les méthodes HTTP et les points d'accès autorisés dans le connecteur.** Cela ne garantit pas qu'un jeton Saxo dérobé soit limité à la lecture. Aucune commande de trading, gestion d'ordres, transfert ou requête HTTP libre n'est fournie. Les seuls POST concernent les jetons OAuth. Voir [SECURITY.md](SECURITY.md).

## Installation Windows

Prérequis : Python **3.10+**, Git et une application Saxo OpenAPI enregistrée pour l'environnement choisi. Commencer par SIM. L'accès LIVE dépend de l'approbation de l'application et des droits attribués par Saxo ; les identifiants applicatifs SIM et LIVE sont distincts. [Environnements Saxo](https://www.developer.saxo/openapi/learn/environments).

Dans PowerShell :

```powershell
Set-Location C:\Users\eric\IdeaProjects
git clone https://github.com/evialle/saxo-readonly.git
Set-Location saxo-readonly
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\saxo-readonly.exe --help
```

Si le dépôt est déjà présent, commencer à `Set-Location saxo-readonly`. L'activation PowerShell de l'environnement virtuel n'est pas nécessaire. Les autres utilisateurs peuvent choisir un autre répertoire parent.

Créer la configuration en dehors du dépôt :

```powershell
$saxoConfigDir = Join-Path $env:LOCALAPPDATA 'saxo-readonly'
New-Item -ItemType Directory -Force -Path $saxoConfigDir | Out-Null
Copy-Item .\config.env.example (Join-Path $saxoConfigDir 'config.env')
notepad (Join-Path $saxoConfigDir 'config.env')
$env:SAXO_CONFIG_FILE = Join-Path $saxoConfigDir 'config.env'
```

Cette variable d'environnement ne concerne que le terminal courant. La définir à nouveau dans un autre terminal, ou utiliser `--config CHEMIN` avant la commande. Ne pas écraser une configuration existante en répétant cette installation.

## Installation Linux ou macOS

```bash
git clone https://github.com/evialle/saxo-readonly.git
cd saxo-readonly
python3 -m venv .venv
.venv/bin/python -m pip install .
install -d -m 700 "$HOME/.config/saxo-readonly"
install -m 600 config.env.example "$HOME/.config/saxo-readonly/config.env"
export SAXO_CONFIG_FILE="$HOME/.config/saxo-readonly/config.env"
```

Modifier le fichier copié avec un éditeur local. Utiliser `.venv/bin/saxo-readonly` à la place de l'exécutable Windows dans la suite. Ne pas recopier l'exemple sur une configuration existante.

## Authentification

Pour une **application PKCE**, renseigner l'AppKey, laisser l'AppSecret vide et conserver `SAXO_OAUTH_FLOW=pkce`. Enregistrer `http://localhost/callback` chez Saxo ; l'URL utilisée par le connecteur est `http://localhost:8765/callback`. Saxo demande une URL sans port lors de l'enregistrement PKCE, puis autorise un port dans la requête d'authentification. Une application confidentielle utilise `SAXO_OAUTH_FLOW=code`, son AppSecret et son URL enregistrée. [Documentation PKCE Saxo](https://www.developer.saxo/openapi/learn/oauth-authorization-code-grant-pkce).

```powershell
.\.venv\Scripts\saxo-readonly.exe auth-start
.\.venv\Scripts\saxo-readonly.exe auth-finish
.\.venv\Scripts\saxo-readonly.exe auth-status
```

1. Exécuter `auth-start`, puis ouvrir l'URL affichée dans son navigateur personnel.
2. Se connecter à Saxo. Le navigateur est redirigé vers l'URL de retour. **Aucun serveur local de retour n'est lancé** : une page « connexion refusée » est normale. Copier l'URL complète depuis la barre d'adresse.
3. Exécuter `auth-finish` et coller cette URL dans la saisie masquée du terminal. Ne jamais la mettre dans un argument de commande, une issue, un journal ou une conversation avec un agent.

Les deux étapes doivent utiliser le même poste, le même utilisateur et la même configuration. Relancer `auth-start` si une tentative expire ou échoue. Les consultations renouvellent les jetons lorsque nécessaire. Pour maintenir une session inactive tant qu'un terminal reste ouvert :

```powershell
.\.venv\Scripts\saxo-readonly.exe refresh --watch --interval 300
```

Ce renouvellement ne garantit pas une connexion permanente : Saxo peut expirer ou révoquer la session. Un PC en veille ou déconnecté ne peut pas la maintenir. Voir le [guide d'exploitation](docs/operations.md).

## Consulter et surveiller

```powershell
.\.venv\Scripts\saxo-readonly.exe accounts
.\.venv\Scripts\saxo-readonly.exe balances
.\.venv\Scripts\saxo-readonly.exe positions
.\.venv\Scripts\saxo-readonly.exe netpositions
.\.venv\Scripts\saxo-readonly.exe snapshot
.\.venv\Scripts\saxo-readonly.exe history --limit 20
.\.venv\Scripts\saxo-readonly.exe report
.\.venv\Scripts\saxo-readonly.exe alerts --threshold 3 --fail-on-alert
```

`snapshot` collecte les données courantes et enregistre un relevé local. `history`, `report` et `alerts` utilisent les relevés enregistrés sans contacter Saxo. `report` produit du Markdown ; les commandes de données produisent du JSON. Ces sorties peuvent contenir des identifiants de compte et des données financières privées : choisir ce que l'on partage.

Le seuil d'alerte est un pourcentage strictement positif. La comparaison porte sur le dernier relevé et son prédécesseur compatible : même environnement, client, devise et ensemble de comptes. Une base nulle ou une valeur absente ne permet pas de calculer un pourcentage. Les alertes instrument utilisent la variation journalière fournie par Saxo ; une donnée absente n'est pas une variation nulle.

**L'écart de valorisation n'est pas un rendement.** Dépôts, retraits, opérations, dividendes, frais et variations de change ne sont pas neutralisés. Le solde consolidé utilise la devise fournie par Saxo ; ne pas additionner des comptes de devises différentes. Les relevés résultent d'appels successifs, et non d'une photographie atomique de tout le marché.

| Code de sortie | Signification |
| --- | --- |
| `0` | Commande terminée ; également utilisé sans historique ou sans référence de comparaison |
| `1` | Échec de configuration, authentification, API ou stockage local |
| `2` | Syntaxe de commande invalide |
| `3` | Alerte déclenchée avec l'option `--fail-on-alert` |
| `130` | Interruption par Ctrl+C |

Le connecteur n'envoie aucun email ni message. Un planificateur peut examiner le JSON ou le code 3, puis gérer les notifications selon votre choix.

## Bibliothèque Python

```python
from saxo_readonly.client import SaxoClient
from saxo_readonly.config import Config

client = SaxoClient(Config.load())
balances = client.balances()
positions = client.positions()
portfolio = client.snapshot()  # Retourne les données ; la CLI les enregistre aussi.
```

Effectuer l'authentification avec la CLI au préalable. `Config.load()` lit le fichier choisi par `SAXO_CONFIG_FILE` ou par l'argument `path` ; les variables d'environnement ont priorité sur le fichier. Voir la [configuration](docs/configuration.md).

## OpenClaw facultatif

Installer le paquet Python sur la machine où l'agent exécute ses commandes, rendre `saxo-readonly` accessible dans son PATH, réaliser l'authentification localement, puis installer le dossier `skills/saxo-readonly`. Le [guide OpenClaw](docs/openclaw.md) détaille ces étapes : copier le skill seul n'installe pas le connecteur.

## Développement et vérification

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Les tests utilisent des données fictives et des réponses réseau simulées. Ils couvrent les restrictions de lecture seule, OAuth, la pagination, le stockage, les alertes et la CLI. GitHub Actions exécute la CI du dépôt sans recevoir d'identifiants Saxo. Les tests hors ligne ne prouvent **pas** l'accès à un compte réel, les droits Saxo ni le succès complet de l'authentification de votre application. Voir [CONTRIBUTING.md](CONTRIBUTING.md).

Licence [Apache 2.0](LICENSE). Les contributions et corrections de compatibilité Saxo sont bienvenues, avec un exemple SIM reproductible sans données personnelles.
