"""Fixtures partagées de la suite de tests NikoForge.

Règles de la suite de tests :

* **Aucun test ne doit nécessiter un serveur LLM.** Le client est soit inutilisé, soit simulé.
* **Aucun test ne doit nécessiter ``config.json`` à la racine du dépôt.** L'``Agent`` est
  instancié avec une configuration jetable écrite dans ``tmp_path``.
* **Aucun test n'écrit hors de ``tmp_path``.** L'outil ``Tools`` est toujours construit avec
  un ``base_dir`` temporaire.

Ces deux derniers points sont la raison d'être de la phase 1 : ils rendent la suite exécutable
sur n'importe quelle machine, y compris en intégration continue, sans préparer d'environnement.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Permet `import core.agent` quel que soit le répertoire d'invocation de pytest.
# (Redondant avec `pythonpath = ["."]` de pyproject.toml, mais rend le fichier autonome.)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


#: Configuration minimale mais complète, pointant vers un port qui ne répond pas.
#: Aucun test ne doit atteindre le réseau : si l'un d'eux le fait, il échoue vite au lieu
#: de parler à un éventuel llama-server lancé sur la machine du développeur.
MINIMAL_CONFIG: dict = {
    "llm": {
        "base_url": "http://127.0.0.1:9/v1",
        "model": "test-model",
        "api_key": "sk-dummy",
        "temperature": 0.0,
        "max_tokens": 128,
        "timeout": 5,
    },
    "context": {
        "max_tokens": 4096,
        "compaction_threshold": 0.8,
        "summary_tokens": 200,
    },
    "paths": {
        "projects_dir": "projects",
        "logs_dir": "logs",
        "skills_dir": "skills",
    },
    "agent": {
        "max_iterations": 3,
        "tool_timeout": 10,
    },
}


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    """Écrit la configuration minimale dans un dossier temporaire et retourne son chemin."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps(MINIMAL_CONFIG, indent=2), encoding="utf-8")
    return path


@pytest.fixture()
def agent(config_path: Path):
    """Un ``Agent`` hors ligne. Aucun appel réseau n'est déclenché par les tests."""
    from core.agent import Agent

    return Agent(str(config_path))


@pytest.fixture()
def tools(tmp_path: Path):
    """Un ``Tools`` confiné dans ``tmp_path`` : toute écriture de test reste temporaire."""
    from core.tools import Tools

    return Tools(base_dir=str(tmp_path))


@pytest.fixture()
def workdir(tmp_path: Path) -> Path:
    """Le ``base_dir`` du fixture ``tools``, pour vérifier ce qui a réellement été écrit."""
    return tmp_path
