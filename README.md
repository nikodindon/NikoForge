# 🔥 NikoForge

**Ton propre Pi.dev / QwenCode local — puissant, minimal et autonome.**

Un agent de coding intelligent qui transforme du **langage naturel** en projets complets et fonctionnels, en utilisant tes modèles locaux (actuellement Qwen3.6-35B-A3B).

---

## 🎯 Objectif

NikoForge est une implémentation **minimaliste mais très efficace** d’un coding agent inspiré de Pi.dev, conçu pour tourner entièrement en local sur ton PC.

L’objectif : laisser le modèle (surtout les gros Qwen) faire le maximum de raisonnement, tout en lui donnant un **harness léger, rapide et fiable** pour lire, écrire, modifier des fichiers et exécuter des commandes.

---

## ✨ Fonctionnalités principales

- **Langage naturel → Projet complet** (frontend, backend, fullstack, scripts, etc.)
- Utilisation de **llama-server** (OpenAI compatible)
- Outils de base : `read`, `write`, `edit`, `bash` (comme Pi)
- Boucle agent simple et robuste avec feedback
- Gestion intelligente du contexte (compaction + résumé)
- Support multi-fichiers et projets structurés
- Très faible overhead (harness ultra-léger)
- Intégration possible avec ton écosystème Hermes

---

## 🛠️ Stack actuelle

- **Modèle** : Qwen3.6-35B-A3B (Q3_K_XL ou Q4)
- **Serveur** : llama-server (`--context 65536`)
- **Langage** : Python
- **Système** : Linux Mint (testé)

---

## 🚀 Installation rapide

### 1. Clone le repo
```bash
git clone https://github.com/nikodindon/NikoForge.git
cd NikoForge

### 2. Crée l'environnement
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Lance llama-server (exemple avec tes params)
```bash
./llama-server -m /home/niko/models/Qwen3.6-35B-A3B-UD-Q3_K_XL.gguf \
  -c 65536 --jinja --flash-attn on -ngl 999 \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  -b 512 -ub 512 --threads 8 --threads-batch 6 \
  --kv-offload --mlock --port 8080 --host 0.0.0.0
```

### 4. Configure
Copie `config.example.json` → `config.json` et ajuste le chemin si besoin.

## Utilisation

### Commande basique
```bash
python nikoforge.py "Ton prompt ici"
```

### Mode interactif
```bash
python nikoforge.py --interactive
```

### Options avancées
```bash
# Sauvegarder le contexte
python nikoforge.py "Ton prompt" --save-context mon_context.json

# Charger un contexte existant
python nikoforge.py --load-context mon_context.json --interactive

# Utiliser une config custom
python nikoforge.py "Ton prompt" --config autre_config.json
```

---

## 📚 Comment fonctionne NikoForge

### Architecture

NikoForge est composé de 4 modules principaux :

**1. core/agent.py (Le cerveau)**
- `Agent.run()` - Boucle principale de l'agent
- `_get_model_response()` - Communique avec llama-server
- `_extract_tool_calls()` - Parse la réponse pour extraire les outils
- `_execute_tool()` - Exécute l'outil demandé

**2. core/tools.py (Les mains)**
- `read_file(path)` - Lit un fichier
- `write_file(path, content)` - Crée ou écrase un fichier
- `edit_file(path, old, new)` - Modifie une partie d'un fichier
- `bash(command)` - Exécute une commande shell
- `list_files(path)` - Liste les fichiers d'un répertoire

**3. core/context.py (La mémoire)**
- `add_message()` - Ajoute un message à l'historique
- `get_messages()` - Retourne l'historique des messages
- `compact()` - Compresse l'historique quand il devient trop long
- `estimate_context_size()` - Estime la taille du contexte en tokens

**4. core/prompt.py (Les instructions)**
- `get_system_prompt()` - Instructions optimisées pour le modèle

### Fonctionnement pas à pas

Quand tu lances `python nikoforge.py "Ta tâche"` :

1. **Initialisation**
   - Charge `config.json`
   - Crée les outils (Tools)
   - Crée le gestionnaire de contexte (ContextManager)
   - Initialise le client OpenAI

2. **Boucle principale** (jusqu'à 20 itérations)
   - Vérifie si le contexte doit être compacté
   - Envoie les messages au modèle via llama-server
   - Récupère la réponse
   - Extrait les appels d'outils de la réponse
   - Exécute chaque outil
   - Ajoute les résultats au contexte
   - Répète jusqu'à ce que la tâche soit terminée

3. **Compaction automatique**
   - Quand le contexte dépasse 80% de la limite (25600 tokens)
   - Génère un résumé des messages anciens
   - Garde les 2 derniers messages + le résumé
   - Continue avec un contexte plus léger

4. **Fin**
   - Affiche les statistiques (itérations, messages, tokens)
   - Sauvegarde le contexte si demandé

### Format des appels d'outils

Le modèle répond avec ce format pour utiliser les outils :

```
[outil: nom_outil]
paramètres...

