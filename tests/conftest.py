"""Fixtures partagées de la suite de tests NikoForge.

Règles de la suite de tests :

* **Aucun test ne nécessite un vrai serveur LLM.** Soit le client est une doublure scriptée,
  soit on lance ``tests/fake_server.py`` — un vrai serveur HTTP qui parle l'API OpenAI.
* **Aucun test ne touche à la configuration de l'utilisateur.** Les tests qui écrivent une
  configuration redirigent ``$NIKOFORGE_CONFIG`` vers ``tmp_path``.
* **Aucun test n'écrit hors de ``tmp_path``.** Le répertoire de travail de l'agent est
  ``tmp_path/workdir``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent

for entry in (REPO_ROOT, TESTS_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from fake_server import FakeLlamaServer  # noqa: E402

from nikoforge.agent import Agent  # noqa: E402
from nikoforge.config import AgentConfig, Config, ContextConfig, LLMConfig  # noqa: E402
from nikoforge.tools import Tools  # noqa: E402

#: Port « discard ». Rien n'y écoute : toute tentative de connexion échoue immédiatement.
#: Garantit qu'un test qui atteindrait le réseau échoue vite, au lieu de parler à un
#: éventuel llama-server lancé sur la machine du développeur.
UNREACHABLE_BASE_URL = "http://127.0.0.1:9/v1"

TEST_MODEL = "modele-de-test"


@pytest.fixture()
def workdir(tmp_path: Path) -> Path:
    """Répertoire de travail de l'agent, créé et isolé."""
    path = tmp_path / "workdir"
    path.mkdir()
    return path


@pytest.fixture()
def config(workdir: Path) -> Config:
    """Configuration complète, valide, mais pointant vers un serveur inexistant.

    Aucune couche externe (fichier TOML, variables d'environnement) n'est lue : la
    configuration est construite en mémoire, ce qui rend les tests indépendants de
    l'environnement de la machine.
    """
    return Config(
        llm=LLMConfig(
            base_url=UNREACHABLE_BASE_URL,
            model=TEST_MODEL,
            api_key="sk-dummy",
            temperature=0.0,
            max_tokens=128,
            timeout=5.0,
        ),
        context=ContextConfig(max_tokens=4096, compaction_threshold=0.8, summary_tokens=200),
        agent=AgentConfig(max_iterations=3, tool_timeout=10),
        workdir=workdir,
    )


@pytest.fixture()
def agent(config: Config) -> Agent:
    """Un agent hors ligne. Instancier l'``Agent`` n'ouvre aucune connexion."""
    return Agent(config)


@pytest.fixture()
def tools(workdir: Path) -> Tools:
    """Un ``Tools`` confiné dans ``workdir`` : toute écriture de test reste temporaire."""
    return Tools(base_dir=str(workdir))


@pytest.fixture()
def fake_server():
    """Faux serveur compatible OpenAI, sur un port libre.

    Vraie communication HTTP : URL, nom de modèle, streaming SSE et ``/props`` sont exercés
    pour de bon. Seul le modèle est simulé.
    """
    server = FakeLlamaServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()


def config_for(base_url: str, model: str = TEST_MODEL, workdir: Path | None = None) -> Config:
    """Configuration minimale pointant vers ``base_url`` (utilitaire hors fixture)."""
    return Config(
        llm=LLMConfig(base_url=base_url, model=model, temperature=0.0, max_tokens=128, timeout=10.0),
        context=ContextConfig(max_tokens=4096, compaction_threshold=0.8, summary_tokens=200),
        agent=AgentConfig(max_iterations=3, tool_timeout=10),
        workdir=workdir or Path.cwd(),
    )
