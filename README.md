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

2. Crée l’environnementbash

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

3. Lance llama-server (exemple avec tes params)bash

./llama-server -m /home/niko/models/Qwen3.6-35B-A3B-UD-Q3_K_XL.gguf \
  -c 65536 --jinja --flash-attn on -ngl 999 \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  -b 512 -ub 512 --threads 8 --threads-batch 6 \
  --kv-offload --mlock --port 8080 --host 0.0.0.0

4. ConfigureCopie config.example.json → config.json et ajuste le chemin si besoin. Utilisationbash

python nikoforge.py "Crée-moi un dashboard React + FastAPI qui affiche les stats système en temps réel avec des graphiques beaux"

Ou en mode interactif :bash

python nikoforge.py --interactive

 Structure du projet

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

 PhilosophieMinimalisme : Moins de code = moins d’erreurs et meilleur raisonnement du modèle
Puissance du modèle : On laisse Qwen3.6 faire le gros du travail
Contrôle : Tout est auditable et modifiable
Évolutif : Facile d’ajouter des skills ou des outils

Roadmap (à venir)Mode "Projet multi-étapes" avec planning
Auto-évaluation + critique loop améliorée
Support des images/vision (si modèle multimodal)
Interface web simple (Gradio / Streamlit)
Intégration Hermes / Mnemo
Système de "skills" avancé (fichiers Markdown)

Liens utilesPi.dev → Inspiration principale
local-intent-coder → Ancêtre de ce projet
Hermes → Écosystème global

Créé avec passion par @nikodindon

“Parce que le futur du coding doit tourner chez soi.”

