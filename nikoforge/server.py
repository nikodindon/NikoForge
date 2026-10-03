"""Découverte et diagnostic du serveur d'inférence.

Ce module n'utilise que la bibliothèque standard (``urllib``) et non le client ``openai`` :
il doit fonctionner même quand la dépendance est cassée — c'est justement le cas qu'il sert
à diagnostiquer (``nikoforge doctor``).

Il corrige aussi le bloquant B2 de la v2 : le serveur absent y produisait « ✗ Erreur modèle:
Connection error. » suivi de « ✗ Pas de réponse du modèle », sans jamais dire à l'utilisateur
que son serveur était éteint, ni comment le lancer.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

#: Délai du test de disponibilité. Court : c'est un diagnostic, pas une inférence.
PROBE_TIMEOUT = 3.0

DEFAULT_PORT = 8080
DEFAULT_MODELS_DIR = Path.home() / "models"


@dataclass(frozen=True)
class Probe:
    """Résultat d'un test de disponibilité du serveur."""

    ok: bool
    models: tuple[str, ...] = ()
    latency: float | None = None
    error: str | None = None
    detail: str = ""

    @property
    def single_model(self) -> str | None:
        return self.models[0] if len(self.models) == 1 else None


def models_url(base_url: str) -> str:
    """``http://h:8080/v1`` -> ``http://h:8080/v1/models``."""
    return base_url.rstrip("/") + "/models"


def port_of(base_url: str, default: int = DEFAULT_PORT) -> int:
    """Extrait le port de ``base_url``, avec une valeur de repli lisible."""
    try:
        parsed = urllib.parse.urlsplit(base_url)
        return parsed.port or default
    except ValueError:
        return default


def probe(base_url: str, timeout: float = PROBE_TIMEOUT) -> Probe:
    """Interroge ``GET /v1/models`` et résume l'état du serveur.

    Ne lève jamais : toute erreur devient un ``Probe`` exploitable par l'appelant. Y compris
    une URL malformée — un utilisateur qui écrit ``--base-url localhost:8080`` (sans schéma)
    doit recevoir un message clair, pas une trace.
    """
    started = time.monotonic()
    try:
        url = models_url(base_url)
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
    except (ValueError, TypeError) as exc:
        return Probe(
            ok=False,
            error=f"URL inexploitable ({exc})",
            detail=(
                f"« {base_url} » n'est pas une URL valide. Attendu : "
                "http://127.0.0.1:8080/v1"
            ),
        )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        latency = time.monotonic() - started
        if exc.code in (401, 403):
            return Probe(
                ok=False,
                latency=latency,
                error=f"HTTP {exc.code} — authentification refusée",
                detail=(
                    "Le serveur répond mais rejette la clé d'API. Renseignez "
                    "NIKOFORGE_API_KEY ou llm.api_key."
                ),
            )
        return Probe(
            ok=False,
            latency=latency,
            error=f"HTTP {exc.code} {exc.reason}",
            detail=f"Le serveur répond sur {url} mais a renvoyé une erreur.",
        )
    except urllib.error.URLError as exc:
        return Probe(
            ok=False,
            latency=time.monotonic() - started,
            error=f"connexion impossible ({exc.reason})",
            detail=f"Aucun serveur n'écoute sur {url}.",
        )
    except TimeoutError:
        return Probe(
            ok=False,
            error=f"pas de réponse en {timeout:g} s",
            detail=f"{url} accepte la connexion mais ne répond pas.",
        )
    except (OSError, ValueError) as exc:
        return Probe(
            ok=False,
            latency=time.monotonic() - started,
            error=f"réponse illisible ({exc})",
            detail=f"{url} n'a pas renvoyé du JSON valide.",
        )

    latency = time.monotonic() - started
    try:
        entries = payload["data"]
    except (TypeError, KeyError):
        return Probe(
            ok=False,
            latency=latency,
            error="réponse inattendue",
            detail=f'{url} n\'a pas renvoyé de clé "data" (attendu : {{"data": [...]}}).',
        )

    models = tuple(
        entry.get("id", "") for entry in entries if isinstance(entry, dict) and entry.get("id")
    )
    if not models:
        return Probe(
            ok=True,
            latency=latency,
            error=None,
            detail=f"{url} répond mais n'annonce aucun modèle chargé.",
        )

    return Probe(ok=True, models=models, latency=latency, detail=f"{len(models)} modèle(s)")


def server_context_size(base_url: str, timeout: float = PROBE_TIMEOUT) -> int | None:
    """Taille de contexte annoncée par le serveur, si elle est interrogeable.

    ``llama.cpp`` expose ``GET /props``. Aucun autre serveur compatible OpenAI n'est tenu de
    le faire : l'absence de réponse n'est pas une erreur, seulement une information manquante
    (``None``). Connaître cette valeur permet d'avertir quand ``context.max_tokens`` la
    dépasse — au-delà, le serveur tronque l'historique en silence.
    """
    url = base_url.rstrip("/").removesuffix("/v1") + "/props"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None

    candidates: list[object] = [payload.get("n_ctx")]
    settings = payload.get("default_generation_settings")
    if isinstance(settings, dict):
        candidates.append(settings.get("n_ctx"))

    for candidate in candidates:
        if isinstance(candidate, int) and candidate > 0:
            return candidate
    return None


def pick_model(probe_result: Probe) -> tuple[str | None, str]:
    """Choisit un modèle parmi ceux annoncés par le serveur.

    Retourne ``(modèle, avertissement)``. Avec un seul modèle — le cas normal d'un
    ``llama-server`` — la découverte se fait sans aucune configuration : c'est ce qui permet
    à ``nikoforge -p "..."`` de fonctionner sur une machine vierge.
    """
    if not probe_result.models:
        return None, ""
    if len(probe_result.models) == 1:
        return probe_result.models[0], ""
    return probe_result.models[0], (
        f"{len(probe_result.models)} modèles annoncés, « {probe_result.models[0]} » retenu "
        f"(forçable avec --model ou NIKOFORGE_MODEL) : "
        + ", ".join(probe_result.models)
    )


# --------------------------------------------------------------------------- #
# Aide à l'installation
# --------------------------------------------------------------------------- #


def find_local_models(models_dir: Path | None = None, limit: int = 5) -> tuple[Path, ...]:
    """Modèles GGUF trouvés localement, du plus récent au plus ancien."""
    directory = Path(models_dir) if models_dir else DEFAULT_MODELS_DIR
    if not directory.is_dir():
        return ()
    found = sorted(
        directory.rglob("*.gguf"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return tuple(found[:limit])


def suggest_server_command(
    base_url: str, models_dir: Path | None = None, model_path: Path | None = None
) -> str:
    """Commande ``llama-server`` prête à copier, adaptée au port de ``base_url``.

    Le modèle proposé est le GGUF local le plus récent s'il y en a, sinon un chemin à compléter.
    """
    port = port_of(base_url)
    if model_path is None:
        local = find_local_models(models_dir)
        model_path = local[0] if local else None
    shown = str(model_path) if model_path else "/chemin/vers/modele.gguf"

    return (
        f"llama-server -m {shown} \\\n"
        f"  --host 127.0.0.1 --port {port} -c 65536 --jinja \\\n"
        f"  -ngl 999 --flash-attn on"
    )
