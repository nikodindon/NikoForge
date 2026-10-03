"""``nikoforge.llm`` : accès au serveur, streaming, outils, raisonnement, erreurs.

Les tests parlent HTTP pour de bon, contre ``tests/fake_server.py`` : le client ``openai``
réel, le vrai SSE, la vraie reconstitution des ``tool_calls`` fragmentés. Seul le modèle est
simulé.

Corrections couvertes ici : C4 (raisonnement gardé à part), C10 (délais, reprise, erreurs
nommées), et la lecture de l'``usage`` réel (C7b).
"""

from __future__ import annotations

import types

import pytest
from conftest import UNREACHABLE_BASE_URL, config_for

from nikoforge import llm as llm_module
from nikoforge.config import apply_overrides, default_config
from nikoforge.llm import (
    LLM,
    ContextTooLong,
    LLMError,
    ModelNotFound,
    RequestTimedOut,
    ServerError,
    ServerUnreachable,
    ToolsUnsupported,
    Usage,
    _accumulate_tool_fragments,
    _field,
    discover_capabilities,
    translate_error,
)
from nikoforge.protocol import ToolCall

MODEL = "modele-de-test"


def client_for(base_url: str, **kwargs) -> tuple[LLM, list[float]]:
    """Un ``LLM`` dont les attentes sont enregistrées au lieu d'être subies."""
    slept: list[float] = []
    config = config_for(base_url)
    llm = LLM(config, sleep=slept.append, **kwargs)
    return llm, slept


# --------------------------------------------------------------------------- #
# Capacités
# --------------------------------------------------------------------------- #


def test_capabilities_are_read_from_props(fake_server):
    caps = discover_capabilities(fake_server.base_url)
    assert caps.supports_tools is True
    assert caps.n_ctx == 8192
    assert caps.supports_parallel_tool_calls is True


def test_capabilities_report_no_tools_when_the_template_says_so(fake_server):
    fake_server.supports_tools = False
    assert discover_capabilities(fake_server.base_url).supports_tools is False


def test_capabilities_on_a_generic_server_without_props(fake_server):
    """Un serveur compatible OpenAI n'a pas forcément ``/props`` : ce n'est pas une erreur.

    On interroge une base dont la route ``/props`` n'existe pas : le serveur répond 404.
    """
    base = fake_server.root_url + "/inexistant/v1"
    caps = discover_capabilities(base)
    assert caps.supports_tools is False
    assert caps.n_ctx is None


def test_capabilities_on_an_unreachable_server_are_empty():
    caps = discover_capabilities(UNREACHABLE_BASE_URL, timeout=1)
    assert caps.supports_tools is False
    assert caps.n_ctx is None


def test_capabilities_are_cached(fake_server):
    llm, _ = client_for(fake_server.base_url)
    first = llm.capabilities()
    fake_server.supports_tools = False  # le serveur change d'avis
    assert llm.capabilities() is first
    assert llm.capabilities(refresh=True).supports_tools is False


# --------------------------------------------------------------------------- #
# Choix du protocole (D1)
# --------------------------------------------------------------------------- #


def test_auto_protocol_uses_native_tools_when_announced(fake_server):
    llm, _ = client_for(fake_server.base_url)
    assert llm.uses_tools is True


def test_auto_protocol_falls_back_to_text_without_tool_support(fake_server):
    fake_server.supports_tools = False
    llm, _ = client_for(fake_server.base_url)
    assert llm.uses_tools is False


def test_protocol_can_be_forced_to_text(fake_server):
    config = apply_overrides(config_for(fake_server.base_url), {"llm": {"protocol": "text"}})
    assert LLM(config).uses_tools is False


def test_protocol_can_be_forced_to_native(fake_server):
    fake_server.supports_tools = False
    config = apply_overrides(config_for(fake_server.base_url), {"llm": {"protocol": "native"}})
    assert LLM(config).uses_tools is True


def test_native_tools_are_sent_in_the_request(fake_server):
    llm, _ = client_for(fake_server.base_url)
    llm.complete([{"role": "user", "content": "bonjour"}])
    body = fake_server.requests[-1]
    assert body["tools"][0]["function"]["name"] == "list_files"
    assert body["tool_choice"] == "auto"


def test_text_protocol_sends_no_tools_field(fake_server):
    config = apply_overrides(config_for(fake_server.base_url), {"llm": {"protocol": "text"}})
    LLM(config).complete([{"role": "user", "content": "bonjour"}])
    assert "tools" not in fake_server.requests[-1]


