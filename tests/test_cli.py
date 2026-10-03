"""Le point d'entrée : ``nikoforge`` et ``python -m nikoforge``.

Deux niveaux :

* **en cours de processus** (``main(argv)``) : rapide, permet d'inspecter les codes de sortie
  et la sortie capturée ;
* **en sous-processus** : le vrai chemin d'un utilisateur, y compris la commande installée
  par ``console_scripts``.

Le test décisif de la phase 2 est ``test_no_configuration_needed_to_run_a_task`` : une tâche
aboutit **sans qu'aucun fichier de configuration n'existe ni ne soit créé**.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from nikoforge import __version__
from nikoforge.cli import (
    EXIT_FAILURE,
    EXIT_OK,
    EXIT_SERVER,
    EXIT_USAGE,
    main,
    rewrite_legacy_prompt,
)

from conftest import REPO_ROOT, UNREACHABLE_BASE_URL

MODEL = "modele-de-test"
REPLY = "Bonjour ! Je suis un faux modèle local."


@pytest.fixture()
def home(monkeypatch, tmp_path: Path) -> Path:
    """Environnement hermétique : aucune lecture ni écriture dans la vraie ``~/.config``.

    ``NIKOFORGE_BASE_URL`` pointe par défaut sur un port fermé, pour qu'aucun test ne parle
    au llama-server éventuellement lancé sur la machine de développement.
    """
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home_dir / ".config"))
    monkeypatch.setenv("NIKOFORGE_BASE_URL", UNREACHABLE_BASE_URL)
    monkeypatch.delenv("NIKOFORGE_CONFIG", raising=False)
    monkeypatch.delenv("NIKOFORGE_MODEL", raising=False)
    return home_dir


def subprocess_env(home: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "NIKOFORGE_BASE_URL": UNREACHABLE_BASE_URL,
            "TERM": "dumb",
            "NO_COLOR": "1",
            "PYTHONPATH": str(REPO_ROOT),
        }
    )
    env.pop("NIKOFORGE_CONFIG", None)
    env.pop("NIKOFORGE_MODEL", None)
    env.update(extra)
    return env


def run_module(*args: str, home: Path, cwd: Path | None = None, **extra: str):
    return subprocess.run(
        [sys.executable, "-m", "nikoforge", *args],
        cwd=str(cwd or REPO_ROOT),
        env=subprocess_env(home, **extra),
        capture_output=True,
        text=True,
        timeout=120,
    )


# --------------------------------------------------------------------------- #
# Version, aide, usage
# --------------------------------------------------------------------------- #


def test_version_exits_zero(home, capsys):
    assert main(["--version"]) == EXIT_OK
    assert capsys.readouterr().out.strip() == f"nikoforge {__version__}"


def test_version_needs_no_configuration(home, capsys):
    """``--version`` ne doit jamais échouer, même sans serveur ni configuration."""
    assert main(["--version"]) == EXIT_OK
    assert "Traceback" not in capsys.readouterr().err


def test_help_exits_zero_and_documents_the_exit_codes(home, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == EXIT_OK
    out = capsys.readouterr().out
    assert "codes de sortie" in out
    assert "0 succès" in out


def test_help_advertises_the_three_entry_points(home, capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "-p PROMPT" in out
    assert "doctor" in out
    assert "init" in out


def test_help_says_no_configuration_file_is_needed(home, capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "Aucun fichier de configuration n'est nécessaire" in capsys.readouterr().out


def test_unknown_option_is_a_usage_error(home, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--inconnu"])
    assert exit_info.value.code == EXIT_USAGE


def test_an_unknown_option_is_a_usage_error(home, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--inconnu"])
    assert exit_info.value.code == EXIT_USAGE


@pytest.mark.known_issue
def test_a_bare_word_is_always_read_as_a_prompt():
    """Ambiguïté assumée : ``nikoforge reparer`` exécute la tâche « reparer ».

    Conséquence de l'alias de compatibilité v2 : une sous-commande mal orthographiée devient
    une tâche au lieu d'une erreur. C'est le comportement des autres agents en ligne de
    commande (le premier mot libre est un prompt), et la notice sur ``stderr`` le signale.
    À trancher définitivement en phase 5, quand les commandes slash du REPL arriveront.
    """
    assert rewrite_legacy_prompt(["reparer"]) == (["-p", "reparer"], True)


def test_a_real_subcommand_is_not_taken_for_a_prompt():
    assert rewrite_legacy_prompt(["doctor", "--cwd", "/tmp"]) == (
        ["doctor", "--cwd", "/tmp"],
        False,
    )
    assert rewrite_legacy_prompt(["init", "-y"]) == (["init", "-y"], False)


def test_options_are_not_taken_for_a_prompt():
    assert rewrite_legacy_prompt(["--version"]) == (["--version"], False)
    assert rewrite_legacy_prompt(["-p", "tâche"]) == (["-p", "tâche"], False)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_print_config_emits_parseable_toml(home, capsys):
    assert main(["--print-config"]) == EXIT_OK
    out = capsys.readouterr().out

    parsed = tomllib.loads(out)

    assert parsed["llm"]["base_url"] == UNREACHABLE_BASE_URL  # venu de l'environnement
    assert "context" in parsed and "agent" in parsed


def test_print_config_needs_no_file(home, capsys):
    assert main(["--print-config"]) == EXIT_OK
    assert "base_url" in capsys.readouterr().out


def test_print_config_reflects_a_file(tmp_path: Path, home, capsys):
    target = tmp_path / "config.toml"
    target.write_text(
        '[llm]\nmodel = "modele-du-fichier"\ntemperature = 0.1\n', encoding="utf-8"
    )

    assert main(["--config", str(target), "--print-config"]) == EXIT_OK

    parsed = tomllib.loads(capsys.readouterr().out)
    assert parsed["llm"]["model"] == "modele-du-fichier"
    assert parsed["llm"]["temperature"] == 0.1


def test_missing_config_file_is_a_configuration_error(tmp_path: Path, home, capsys):
    assert main(["--config", str(tmp_path / "absent.toml"), "--print-config"]) == EXIT_USAGE
    assert "introuvable" in capsys.readouterr().err


def test_invalid_key_in_the_config_is_reported(tmp_path: Path, home, capsys):
    target = tmp_path / "config.toml"
    target.write_text("[llm]\nmax_token = 10\n", encoding="utf-8")

    assert main(["--config", str(target), "--print-config"]) == EXIT_USAGE

    err = capsys.readouterr().err
    assert "max_token" in err
    assert "max_tokens" in err


def test_print_system_prompt_lists_the_tools(home, capsys):
    assert main(["--print-system-prompt"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "NikoForge" in out
    assert "tool_calls" in out


# --------------------------------------------------------------------------- #
# Serveur injoignable (corrige B2 et une partie de C17)
# --------------------------------------------------------------------------- #


def test_no_server_gives_an_actionable_message_and_a_specific_exit_code(home, capsys):
    """B2 : l'utilisateur doit apprendre que son serveur est éteint, et comment le lancer."""
    assert main(["-p", "dis bonjour"]) == EXIT_SERVER

    out = capsys.readouterr().out
    assert "serveur injoignable" in out
    assert UNREACHABLE_BASE_URL in out
    assert "llama-server -m" in out
    assert "nikoforge doctor" in out


