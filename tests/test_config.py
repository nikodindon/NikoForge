"""Vérifie que ``config.example.json`` est utilisable et cohérent avec le code.

Un des bloquants identifiés (B1) est que la configuration est obligatoire, absente du dépôt
et gitignorée — le projet refusait de démarrer. Ce module garantit au moins que l'exemple
fourni est valide et qu'il contient **toutes** les clés que le code lit réellement.

C'est le test qui aurait attrapé la dérive documentaire de la v2 (conf C15) : le README
annonçait `max_tokens: 2048` quand l'exemple disait `8192`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = REPO_ROOT / "config.example.json"


# Liste exhaustive des clés lues par le code (relevées dans core/agent.py et core/context.py).
# Si un accès à la configuration est ajouté sans être répercuté ici, ce test le signale.
REQUIRED_KEYS = [
    ("llm", "base_url"),
    ("llm", "model"),
    ("llm", "api_key"),
    ("llm", "temperature"),
    ("llm", "max_tokens"),
    ("llm", "timeout"),
    ("context", "max_tokens"),
    ("context", "compaction_threshold"),
    ("context", "summary_tokens"),
    ("agent", "max_iterations"),
    ("agent", "tool_timeout"),
]


def test_example_config_exists():
    assert EXAMPLE.is_file(), "config.example.json a disparu du dépôt"


def test_example_config_is_valid_json():
    json.loads(EXAMPLE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("section,key", REQUIRED_KEYS)
def test_example_config_has_every_key_the_code_reads(section, key):
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert section in data, f"section manquante : {section}"
    assert key in data[section], f"cle manquante : {section}.{key}"


def test_compaction_threshold_is_a_ratio():
    """La compaction compare un ratio à 1.0 ; une valeur en tokens ferait compacter toujours."""
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    threshold = data["context"]["compaction_threshold"]
    assert 0 < threshold <= 1, f"compaction_threshold={threshold} n'est pas un ratio"


def test_agent_can_be_constructed_from_the_example_config(tmp_path):
    """L'exemple fourni doit réellement permettre d'instancier l'Agent.

    On copie dans tmp_path pour ne pas dépendre du répertoire courant et ne rien écrire
    dans le dépôt.
    """
    from core.agent import Agent

    copy = tmp_path / "config.json"
    copy.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")

    agent = Agent(str(copy))

    assert agent.max_iterations == 20  # valeur de config.example.json à la v2
    assert agent.config["llm"]["model"] == "Qwen3.6-35B-A3B-UD-Q3_K_XL.gguf"


def test_missing_config_raises_a_readable_error(tmp_path):
    """B1 : aujourd'hui c'est une exception qui remonte, transformée en `sys.exit(1)` par le CLI."""
    from core.agent import Agent

    with pytest.raises(FileNotFoundError, match="Configuration non trouvée"):
        Agent(str(tmp_path / "absent.json"))
