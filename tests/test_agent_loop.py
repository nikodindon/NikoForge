"""``nikoforge.agent`` : boucle de la tâche, approbation, rendu des résultats.

Ces tests traversent toute la pile pour de bon : ``Agent`` → ``LLM`` → SDK ``openai`` → HTTP
→ ``tests/fake_server.py``. Seul le modèle est simulé, ce qui permet de vérifier ce que le
modèle **reçoit réellement** (``fake_server.last_messages()``) et pas seulement ce que l'agent
croit lui envoyer.

Corrections couvertes : C2 (itération par tâche), C3 (rendu modèle distinct de l'affichage),
C6 (sorties bornées), C9 (approbation avant exécution), C16 (suppression de texte possible).
"""

from __future__ import annotations

import dataclasses
import io
import json

from conftest import config_for

from nikoforge.agent import (
    ALLOW,
    ASK,
    DENY,
    MODEL_OUTPUT_LIMIT,
    Agent,
    ApprovalPolicy,
    render_refusal,
    render_result_for_model,
    truncate_for_model,
)
from nikoforge.llm import LLM
from nikoforge.prompt import get_system_prompt
from nikoforge.protocol import ToolCall
from nikoforge.tools import ToolResult


def make_agent(fake_server, workdir, **kwargs) -> Agent:
    """Un agent complet, branché sur le faux serveur, muet dans la sortie de test."""
    options = {
        "policy": ApprovalPolicy(auto_approve=True),
        "echo": False,
        "stream": io.StringIO(),
    }
    options.update(kwargs)
    return Agent(config_for(fake_server.base_url, workdir=workdir), **options)


def tool_round(fake_server, *calls, reply_after: str = "Terminé."):
    """Programme : le serveur propose des appels d'outils, puis répond du texte."""
    fake_server.tool_calls = [{"name": name, "arguments": args} for name, args in calls]
    fake_server.replies = [reply_after]


# --------------------------------------------------------------------------- #
# Politique d'approbation (C9)
# --------------------------------------------------------------------------- #


def test_default_policy_frees_reads_and_asks_for_writes():
    policy = ApprovalPolicy()
    assert policy.decide("read_file") == ALLOW
    assert policy.decide("list_files") == ALLOW
    assert policy.decide("write_file") == ASK
    assert policy.decide("edit_file") == ASK
    assert policy.decide("bash") == ASK
    assert policy.decide("outil_inconnu") == ASK


def test_auto_approve_answers_yes_to_everything():
    assert ApprovalPolicy(auto_approve=True).decide("bash") == ALLOW


def test_allow_always_is_remembered_for_the_session():
    policy = ApprovalPolicy()
    policy.allow_always("bash")
    assert policy.decide("bash") == ALLOW
    assert policy.decide("write_file") == ASK


def test_a_specific_rule_wins():
    assert ApprovalPolicy(rules={"bash": DENY}).decide("bash") == DENY


# --------------------------------------------------------------------------- #
# Rendu destiné au modèle (C3) et bornage (C6)
# --------------------------------------------------------------------------- #


def test_bash_result_sent_to_the_model_names_every_field():
    """C3 inversé : plus de ``repr()`` Python, plus de « ✓ Succès / Données : »."""
    result = ToolResult(True, {"stdout": "total 8\n", "stderr": "", "exit_code": 0})
    rendered = render_result_for_model(ToolCall("bash", {"command": "ls"}), result)

    assert rendered.startswith("[outil bash — succès]")
    assert "code de sortie : 0" in rendered
    assert "sortie standard :" in rendered
    assert "total 8" in rendered
    assert "{" not in rendered and "'stdout'" not in rendered
    assert "✓" not in rendered
    assert "Données" not in rendered


def test_a_failing_command_reports_its_exit_code_and_stderr():
    result = ToolResult(False, {"stdout": "", "stderr": "boom\n", "exit_code": 3}, "boom\n")
    rendered = render_result_for_model(ToolCall("bash", {"command": "x"}), result)

    assert "— échec" in rendered
    assert "code de sortie : 3" in rendered
    assert "sortie d'erreur :" in rendered
    assert "boom" in rendered


def test_a_command_without_output_says_so_explicitly():
    result = ToolResult(True, {"stdout": "", "stderr": "", "exit_code": 0})
    assert "(aucune sortie)" in render_result_for_model(ToolCall("bash", {}), result)