def test_a_server_refusing_tools_is_retried_without_them(fake_server):
    """Repli automatique : un 400 sur `tools` ne doit pas tuer la session."""
    fake_server.reject_tools = True
    llm, slept = client_for(fake_server.base_url)

    completion = llm.complete([{"role": "user", "content": "bonjour"}])

    assert completion.text
    assert completion.attempts == 1  # ce n'est pas la faute du réseau
    assert llm.uses_tools is False  # mémorisé pour la suite de la session
    assert "tools" in fake_server.requests[0]
    assert "tools" not in fake_server.requests[1]
    assert slept == []


def test_tools_unsupported_is_raised_when_tools_were_forced(fake_server):
    fake_server.reject_tools = True
    config = apply_overrides(config_for(fake_server.base_url), {"llm": {"protocol": "native"}})
    with pytest.raises(ToolsUnsupported, match="refuse le champ"):
        LLM(config).complete([{"role": "user", "content": "bonjour"}])


# --------------------------------------------------------------------------- #
# Modèle
# --------------------------------------------------------------------------- #


def test_the_model_is_discovered_when_empty(fake_server):
    config = apply_overrides(config_for(fake_server.base_url), {"llm": {"model": ""}})
    llm = LLM(config)
    assert llm.model == MODEL
    llm.complete([{"role": "user", "content": "bonjour"}])
    assert fake_server.requests[-1]["model"] == MODEL


def test_an_unreachable_server_is_named_as_such():
    config = apply_overrides(config_for(UNREACHABLE_BASE_URL), {"llm": {"model": ""}})
    with pytest.raises(ServerUnreachable, match="injoignable"):
        LLM(config).model


def test_a_server_without_any_model_is_reported(fake_server):
    fake_server.models = ()
    config = apply_overrides(config_for(fake_server.base_url), {"llm": {"model": ""}})
    with pytest.raises(ModelNotFound, match="aucun modèle"):
        LLM(config).model


# --------------------------------------------------------------------------- #
# Streaming
# --------------------------------------------------------------------------- #


def test_text_is_streamed_in_pieces_and_reassembled(fake_server):
    fake_server.replies = ["Bonjour, ceci est une réponse assez longue pour être découpée."]
    pieces: list[str] = []
    llm, _ = client_for(fake_server.base_url, on_text=pieces.append)

    completion = llm.complete([{"role": "user", "content": "bonjour"}])

    assert len(pieces) > 1, "le flux doit arriver en plusieurs morceaux"
    assert "".join(pieces) == completion.text
    assert completion.text == fake_server.replies[0]


def test_usage_comes_from_the_server(fake_server):
    """C7b : les tokens réels du serveur remplacent l'estimation ``len // 4``."""
    llm, _ = client_for(fake_server.base_url)
    completion = llm.complete([{"role": "user", "content": "bonjour"}])
    assert completion.usage == Usage(prompt_tokens=11, completion_tokens=7, total_tokens=18)


def test_usage_is_optional(fake_server):
    """Tous les serveurs n'envoient pas l'usage dans le flux : ce n'est pas une erreur."""
    fake_server.include_usage = False
    llm, _ = client_for(fake_server.base_url)
    assert llm.complete([{"role": "user", "content": "bonjour"}]).usage is None


def test_finish_reason_and_elapsed_are_reported(fake_server):
    llm, _ = client_for(fake_server.base_url)
    completion = llm.complete([{"role": "user", "content": "bonjour"}])
    assert completion.finish_reason == "stop"
    assert completion.elapsed >= 0
    assert completion.model == MODEL


def test_stream_options_request_the_usage(fake_server):
    llm, _ = client_for(fake_server.base_url)
    llm.complete([{"role": "user", "content": "bonjour"}])
    assert fake_server.requests[-1]["stream_options"] == {"include_usage": True}


def test_stop_sequences_are_forwarded(fake_server):
    config = apply_overrides(config_for(fake_server.base_url), {"llm": {"stop": ["</tool_calls>"]}})
    LLM(config).complete([{"role": "user", "content": "bonjour"}])
    assert fake_server.requests[-1]["stop"] == ["</tool_calls>"]


def test_thinking_is_disabled_by_default(fake_server):
    llm, _ = client_for(fake_server.base_url)
    llm.complete([{"role": "user", "content": "bonjour"}])
    assert fake_server.requests[-1]["chat_template_kwargs"] == {"enable_thinking": False}


def test_thinking_can_be_enabled(fake_server):
    config = apply_overrides(
        config_for(fake_server.base_url), {"llm": {"enable_thinking": True}}
    )
    LLM(config).complete([{"role": "user", "content": "bonjour"}])
    assert "chat_template_kwargs" not in fake_server.requests[-1]


