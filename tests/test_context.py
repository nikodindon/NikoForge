"""``core.context.ContextManager`` : historique, estimation, compaction, persistance.

La compaction est le point faible de la v2 (bug C7) : malgré ce qu'annonce le README, ce
n'est pas un résumé généré par le modèle mais une concaténation de messages bruts tronquée
par découpage de chaîne, qui ne conserve que les 2 derniers messages.
"""

from __future__ import annotations

import json

import pytest

from nikoforge.context import ContextManager


@pytest.fixture()
def ctx():
    return ContextManager(max_tokens=100, compaction_threshold=0.8)


# --------------------------------------------------------------------------- #
# Historique
# --------------------------------------------------------------------------- #


def test_add_message_stores_role_content_and_timestamp(ctx):
    ctx.add_message("user", "bonjour")
    assert len(ctx.messages) == 1
    message = ctx.messages[0]
    assert message["role"] == "user"
    assert message["content"] == "bonjour"
    assert "timestamp" in message


def test_get_messages_returns_the_history_unchanged_before_compaction(ctx):
    ctx.add_message("user", "a")
    ctx.add_message("assistant", "b")
    assert ctx.get_messages() == [
        {"role": "user", "content": "a", "timestamp": ctx.messages[0]["timestamp"]},
        {"role": "assistant", "content": "b", "timestamp": ctx.messages[1]["timestamp"]},
    ]


def test_get_messages_returns_the_live_list(ctx):
    """Pas de copie : le retour de ``get_messages()`` est ``self.messages`` lui-même.

    Une mutation par l'appelant se répercute donc sur l'état du gestionnaire de contexte.
    À surveiller en phase 3.
    """
    ctx.add_message("user", "a")
    assert ctx.get_messages() is ctx.messages


# --------------------------------------------------------------------------- #
# Estimation de taille
# --------------------------------------------------------------------------- #


def test_estimate_tokens_is_length_divided_by_four(ctx):
    assert ctx.estimate_tokens("abcdefgh") == 2
    assert ctx.estimate_tokens("") == 0
    assert ctx.estimate_tokens("A" * 400) == 100


@pytest.mark.known_issue
def test_estimate_tokens_is_wrong_for_non_ascii_and_code(ctx):
    """Bug C7b — ``len // 4`` suppose 4 caractères par token.

    Faux pour du code (~3 caractères/token, sous-estimation de 25 %) et franchement faux
    hors alphabet latin : 4 idéogrammes font environ 4 tokens, pas 1. Une session en
    chinois croit avoir 4 fois moins de contexte qu'elle n'en consomme — donc ne compacte
    pas, et dépasse la fenêtre du serveur.

    Le serveur renvoie pourtant un ``usage`` exact en fin de stream, qui n'est jamais lu.
    """
    assert ctx.estimate_tokens("你好世界") == 1, "BUG C7b : 4 idéogrammes ≈ 4 tokens, pas 1"


def test_estimate_context_size_sums_every_message(ctx):
    ctx.add_message("user", "A" * 40)  # 10 tokens
    ctx.add_message("assistant", "B" * 80)  # 20 tokens
    assert ctx.estimate_context_size() == 30


def test_estimate_context_size_includes_the_summary(ctx):
    ctx.add_message("user", "A" * 40)
    ctx.summary = "B" * 80
    assert ctx.estimate_context_size() == 30


# --------------------------------------------------------------------------- #
# Déclenchement de la compaction
# --------------------------------------------------------------------------- #


def test_needs_compaction_is_false_when_small(ctx):
    ctx.add_message("user", "court")
    assert ctx.needs_compaction() is False


def test_needs_compaction_triggers_at_the_threshold(ctx):
    # max_tokens=100, seuil 0.8 -> 80 tokens -> 320 caractères
    ctx.add_message("user", "A" * 320)
    assert ctx.needs_compaction() is True


def test_needs_compaction_uses_a_ratio(ctx):
    """Un seuil mal configuré (en tokens plutôt qu'en ratio) rendrait le test toujours vrai."""
    strict = ContextManager(max_tokens=1000, compaction_threshold=0.01)
    strict.add_message("user", "A" * 40)  # 10 tokens >= 10
    assert strict.needs_compaction() is True


# --------------------------------------------------------------------------- #
# Compaction
# --------------------------------------------------------------------------- #


def test_compact_does_nothing_below_four_messages(ctx):
    ctx.add_message("user", "a")
    ctx.add_message("assistant", "b")
    ctx.add_message("user", "c")

    ctx.compact(summary_tokens=50)

    assert len(ctx.messages) == 3
    assert ctx.summary == ""
    assert ctx.compaction_count == 0


def test_compact_keeps_only_the_two_last_messages(ctx):
    for i in range(6):
        ctx.add_message("user", f"message {i}")
    ctx.add_message("assistant", "dernier assistant")
    ctx.add_message("user", "dernier user")

    ctx.compact(summary_tokens=50)

    assert len(ctx.messages) == 2
    assert ctx.messages[-1]["content"] == "dernier user"
    assert ctx.compaction_count == 1


@pytest.mark.known_issue
def test_compact_loses_the_original_task(ctx):
    """Bug C7 — la tâche initiale n'est plus dans le contexte actif.

    ``compact()`` conserve ``messages[-2:]`` sans distinguer le premier message utilisateur.
    Après compaction, l'agent a oublié ce qu'on lui a demandé ; il ne lui reste qu'un
    « résumé » qui est une concaténation tronquée.

    Comportement attendu en phase 3 : conserver system + tâche initiale + K derniers échanges.
    """
    ctx.add_message("user", "TACHE: refactorise core/tools.py et ajoute des tests")
    for i in range(6):
        ctx.add_message("assistant", f"etape {i} " + "blabla " * 30)
        ctx.add_message("user", f"resultat {i} " + "sortie " * 30)

    ctx.compact(summary_tokens=200)

    assert len(ctx.messages) == 2
    assert all("TACHE" not in m["content"] for m in ctx.messages), (
        "BUG C7 : la tache initiale devrait rester dans le contexte actif"
    )


