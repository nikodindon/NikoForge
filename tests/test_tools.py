"""``core.tools`` : lecture, écriture, édition, listing, shell.

Le fixture ``tools`` confine toute écriture dans ``tmp_path`` : ce module ne touche jamais
au dépôt (contrairement à la v2, dont les 9 résidus en racine étaient précisément des
fichiers créés par ces outils avec ``base_dir="."`` — bug C13/C14).
"""

from __future__ import annotations

import pytest

from nikoforge.tools import ToolResult, format_tool_result


# --------------------------------------------------------------------------- #
# read_file
# --------------------------------------------------------------------------- #


def test_read_file_returns_content(tools, workdir):
    (workdir / "a.txt").write_text("bonjour\n", encoding="utf-8")
    result = tools.read_file("a.txt")
    assert result.success is True
    assert result.data == "bonjour\n"
    assert result.error is None


def test_read_file_handles_utf8(tools, workdir):
    (workdir / "a.txt").write_text("éàçü — ★", encoding="utf-8")
    assert tools.read_file("a.txt").data == "éàçü — ★"


def test_read_file_missing_returns_error(tools):
    result = tools.read_file("absent.txt")
    assert result.success is False
    assert result.data is None
    assert "non trouvé" in result.error


def test_read_file_accepts_absolute_path(tools, workdir):
    target = workdir / "abs.txt"
    target.write_text("x", encoding="utf-8")
    assert tools.read_file(str(target)).data == "x"


def test_read_file_reads_whole_file_without_any_bound(tools, workdir):
    """Bug C6 — pas d'``offset``/``limit`` : un gros fichier explose le contexte.

    Aucun paramètre d'offset n'existe sur la méthode, et le contenu entier est renvoyé.
    """
    (workdir / "gros.txt").write_text("A" * 50_000, encoding="utf-8")
    result = tools.read_file("gros.txt")

    assert result.success is True
    assert len(result.data) == 50_000, "BUG C6 : le contenu devrait pouvoir être borné"
    import inspect

    assert "offset" not in inspect.signature(tools.read_file).parameters
    assert "limit" not in inspect.signature(tools.read_file).parameters


# --------------------------------------------------------------------------- #
# write_file
# --------------------------------------------------------------------------- #


def test_write_file_creates_the_file(tools, workdir):
    result = tools.write_file("a.txt", "contenu")
    assert result.success is True
    assert (workdir / "a.txt").read_text(encoding="utf-8") == "contenu"


def test_write_file_creates_missing_parent_directories(tools, workdir):
    result = tools.write_file("deep/nested/dir/a.txt", "x")
    assert result.success is True
    assert (workdir / "deep/nested/dir/a.txt").is_file()


def test_write_file_overwrites_silently(tools, workdir):
    (workdir / "a.txt").write_text("ancien", encoding="utf-8")
    tools.write_file("a.txt", "nouveau")
    assert (workdir / "a.txt").read_text(encoding="utf-8") == "nouveau"


def test_write_file_preserves_content_byte_for_byte(tools, workdir):
    """Le contenu passé à l'outil est écrit tel quel (le bug C1b est en amont, dans le parser)."""
    content = "    indente\n\n\ttabule\n"
    tools.write_file("a.py", content)
    assert (workdir / "a.py").read_text(encoding="utf-8") == content


@pytest.mark.known_issue
def test_write_file_escapes_the_base_dir_without_complaint(tools, workdir):
    """Bug C14 — ``_resolve_path`` n'applique aucun confinement.

    Un `..` sortant est résolu sans contrôle : la notion de ``base_dir`` est décorative.
    """
    result = tools.write_file("../hors_sandbox.txt", "evade")
    assert result.success is True, "BUG C14 : écrire hors de base_dir devrait être refusé"
    assert (workdir.parent / "hors_sandbox.txt").is_file()
    assert ".." in result.data


# --------------------------------------------------------------------------- #
# edit_file
# --------------------------------------------------------------------------- #