def test_max_tokens_can_be_overridden_per_call(fake_server):
    llm, _ = client_for(fake_server.base_url)
    llm.complete([{"role": "user", "content": "bonjour"}], max_tokens=64)
    assert fake_server.requests[-1]["max_tokens"] == 64


# --------------------------------------------------------------------------- #
# Raisonnement (C4)
# --------------------------------------------------------------------------- #


def test_reasoning_is_kept_apart_from_the_answer(fake_server):
    """C4 : en v2, la réflexion était concaténée à la réponse et stockée dans l'historique."""
    fake_server.reasoning = ["Je réfléchis ", "longuement."]
    fake_server.replies = ["La réponse."]
    thoughts: list[str] = []
    llm, _ = client_for(fake_server.base_url, on_reasoning=thoughts.append)

    completion = llm.complete([{"role": "user", "content": "bonjour"}])

    assert completion.reasoning == "Je réfléchis longuement."
    assert completion.text == "La réponse."
    assert "réfléchis" not in completion.text
    assert "".join(thoughts) == completion.reasoning


def test_absent_reasoning_is_an_empty_string(fake_server):
    llm, _ = client_for(fake_server.base_url)
    assert llm.complete([{"role": "user", "content": "bonjour"}]).reasoning == ""


# --------------------------------------------------------------------------- #
# Appels d'outils natifs, fragmentés
# --------------------------------------------------------------------------- #


def test_fragmented_native_tool_calls_are_reassembled(fake_server):
    """llama.cpp envoie ``tool_calls`` morceau par morceau : un client naïf lit du JSON tronqué."""
    fake_server.tool_calls = [{"name": "list_files", "arguments": {"path": "."}}]

    llm, _ = client_for(fake_server.base_url)
    completion = llm.complete([{"role": "user", "content": "liste"}])

    assert completion.calls == (ToolCall("list_files", {"path": "."}, call_id="call_0"),)


def test_several_native_tool_calls_keep_their_order(fake_server):
    fake_server.tool_calls = [
        {"name": "read_file", "arguments": {"path": "a.py"}},
        {"name": "bash", "arguments": {"command": "pytest -q"}},
    ]
    llm, _ = client_for(fake_server.base_url)

    completion = llm.complete([{"role": "user", "content": "vas-y"}])

    assert [call.name for call in completion.calls] == ["read_file", "bash"]
    assert completion.calls[1].arguments == {"command": "pytest -q"}


def test_native_call_with_long_arguments_survives_fragmentation(fake_server):
    content = "ligne 1\nligne 2\n" * 40
    fake_server.tool_calls = [
        {"name": "write_file", "arguments": {"path": "gros.txt", "content": content}}
    ]
    llm, _ = client_for(fake_server.base_url)

    completion = llm.complete([{"role": "user", "content": "écris"}])

    assert completion.calls[0].arguments["content"] == content


def test_text_protocol_tool_calls_are_decoded(fake_server):
    """Un serveur sans `tools` doit pouvoir appeler des outils malgré tout."""
    fake_server.replies = [
        'Je liste.\n<tool_calls><tool name="list_files"><param name="path">.</param>'
        "</tool></tool_calls>"
    ]
    config = apply_overrides(config_for(fake_server.base_url), {"llm": {"protocol": "text"}})

    completion = LLM(config).complete([{"role": "user", "content": "liste"}])

    assert completion.calls == (ToolCall("list_files", {"path": "."}),)
    assert completion.text == "Je liste."


# --------------------------------------------------------------------------- #
# Erreurs et reprise (C10)
# --------------------------------------------------------------------------- #


def test_an_unreachable_server_raises_a_named_error():
    llm, slept = client_for(UNREACHABLE_BASE_URL, max_retries=0)
    with pytest.raises(ServerUnreachable) as excinfo:
        llm.complete([{"role": "user", "content": "bonjour"}])
    assert "injoignable" in str(excinfo.value)
    assert "nikoforge doctor" in str(excinfo.value)


def test_a_transient_500_is_retried_and_succeeds(fake_server):
    fake_server.error_queue = [(500, "internal error")]
    llm, slept = client_for(fake_server.base_url, max_retries=2)

    completion = llm.complete([{"role": "user", "content": "bonjour"}])

    assert completion.attempts == 2
    assert fake_server.call_count == 2
    assert slept == [1.0]  # attente croissante, injectée donc instantanée


def test_retries_give_up_with_a_named_error(fake_server):
    fake_server.fail_with = (503, "service unavailable")
    llm, slept = client_for(fake_server.base_url, max_retries=2)

    with pytest.raises(ServerError, match="erreur 503"):
        llm.complete([{"role": "user", "content": "bonjour"}])

    assert fake_server.call_count == 3  # 1 tentative + 2 reprises
    assert slept == [1.0, 2.0]  # attente doublée


