"""``core.ui.NikoForgeUI`` : rendu du terminal.

Ce module n'est testable qu'en capturant ``sys.stdout`` : toutes les méthodes sont des
``staticmethod`` qui impriment directement, sans point d'injection. C'est précisément ce que
la phase 5 corrige (séparation rendu/logique, modes ``plain``/``rich``/``json``).

On se limite donc ici aux défauts de rendu vérifiables, et on documente l'absence de
version unique (bug C15d).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nikoforge import ui as ui_module
from nikoforge.ui import NikoForgeUI

# --------------------------------------------------------------------------- #
# Messages simples
# --------------------------------------------------------------------------- #


def test_print_error_format(capsys):
    NikoForgeUI.print_error("boum")
    assert capsys.readouterr().out == "\n❌ Erreur: boum\n\n"


def test_print_success_format(capsys):
    NikoForgeUI.print_success("gagné")
    assert capsys.readouterr().out == "\n✅ gagné\n\n"


def test_print_info_format(capsys):
    NikoForgeUI.print_info("note")
    assert capsys.readouterr().out == "\nℹ️  note\n\n"


def test_print_warning_format(capsys):
    NikoForgeUI.print_warning("attention")
    assert capsys.readouterr().out == "\n⚠️  attention\n\n"


# --------------------------------------------------------------------------- #
# En-tête et barre de statut
# --------------------------------------------------------------------------- #


def test_print_header_shows_the_configuration(capsys):
    NikoForgeUI.print_header(model="modèle-x", base_url="http://h:1/v1", max_tokens=4096)
    out = capsys.readouterr().out
    assert "modèle-x" in out
    assert "http://h:1/v1" in out
    assert "4096" in out


@pytest.mark.known_issue
def test_print_header_closes_its_box_with_the_wrong_corner(capsys):
    """Bug C15d — la boîte s'ouvre sur ``╭…╮`` et se ferme sur ``╰…╮``.

    Le dernier caractère devrait être ``╯``. Défaut cosmétique, mais c'est la première
    chose que voit l'utilisateur au lancement.

    ``core/ui.py`` :
        print(f"╰{'─' * 68}╮")
    """
    NikoForgeUI.print_header(model="m", base_url="u", max_tokens=1)
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    last = lines[-1]

    assert last.startswith("╰")
    assert last.endswith("╮"), "BUG C15d : le coin devrait etre ╯"


def test_print_status_bar_shows_a_percentage_and_a_bar(capsys):
    NikoForgeUI.print_status_bar(
        model="m", current_tokens=50, max_tokens=100, iteration=2, elapsed_time=12.5
    )
    out = capsys.readouterr().out
    assert "50.0%" in out
    assert "2 itérations" in out
    assert "12.5s" in out
    assert "█" in out and "░" in out


def test_print_status_bar_handles_a_zero_max_tokens(capsys):
    """Évite la division par zéro : le cas est explicitement gardé dans le code."""
    NikoForgeUI.print_status_bar(
        model="m", current_tokens=0, max_tokens=0, iteration=1, elapsed_time=0.1
    )
    assert "0.0%" in capsys.readouterr().out


def test_print_status_bar_switches_to_minutes(capsys):
    NikoForgeUI.print_status_bar(
        model="m", current_tokens=1, max_tokens=100, iteration=1, elapsed_time=125.0
    )
    assert "2.1m" in capsys.readouterr().out


def test_print_stats_lists_the_context_fields(capsys):
    NikoForgeUI.print_stats(
        {
            "iteration": 3,
            "context_stats": {
                "total_messages": 7,
                "estimated_tokens": 1234,
                "compaction_count": 0,
            },
        }
    )
    out = capsys.readouterr().out
    assert "Itérations: 3" in out
    assert "Messages: 7" in out
    assert "Tokens estimés: 1234" in out
    assert "Compactions" not in out


def test_print_stats_shows_compactions_only_when_there_were_some(capsys):
    NikoForgeUI.print_stats(
        {
            "iteration": 1,
            "context_stats": {
                "total_messages": 2,
                "estimated_tokens": 10,
                "compaction_count": 2,
            },
        }
    )
    assert "Compactions: 2" in capsys.readouterr().out


def test_print_help_documents_both_modes(capsys):
    NikoForgeUI.print_help()
    out = capsys.readouterr().out
    assert "quit/exit/q" in out
    assert "Mode direct" in out
    assert "Mode interactif" in out


# --------------------------------------------------------------------------- #
# Version en dur (bug C15d)
# --------------------------------------------------------------------------- #


@pytest.mark.known_issue
def test_the_version_string_is_hardcoded_in_two_places():
    """Bug C15d — aucun ``__version__`` : « v2.0 » est écrit en clair dans le logo **et** en
    valeur par défaut de ``print_header``.

    Deux endroits à mettre à jour à chaque version, donc un endroit oublié à chaque fois.
    La phase 2 introduit ``nikoforge.__version__`` comme source unique.

    Le README, lui, annonce v2.0 ; ``pyproject.toml`` déclare 2.0.0 ; la cible est 3.0.0.
    """
    source = Path(ui_module.__file__).read_text(encoding="utf-8")

    assert source.count("v2.0") == 2, "BUG C15d : la version devrait avoir une source unique"
    assert not hasattr(ui_module, "__version__")
