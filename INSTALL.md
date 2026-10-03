# Installation NikoForge v3.0 (dev) — depuis le dépôt

```bash
git clone -b dev https://github.com/nikodindon/NikoForge.git
cd NikoForge
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest        # 416 verts
.venv/bin/nikoforge doctor         # diagnostic du serveur et du modèle
```

Dépendance unique : `openai>=1.0.0`. Le serveur LLM (`llama-server`) doit être lancé séparément (non inclus).

# Utilisation

```
nikoforge --base-url http://100.91.114.49:8080/v1 -p "Crée un fichier..."
```

Protocole : détecté sur `/props` (`native` si `supports_tools`, sinon `text` en CDATA). `D3` (sandbox) : aucun confinement par défaut (tranché). Voir `docs/DECISIONS.md`, `docs/REFONTE.md` (C1-C18), `ROADMAP.md` (phases 0-6).

Tests réels : un vrai `llama-server` (modèle Ornith-1.5-35B, port 8080) est testé. Les faux serveurs (`tests/fake_server.py`) couvrent le protocole natif, le raisonnement, et les erreurs.

# Commandes de test (réelles, pas simulées)

```bash
# 1. Installation + suite complète
.venv/bin/python -m pytest -q

# 2. Diagnostic sur le vrai serveur
.venv/bin/nikoforge --base-url http://100.91.114.49:8080/v1 doctor

# 3. Tache E2E sur le vrai serveur (fichier + execution)
.venv/bin/nikoforge --base-url http://100.91.114.49:8080/v1 --cwd /tmp/nf_e2e -p "Cree hello.py..."

# 4. Mode REPL interactif
.venv/bin/nikoforge -i

# 5. Protocole force (native / text)
.venv/bin/nikoforge --base-url http://... --protocol native -p "..."

# 6. Session resume, undo, stats (phase 5 stubs)
.venv/bin/nikoforge --list-sessions
.venv/bin/nikoforge -c <session>

# 7. Sortie brute (CI / pipe)
.venv/bin/nikoforge --plain -p "..." | cat
```

Serveur de test : `tests/fake_server.py` (local, sans GPU).

# Mode stream (temps reel)
.venv/bin/nikoforge --stream --base-url http://100.91.114.49:8080/v1 -p "..."
# Affiche chaque etape au fur et a mesure (agent.py : _say(), chaque outil, chaque resultat, chaque refus).