def test_no_server_does_not_start_the_agent(home, capsys):
    """Aucune itération n'est tentée : le pré-vol interrompt avant d'appeler le modèle."""
    main(["-p", "dis bonjour"])
    assert "Itération" not in capsys.readouterr().out


def test_doctor_exits_one_without_a_server(home, capsys):
    assert main(["doctor"]) == EXIT_FAILURE
    out = capsys.readouterr().out
    assert "✖ serveur" in out
    assert "bloquant" in out


def test_the_no_preflight_flag_is_accepted(home, capsys):
    """Drapeau conservé pour la compatibilité : il ne désactive plus rien."""
    assert main(["--no-preflight", "-p", "x"]) == EXIT_SERVER


# --------------------------------------------------------------------------- #
# Doctor avec un serveur
# --------------------------------------------------------------------------- #


def test_doctor_is_green_with_a_working_server(home, fake_server, monkeypatch, capsys):
    monkeypatch.setenv("NIKOFORGE_BASE_URL", fake_server.base_url)

    assert main(["doctor"]) == EXIT_OK

    out = capsys.readouterr().out
    assert "✔ serveur" in out
    assert "✔ modèle" in out
    assert MODEL in out
    assert "Tout est opérationnel" in out


def test_doctor_reports_a_bad_workdir(home, fake_server, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("NIKOFORGE_BASE_URL", fake_server.base_url)

    assert main(["doctor", "--cwd", str(tmp_path / "absent")]) == EXIT_FAILURE

    out = capsys.readouterr().out
    assert "✖ workdir" in out
    assert "mkdir -p" in out


def test_doctor_reports_the_context_mismatch(home, fake_server, monkeypatch, capsys):
    fake_server.n_ctx = 1024
    monkeypatch.setenv("NIKOFORGE_BASE_URL", fake_server.base_url)

    main(["doctor"])

    out = capsys.readouterr().out
    assert "⚠ contexte" in out
    assert "--context 1024" in out


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #


def test_init_writes_a_complete_commented_config(tmp_path: Path, home, fake_server, monkeypatch, capsys):
    monkeypatch.setenv("NIKOFORGE_BASE_URL", fake_server.base_url)

    assert main(["init", "-y"]) == EXIT_OK

    target = home / ".config" / "nikoforge" / "config.toml"
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    parsed = tomllib.loads(text)

    assert parsed["llm"]["base_url"] == fake_server.base_url
    assert parsed["llm"]["model"] == MODEL  # découvert auprès du serveur
    assert text.count("#") > 15  # commenté
    assert "Prochaines étapes" in capsys.readouterr().out


def test_init_without_a_server_still_writes_and_explains(tmp_path: Path, home, capsys):
    """Pas de serveur ? L'assistant n'échoue pas : il écrit la configuration et montre la commande."""
    assert main(["init", "-y"]) == EXIT_OK

    out = capsys.readouterr().out
    target = home / ".config" / "nikoforge" / "config.toml"

    assert target.is_file()
    assert tomllib.loads(target.read_text(encoding="utf-8"))["llm"]["model"] == ""
    assert "serveur injoignable" in out
    assert "llama-server -m" in out


def test_init_refuses_to_overwrite_without_force(home, capsys):
    target = home / ".config" / "nikoforge" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text("# ne pas toucher\n", encoding="utf-8")

    assert main(["init", "-y"]) == EXIT_FAILURE

    assert target.read_text(encoding="utf-8") == "# ne pas toucher\n"
    assert "--force" in capsys.readouterr().out


def test_init_force_overwrites(home, capsys):
    target = home / ".config" / "nikoforge" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text("# ancien\n", encoding="utf-8")

    assert main(["init", "-y", "--force"]) == EXIT_OK

    assert "# ancien" not in target.read_text(encoding="utf-8")


def test_init_flag_is_an_alias_of_the_subcommand(home, capsys):
    assert main(["--init", "-y"]) == EXIT_OK
    assert (home / ".config" / "nikoforge" / "config.toml").is_file()


def test_init_reads_a_config_written_earlier(home, fake_server, monkeypatch, capsys):
    """Boucle complète : écriture, puis rechargement par une invocation suivante."""
    monkeypatch.setenv("NIKOFORGE_BASE_URL", fake_server.base_url)
    main(["init", "-y"])
    capsys.readouterr()

    assert main(["doctor"]) == EXIT_OK

    out = capsys.readouterr().out
    assert "config" in out
    assert str(home / ".config" / "nikoforge" / "config.toml") in out


# --------------------------------------------------------------------------- #
# Exécution d'une tâche (critère de sortie n° 2 de la phase 2)
# --------------------------------------------------------------------------- #


def test_no_configuration_needed_to_run_a_task(home, fake_server, monkeypatch, capsys):
    """Aucun fichier de configuration, aucun argument : la tâche aboutit quand même."""
    monkeypatch.setenv("NIKOFORGE_BASE_URL", fake_server.base_url)

    assert main(["-p", "dis bonjour"]) == EXIT_OK

    out = capsys.readouterr().out
    assert REPLY in out
    assert "Terminé" in out
    assert fake_server.call_count == 1
    assert not (home / ".config").exists(), "aucun fichier ne doit avoir été créé"


def test_the_model_is_discovered_from_the_server(home, fake_server, monkeypatch, capsys):
    """Le GGUF chargé est repris tel quel : llama-server l'annonce sur /v1/models."""
    monkeypatch.setenv("NIKOFORGE_BASE_URL", fake_server.base_url)
    fake_server.models = ("un/modele/avec/un/chemin.gguf",)

    assert main(["-p", "dis bonjour"]) == EXIT_OK

    assert fake_server.requests[-1]["model"] == "un/modele/avec/un/chemin.gguf"


def test_an_explicit_model_wins_over_the_discovery(home, fake_server, monkeypatch, capsys):
    monkeypatch.setenv("NIKOFORGE_BASE_URL", fake_server.base_url)

    assert main(["--model", "mon-choix", "-p", "dis bonjour"]) == EXIT_OK

    assert fake_server.requests[-1]["model"] == "mon-choix"


def test_the_system_prompt_is_sent_first(home, fake_server, monkeypatch, capsys):
    monkeypatch.setenv("NIKOFORGE_BASE_URL", fake_server.base_url)

    main(["-p", "dis bonjour"])

    messages = fake_server.last_messages()
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "dis bonjour", "timestamp": messages[1]["timestamp"]}