[outil: autre_outil]
{"param": "valeur"}
```

Exemple de réponse du modèle :
```
Je vais créer le fichier hello.py. D'abord je vais vérifier le répertoire.

[outil: list_files]
{"path": "."}

Maintenant je crée le fichier.

[outil: write_file]
{"path": "hello.py", "content": "print('Hello NikoForge!')"}
```

### Gestion du contexte

Le contexte grandit à chaque message :
- 1 message utilisateur ≈ 200 tokens
- 1 message assistant ≈ 500 tokens
- 1 résultat d'outil ≈ 100 tokens

Avec 20 itérations ≈ 16000 tokens

Quand le contexte dépasse 25600 tokens (80% de 32000) :
- `compact()` est appelé
- Les 2 derniers messages sont conservés
- Un résumé des messages anciens est généré
- Le résumé remplace les anciens messages

---

## 💡 Exemples de prompts

### Prompts simples (pour tester)

```bash
# Test basique
python nikoforge.py "Crée un fichier hello.py avec print('Hello NikoForge!')"

# Lecture/écriture
python nikoforge.py "Lis le fichier README.md et crée un résumé dans SUMMARY.md"

# Modification
python nikoforge.py "Dans hello.py, remplace 'Hello NikoForge!' par 'Bonjour!'"

# Commande shell
python nikoforge.py "Liste tous les fichiers Python dans le répertoire courant"
```

### Prompts intermédiaires

```bash
# Création de script
python nikoforge.py "Crée un script Python analyze_logs.py qui lit un fichier log passé en argument et compte le nombre d'erreurs (lignes contenant 'ERROR')"

# Structure de projet
python nikoforge.py "Crée la structure d'un projet Python avec:
- Un package src/
- Un module main.py dans src/
- Un fichier requirements.txt
- Un fichier README.md
- Un répertoire tests/ avec un test vide"

# API simple
python nikoforge.py "Crée une API FastAPI simple avec:
- Un endpoint GET /hello qui retourne {'message': 'Hello World'}
- Un endpoint POST /echo qui renvoie ce qu'il reçoit
- Sauvegarde dans api/main.py"
```

### Prompts avancés

```bash
# Application CLI complète
python nikoforge.py "Crée une application CLI en Python qui:

Requirements:
- Accepte un argument --file pour un fichier
- Lit le fichier et compte les lignes, mots, caractères
- Affiche les statistiques
- Gère les erreurs si le fichier n'existe pas

Structure:
- Un package cli/
- Un module cli/main.py
- Un module cli/utils.py avec les fonctions de comptage
- Un fichier setup.py pour l'installation

Tests:
- Un fichier test_sample.txt avec du texte de test
- Des tests basiques dans tests/"

# Dashboard web
python nikoforge.py "Crée un dashboard web avec Flask:

Features:
- Page d'accueil avec un tableau de bord
- Affiche des métriques système (CPU, RAM, Disque)
- Graphiques simples avec Chart.js
- Rafraîchissement auto toutes les 5 secondes

