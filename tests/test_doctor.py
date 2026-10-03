"""``nikoforge.doctor`` : diagnostic de l'installation.

Le doctor est la réponse au bloquant B2 (« le serveur est éteint » doit être dit clairement,
avec le remède) et le premier pas du correctif C17 (code de sortie exploitable).
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest
from conftest import UNREACHABLE_BASE_URL, config_for

from nikoforge.config import default_config
from nikoforge.doctor import (
    FAIL,
    OK,
    WARN,
    Check,
    Report,
    check_config,
    check_context,
    check_model,
    check_package,
    check_python,
    check_server,
    check_skills,
    check_storage,
    check_tools,
    check_workdir,
    render_summary_line,
    run_doctor,
)
from nikoforge.server import Probe, probe

FAKE = "modele-de-test"


# --------------------------------------------------------------------------- #
# Objets de rapport
# --------------------------------------------------------------------------- #


def test_check_render_marks_the_status():
    assert Check("python", OK, "3.12").render().startswith("✔")
    assert Check("python", WARN, "vieux").render().startswith("⚠")
    assert Check("python", FAIL, "absent").render().startswith("✖")


def test_check_render_indents_the_remedy():
    rendered = Check("x", FAIL, "détail", "première ligne\nseconde ligne").render()
    assert "  → première ligne" in rendered
    assert "  → seconde ligne" in rendered


def test_report_exit_code_is_zero_without_failure():
    report = Report(checks=[Check("a", OK), Check("b", WARN)])
    assert report.exit_code == 0
    assert report.failed == []
    assert len(report.warnings) == 1


def test_report_exit_code_is_one_with_a_failure():
    report = Report(checks=[Check("a", OK), Check("b", FAIL)])
    assert report.exit_code == 1
    assert [check.label for check in report.failed] == ["b"]


def test_report_renders_a_conclusion():
    assert "bloquant" in Report(checks=[Check("a", FAIL)]).render()
    assert "opérationnel" in Report(checks=[Check("a", OK)]).render()


# --------------------------------------------------------------------------- #
# Contrôles sans effet de bord
# --------------------------------------------------------------------------- #


def test_check_python_passes_on_a_supported_interpreter():
    assert check_python().status == OK


def test_check_python_mentions_the_minimum_version_when_too_old(monkeypatch):
    """``sys.version_info`` est remplacé par un objet offrant ``major``/``minor``/``micro``."""
    import types

    monkeypatch.setattr("sys.version_info", types.SimpleNamespace(major=3, minor=9, micro=0))
    result = check_python()
    assert result.status == FAIL
    assert "3.11" in result.remedy


def test_check_package_passes_with_openai_installed():
    assert check_package().status == OK
    assert "nikoforge" in check_package().detail


def test_check_package_reports_a_missing_dependency(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "openai":
            raise ImportError("simulé")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = check_package()
    assert result.status == FAIL
    assert "openai" in result.detail
    assert "pip install" in result.remedy


def test_check_config_reports_the_absence_of_a_file_as_normal():
    result = check_config(default_config())
    assert result.status == OK
    assert "aucun fichier" in result.detail


def test_check_config_shows_the_loaded_path(tmp_path: Path):
    target = tmp_path / "config.toml"
    target.write_text("", encoding="utf-8")
    from nikoforge.config import load_config

    config = load_config(str(target), env={})
    assert check_config(config).detail == str(target)


def test_check_tools_lists_the_five_tools():
    result = check_tools()
    assert result.status == OK
    for name in ("read_file", "write_file", "edit_file", "bash", "list_files"):
        assert name in result.detail


def test_check_skills_warns_when_the_directory_is_absent(tmp_path: Path):
    config = default_config(tmp_path)
    result = check_skills(config)
    assert result.status == WARN
    assert "pas de répertoire" in result.detail


def test_check_skills_lists_the_available_files(tmp_path: Path, config):
    skills = config.workdir / "skills"
    skills.mkdir()
    (skills / "python.md").write_text("x", encoding="utf-8")
    (skills / "web.md").write_text("x", encoding="utf-8")
    (skills / "README.md").write_text("x", encoding="utf-8")

    result = check_skills(config)

    assert result.status == WARN  # non bloquant : le chargement arrive en phase 4
    assert "2 présent(s)" in result.detail
    assert "python" in result.detail and "web" in result.detail
    assert "README" not in result.detail


def test_check_storage_announces_both_directories():
    result = check_storage()
    assert result.status == OK
    assert "share" in result.detail and "state" in result.detail


# --------------------------------------------------------------------------- #
# Répertoire de travail
# --------------------------------------------------------------------------- #


def test_check_workdir_accepts_a_writable_directory(workdir: Path):
    assert check_workdir(default_config(workdir)).status == OK


def test_check_workdir_proposes_mkdir_when_missing(tmp_path: Path):
    config = default_config(tmp_path / "absent")
    result = check_workdir(config)
    assert result.status == FAIL
    assert result.remedy.startswith("mkdir -p")


def test_check_workdir_rejects_a_file(tmp_path: Path):
    target = tmp_path / "fichier"
    target.write_text("x", encoding="utf-8")
    result = check_workdir(default_config(target))
    assert result.status == FAIL
    assert "pas un répertoire" in result.detail


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignore les permissions de fichier")
def test_check_workdir_detects_a_read_only_directory(tmp_path: Path):
    locked = tmp_path / "verrouille"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        result = check_workdir(default_config(locked))
        assert result.status == FAIL
        assert "lecture seule" in result.detail
    finally:
        locked.chmod(0o700)


def test_check_workdir_leaves_no_probe_file(workdir: Path):
    check_workdir(default_config(workdir))
    assert list(workdir.iterdir()) == []


# --------------------------------------------------------------------------- #
# Serveur et modèle
# --------------------------------------------------------------------------- #


def test_check_server_succeeds_against_a_real_http_server(fake_server):
    result, probe_result = check_server(config_for(fake_server.base_url))
    assert result.status == OK
    assert probe_result.ok is True
    assert "modele-de-test" in " ".join(probe_result.models)


def test_check_server_gives_the_command_to_copy_when_unreachable():
    result, probe_result = check_server(config_for(UNREACHABLE_BASE_URL))
    assert result.status == FAIL
    assert probe_result.ok is False
    assert "llama-server -m" in result.remedy


def test_check_model_validates_a_configured_name(fake_server):
    config = config_for(fake_server.base_url, model=FAKE)
    assert check_model(config, probe(fake_server.base_url)).status == OK


def test_check_model_warns_when_the_name_is_not_announced(fake_server):
    config = config_for(fake_server.base_url, model="autre-modele")
    result = check_model(config, probe(fake_server.base_url))
    assert result.status == WARN
    assert "non annoncé" in result.detail


def test_check_model_discovers_the_name_when_empty(fake_server):
    config = config_for(fake_server.base_url, model="")
    result = check_model(config, probe(fake_server.base_url))
    assert result.status == OK
    assert "découvert" in result.detail


def test_check_model_warns_when_the_server_is_down():
    result = check_model(config_for(UNREACHABLE_BASE_URL, model=""), probe(UNREACHABLE_BASE_URL))
    assert result.status == WARN


def test_check_model_fails_without_any_announced_model():
    result = check_model(config_for("http://h:1/v1", model=""), Probe(ok=True, models=()))
    assert result.status == FAIL
    assert "llama-server -m" in result.remedy


def test_check_context_ok_when_it_fits(fake_server):
    fake_server.n_ctx = 65536
    config = config_for(fake_server.base_url)
    result = check_context(config, probe(fake_server.base_url))
    assert result.status == OK
    assert "65536" in result.detail


def test_check_context_warns_when_it_exceeds_the_server(fake_server):
    fake_server.n_ctx = 1024
    config = config_for(fake_server.base_url)
    config = dataclasses.replace(
        config, context=dataclasses.replace(config.context, max_tokens=8192)
    )
    result = check_context(config, probe(fake_server.base_url))
    assert result.status == WARN
    assert "nikoforge --context 1024" in result.remedy


def test_check_context_is_informative_when_the_server_does_not_say():
    result = check_context(config_for(UNREACHABLE_BASE_URL), Probe(ok=False))
    assert result.status == OK
    assert "non vérifiable" in result.detail


# --------------------------------------------------------------------------- #
# Rapport complet
# --------------------------------------------------------------------------- #


def test_run_doctor_is_green_with_a_working_server(fake_server, tmp_path: Path):
    report = run_doctor(config_for(fake_server.base_url, workdir=tmp_path))
    assert report.exit_code == 0, report.render()
    labels = [check.label for check in report.checks]
    assert labels == [
        "python",
        "paquet",
        "config",
        "serveur",
        "modèle",
        "contexte",
        "outils",
        "skills",
        "workdir",
        "stockage",
    ]


def test_run_doctor_fails_without_a_server(tmp_path: Path):
    report = run_doctor(config_for(UNREACHABLE_BASE_URL, workdir=tmp_path))
    assert report.exit_code == 1
    assert "serveur" in [check.label for check in report.failed]
    assert "llama-server" in report.render()


def test_run_doctor_fails_on_a_missing_workdir(tmp_path: Path, fake_server):
    report = run_doctor(config_for(fake_server.base_url, workdir=tmp_path / "absent"))
    assert report.exit_code == 1
    assert "workdir" in [check.label for check in report.failed]


def test_summary_line_names_the_port_and_the_config_source(fake_server):
    config = config_for(fake_server.base_url)
    line = render_summary_line(config, run_doctor(config))
    assert "prêt" in line
    assert str(fake_server.port) in line
    assert "valeurs par défaut" in line