@pytest.mark.known_issue
def test_an_empty_model_answer_exits_non_zero(home, fake_server, monkeypatch, capsys):
    """C17 (partie « code de sortie ») : la v2 sortait toujours en 0, même sans réponse.

    Ici, une réponse vide du modèle devient un échec visible — ce qui permet à un script de
    détecter le problème. La partie « échec en cours de tour » reste à faire en phase 5.
    """
    fake_server.replies = [""]
    monkeypatch.setenv("NIKOFORGE_BASE_URL", fake_server.base_url)

    assert main(["-p", "dis bonjour"]) == EXIT_FAILURE
    assert "aucune réponse du modèle" in capsys.readouterr().out


def test_a_positional_prompt_still_works_with_a_deprecation_notice(
    home, fake_server, monkeypatch, capsys
):
    monkeypatch.setenv("NIKOFORGE_BASE_URL", fake_server.base_url)

    assert main(["dis bonjour"]) == EXIT_OK

    captured = capsys.readouterr()
    assert REPLY in captured.out
    assert "déprécié" in captured.err


def test_interactive_flag_is_accepted_with_a_deprecation_notice(
    home, fake_server, monkeypatch, capsys
):
    monkeypatch.setenv("NIKOFORGE_BASE_URL", fake_server.base_url)

    assert main(["-i", "-p", "dis bonjour"]) == EXIT_OK

    assert "déprécié" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Sous-processus : le vrai chemin utilisateur