Structure:
- app/ (package Flask)
- app/templates/ (templates HTML)
- app/static/ (CSS, JS)
- run.py pour lancer l'app
- requirements.txt"

# Projet multi-étapes
python nikoforge.py "Crée un outil de conversion de fichiers:

Étape 1 - Structure:
- Package converter/
- Module converter/core.py (logique de conversion)
- Module converter/cli.py (interface CLI)
- tests/ avec pytest

Étape 2 - Fonctionnalités:
- Convertir TXT vers JSON (une ligne par objet)
- Convertir CSV vers JSON
- Support des flags --input et --output

Étape 3 - Documentation:
- README.md avec exemples d'utilisation
- Docstring pour toutes les fonctions

Implémente étape par étape et teste chaque étape."
```

### Mode interactif

En mode interactif, tu peux dialoguer avec NikoForge de manière continue :

```bash
python nikoforge.py --interactive
```

Ensuite tu peux taper successivement :
```
❓ NikoForge> Crée un fichier test.py
❓ NikoForge> Lis test.py et ajoute une fonction
❓ NikoForge> Teste le fichier avec python test.py
❓ NikoForge> Corrige les erreurs
```

---

## ⚙️ Configuration (config.json)

```json
{
  "llm": {
    "base_url": "http://localhost:8080/v1",
    "model": "Qwen3.6-35B-A3B-UD-Q3_K_XL.gguf",
    "api_key": "sk-dummy",
    "temperature": 0.7,
    "max_tokens": 2048,
    "timeout": null
  },
  "context": {
    "max_tokens": 32000,
    "compaction_threshold": 0.8,
    "summary_tokens": 1000
  },
  "paths": {
    "projects_dir": "projects",
    "logs_dir": "logs",
    "skills_dir": "skills"
  },
  "agent": {
    "max_iterations": 20,
    "tool_timeout": 600
  }
}
```

**Paramètres llm :**
- `base_url` - URL de llama-server
- `model` - Nom du modèle
- `api_key` - Clé API (dummy pour local)
- `temperature` - Créativité (0.0 = précis, 1.0 = créatif)
- `max_tokens` - Maximum de tokens par réponse
- `timeout` - Timeout en secondes (null = pas de limite)

**Paramètres context :**
- `max_tokens` - Limite du contexte total
- `compaction_threshold` - Compacter à X% de la limite
- `summary_tokens` - Taille du résumé lors de la compaction

**Paramètres agent :**
- `max_iterations` - Maximum de boucles avant arrêt
- `tool_timeout` - Timeout des commandes bash (en secondes)

---

## Structure du projet

NikoForge/
├── nikoforge.py          # Point d'entrée principal
├── config.json
├── core/
│   ├── agent.py          # Boucle agent
│   ├── tools.py          # read, write, edit, bash
│   ├── context.py        # Gestion du contexte & compaction
│   └── prompt.py         # System prompt optimisé
├── skills/               # Instructions réutilisables (comme Pi)
├── logs/
├── projects/             # Projets générés
├── AGENTS.md             # Instructions pour les agents (très important)
└── README.md

## Philosophie

- **Minimalisme** : Moins de code = moins d'erreurs et meilleur raisonnement du modèle
- **Puissance du modèle** : On laisse Qwen3.6 faire le gros du travail
- **Contrôle** : Tout est auditable et modifiable
- **Évolutif** : Facile d'ajouter des skills ou des outils

## Roadmap (à venir)

- Mode "Projet multi-étapes" avec planning
- Auto-évaluation + critique loop améliorée
- Support des images/vision (si modèle multimodal)
- Interface web simple (Gradio / Streamlit)
- Intégration Hermes / Mnemo
- Système de "skills" avancé (fichiers Markdown)

## Liens utiles

- **Pi.dev** → Inspiration principale
- **local-intent-coder** → Ancêtre de ce projet
- **Hermes** → Écosystème global

---

Créé avec passion par @nikodindon

"Parce que le futur du coding doit tourner chez soi."

