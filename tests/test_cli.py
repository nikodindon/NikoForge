"""Le point d'entrée ``nikoforge.py``, exercé en sous-processus.

Ces tests sont les seuls à lancer un vrai processus : ils vérifient ce que l'utilisateur
voit réellement (codes de retour inclus). Ils documentent notamment le bloquant B1 —
sans ``config.json``, le programme refuse de démarrer — et un défaut connexe : quand le
modèle est injoignable, le CLI sort quand même en **succès**.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRY = REPO_ROOT / "nikoforge.py"

pytestmark = pytest.mark.skipif(
    not ENTRY.is_file(), reason="nikoforge.py introuvable"
)


def run_nikoforge(*args: str, cwd: Path, stdin: str = "", timeout: int = 60):
    """Lance le CLI depuis ``cwd``, sans terminal et sans réseau exploitable."""
    environment = dict(os.environ, TERM="dumb", NO_COLOR="1")
    return subprocess.run(
        [sys.executable, str(ENTRY), *args],
        cwd=str(cwd),
        env=environment,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture()
def empty_dir(tmp_path: Path) -> Path:
    """Un dossier de travail sans ``config.json``."""
    return tmp_path


@pytest.fixture()
def configured_dir(tmp_path: Path) -> Path:
    """Un dossier de travail contenant une configuration valide mais sans serveur."""
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "llm": {
                    "base_url": "http://127.0.0.1:9/v1",
                    "model": "test-model",
                    "api_key": "sk-dummy",
                    "temperature": 0.0,
                    "max_tokens": 64,
                    "timeout": 3,
                },
                "context": {
                    "max_tokens": 4096,
                    "compaction_threshold": 0.8,
                    "summary_tokens": 200,
                },
                "paths": {"projects_dir": "p", "logs_dir": "l", "skills_dir": "s"},
                "agent": {"max_iterations": 2, "tool_timeout": 5},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


# --------------------------------------------------------------------------- #
# Aide et documentation
# --------------------------------------------------------------------------- #


def test_help_exits_successfully(empty_dir):
    result = run_nikoforge("--help", cwd=empty_dir)
    assert result.returncode == 0
    assert "NikoForge" in result.stdout


def test_help_lists_the_interactive_flag(empty_dir):
    result = run_nikoforge("--help", cwd=empty_dir)
    assert "--interactive" in result.stdout


def test_help_documents_the_config_flag(empty_dir):
    result = run_nikoforge("--help", cwd=empty_dir)
    assert "--config" in result.stdout


def test_help_does_not_require_a_configuration(empty_dir):
    """``--help`` doit marcher partout : c'est la porte d'entrée d'un utilisateur bloqué."""
    assert "Configuration non trouvée" not in run_nikoforge("--help", cwd=empty_dir).stdout


# --------------------------------------------------------------------------- #
# Bloquant B1 : la configuration obligatoire
# --------------------------------------------------------------------------- #


@pytest.mark.known_issue
def test_without_configuration_the_program_refuses_to_start(empty_dir):
    """Bug B1 — ``config.json`` est obligatoire, absent du dépôt et gitignoré.

    L'utilisateur qui suit le README à la lettre (clone, venv, pip, puis lancement) tombe
    sur ce message et sort en code 1. La copie de ``config.example.json`` est une étape
    manuelle non imposée par le programme.
    """
    result = run_nikoforge("dis bonjour", cwd=empty_dir)

    assert result.returncode == 1, "BUG B1 : le programme ne devrait pas exiger config.json"
    assert "Configuration non trouvée: config.json" in result.stdout
    assert "Erreur d'initialisation" in result.stdout


def test_a_missing_explicit_config_path_is_reported_by_name(empty_dir):
    result = run_nikoforge("--config", "autre.json", "tache", cwd=empty_dir)
    assert result.returncode == 1
    assert "Configuration non trouvée: autre.json" in result.stdout


def test_the_logo_is_printed_before_the_error(empty_dir):
    """L'échec arrive après l'affichage du logo : l'utilisateur voit une bannière, puis l'arrêt."""
    result = run_nikoforge(cwd=empty_dir)
    assert "NIKOFORGE" in result.stdout.replace(" ", "").upper() or "╔" in result.stdout


# --------------------------------------------------------------------------- #
# Aide à l'usage quand la configuration est présente
# --------------------------------------------------------------------------- #


def test_without_a_task_it_prints_the_usage(configured_dir):
    result = run_nikoforge(cwd=configured_dir)
    assert result.returncode == 1
    assert "Tu dois fournir une tâche" in result.stdout


def test_a_direct_task_reaches_the_model_and_fails_cleanly(configured_dir):
    """Le serveur n'existe pas : l'échec est signalé, la boucle s'arrête, les statistiques sortent."""
    result = run_nikoforge("dis bonjour", cwd=configured_dir)
    assert "Pas de réponse du modèle" in result.stdout
    assert "Statistiques" in result.stdout


@pytest.mark.known_issue
def test_a_failed_run_still_exits_with_code_zero(configured_dir):
    """Le modèle est injoignable : aucune tâche n'a été accomplie, et pourtant le code de
    retour est 0.

    Scripts et intégrations continues ne peuvent donc pas détecter l'échec. À corriger en
    phase 5 (codes de retour exploitables) avec le message actionnable de B2.
    """
    result = run_nikoforge("dis bonjour", cwd=configured_dir)

    assert result.returncode == 0, "BUG : un echec ne devrait pas sortir en succes"
    assert "Erreur modèle" in result.stdout
    assert "serveur" not in result.stdout.lower(), "BUG B2 : aucun diagnostic actionnable"


@pytest.mark.known_issue
def test_interactive_mode_crashes_on_end_of_input(configured_dir):
    """En mode interactif, une fin d'entrée standard (pipe, ``< /dev/null``, Ctrl+D) n'est pas
    gérée : ``input()`` lève ``EOFError``, qui n'est pas attrapé (seul ``KeyboardInterrupt``
    l'est). Le programme se termine sur une trace Python.

    Conséquence : le REPL ne peut pas être piloté par un tube, donc pas scriptable.
    """
    result = run_nikoforge("--interactive", cwd=configured_dir, stdin="")

    assert result.returncode == 1
    assert "EOFError" in result.stderr, "comportement de la v2 : trace au lieu d'une sortie propre"


def test_an_empty_command_line_keeps_the_repl_alive_forever(configured_dir):
    """Une ligne vide dans le REPL fait simplement ``continue`` : le REPL est un ``while True``
    sans limite d'itérations. À vérifier ici : une seule ligne vide ne termine pas le process.

    On ferme ensuite l'entrée, ce qui provoque l'``EOFError`` connu (test précédent) ; on
    ignore donc le code de retour et on vérifie seulement qu'aucune tâche n'a été lancée.
    """
    result = run_nikoforge("--interactive", cwd=configured_dir, stdin="\n\n\n")

    assert "Tâche:" not in result.stdout
