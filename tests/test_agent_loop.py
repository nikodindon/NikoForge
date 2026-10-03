"""Boucle de l'agent (``core.agent.Agent``) et routage des outils.

Le client du modèle est remplacé par un doublure scriptée : aucun test de ce module ne
touche le réseau. Cela permet d'exercer la boucle, l'extraction des outils et l'injection
des résultats sans llama-server.

Le bug C2 (``iteration`` jamais remise à zéro) est testé ici : c'est le défaut le plus
vicieux du lot, parce qu'il ne produit ni erreur ni message.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from nikoforge.agent import Agent


# --------------------------------------------------------------------------- #
# Doublure de client OpenAI
# --------------------------------------------------------------------------- #


class _Delta:
    def __init__(self, content: str):
        self.content = content
        self.reasoning_content = None


class _Chunk:
    def __init__(self, content: str):
        self.choices = [types.SimpleNamespace(delta=_Delta(content))]


class _ScriptedCompletions:
    """Rejoue les réponses fournies. Une fois la liste épuisée, rejoue la dernière.

    Ce dernier point est ce qui permet de simuler un modèle qui boucle sur un appel d'outil
    et d'observer l'épuisement du budget d'itérations.
    """

    def __init__(self, responses: list[list[_Chunk]]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return iter(self.responses[index])


class FakeClient:
    def __init__(self, responses: list[list[_Chunk]]):
        self.chat = types.SimpleNamespace(completions=_ScriptedCompletions(responses))

    @property
    def calls(self) -> list[dict]:
        return self.chat.completions.calls


def chunk(text: str) -> _Chunk:
    return _Chunk(text)


def tool_calls_xml(name: str, **params: str) -> str:
    inner = "".join(
        f'<param name="{key}">{value}</param>\n' for key, value in params.items()
    )
    return f'<tool_calls>\n<tool name="{name}">\n{inner}</tool>\n</tool_calls>'


@pytest.fixture()
def sandbox(workdir: Path) -> Path:
    """Répertoire de travail de l'agent.

    Il est déjà isolé : la fixture ``config`` de ``conftest`` y place ``Config.workdir``,
    et l'``Agent`` construit son ``Tools`` avec ce répertoire.
    """
    return workdir


@pytest.fixture()
def sandboxed_agent(agent: Agent) -> Agent:
    """Un agent confiné dans ``tmp_path`` : la boucle n'écrit jamais dans le dépôt."""
    return agent


# --------------------------------------------------------------------------- #
# Boucle nominale
# --------------------------------------------------------------------------- #


def test_run_terminates_when_the_model_calls_no_tool(agent, capsys):
    agent.client = FakeClient([[chunk("Bonjour.")]])

    result = agent.run("dis bonjour")

    assert result == "Bonjour."
    assert agent.iteration == 1
    assert [m["role"] for m in agent.context.messages] == ["user", "assistant"]
    assert agent.context.messages[-1]["content"] == "Bonjour."


def test_run_executes_a_tool_then_stops(sandboxed_agent, sandbox):
    agent = sandboxed_agent
    (sandbox / "a.txt").write_text("x", encoding="utf-8")
    agent.client = FakeClient(
        [
            [chunk(tool_calls_xml("list_files", path="."))],
            [chunk("Termine.")],
        ]
    )

    result = agent.run("liste les fichiers")

    assert result == "Termine."
    assert agent.iteration == 2
    assert [m["role"] for m in agent.context.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_tool_result_is_injected_as_a_user_message(sandboxed_agent, sandbox):
    """La v2 n'utilise ni le rôle ``tool`` ni un balisage dédié : le résultat part en
    message **utilisateur**, préfixé de ``[outil: nom]``.

    Le modèle voit donc alterner « assistant qui appelle un outil » puis « utilisateur qui
    renvoie un résultat ». C'est le patron ReAct, mais avec un rôle qui n'est pas celui du
    protocole OpenAI — à trancher en phase 3.
    """
    agent = sandboxed_agent
    (sandbox / "a.txt").write_text("x", encoding="utf-8")
    agent.client = FakeClient(
        [
            [chunk(tool_calls_xml("list_files", path="."))],
            [chunk("Fini.")],
        ]
    )

    agent.run("liste")

    injected = agent.context.messages[2]
    assert injected["role"] == "user"
    assert injected["content"].startswith("[outil: list_files]")


@pytest.mark.known_issue
def test_the_model_receives_the_human_rendering_of_the_tool_result(sandboxed_agent):
    """Bug C3 — au niveau de la boucle, le message injecté est celui destiné à l'affichage.

    ``stdout``, ``stderr`` et ``exit_code`` arrivent donc au modèle sous forme de ``repr()``
    Python, avec les sauts de ligne échappés.
    """
    agent = sandboxed_agent
    agent.client = FakeClient(
        [
            [chunk(tool_calls_xml("bash", command="echo hi"))],
            [chunk("Fini.")],
        ]
    )

    agent.run("lance echo")

    injected = agent.context.messages[2]["content"]
    assert "✓ Succès" in injected, "BUG C3 : marqueur d'affichage humain envoye au modele"
    assert "Données: {'stdout':" in injected
    assert "\\n" in injected, "BUG C3 : le modele recoit des sauts de ligne echappes"


def test_run_reports_an_empty_model_response(agent, capsys):
    """Un stream vide fait sortir de la boucle avec un message explicite, sans exception."""
    agent.client = FakeClient([[]])

    result = agent.run("tache")

    assert result == ""
    assert "Pas de réponse du modèle" in capsys.readouterr().out


def test_run_swallows_connection_errors(agent, capsys):
    """Bug B2 — une erreur de connexion est attrapée et transformée en « Pas de réponse ».

    L'utilisateur n'apprend pas que le serveur est éteint, ni quel port il devrait écouter.
    """
    class Boom:
        def create(self, **kwargs):
            raise ConnectionError("Connection refused")

    agent.client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=Boom())
    )

    result = agent.run("tache")

    out = capsys.readouterr().out
    assert result == ""
    assert "Erreur modèle" in out
    assert "serveur" not in out.lower(), "BUG B2 : aucun diagnostic actionnable"


