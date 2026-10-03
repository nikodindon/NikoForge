"""Faux serveur d'inférence, compatible avec l'API OpenAI.

Utilisé par les tests et par les démonstrations. Il parle vraiment HTTP : le client ``openai``
réel, le vrai streaming SSE, ``GET /v1/models`` et ``GET /props`` sont exercés. Seul le modèle
est simulé.

Pourquoi un faux serveur plutôt qu'une doublure du client ? Parce que les bugs les plus
coûteux d'un harness d'agent se logent dans les coutures : l'URL, le nom de modèle, le format
des événements SSE, la reconstitution des ``tool_calls`` fragmentés, l'usage en fin de flux,
la taille de contexte annoncée. Une doublure du client laisse toutes ces coutures non testées.

Il sait reproduire les situations qui comptent :

* réponse texte, avec ou sans raisonnement (``reasoning_content``) ;
* appels d'outils **natifs**, envoyés morceau par morceau comme le fait llama.cpp ;
* refus du champ ``tools`` (HTTP 400) pour exercer le repli de protocole ;
* erreurs transitoires (5xx) pour exercer la reprise ;
* usage en fin de flux, ou pas — les deux existent dans la nature.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_MODEL = "modele-de-test"
DEFAULT_REPLY = "Bonjour ! Je suis un faux modèle local."


class _Server(ThreadingHTTPServer):
    """Serveur de test : une connexion coupée par le client n'est pas une erreur."""

    daemon_threads = True

    def handle_error(self, request, client_address) -> None:  # noqa: D102
        pass


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # noqa: D102 - un faux serveur reste muet
        pass

    @property
    def server_state(self) -> FakeLlamaServer:
        return self.server.fake  # type: ignore[attr-defined]

    # -- utilitaires ------------------------------------------------------ #

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return {}

    # -- routes ----------------------------------------------------------- #

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        state = self.server_state

        if path == "/v1/models":
            self._json(
                {
                    "object": "list",
                    "data": [
                        {"id": name, "object": "model", "owned_by": "fake"}
                        for name in state.models
                    ],
                }
            )
            return

        if path == "/props":
            self._json(
                {
                    # n_ctx n'est pas à la racine chez llama.cpp : il est niché ici.
                    "default_generation_settings": {"n_ctx": state.n_ctx},
                    "chat_template": "{{ messages }}",
                    "chat_template_caps": {
                        "supports_tools": state.supports_tools,
                        "supports_system_role": True,
                        "supports_parallel_tool_calls": state.supports_parallel_tool_calls,
                    },
                    "total_slots": 1,
                }
            )
            return

        if path == "/health":
            self._json({"status": "ok"})
            return

        self._json({"error": {"message": f"route inconnue : {self.path}"}}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        state = self.server_state
        body = self._read_body()

        if path not in ("/v1/chat/completions", "/v1/completions"):
            self._json({"error": {"message": f"route inconnue : {self.path}"}}, status=404)
            return

        state.record(body)

        # Erreurs programmées, consommées dans l'ordre : sert à exercer la reprise.
        if state.error_queue:
            status_code, message = state.error_queue.pop(0)
            self._json({"error": {"message": message, "type": "fake_error"}}, status=status_code)
            return

        if state.fail_with is not None:
            status_code, message = state.fail_with
            self._json({"error": {"message": message, "type": "fake_error"}}, status=status_code)
            return

        if state.reject_tools and body.get("tools"):
            self._json(
                {
                    "error": {
                        "message": "this server does not support the `tools` parameter",
                        "type": "invalid_request_error",
                    }
                },
                status=400,
            )
            return

        model = body.get("model") or (state.models[0] if state.models else DEFAULT_MODEL)

        if body.get("stream"):
            self._stream(state, model)
        else:
            self._json(state.completion(model))

    # -- réponses --------------------------------------------------------- #

    def _stream(self, state: FakeLlamaServer, model: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        for payload in state.stream_events(model):
            self.wfile.write(b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


class FakeLlamaServer:
    """Serveur de test, démarré dans un fil d'exécution.

    Usage ::

        with FakeLlamaServer(replies=["Fini."]) as server:
            config = config_for(server.base_url)
    """

    def __init__(
        self,
        models: Iterable[str] = (DEFAULT_MODEL,),
        replies: Iterable[str] | None = None,
        n_ctx: int = 8192,
        *,
        reasoning: Iterable[str] | None = None,
        tool_calls: Iterable[dict[str, Any]] | None = None,
        tool_call_rounds: int = 1,
        supports_tools: bool = True,
        supports_parallel_tool_calls: bool = True,
        reject_tools: bool = False,
        include_usage: bool = True,
    ):
        self.models: tuple[str, ...] = tuple(models)
        self.replies: list[str] = list(replies) if replies is not None else [DEFAULT_REPLY]
        self.reasoning: list[str] = list(reasoning) if reasoning is not None else []
        #: Appels d'outils natifs, sous la forme ``{"name": ..., "arguments": {...}}``.
        self.tool_calls: list[dict[str, Any]] = list(tool_calls) if tool_calls else []
        #: Les appels d'outils ne sont émis que pour les N premières requêtes : au-delà, la
        #: boucle de l'agent doit pouvoir se terminer au lieu de tourner jusqu'au budget.
        self.tool_call_rounds = tool_call_rounds
        self.n_ctx = n_ctx
        self.supports_tools = supports_tools
        self.supports_parallel_tool_calls = supports_parallel_tool_calls
        self.reject_tools = reject_tools
        self.include_usage = include_usage

        self.requests: list[dict] = []
        #: Erreurs à renvoyer aux prochains appels : ``[(500, "message"), …]``.
        self.error_queue: list[tuple[int, str]] = []
        #: Erreur permanente : ``(status, message)``.
        self.fail_with: tuple[int, str] | None = None

        self._index = 0
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -- cycle de vie ----------------------------------------------------- #

    def start(self) -> FakeLlamaServer:
        self._httpd = _Server(("127.0.0.1", 0), _Handler)
        self._httpd.fake = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._httpd = None
        self._thread = None

    def __enter__(self) -> FakeLlamaServer:
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    # -- inspection ------------------------------------------------------- #

    @property
    def port(self) -> int:
        assert self._httpd is not None, "le serveur n'est pas démarré"
        return self._httpd.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def root_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def last_messages(self) -> list[dict]:
        return self.requests[-1].get("messages", []) if self.requests else []

    def next_reply(self) -> str:
        if not self.replies:
            return DEFAULT_REPLY
        reply = self.replies[min(self._index, len(self.replies) - 1)]
        self._index += 1
        return reply

    def record(self, body: dict) -> None:
        self.requests.append(body)

    @property
    def tool_rounds_left(self) -> int:
        """Reste-t-il des tours où le serveur doit proposer des appels d'outils ?"""
        served = len(self.requests) - 1  # la requête en cours
        return max(0, self.tool_call_rounds - served)

    @property
    def emits_tools(self) -> bool:
        return bool(self.tool_calls) and self.tool_rounds_left > 0

    # -- construction des réponses ---------------------------------------- #

    def stream_events(self, model: str) -> list[dict]:
        """Événements SSE, dans l'ordre où un vrai serveur les enverrait."""
        events: list[dict] = []

        for piece in _split(reasoning_text(self)):
            events.append(_chunk(reasoning=piece, model=model))

        for piece in _split(next_reply_now(self)):
            events.append(_chunk(content=piece, model=model))

        if self.emits_tools:
            events.extend(_tool_call_events(self, model))

        events.append(_chunk(model=model, finish_reason="stop"))
        if self.include_usage:
            events.append(_chunk(model=model, usage=True))
        return events

    def completion(self, model: str) -> dict:
        message: dict[str, Any] = {"role": "assistant", "content": next_reply_now(self)}
        if self.reasoning:
            message["reasoning_content"] = reasoning_text(self)
        if self.emits_tools:
            message["tool_calls"] = [
                {
                    "id": f"call_{index}",
                    "type": "function",
                    "function": {
                        "name": spec["name"],
                        "arguments": json.dumps(spec.get("arguments", {})),
                    },
                }
                for index, spec in enumerate(self.tool_calls)
            ]
        payload: dict[str, Any] = {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        }
        if self.include_usage:
            payload["usage"] = _usage()
        return payload


def reasoning_text(server: FakeLlamaServer) -> str:
    return "".join(server.reasoning)


def next_reply_now(server: FakeLlamaServer) -> str:
    return server.next_reply()


def _tool_call_events(server: FakeLlamaServer, model: str) -> list[dict]:
    """Émet les appels d'outils fragmentés, comme le fait llama.cpp.

    Le premier morceau porte l'``id``, le ``type`` et le **nom** ; les suivants ne portent que
    des bouts d'``arguments``. Un client qui ne reconstitue pas les fragments obtient du JSON
    tronqué — c'est précisément ce qui doit être testé.
    """
    events: list[dict] = []
    for index, spec in enumerate(server.tool_calls):
        events.append(
            _chunk(
                model=model,
                tool_call={
                    "index": index,
                    "id": f"call_{index}",
                    "type": "function",
                    "function": {"name": spec["name"], "arguments": ""},
                },
            )
        )
        arguments = json.dumps(spec.get("arguments", {}))
        for piece in _split(arguments, size=7):
            events.append(
                _chunk(
                    model=model,
                    tool_call={"index": index, "function": {"arguments": piece}},
                )
            )
    return events


def _split(text: str, size: int = 12) -> list[str]:
    """Découpe un texte en morceaux, comme un modèle qui streame token par token."""
    if not text:
        return []
    return [text[index : index + size] for index in range(0, len(text), size)]


def _usage() -> dict[str, int]:
    return {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}


def _chunk(
    model: str,
    content: str | None = None,
    reasoning: str | None = None,
    tool_call: dict | None = None,
    finish_reason: str | None = None,
    usage: bool = False,
) -> dict:
    delta: dict[str, Any] = {}
    if content:
        delta["content"] = content
    if reasoning:
        delta["reasoning_content"] = reasoning
    if tool_call:
        delta["tool_calls"] = [tool_call]

    payload: dict[str, Any] = {
        "id": "chatcmpl-fake",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if usage:
        payload["usage"] = _usage()
    return payload
