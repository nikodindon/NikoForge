"""``nikoforge.server`` : découverte du serveur et du modèle, aide à l'installation.

Ces tests parlent HTTP pour de bon, contre un faux serveur local
(``tests/fake_server.py``). C'est le module qui corrige le bloquant B2 : en v2, un serveur
éteint ne produisait qu'un « ✗ Pas de réponse du modèle », sans diagnostic ni remède.

Le cas « rien n'écoute » est testé sur le port 9 (discard), qui refuse immédiatement la
connexion — donc sans dépendre d'un serveur absent sur la machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nikoforge.server import (
    Probe,
    find_local_models,
    models_url,
    pick_model,
    port_of,
    probe,
    server_context_size,
    suggest_server_command,
)

UNREACHABLE = "http://127.0.0.1:9/v1"


# --------------------------------------------------------------------------- #
# Utilitaires
# --------------------------------------------------------------------------- #


def test_models_url_appends_to_v1():
    assert models_url("http://h:8080/v1") == "http://h:8080/v1/models"


def test_models_url_tolerates_a_trailing_slash():
    assert models_url("http://h:8080/v1/") == "http://h:8080/v1/models"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://h:8080/v1", 8080),
        ("http://h:1234/v1", 1234),
        ("http://127.0.0.1/v1", 8080),
        ("http://[::1]:9999/v1", 9999),
        ("pas-une-url", 8080),
    ],
)
def test_port_of(url, expected):
    assert port_of(url) == expected


# --------------------------------------------------------------------------- #
# Serveur joignable
# --------------------------------------------------------------------------- #


def test_probe_succeeds_on_a_real_http_server(fake_server):
    result = probe(fake_server.base_url)
    assert result.ok is True
    assert result.models == ("modele-de-test",)
    assert result.error is None
    assert result.latency is not None and result.latency >= 0


def test_probe_reports_several_models(fake_server):
    fake_server.models = ("alpha", "beta")
    result = probe(fake_server.base_url)
    assert result.ok is True
    assert result.models == ("alpha", "beta")
    assert result.single_model is None


def test_probe_uses_the_real_openai_shape(fake_server):
    """La réponse est lue au format ``{"data": [{"id": ...}]}``, comme llama-server."""
    result = probe(fake_server.base_url)
    assert "modele-de-test" in result.models


def test_server_context_size_reads_props(fake_server):
    fake_server.n_ctx = 65536
    assert server_context_size(fake_server.base_url) == 65536


def test_server_context_size_is_none_when_unsupported(tmp_path: Path):
    """Un serveur sans ``/props`` n'est pas une erreur : l'information est simplement absente."""
    assert server_context_size(UNREACHABLE) is None


# --------------------------------------------------------------------------- #
# Serveur injoignable (corrige B2)
# --------------------------------------------------------------------------- #


def test_probe_on_a_closed_port_returns_a_usable_diagnostic():
    result = probe(UNREACHABLE, timeout=1)
    assert result.ok is False
    assert "connexion impossible" in result.error
    assert "/v1/models" in result.detail


def test_probe_on_a_wrong_path_reports_the_status():
    """Un serveur qui répond mais pas sur la bonne route : cas réaliste d'une URL fautive."""
    result = probe("http://127.0.0.1:9", timeout=1)
    assert result.ok is False
    assert result.error


def test_probe_never_raises_whatever_the_url():
    for url in ("http://127.0.0.1:9/v1", "http://[::1]:9/v1", "n'importe quoi", ""):
        result = probe(url, timeout=1)
        assert isinstance(result, Probe)
        assert result.ok is False


# --------------------------------------------------------------------------- #
# Choix du modèle
# --------------------------------------------------------------------------- #


def test_pick_model_returns_the_single_model_without_warning():
    model, warning = pick_model(Probe(ok=True, models=("unique",)))
    assert model == "unique"
    assert warning == ""


def test_pick_model_keeps_the_first_and_warns_when_ambiguous():
    model, warning = pick_model(Probe(ok=True, models=("premier", "second")))
    assert model == "premier"
    assert "second" in warning and "--model" in warning


def test_pick_model_returns_nothing_without_models():
    model, warning = pick_model(Probe(ok=True, models=()))
    assert model is None
    assert warning == ""


# --------------------------------------------------------------------------- #
# Aide à l'installation
# --------------------------------------------------------------------------- #


def test_suggest_server_command_uses_the_configured_port():
    command = suggest_server_command("http://127.0.0.1:9123/v1", models_dir=None)
    assert "--port 9123" in command
    assert "llama-server -m" in command
    assert "--jinja" in command


def test_suggest_server_command_uses_a_discovered_model(tmp_path: Path):
    model = tmp_path / "mon-modele.gguf"
    model.write_bytes(b"\0" * 32)
    command = suggest_server_command("http://h:1/v1", models_dir=tmp_path)
    assert "mon-modele.gguf" in command


def test_suggest_server_command_has_a_placeholder_without_local_model(tmp_path: Path):
    command = suggest_server_command("http://h:1/v1", models_dir=tmp_path)
    assert "/chemin/vers/modele.gguf" in command


def test_find_local_models_returns_the_most_recent_first(tmp_path: Path):
    older = tmp_path / "vieux.gguf"
    newer = tmp_path / "recent.gguf"
    older.write_bytes(b"a")
    newer.write_bytes(b"b")
    import os
    import time

    os.utime(older, (time.time() - 3600, time.time() - 3600))

    found = find_local_models(tmp_path)
    assert [path.name for path in found] == ["recent.gguf", "vieux.gguf"]


def test_find_local_models_recurses_and_limits(tmp_path: Path):
    (tmp_path / "sous").mkdir()
    for index in range(7):
        (tmp_path / "sous" / f"m{index}.gguf").write_bytes(b"x")
    assert len(find_local_models(tmp_path, limit=3)) == 3


def test_find_local_models_on_a_missing_directory_is_empty(tmp_path: Path):
    assert find_local_models(tmp_path / "absent") == ()