def test_the_prompt_is_sent_as_a_leading_system_message(agent):
    agent.client = FakeClient([[chunk("ok")]])

    agent.run("tache")

    messages = agent.client.calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert "NikoForge" in messages[0]["content"]


def test_the_stream_is_requested(agent):
    agent.client = FakeClient([[chunk("ok")]])

    agent.run("tache")

    assert agent.client.calls[0]["stream"] is True


# --------------------------------------------------------------------------- #
# Bug C2 : budget d'itérations de session
# --------------------------------------------------------------------------- #


@pytest.mark.known_issue
def test_iteration_budget_is_consumed_across_tasks(agent, capsys):
    """Bug C2 — ``iteration`` n'est jamais remis à zéro entre deux tâches.

    ``max_iterations`` est donc un budget de **session**, pas de tâche. Une fois épuisé,
    ``run()`` renvoie une chaîne vide : pas d'exception, pas de message, aucune trace.
    En mode interactif, la énième consigne de l'utilisateur ne fait plus rien.

    Comportement attendu en phase 3 : le compteur est local à la tâche.
    """
    agent.iteration = agent.max_iterations  # 20 itérations deja consommees
    agent.client = FakeClient([[chunk("je ne devrais pas etre appele")]])

    result = agent.run("une nouvelle tache totalement differente")

    assert result == "", "BUG C2 : la tache devrait s'executer"
    assert agent.client.calls == [], "BUG C2 : aucun appel au modele n'a ete fait"
    assert [m["role"] for m in agent.context.messages] == ["user"]
    assert "Itération" not in capsys.readouterr().out


def test_the_loop_stops_at_max_iterations(agent, capsys):
    """Le garde-fou fonctionne : un modèle qui boucle est arrêté. Reste que le budget est
    global (voir le test précédent)."""
    agent.client = FakeClient([[chunk(tool_calls_xml("list_files", path="."))]])

    agent.run("tache qui boucle")

    assert agent.iteration == agent.max_iterations
    assert f"Itération {agent.max_iterations}/{agent.max_iterations}" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# _execute_tool : routage et validation des paramètres
# --------------------------------------------------------------------------- #


def test_execute_tool_read_file(sandboxed_agent, sandbox):
    (sandbox / "a.txt").write_text("contenu", encoding="utf-8")
    result = sandboxed_agent._execute_tool({"name": "read_file", "params": {"path": "a.txt"}})
    assert result.success is True
    assert result.data == "contenu"


def test_execute_tool_read_file_requires_path(sandboxed_agent):
    result = sandboxed_agent._execute_tool({"name": "read_file", "params": {}})
    assert result.success is False
    assert result.error == "Paramètre 'path' manquant"


def test_execute_tool_write_file_requires_path(sandboxed_agent):
    result = sandboxed_agent._execute_tool({"name": "write_file", "params": {"content": "x"}})
    assert result.success is False
    assert result.error == "Paramètre 'path' manquant"


def test_execute_tool_write_file_creates_the_file(sandboxed_agent, sandbox):
    result = sandboxed_agent._execute_tool(
        {"name": "write_file", "params": {"path": "b.txt", "content": "hello"}}
    )
    assert result.success is True
    assert (sandbox / "b.txt").read_text(encoding="utf-8") == "hello"


def test_execute_tool_edit_file_requires_both_contents(sandboxed_agent):
    result = sandboxed_agent._execute_tool(
        {"name": "edit_file", "params": {"path": "a.txt"}}
    )
    assert result.success is False
    assert result.error == "Paramètres manquants pour edit_file"