# --------------------------------------------------------------------------- #


def test_module_invocation_reports_the_version(home):
    result = run_module("--version", home=home)
    assert result.returncode == EXIT_OK
    assert f"nikoforge {__version__}" in result.stdout


def test_module_invocation_prints_help(home):
    result = run_module("--help", home=home)
    assert result.returncode == EXIT_OK
    assert "Aucun fichier de configuration" in result.stdout


def test_module_invocation_exits_three_without_a_server(home):
    result = run_module("-p", "dis bonjour", home=home)
    assert result.returncode == EXIT_SERVER
    assert "serveur injoignable" in result.stdout


def test_module_invocation_exits_one_for_doctor_without_a_server(home):
    result = run_module("doctor", home=home)
    assert result.returncode == EXIT_FAILURE
    assert "✖ serveur" in result.stdout


def test_end_to_end_in_a_subprocess_without_any_configuration(home, fake_server, capsys, tmp_path: Path):
    """Le critère de sortie de la phase 2, vérifié sur le vrai chemin d'un utilisateur.

    Répertoire de travail vierge, aucun fichier de configuration, aucune variable de modèle :
    la commande aboutit et le modèle est découvert.
    """
    workdir = tmp_path / "ailleurs"
    workdir.mkdir()

    result = run_module(
        "-p",
        "dis bonjour",
        home=home,
        cwd=workdir,
        NIKOFORGE_BASE_URL=fake_server.base_url,
    )

    assert result.returncode == EXIT_OK, result.stdout + result.stderr
    assert REPLY in result.stdout
    assert fake_server.call_count == 1
    assert not (home / ".config").exists()
    assert list(workdir.iterdir()) == [], "l'agent ne doit rien écrire sans qu'on le lui demande"


def test_installed_console_script_works_if_present(home):
    """Vérifie l'entrée ``console_scripts`` déclarée dans pyproject.toml, si installée."""
    script = Path(sys.executable).parent / "nikoforge"
    if not script.exists():
        pytest.skip("commande `nikoforge` non installée dans cet environnement")

    result = subprocess.run(
        [str(script), "--version"],
        env=subprocess_env(home),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == EXIT_OK
    assert f"nikoforge {__version__}" in result.stdout
