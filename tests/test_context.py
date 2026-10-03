"""``nikoforge.context`` : historique, mesure réelle du contexte, compaction par le modèle.

Trois corrections vérifiées ici (``docs/REFONTE.md``) :

* **C7** — la compaction délègue le résumé à un appelant (l'agent, qui a accès au modèle) et
  **épingle** les premiers messages : la tâche initiale survit.
* **C7b** — la taille du contexte vient de l'``usage`` du serveur, pas de ``len // 4``.
* **C8** — le résumé est replié dans le message ``system`` initial, il n'est plus un second
  message ``system`` au milieu de l'historique.
"""

from __future__ import annotations

import json

import pytest

from nikoforge.context import ContextManager


@pytest.fixture()
def ctx():
    return ContextManager(max_tokens=1000, compaction_threshold=0.8, pinned=1, keep_recent=2)


def feed(ctx: ContextManager, count: int, size: int = 20) -> None:
    """Remplit l'historique : une tâche épinglée puis des allers-retours."""
    ctx.add_message("user", "TACHE: refactorise le module")
    for index in range(count):
        ctx.add_message("assistant", f"etape {index} " + "x" * size)
        ctx.add_message("user", f"resultat {index} " + "y" * size)


# --------------------------------------------------------------------------- #
# Historique et message système (C8)
# --------------------------------------------------------------------------- #


def test_add_message_stores_role_content_and_timestamp(ctx):
    message = ctx.add_message("user", "bonjour")
    assert message["role"] == "user"
    assert message["content"] == "bonjour"
    assert message["timestamp"]
    assert ctx.messages == [message]


def test_get_messages_returns_the_raw_history_only(ctx):
    """C8 inversé : plus aucun message ``system`` injecté au milieu de l'historique."""
    ctx.add_message("user", "a")
    ctx.summary = "un résumé"
    ctx.compaction_count = 1

    assert ctx.get_messages() == ctx.messages
    assert all(message["role"] != "system" for message in ctx.get_messages())


def test_build_messages_starts_with_the_system_prompt(ctx):
    ctx.add_message("user", "a")
    built = ctx.build_messages("SYSTEME")
    assert built[0] == {"role": "system", "content": "SYSTEME"}
    assert built[1]["role"] == "user"
    assert built[1]["content"] == "a"


def test_build_messages_folds_the_summary_into_the_system_prompt(ctx):
    """C8 : le résumé complète le system prompt au lieu d'être un second message system."""
    ctx.add_message("user", "suite")
    ctx.summary = "ce qui s'est passé avant"

    built = ctx.build_messages("SYSTEME")

    assert len([m for m in built if m["role"] == "system"]) == 1
    assert built[0]["content"].startswith("SYSTEME")
    assert "ce qui s'est passé avant" in built[0]["content"]


def test_build_messages_omits_the_summary_when_there_is_none(ctx):
    ctx.add_message("user", "a")
    assert ctx.build_messages("SYSTEME")[0]["content"] == "SYSTEME"


def test_build_messages_strips_internal_fields(ctx):
    """Les messages envoyés au serveur ne contiennent que ``role`` et ``content``."""
    ctx.add_message("user", "a")
    assert set(ctx.build_messages("S")[1]) == {"role", "content"}


# --------------------------------------------------------------------------- #
# Mesure : le serveur fait foi (C7b)
# --------------------------------------------------------------------------- #


def test_estimate_tokens_is_a_documented_approximation(ctx):
    assert ctx.estimate_tokens("abcdefgh") == 2
    assert ctx.estimate_tokens("A" * 400) == 100
    assert ctx.estimate_tokens("你好世界") == 1  # 4 idéogrammes ≈ 4 tokens, pas 1


def test_context_size_uses_the_estimate_before_any_measurement(ctx):
    ctx.add_message("user", "A" * 400)
    assert ctx.context_size() == 100


def test_recorded_usage_replaces_the_estimate(ctx):
    """C7b : la mesure du serveur prime sur l'estimation."""
    ctx.add_message("user", "A" * 400)  # l'estimation dirait 100
    ctx.record_usage(prompt_tokens=777, completion_tokens=12)

    assert ctx.context_size() == 777
    assert ctx.last_completion_tokens == 12


def test_messages_added_after_the_measurement_are_estimated(ctx):
    ctx.add_message("user", "A" * 400)
    ctx.record_usage(prompt_tokens=777)
    ctx.add_message("assistant", "B" * 80)  # 20 tokens ajoutés depuis la mesure

    assert ctx.context_size() == 797


def test_compaction_invalidates_the_measurement(ctx):
    feed(ctx, 4)
    ctx.record_usage(prompt_tokens=900)
    ctx.compact(lambda _: "résumé")

    assert ctx.last_prompt_tokens is None
    assert ctx.context_size() < 900


# --------------------------------------------------------------------------- #
# Déclenchement
# --------------------------------------------------------------------------- #


def test_needs_compaction_is_false_when_small(ctx):
    ctx.add_message("user", "court")
    assert ctx.needs_compaction() is False


def test_needs_compaction_uses_the_real_size(ctx):
    """max_tokens=1000, seuil 0.8 → 800 tokens."""
    ctx.add_message("user", "court")
    ctx.record_usage(prompt_tokens=799)
    assert ctx.needs_compaction() is False
    ctx.record_usage(prompt_tokens=800)
    assert ctx.needs_compaction() is True