@pytest.mark.known_issue
def test_compact_summary_is_a_raw_concatenation_not_a_summary(ctx):
    """Bug C7 — le README annonce « génère un résumé ». Il n'y a aucun appel au modèle.

    ``_generate_summary`` préfixe chaque message de ``[role]:`` et colle le tout.
    """
    ctx.add_message("user", "TACHE: analyse les logs")
    for i in range(6):
        ctx.add_message("assistant", f"blabla {i} " * 40)

    ctx.compact(summary_tokens=120)

    assert "[user]: TACHE: analyse les logs" in ctx.summary
    assert "[assistant]:" in ctx.summary, "BUG C7 : ce n'est pas un resume, c'est un collage"


@pytest.mark.known_issue
def test_compact_summary_is_cut_mid_word_by_string_slicing(ctx):
    """Bug C7 — la troncature finale fait ``summary[:len-100] + "..."``.

    Le découpage est fait en caractères, pas en tokens ni en mots : la fin du résumé peut
    être coupée au milieu d'un mot, voire d'un token.
    """
    ctx.add_message("user", "TACHE: " + "mot " * 200)
    for i in range(8):
        ctx.add_message("assistant", f"reponse {i} " + "vocabulaire " * 20)

    ctx.compact(summary_tokens=40)

    assert ctx.summary.endswith("..."), "BUG C7 : troncature par decoupage de chaine"


@pytest.mark.known_issue
def test_summary_is_injected_as_a_system_message_in_the_middle(ctx):
    """Bug C8 — le résumé devient un second message ``system``.

    ``get_messages()`` préfixe l'historique d'un message ``role: system``. Or
    ``Agent._get_model_response`` envoie déjà le vrai system prompt en première position :
    la requête part donc avec **deux** messages system consécutifs. Le gabarit Jinja de
    llama.cpp (``--jinja``, obligatoire pour Qwen3) n'en garantit pas le rendu.

    Comportement attendu en phase 3 : replier le résumé dans le system prompt initial.
    """
    for i in range(6):
        ctx.add_message("user", f"message {i}")
    ctx.compact(summary_tokens=50)

    messages = ctx.get_messages()

    assert messages[0]["role"] == "system", "BUG C8 : un system au milieu de l'historique"
    assert "Résumé" in messages[0]["content"]
    assert ctx.messages[0]["role"] == "user"


@pytest.mark.known_issue
def test_compaction_count_never_resets(ctx):
    """Le compteur ne redescend jamais, et ``get_messages`` préfixe le résumé dès qu'il est > 0.

    Tant que ``compaction_count`` vaut plus de zéro, chaque requête embarque la ligne
    « Résumé des échanges précédents ». Seul ``reset()`` remet le compteur à zéro.
    """
    for i in range(6):
        ctx.add_message("user", f"message {i}")
    ctx.compact(summary_tokens=50)
    assert ctx.compaction_count == 1

    for i in range(6):
        ctx.add_message("user", f"suite {i}")
    ctx.compact(summary_tokens=50)

    assert ctx.compaction_count == 2
    assert ctx.get_messages()[0]["role"] == "system"


# --------------------------------------------------------------------------- #
# Statistiques, réinitialisation, persistance
# --------------------------------------------------------------------------- #


def test_get_stats_shape(ctx):
    ctx.add_message("user", "a" * 40)
    stats = ctx.get_stats()
    assert stats == {
        "total_messages": 1,
        "compaction_count": 0,
        "estimated_tokens": 10,
        "max_tokens": 100,
        "has_summary": False,
    }


def test_reset_clears_everything(ctx):
    for i in range(6):
        ctx.add_message("user", f"message {i}")
    ctx.compact(summary_tokens=50)

    ctx.reset()

    assert ctx.messages == []
    assert ctx.summary == ""
    assert ctx.compaction_count == 0


def test_save_and_load_roundtrip(ctx, tmp_path):
    ctx.add_message("user", "bonjour")
    ctx.add_message("assistant", "salut")
    ctx.summary = "resume"
    ctx.compaction_count = 1
    target = tmp_path / "ctx.json"

    ctx.save_to_file(str(target))

    other = ContextManager()
    other.load_from_file(str(target))

    assert other.messages == ctx.messages
    assert other.summary == "resume"
    assert other.compaction_count == 1


def test_save_writes_readable_json_with_stats(ctx, tmp_path):
    ctx.add_message("user", "hi")
    target = tmp_path / "ctx.json"
    ctx.save_to_file(str(target))

    data = json.loads(target.read_text(encoding="utf-8"))

    assert set(data) == {"messages", "summary", "compaction_count", "stats"}
    assert data["stats"]["total_messages"] == 1


def test_load_tolerates_a_partial_file(ctx, tmp_path):
    """Les clés absentes prennent leur valeur par défaut : la reprise d'une vieille session
    ne lève pas d'exception."""
    target = tmp_path / "ctx.json"
    target.write_text("{}", encoding="utf-8")

    ctx.load_from_file(str(target))

    assert ctx.messages == []
    assert ctx.summary == ""
    assert ctx.compaction_count == 0