def test_edit_file_replaces_the_pattern(tools, workdir):
    (workdir / "a.txt").write_text("couleur = rouge", encoding="utf-8")
    result = tools.edit_file("a.txt", "rouge", "bleu")
    assert result.success is True
    assert (workdir / "a.txt").read_text(encoding="utf-8") == "couleur = bleu"


def test_edit_file_reports_a_pattern_that_does_not_exist(tools, workdir):
    (workdir / "a.txt").write_text("abc", encoding="utf-8")
    result = tools.edit_file("a.txt", "zzz", "yyy")
    assert result.success is False
    assert "non trouvé" in result.error
    assert (workdir / "a.txt").read_text(encoding="utf-8") == "abc"


def test_edit_file_on_a_missing_file_fails(tools):
    result = tools.edit_file("absent.txt", "a", "b")
    assert result.success is False
    assert "non trouvé" in result.error


@pytest.mark.known_issue
def test_edit_file_replaces_all_occurrences_silently(tools, workdir):
    """Bug C5 — ``str.replace`` sans contrôle d'unicité.

    Le motif apparaît deux fois : les deux sont modifiées, et l'outil répond succès.
    C'est une corruption de fichier déguisée. Le comportement attendu (phase 3) est une
    erreur explicite indiquant le nombre d'occurrences et leurs lignes.
    """
    (workdir / "multi.py").write_text("x = 1\ny = 2\nx = 1\n", encoding="utf-8")

    result = tools.edit_file("multi.py", "x = 1", "x = 999")

    assert result.success is True, "BUG C5 : l'ambiguïté devrait être signalée"
    assert (workdir / "multi.py").read_text(encoding="utf-8") == "x = 999\ny = 2\nx = 999\n"


def test_edit_file_accepts_an_empty_replacement(tools, workdir):
    """Suppression de texte : ``new_content=""`` est falsy, mais le routeur de l'Agent
    le refuse (voir test_agent_loop). Ici on appelle la couche Tools directement."""
    (workdir / "a.txt").write_text("garder\nsupprimer\n", encoding="utf-8")
    result = tools.edit_file("a.txt", "supprimer\n", "")
    assert result.success is True
    assert (workdir / "a.txt").read_text(encoding="utf-8") == "garder\n"


# --------------------------------------------------------------------------- #
# list_files
# --------------------------------------------------------------------------- #


def test_list_files_returns_entries_with_type(tools, workdir):
    (workdir / "a.txt").write_text("x", encoding="utf-8")
    (workdir / "sous_dossier").mkdir()

    result = tools.list_files(".")

    assert result.success is True
    entries = {e["name"]: e["type"] for e in result.data}
    assert entries == {"a.txt": "file", "sous_dossier": "dir"}


def test_list_files_is_not_sorted(tools, workdir):
    """L'ordre vient de ``Path.iterdir()`` : il est propre au système de fichiers.

    À noter : un agent qui veut un ordre stable ne peut pas compter sur cet outil.
    """
    for name in ["c.txt", "a.txt", "b.txt"]:
        (workdir / name).write_text("x", encoding="utf-8")

    names = [e["name"] for e in tools.list_files(".").data]

    assert sorted(names) == ["a.txt", "b.txt", "c.txt"]


def test_list_files_on_a_missing_directory_fails(tools):
    result = tools.list_files("absent/")
    assert result.success is False
    assert "non trouvé" in result.error


def test_list_files_on_a_file_fails(tools, workdir):
    (workdir / "a.txt").write_text("x", encoding="utf-8")
    result = tools.list_files("a.txt")
    assert result.success is False
    assert "pas un répertoire" in result.error


def test_list_files_returns_relative_paths(tools, workdir):
    (workdir / "sub").mkdir()
    (workdir / "sub" / "a.txt").write_text("x", encoding="utf-8")
    entries = {e["name"]: e["path"] for e in tools.list_files("sub").data}
    assert entries == {"a.txt": "sub/a.txt"}


# --------------------------------------------------------------------------- #
# bash
# --------------------------------------------------------------------------- #