def test_compactable_counts_the_middle_only(ctx):
    feed(ctx, 4)  # 1 épinglé + 8 messages
    assert len(ctx.messages) == 9
    assert ctx.compactable() == 9 - 1 - 2  # hors tête épinglée et queue gardée


def test_nothing_to_compact_below_the_threshold(ctx):
    ctx.add_message("user", "tache")
    ctx.add_message("assistant", "réponse")
    assert ctx.compactable() == 0
    assert ctx.compact(lambda _: "résumé") is False
    assert ctx.compaction_count == 0


# --------------------------------------------------------------------------- #
# Compaction (C7)
# --------------------------------------------------------------------------- #


def test_compact_keeps_the_pinned_task_and_the_recent_messages(ctx):
    """C7 inversé : en v2, la tâche initiale disparaissait du contexte actif."""
    feed(ctx, 4)
    seen: list[str] = []

    def summarize(transcript: str) -> str:
        seen.append(transcript)
        return "RÉSUMÉ"

    assert ctx.compact(summarize) is True

    assert ctx.messages[0]["content"].startswith("TACHE:")
    assert len(ctx.messages) == 1 + ctx.keep_recent
    assert ctx.summary == "RÉSUMÉ"
    assert ctx.compaction_count == 1
    # Le transcript soumis au résumé contient bien ce qui a été retiré, et pas la tâche.
    assert seen and "TACHE:" not in seen[0]
    assert "etape 0" in seen[0]


def test_the_transcript_labels_each_message_with_its_role(ctx):
    feed(ctx, 4)
    seen: list[str] = []
    ctx.compact(lambda transcript: seen.append(transcript) or "r")
    assert "[assistant] :" in seen[0]
    assert "[user] :" in seen[0]


def test_compact_refuses_an_empty_summary_without_touching_the_history(ctx):
    """Mieux vaut un contexte trop grand qu'un historique amputé sans résumé."""
    feed(ctx, 4)
    before = list(ctx.messages)

    assert ctx.compact(lambda _: "   ") is False

    assert ctx.messages == before
    assert ctx.compaction_count == 0
    assert ctx.summary == ""


def test_a_failing_summarizer_leaves_the_history_intact(ctx):
    feed(ctx, 4)
    before = list(ctx.messages)

    def boom(_: str) -> str:
        raise RuntimeError("modèle indisponible")

    with pytest.raises(RuntimeError):
        ctx.compact(boom)

    assert ctx.messages == before
    assert ctx.compaction_count == 0


def test_fallback_summary_does_not_cut_in_the_middle_of_a_word(ctx):
    """La v2 tronquait par ``summary[:len-100]``, couper un mot au hasard."""
    ctx.summary_tokens = 5  # 20 caractères de résumé autorisés
    feed(ctx, 4)

    assert ctx.compact() is True

    assert "tronqué faute de résumé" in ctx.summary
    assert not ctx.summary.endswith("…")


def test_several_compactions_accumulate(ctx):
    feed(ctx, 4)
    ctx.compact(lambda _: "premier")
    feed(ctx, 4)
    ctx.compact(lambda _: "second")

    assert ctx.compaction_count == 2
    assert ctx.summary == "second"
    assert ctx.messages[0]["content"].startswith("TACHE:")


# --------------------------------------------------------------------------- #
# Statistiques, réinitialisation, persistance
# --------------------------------------------------------------------------- #


def test_get_stats_reports_the_real_size(ctx):
    ctx.add_message("user", "A" * 40)
    ctx.record_usage(prompt_tokens=123)
    stats = ctx.get_stats()
    assert stats["total_messages"] == 1
    assert stats["estimated_tokens"] == 123  # la mesure, pas l'estimation
    assert stats["max_tokens"] == 1000
    assert stats["has_summary"] is False


def test_reset_clears_everything(ctx):
    feed(ctx, 4)
    ctx.record_usage(prompt_tokens=500)
    ctx.compact(lambda _: "résumé")

    ctx.reset()

    assert ctx.messages == []
    assert ctx.summary == ""
    assert ctx.compaction_count == 0
    assert ctx.last_prompt_tokens is None
    assert ctx.context_size() == 0


def test_save_and_load_roundtrip(ctx, tmp_path):
    ctx.add_message("user", "bonjour")
    ctx.summary = "résumé"
    ctx.compaction_count = 2
    target = tmp_path / "ctx.json"

    ctx.save_to_file(str(target))

    other = ContextManager()
    other.load_from_file(str(target))

    assert other.messages == ctx.messages
    assert other.summary == "résumé"
    assert other.compaction_count == 2
    assert other.last_prompt_tokens is None  # une mesure ne se transporte pas


def test_saved_file_is_readable_json(ctx, tmp_path):
    ctx.add_message("user", "hi")
    target = tmp_path / "ctx.json"
    ctx.save_to_file(str(target))
    data = json.loads(target.read_text(encoding="utf-8"))
    assert set(data) == {"messages", "summary", "compaction_count", "stats"}


def test_load_tolerates_a_partial_file(ctx, tmp_path):
    target = tmp_path / "ctx.json"
    target.write_text("{}", encoding="utf-8")
    ctx.load_from_file(str(target))
    assert ctx.messages == []
    assert ctx.summary == ""