def test_a_file_read_is_passed_through():
    result = ToolResult(True, "le contenu du fichier")
    rendered = render_result_for_model(ToolCall("read_file", {"path": "a"}), result)
    assert rendered == "[outil read_file — succès]\nle contenu du fichier"


def test_a_tool_failure_is_passed_through():
    result = ToolResult(False, None, "Fichier non trouvé: a")
    rendered = render_result_for_model(ToolCall("read_file", {"path": "a"}), result)
    assert "— échec" in rendered
    assert "Fichier non trouvé: a" in rendered


def test_truncation_keeps_head_and_tail():
    """C6 : la queue compte, c'est là qu'est la trace d'erreur d'un test qui échoue."""
    text = "D" * 5000 + "FIN" + "F" * 5000
    truncated = truncate_for_model(text, limit=1000)

    assert len(truncated) < len(text)
    assert truncated.startswith("D" * 100)
    assert truncated.endswith("F" * 100)
    assert "caractères omis" in truncated


def test_short_text_is_not_truncated():
    assert truncate_for_model("court", limit=1000) == "court"


def test_the_limit_is_generous_enough_for_normal_output():
    assert MODEL_OUTPUT_LIMIT >= 4000


def test_refusal_message_tells_the_model_what_to_do():
    rendered = render_refusal(ToolCall("bash", {"command": "rm -rf /"}), "refusé par l'utilisateur")
    assert "NON EXÉCUTÉ" in rendered
    assert "refusé par l'utilisateur" in rendered
    assert "autre approche" in rendered


# --------------------------------------------------------------------------- #
# Boucle nominale
# --------------------------------------------------------------------------- #


def test_a_task_without_tool_calls_ends_immediately(fake_server, workdir):
    fake_server.replies = ["Bonjour !"]
    agent = make_agent(fake_server, workdir)

    result = agent.run("dis bonjour")

    assert result.ok
    assert result.stop_reason == "done"
    assert result.iterations == 1
    assert result.tool_calls == 0
    assert result.text == "Bonjour !"
    assert fake_server.call_count == 1


def test_the_system_prompt_is_sent_first(fake_server, workdir):
    agent = make_agent(fake_server, workdir)
    agent.run("bonjour")

    messages = fake_server.last_messages()
    assert messages[0]["role"] == "system"
    assert "NikoForge" in messages[0]["content"]


def test_the_system_prompt_lists_the_tools_from_the_registry(fake_server, workdir):
    """C15a : le prompt est engendré depuis ``TOOL_SPECS``, donc plus de dérive possible."""
    prompt = get_system_prompt(workdir)
    for name in ("list_files", "read_file", "write_file", "edit_file", "bash"):
        assert name in prompt
    assert str(workdir) in prompt  # en v2, « {cwd} » restait littéral


def test_a_tool_call_is_executed_and_its_result_fed_back(fake_server, workdir):
    tool_round(fake_server, ("write_file", {"path": "a.txt", "content": "bonjour"}))
    agent = make_agent(fake_server, workdir)

    result = agent.run("écris a.txt")

    assert result.ok
    assert result.tool_calls == 1
    assert result.iterations == 2
    assert (workdir / "a.txt").read_text(encoding="utf-8") == "bonjour"
    # Le résultat est bien revenu au modèle, avec ses champs nommés.
    assert any("succès" in str(m.get("content", "")) for m in fake_server.last_messages())


def test_the_model_receives_readable_output_not_a_python_repr(fake_server, workdir):
    tool_round(fake_server, ("bash", {"command": "echo bonjour"}))
    agent = make_agent(fake_server, workdir)

    agent.run("lance echo")

    feedback = [m for m in fake_server.last_messages() if "[outil bash" in str(m.get("content", ""))]
    assert feedback, "le résultat d'outil doit être renvoyé au modèle"
    content = feedback[-1]["content"]
    assert "code de sortie : 0" in content
    assert "\\n" not in content, "des sauts de ligne échappés signaleraient une repr() Python"


