"""Faux serveur d'inférence, compatible avec l'API OpenAI.

Utilisé par les tests et par la démonstration de bout en bout. Il parle vraiment HTTP :
le client ``openai`` réel, le vrai streaming SSE et le vrai ``GET /v1/models`` sont exercés.
Seul le modèle est simulé.

Pourquoi un faux serveur plutôt qu'une doublure du client ? Parce que les bugs les plus
coûteux d'un harness d'agent se logent dans les coutures : l'URL, le nom de modèle, le
format des événements SSE, la taille de contexte annoncée. Une doublure du client laisse
toutes ces coutures non testées.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable

DEFAULT_MODEL = "modele-de-test"
DEFAULT_REPLY = "Bonjour ! Je suis un faux modèle local."


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # Le silence : un faux serveur ne doit pas polluer la sortie de pytest.
    def log_message(self, *args: Any) -> None:  # noqa: D102
        pass

    # -- utilitaires ------------------------------------------------------ #

    @property
    def server_state(self) -> "FakeLlamaServer":
        return self.server.fake  # type: ignore[attr-defined]

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
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
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
                    "n_ctx": state.n_ctx,
                    "default_generation_settings": {"n_ctx": state.n_ctx},
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

        if state.fail_with is not None:
            status, message = state.fail_with
            self._json({"error": {"message": message}}, status=status)
            return

        reply = state.next_reply()
        model = body.get("model") or (state.models[0] if state.models else DEFAULT_MODEL)

        if body.get("stream"):
            self._stream(reply, model)
        else:
            self._json(_completion(reply, model))

    # -- streaming -------------------------------------------------------- #

    def _stream(self, reply: str, model: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        for piece in _split(reply):
            self.wfile.write(_sse(_chunk(piece, model)))
        self.wfile.write(_sse(_chunk("", model, finish_reason="stop")))
        self.wfile.write(_sse(_chunk("", model, usage=True)))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def _split(reply: str, size: int = 12) -> Iterable[str]:
    """Découpe la réponse en morceaux, comme un vrai modèle qui streame token par token."""
    if not reply:
        return [""]
    return [reply[index : index + size] for index in range(0, len(reply), size)]


def _chunk(
    content: str, model: str, finish_reason: str | None = None, usage: bool = False
) -> dict:
    payload: dict[str, Any] = {
        "id": "chatcmpl-fake",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": ({"content": content} if content else {}),
                "finish_reason": finish_reason,
            }
        ],
    }
    if usage:
        payload["usage"] = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    return payload


def _completion(reply: str, model: str) -> dict:
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


def _sse(payload: dict) -> bytes:
    return b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n"


class FakeLlamaServer:
    """Serveur de test, démarré dans un fil d'exécution.

    Usage :

        with FakeLlamaServer(replies=["Fini."]) as server:
            config = Config(llm=LLMConfig(base_url=server.base_url, model=...))
    """

    def __init__(
        self,
        models: Iterable[str] = (DEFAULT_MODEL,),
        replies: Iterable[str] | None = None,
        n_ctx: int = 8192,
    ):
        self.models: tuple[str, ...] = tuple(models)
        self.replies: list[str] = list(replies) if replies is not None else [DEFAULT_REPLY]
        self.n_ctx = n_ctx
        self.requests: list[dict] = []
        self.fail_with: tuple[int, str] | None = None
        self._index = 0
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -- cycle de vie ----------------------------------------------------- #

    def start(self) -> "FakeLlamaServer":
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
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

    def __enter__(self) -> "FakeLlamaServer":
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

    def next_reply(self) -> str:
        """Réponse suivante de la file ; la dernière est répétée indéfiniment."""
        if not self.replies:
            return DEFAULT_REPLY
        reply = self.replies[min(self._index, len(self.replies) - 1)]
        self._index += 1
        return reply

    def record(self, body: dict) -> None:
        self.requests.append(body)

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def last_messages(self) -> list[dict]:
        return self.requests[-1].get("messages", []) if self.requests else []