def test_a_context_overflow_is_not_retried(fake_server):
    fake_server.fail_with = (400, "the request exceeds the available context size (n_ctx)")
    llm, slept = client_for(fake_server.base_url, max_retries=2)

    with pytest.raises(ContextTooLong, match="fenêtre de contexte"):
        llm.complete([{"role": "user", "content": "bonjour"}])

    assert fake_server.call_count == 1
    assert slept == []


def test_an_unknown_model_is_reported(fake_server):
    fake_server.fail_with = (404, "model not found")
    llm, _ = client_for(fake_server.base_url, max_retries=0)
    with pytest.raises(ModelNotFound, match="ne connaît pas le modèle"):
        llm.complete([{"role": "user", "content": "bonjour"}])


# --------------------------------------------------------------------------- #
# translate_error, en unitaire
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("exception", "expected", "fragment"),
    [
        (ConnectionError("connection refused"), ServerUnreachable, "injoignable"),
        (OSError("connect failed"), ServerUnreachable, "injoignable"),
        (RuntimeError("read timed out"), RequestTimedOut, "délai imparti"),
        (RuntimeError("HTTP 502 bad gateway"), LLMError, "erreur d'accès"),
        (RuntimeError("boom"), LLMError, "boom"),
    ],
)
def test_translate_error_maps_the_common_cases(exception, expected, fragment):
    config = default_config()
    translated = translate_error(exception, config, "un-modele")
    assert isinstance(translated, expected)
    assert fragment in str(translated)


def test_translate_error_recognises_a_tools_refusal():
    class Fake(Exception):
        status_code = 400

    error = Fake("this server does not support the `tools` parameter")
    assert isinstance(translate_error(error, default_config(), "m"), ToolsUnsupported)


def test_translate_error_recognises_a_context_overflow():
    class Fake(Exception):
        status_code = 400
        def __str__(self):
            return "the prompt is too long for n_ctx 4096"

    assert isinstance(translate_error(Fake(), default_config(), "m"), ContextTooLong)


def test_translate_error_marks_5xx_as_retryable():
    class Fake(Exception):
        status_code = 500

    translated = translate_error(Fake("souci"), default_config(), "m")
    assert isinstance(translated, ServerError)
    assert translated.retryable is True


# --------------------------------------------------------------------------- #
# Détails du flux, en unitaire
# --------------------------------------------------------------------------- #


def test_field_reads_the_attribute():
    assert _field(types.SimpleNamespace(content="x"), "content") == "x"


def test_field_falls_back_on_model_extra():
    """``reasoning_content`` n'est pas déclaré par le SDK : il atterrit dans ``model_extra``."""
    delta = types.SimpleNamespace(content=None, model_extra={"reasoning_content": "pensée"})
    assert _field(delta, "reasoning_content") == "pensée"


def test_field_returns_none_when_absent():
    assert _field(types.SimpleNamespace(), "content") is None
    assert _field(types.SimpleNamespace(content=None, model_extra=None), "content") is None


def test_tool_fragments_are_accumulated_by_index():
    fragments: dict[int, dict] = {}
    _accumulate_tool_fragments(
        fragments,
        [
            types.SimpleNamespace(
                index=0,
                id="c1",
                function=types.SimpleNamespace(name="bash", arguments=""),
            )
        ],
    )
    _accumulate_tool_fragments(
        fragments, [types.SimpleNamespace(index=0, function=types.SimpleNamespace(arguments='{"a"'))]
    )
    _accumulate_tool_fragments(
        fragments, [types.SimpleNamespace(index=0, function=types.SimpleNamespace(arguments=": 1}"))]
    )

    assert fragments[0] == {"id": "c1", "name": "bash", "arguments": '{"a": 1}'}


def test_tool_fragments_without_index_use_their_position():
    fragments: dict[int, dict] = {}
    _accumulate_tool_fragments(
        fragments,
        [types.SimpleNamespace(function=types.SimpleNamespace(name="x", arguments="{}"))],
    )
    assert fragments[0]["name"] == "x"


def test_tool_fragments_ignore_an_empty_delta():
    fragments: dict[int, dict] = {}
    _accumulate_tool_fragments(fragments, None)
    _accumulate_tool_fragments(fragments, [])
    assert fragments == {}


def test_the_llm_module_exposes_the_documented_errors():
    for name in (
        "LLMError",
        "ServerUnreachable",
        "ModelNotFound",
        "ToolsUnsupported",
        "ContextTooLong",
        "RequestTimedOut",
        "ServerError",
    ):
        assert hasattr(llm_module, name)