def test_a_huge_command_output_is_bounded_before_reaching_the_model(fake_server, workdir):
    """C6 : en v2, un ``cat`` sur un gros fichier saturait le contexte d'un coup."""
    tool_round(fake_server, ("bash", {"command": "yes A | head -n 20000"}))
    agent = make_agent(fake_server, workdir)

    agent.run("produis beaucoup")

    feedback = [
        m["content"]
        for m in fake_server.last_messages()
        if "[outil bash" in str(m.get("content", ""))
    ]
    assert len(feedback[-1]) < 20_000
    assert "caractères omis" in feedback[-1]


def test_several_tool_calls_in_one_round_are_all_executed(fake_server, workdir):
    tool_round(
        fake_server,
        ("write_file", {"path": "a.txt", "content": "a"}),
        ("write_file", {"path": "b.txt", "content": "b"}),
    )
    agent = make_agent(fake_server, workdir)

    result = agent.run("écris deux fichiers")

    assert result.tool_calls == 2
    assert (workdir / "a.txt").is_file()
    assert (workdir / "b.txt").is_file()


def test_the_assistant_message_is_stored_without_the_tool_markup(fake_server, workdir):
    """Le balisage ne doit pas polluer l'historique : C1a le faisait à chaque tour."""
    fake_server.replies = [
        'Je liste.\n<tool_calls><tool name="list_files"><param name="path">.</param>'
        "</tool></tool_calls>"
    ]
    agent = make_agent(fake_server, workdir)
    agent.config = dataclasses.replace(
        agent.config, llm=dataclasses.replace(agent.config.llm, protocol="text")
    )
    agent.llm = LLM(agent.config)

    agent.run("liste")

    stored = [m["content"] for m in agent.context.messages if m["role"] == "assistant"]
    assert stored and stored[0] == "Je liste."
    assert "<tool_calls" not in stored[0]


# --------------------------------------------------------------------------- #
# Itération par tâche (C2)
# --------------------------------------------------------------------------- #


def test_the_iteration_budget_is_per_task(fake_server, workdir):
    """C2 inversé : en v2, ``max_iterations`` était un budget de **session**.

    Après 20 itérations cumulées, ``run()`` retournait une chaîne vide sans aucun message.
    """
    fake_server.replies = ["un", "deux", "trois", "quatre"]
    config = config_for(fake_server.base_url, workdir=workdir)
    config = dataclasses.replace(
        config, agent=dataclasses.replace(config.agent, max_iterations=1)
    )
    agent = Agent(config, policy=ApprovalPolicy(auto_approve=True), echo=False, stream=io.StringIO())

    first = agent.run("première tâche")
    second = agent.run("deuxième tâche")

    assert first.ok and first.iterations == 1
    assert second.ok and second.iterations == 1, "la seconde tâche doit avoir son propre budget"
    assert second.text == "deux"
    assert fake_server.call_count == 2


def test_a_model_that_loops_until_the_budget_stops_cleanly(fake_server, workdir):
    fake_server.tool_calls = [{"name": "list_files", "arguments": {"path": "."}}]
    fake_server.tool_call_rounds = 99  # le modèle ne s'arrête jamais
    config = config_for(fake_server.base_url, workdir=workdir)
    config = dataclasses.replace(
        config, agent=dataclasses.replace(config.agent, max_iterations=2)
    )
    agent = Agent(config, policy=ApprovalPolicy(auto_approve=True), echo=False, stream=io.StringIO())

    result = agent.run("boucle")

    assert result.stop_reason == "max_iterations"
    assert result.ok is False
    assert result.iterations == 2


def test_a_cancelled_task_stops_before_calling_the_model(fake_server, workdir):
    agent = make_agent(fake_server, workdir, should_stop=lambda: True)
    result = agent.run("tache")
    assert result.stop_reason == "cancelled"
    assert fake_server.call_count == 0


def test_a_cancellation_during_the_task_stops_the_loop(fake_server, workdir):
    tool_round(fake_server, ("list_files", {"path": "."}))
    calls = {"count": 0}

    def should_stop() -> bool:
        calls["count"] += 1
        return calls["count"] > 1  # on laisse passer la première itération

    agent = make_agent(fake_server, workdir, should_stop=should_stop)

    result = agent.run("tache")

    assert result.stop_reason == "cancelled"
    assert fake_server.call_count == 1


# --------------------------------------------------------------------------- #
# Validation des arguments (C16)
# --------------------------------------------------------------------------- #