@pytest.mark.known_issue
def test_execute_tool_cannot_delete_text(sandboxed_agent, sandbox):
    """Le contrôle ``all([path, old, new_content])`` rejette une chaîne vide.

    Conséquence : demander à l'agent de **supprimer** une portion de fichier est impossible
    au niveau de l'Agent (la couche ``Tools``, elle, l'accepte). Défaut non répertorié dans
    l'audit initial ; à traiter en phase 3 avec la refonte du routage.
    """
    (sandbox / "a.txt").write_text("garder\nsupprimer\n", encoding="utf-8")

    result = sandboxed_agent._execute_tool(
        {"name": "edit_file", "params": {"path": "a.txt", "old_content": "supprimer\n", "new_content": ""}}
    )

    assert result.success is False, "limitation : impossible de supprimer du texte"
    assert result.error == "Paramètres manquants pour edit_file"


def test_execute_tool_bash_requires_command(sandboxed_agent):
    result = sandboxed_agent._execute_tool({"name": "bash", "params": {}})
    assert result.success is False
    assert result.error == "Paramètre 'command' manquant"


def test_execute_tool_bash_converts_a_string_timeout(sandboxed_agent):
    result = sandboxed_agent._execute_tool(
        {"name": "bash", "params": {"command": "true", "timeout": "5"}}
    )
    assert result.success is True


def test_execute_tool_bash_falls_back_on_an_invalid_timeout(sandboxed_agent):
    """Un timeout non convertible retombe sur ``agent.tool_timeout`` au lieu de planter."""
    result = sandboxed_agent._execute_tool(
        {"name": "bash", "params": {"command": "true", "timeout": "beaucoup"}}
    )
    assert result.success is True


def test_execute_tool_list_files_defaults_to_current_directory(sandboxed_agent, sandbox):
    (sandbox / "a.txt").write_text("x", encoding="utf-8")
    result = sandboxed_agent._execute_tool({"name": "list_files", "params": {}})
    assert result.success is True
    assert [e["name"] for e in result.data] == ["a.txt"]


def test_execute_tool_rejects_an_unknown_tool(sandboxed_agent):
    result = sandboxed_agent._execute_tool({"name": "ftp_upload", "params": {}})
    assert result.success is False
    assert result.error == "Outil inconnu: ftp_upload"


@pytest.mark.known_issue
def test_execute_tool_accepts_undocumented_parameter_aliases(sandboxed_agent, sandbox):
    """Bug C15a — le routeur accepte ``raw`` comme alias de ``path``, ``content`` et
    ``command``, alors que le system prompt ne mentionne que les noms canoniques.

    Le prompt envoyé au modèle et le routeur qui exécute ne partagent aucune source de
    vérité : c'est exactement la dérive que la phase 4 supprime en générant le prompt
    depuis un registre d'outils.
    """
    (sandbox / "a.txt").write_text("contenu", encoding="utf-8")

    result = sandboxed_agent._execute_tool({"name": "read_file", "params": {"raw": "a.txt"}})

    assert result.success is True, "le routeur accepte un alias absent du prompt"
    assert result.data == "contenu"


def test_execute_tool_reports_an_unexpected_error_as_a_tool_result(sandboxed_agent):
    """Toute exception d'outil est convertie en résultat d'échec, jamais propagée."""
    sandboxed_agent.tools = types.SimpleNamespace(read_file=lambda path: 1 / 0)
    result = sandboxed_agent._execute_tool({"name": "read_file", "params": {"path": "a"}})
    assert result.success is False
    assert result.error.startswith("Erreur exécution outil:")


# --------------------------------------------------------------------------- #
# Statistiques
# --------------------------------------------------------------------------- #


def test_get_stats_shape(agent):
    agent.client = FakeClient([[chunk("ok")]])
    agent.run("tache")

    stats = agent.get_stats()

    assert stats["iteration"] == 1
    assert set(stats["context_stats"]) == {
        "total_messages",
        "compaction_count",
        "estimated_tokens",
        "max_tokens",
        "has_summary",
    }


def test_get_stats_reports_the_estimated_token_count(agent):
    agent.client = FakeClient([[chunk("A" * 400)]])
    agent.run("tache")

    stats = agent.get_stats()

    # 400 caracteres assistant + 5 pour "tache" -> 405 // 4
    assert stats["context_stats"]["estimated_tokens"] == 101


def test_save_context_writes_a_readable_json_file(agent, tmp_path):
    agent.client = FakeClient([[chunk("ok")]])
    agent.run("tache")
    target = tmp_path / "ctx.json"

    agent.save_context(str(target))

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["messages"][0] == {
        "role": "user",
        "content": "tache",
        "timestamp": data["messages"][0]["timestamp"],
    }