def test_bash_returns_stdout_and_exit_code(tools):
    result = tools.bash("echo bonjour")
    assert result.success is True
    assert result.data["stdout"] == "bonjour\n"
    assert result.data["stderr"] == ""
    assert result.data["exit_code"] == 0


def test_bash_runs_in_the_base_dir(tools, workdir):
    result = tools.bash("pwd")
    assert result.data["stdout"].strip() == str(workdir)


def test_bash_nonzero_exit_is_a_failure(tools):
    result = tools.bash("echo oups >&2; exit 3")
    assert result.success is False
    assert result.data["exit_code"] == 3
    assert result.data["stderr"] == "oups\n"
    assert result.error == "oups\n"


def test_bash_failure_without_stderr_has_an_empty_error(tools):
    """Nuance : ``exit 3`` sans message laisse ``error`` à ``""``.

    ``format_tool_result`` affiche alors « ✗ Erreur: » suivi de rien — un message
    inexploitable pour l'humain comme pour le modèle.
    """
    result = tools.bash("exit 3")
    assert result.success is False
    assert result.error == ""
    assert format_tool_result(result) == "✗ Erreur: "


def test_bash_timeout_is_reported_in_seconds(tools):
    result = tools.bash("sleep 5", timeout=1)
    assert result.success is False
    assert result.data is None
    assert result.error == "Commande timeout après 1s"


def test_bash_output_is_not_truncated(tools):
    """Bug C6 (volet shell) — stdout et stderr complets, sans borne.

    Une commande verbeuse sature le contexte en une seule itération.
    """
    result = tools.bash("yes A | head -n 20000")
    assert len(result.data["stdout"]) == 40_000, "BUG C6 : la sortie devrait être bornée"


def test_bash_stderr_is_captured_even_on_success(tools):
    result = tools.bash("echo avertissement >&2; echo ok")
    assert result.success is True
    assert result.data["stdout"] == "ok\n"
    assert result.data["stderr"] == "avertissement\n"


def test_bash_uses_shell_features(tools, workdir):
    """``shell=True`` : les redirections et les tubes fonctionnent (et donc l'injection aussi)."""
    result = tools.bash("echo contenu > ecrit_par_le_shell.txt")
    assert result.success is True
    assert (workdir / "ecrit_par_le_shell.txt").read_text(encoding="utf-8") == "contenu\n"


# --------------------------------------------------------------------------- #
# ToolResult et formatage destiné à l'affichage
# --------------------------------------------------------------------------- #


def test_tool_result_to_dict():
    result = ToolResult(True, "données", None)
    assert result.to_dict() == {"success": True, "data": "données", "error": None}


def test_format_tool_result_on_success_with_data():
    assert format_tool_result(ToolResult(True, "ok")) == "✓ Succès\nDonnées: ok\n"


def test_format_tool_result_on_success_without_data():
    assert format_tool_result(ToolResult(True, None)) == "✓ Succès\n"


def test_format_tool_result_on_failure():
    assert format_tool_result(ToolResult(False, None, "boum")) == "✗ Erreur: boum"


@pytest.mark.known_issue
def test_format_tool_result_exposes_a_python_repr_to_the_model(tools):
    """Bug C3 — cette chaîne, écrite pour l'humain, est envoyée telle quelle **au modèle**.

    ``core/agent.py`` construit le message du modèle avec ``format_tool_result``. Le modèle
    doit donc déchiffrer une ``repr()`` Python avec ses ``\\n`` échappés, précédée d'un « ✓ »
    et du mot français « Données ». ``stdout``, ``stderr`` et ``exit_code`` ne lui sont pas
    présentés comme des champs distincts.

    La phase 3 sépare ``to_model()`` (champs texte explicites) de ``to_human()``.
    """
    result = tools.bash("echo hi")

    rendered = format_tool_result(result)

    assert rendered.startswith("✓ Succès\nDonnées: {'stdout':")
    assert "\\n" in rendered, "BUG C3 : le modèle reçoit des \\n échappés au lieu du texte"
    assert "exit_code" in rendered