def test_deleting_text_is_possible(fake_server, workdir):
    """C16 inversé : ``all([path, old, new])`` refusait une ``new_content`` vide."""
    (workdir / "a.txt").write_text("garder\nsupprimer\n", encoding="utf-8")
    tool_round(
        fake_server,
        ("edit_file", {"path": "a.txt", "old_content": "supprimer\n", "new_content": ""}),
    )
    agent = make_agent(fake_server, workdir)

    result = agent.run("supprime la ligne")

    assert result.tool_calls == 1
    assert (workdir / "a.txt").read_text(encoding="utf-8") == "garder\n"


def test_an_unknown_parameter_is_reported_to_the_model(fake_server, workdir):
    """C15a : le routeur n'accepte plus d'alias muets ; il explique."""
    tool_round(fake_server, ("read_file", {"raw": "a.txt"}))
    agent = make_agent(fake_server, workdir)

    result = agent.run("lis a.txt")

    assert result.tool_calls == 0
    # L'appel a été refusé mais la tâche se poursuit : le modèle reçoit l'explication.
    assert result.ok
    feedback = fake_server.last_messages()[-1]["content"]
    assert "NON EXÉCUTÉ" in feedback
    assert "raw" in feedback and "path" in feedback


def test_a_missing_parameter_is_reported_to_the_model(fake_server, workdir):
    tool_round(fake_server, ("write_file", {"content": "sans chemin"}))
    agent = make_agent(fake_server, workdir)

    agent.run("écris un fichier")

    assert "manquant" in fake_server.last_messages()[-1]["content"]


def test_an_unknown_tool_is_reported_to_the_model(fake_server, workdir):
    tool_round(fake_server, ("ftp_upload", {"host": "x"}))
    agent = make_agent(fake_server, workdir)

    agent.run("envoie")

    feedback = fake_server.last_messages()[-1]["content"]
    assert "NON EXÉCUTÉ" in feedback
    assert "ftp_upload" in feedback
    assert "read_file" in feedback  # la liste des outils disponibles est fournie


def test_an_empty_model_answer_is_reported(fake_server, workdir):
    fake_server.replies = [""]
    agent = make_agent(fake_server, workdir)

    result = agent.run("tache")

    assert result.stop_reason == "no_response"
    assert result.ok is False


# --------------------------------------------------------------------------- #
# Approbation pendant la boucle (C9)
# --------------------------------------------------------------------------- #


def test_a_refused_action_is_not_executed_and_the_model_is_told(fake_server, workdir):
    tool_round(fake_server, ("write_file", {"path": "refuse.txt", "content": "x"}))
    agent = make_agent(
        fake_server,
        workdir,
        policy=ApprovalPolicy(auto_approve=False),
        approver=lambda call: False,
    )

    result = agent.run("écris un fichier")

    assert result.denied == 1
    assert result.tool_calls == 0
    assert not (workdir / "refuse.txt").exists()
    assert "refusé" in fake_server.last_messages()[-1]["content"].lower()


def test_an_accepted_action_is_executed(fake_server, workdir):
    tool_round(fake_server, ("write_file", {"path": "ok.txt", "content": "x"}))
    agent = make_agent(
        fake_server,
        workdir,
        policy=ApprovalPolicy(auto_approve=False),
        approver=lambda call: True,
    )

    result = agent.run("écris un fichier")

    assert result.tool_calls == 1
    assert (workdir / "ok.txt").is_file()


def test_a_read_only_action_never_asks(fake_server, workdir):
    (workdir / "a.txt").write_text("contenu", encoding="utf-8")
    tool_round(fake_server, ("read_file", {"path": "a.txt"}))
    asked: list[str] = []

    def approver(call: ToolCall) -> bool:
        asked.append(call.name)
        return True

    agent = make_agent(
        fake_server, workdir, policy=ApprovalPolicy(auto_approve=False), approver=approver
    )
    agent.run("lis le fichier")

    assert asked == [], "la lecture ne doit pas demander confirmation"


def test_without_an_approver_an_asked_action_is_refused_with_a_clear_reason(fake_server, workdir):
    """Un mode non interactif ne doit pas bloquer indéfiniment sur une question."""
    tool_round(fake_server, ("bash", {"command": "echo x"}))
    agent = make_agent(
        fake_server, workdir, policy=ApprovalPolicy(auto_approve=False), approver=None
    )

    result = agent.run("lance une commande")

    assert result.denied == 1
    assert "confirmation" in fake_server.last_messages()[-1]["content"]


def test_a_denied_tool_is_refused_by_policy(fake_server, workdir):
    tool_round(fake_server, ("bash", {"command": "rm -rf /"}))
    agent = make_agent(
        fake_server, workdir, policy=ApprovalPolicy(rules={"bash": DENY})
    )

    result = agent.run("supprime tout")

    assert result.denied == 1
    assert "politique d'approbation" in fake_server.last_messages()[-1]["content"]


# --------------------------------------------------------------------------- #
# Erreurs du serveur
# --------------------------------------------------------------------------- #


def test_a_server_error_ends_the_task_with_a_named_cause(fake_server, workdir):
    fake_server.fail_with = (503, "service unavailable")
    agent = make_agent(fake_server, workdir)

    result = agent.run("tache")

    assert result.stop_reason == "error"
    assert result.ok is False
    assert "503" in result.error


def test_an_unreachable_server_is_reported_in_the_result(workdir):
    config = config_for("http://127.0.0.1:9/v1", workdir=workdir)
    agent = Agent(config, echo=False, stream=io.StringIO())

    result = agent.run("tache")

    assert result.stop_reason == "error"
    assert "injoignable" in result.error


# --------------------------------------------------------------------------- #
# Compaction, branchée sur le modèle
# --------------------------------------------------------------------------- #


def test_compaction_uses_the_model_and_keeps_the_task(fake_server, workdir):
    fake_server.replies = ["Compris."]
    config = config_for(fake_server.base_url, workdir=workdir)
    config = dataclasses.replace(
        config, context=dataclasses.replace(config.context, max_tokens=60, summary_tokens=40)
    )
    agent = Agent(config, policy=ApprovalPolicy(auto_approve=True), echo=False, stream=io.StringIO())
    agent.context.add_message("user", "TACHE: la consigne initiale")
    for index in range(10):
        agent.context.add_message("assistant", f"tour {index} " + "z" * 40)
    agent.context.record_usage(prompt_tokens=1000)  # force le dépassement du seuil

    result = agent.run("nouvelle consigne")

    assert result.ok
    # Une requête a servi à résumer, l'autre à la tâche.
    assert fake_server.call_count == 2
    assert agent.context.compaction_count == 1
    # C7 inversé : la tête épinglée survit à la compaction.
    assert agent.context.messages[0]["content"] == "TACHE: la consigne initiale"
    assert agent.context.summary
    # Le résumé arrive par le message système de la requête suivante (C8).
    assert "Résumé des échanges" in fake_server.last_messages()[0]["content"]


def test_compaction_asks_for_a_summary_without_tools(fake_server, workdir):
    fake_server.replies = ["Résumé."]
    config = config_for(fake_server.base_url, workdir=workdir)
    config = dataclasses.replace(
        config, context=dataclasses.replace(config.context, max_tokens=60, summary_tokens=40)
    )
    agent = Agent(config, policy=ApprovalPolicy(auto_approve=True), echo=False, stream=io.StringIO())
    for index in range(8):
        agent.context.add_message("assistant", f"tour {index} " + "z" * 40)

    agent.run("consigne")

    summary_request = fake_server.requests[0]
    assert "tools" not in summary_request
    assert "Résume les échanges" in summary_request["messages"][0]["content"]


# --------------------------------------------------------------------------- #
# Structure des messages (C18 : constaté en usage réel)
# --------------------------------------------------------------------------- #


def test_a_native_tool_call_is_stored_with_its_tool_calls_field(fake_server, workdir):
    """Sans ce champ, le gabarit du serveur ne relie pas l'appel à sa réponse.

    Constaté sur un serveur réel : le message assistant partait vide, les résultats
    arrivaient en messages « user », et le modèle rappelait l'outil indéfiniment jusqu'à
    épuiser son budget.
    """
    tool_round(fake_server, ("write_file", {"path": "a.txt", "content": "x"}))
    agent = make_agent(fake_server, workdir)

    agent.run("écris a.txt")

    assistant = [m for m in agent.context.messages if m["role"] == "assistant"][0]
    assert assistant["tool_calls"][0]["function"]["name"] == "write_file"
    assert assistant["tool_calls"][0]["id"] == "call_0"
    assert assistant["tool_calls"][0]["type"] == "function"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {
        "path": "a.txt",
        "content": "x",
    }


def test_a_native_tool_result_is_a_tool_message_carrying_the_call_id(fake_server, workdir):
    tool_round(fake_server, ("list_files", {"path": "."}))
    agent = make_agent(fake_server, workdir)

    agent.run("liste")

    results = [m for m in agent.context.messages if m["role"] == "tool"]
    assert results and results[0]["tool_call_id"] == "call_0"
    assert results[0]["name"] == "list_files"
    assert not [m for m in agent.context.messages if m["role"] == "user"][1:], (
        "les résultats natifs ne doivent pas partir en messages utilisateur"
    )


def test_the_server_receives_the_standard_tool_conversation(fake_server, workdir):
    tool_round(fake_server, ("read_file", {"path": "a.txt"}), reply_after="Fini.")
    (workdir / "a.txt").write_text("contenu", encoding="utf-8")
    agent = make_agent(fake_server, workdir)

    agent.run("lis a.txt")

    messages = fake_server.last_messages()
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "tool"]
    assert messages[2]["tool_calls"][0]["function"]["name"] == "read_file"
    assert messages[3]["tool_call_id"] == "call_0"


def test_text_protocol_results_stay_user_messages(fake_server, workdir):
    """Le protocole textuel n'a pas d'identifiant d'appel : on garde la forme ReAct."""
    fake_server.replies = [
        'Je lis.\n<tool_calls><tool name="read_file"><param name="path">a.txt</param>'
        "</tool></tool_calls>",
        "Fini.",
    ]
    (workdir / "a.txt").write_text("contenu", encoding="utf-8")
    agent = make_agent(fake_server, workdir)
    agent.config = dataclasses.replace(
        agent.config, llm=dataclasses.replace(agent.config.llm, protocol="text")
    )
    agent.llm = LLM(agent.config)

    result = agent.run("lis a.txt")

    assert result.ok
    roles = [m["role"] for m in agent.context.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert agent.context.messages[2]["content"].startswith("[outil read_file")
    assert all("tool_calls" not in m for m in agent.context.messages)


# --------------------------------------------------------------------------- #
# Compaction : ne jamais couper un échange d'outils
# --------------------------------------------------------------------------- #


def test_compaction_never_leaves_an_orphan_tool_message():
    """Un message ``tool`` sans son ``tool_calls`` fait échouer le gabarit du serveur."""
    from nikoforge.context import ContextManager

    ctx = ContextManager(max_tokens=1000, pinned=1, keep_recent=3)
    ctx.add_message("user", "TACHE")
    ctx.add_message("assistant", "etape 1")
    ctx.add_message("user", "resultat 1")
    ctx.add_message("assistant", "", tool_calls=[{"id": "c1"}])
    for index in range(4):
        ctx.add_message("tool", f"resultat {index}", tool_call_id=f"c{index}")
    ctx.add_message("assistant", "bavardage")

    assert ctx.compact(lambda _: "résumé") is True

    assert ctx.messages[0]["content"] == "TACHE"
    # La coupe a reculé pour englober le message assistant porteur des appels : le premier
    # message conservé après la tête est bien celui qui porte `tool_calls`.
    assert ctx.messages[1]["role"] == "assistant"
    assert "tool_calls" in ctx.messages[1]
    assert not [m for m in ctx.messages if m["role"] == "tool" and "tool_call_id" not in m]


# --------------------------------------------------------------------------- #
# Statistiques
# --------------------------------------------------------------------------- #


def test_get_stats_reports_the_context_measurement(fake_server, workdir):
    fake_server.replies = ["ok"]
    agent = make_agent(fake_server, workdir)
    agent.run("tache")

    stats = agent.get_stats()

    assert stats["iteration"] == 1
    assert stats["context_stats"]["estimated_tokens"] == 11  # l'usage du faux serveur
    assert stats["context_stats"]["total_messages"] == 2


def test_saving_and_loading_the_context_round_trips(fake_server, workdir, tmp_path):
    fake_server.replies = ["ok"]
    agent = make_agent(fake_server, workdir)
    agent.run("bonjour")
    target = tmp_path / "ctx.json"

    agent.save_context(str(target))

    other = make_agent(fake_server, workdir)
    other.load_context(str(target))
    assert other.context.messages == agent.context.messages
