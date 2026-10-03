"""Assistant de premier lancement : ``nikoforge init``.

Objectif : supprimer l'étape manuelle qui bloquait la v2 (« copie ``config.example.json``
puis édite le JSON » — bloquant B1). Ici, l'assistant détecte le serveur, lit la liste des
modèles qu'il annonce, et écrit un TOML complet. Si aucun serveur ne répond, il affiche la
commande ``llama-server`` à copier plutôt que d'échouer.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, TextIO

from .config import Config, write_config
from .server import (
    find_local_models,
    probe,
    suggest_server_command,
)

DEFAULT_MODELS_DIR = Path.home() / "models"


def _ask(question: str, default: str, interactive: bool, input_fn: Callable[[str], str]) -> str:
    """Pose une question, ou prend la valeur par défaut si l'on n'est pas interactif."""
    if not interactive:
        return default
    try:
        answer = input_fn(f"{question} [{default}] : ").strip()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    return answer or default


def _choose_model(
    models: tuple[str, ...], interactive: bool, input_fn: Callable[[str], str], stream: TextIO
) -> str:
    if len(models) == 1 or not interactive:
        return models[0]

    print("Plusieurs modèles sont annoncés par le serveur :", file=stream)
    for index, name in enumerate(models, start=1):
        print(f"  {index}. {name}", file=stream)
    raw = _ask("Numéro du modèle", "1", interactive, input_fn)
    try:
        return models[int(raw) - 1]
    except (ValueError, IndexError):
        print(f"Choix invalide, « {models[0]} » retenu.", file=stream)
        return models[0]


def run_init(
    config: Config,
    target: Path,
    *,
    force: bool = False,
    interactive: bool = True,
    models_dir: Path | None = None,
    stream: TextIO | None = None,
    input_fn: Callable[[str], str] = input,
) -> int:
    """Écrit la configuration en TOML. Retourne le code de sortie."""
    out = sys.stdout if stream is None else stream
    target = Path(target).expanduser()

    if target.exists() and not force:
        print(f"{target} existe déjà.", file=out)
        print("Rien n'a été modifié. Utilisez --force pour l'écraser.", file=out)
        return 1

    print(f"Configuration NikoForge — écriture dans {target}", file=out)
    print(file=out)

    result = probe(config.llm.base_url)

    if result.ok:
        latency = f" ({result.latency * 1000:.0f} ms)" if result.latency else ""
        print(f"✔ serveur joignable : {config.llm.base_url}{latency}", file=out)
    else:
        print(f"✖ serveur injoignable : {config.llm.base_url} — {result.error}", file=out)
        print(f"  {result.detail}", file=out)
        print(file=out)
        print("  Démarrez-le, puis relancez `nikoforge init` :", file=out)
        for line in suggest_server_command(config.llm.base_url, models_dir).splitlines():
            print(f"    {line}", file=out)
        local = find_local_models(models_dir) if models_dir or DEFAULT_MODELS_DIR.is_dir() else ()
        if local:
            print(file=out)
            print(
                f"  ({len(local)} fichier(s) .gguf trouvé(s) localement, "
                "le plus récent est proposé ci-dessus)",
                file=out,
            )
        print(file=out)

    model = config.llm.model
    if result.ok and result.models:
        if model and model not in result.models:
            print(f"⚠ le modèle configuré ({model}) n'est pas annoncé par le serveur", file=out)
            model = ""
        if not model:
            model = _choose_model(result.models, interactive, input_fn, out)
            print(f"✔ modèle retenu : {model}", file=out)
    elif result.ok:
        print("⚠ le serveur ne répond mais n'annonce aucun modèle chargé", file=out)

    if not result.ok:
        print(
            "  Le modèle reste vide : il sera découvert automatiquement au démarrage,\n"
            "  dès qu'un serveur annoncera un modèle.",
            file=out,
        )

    # Réécrit le TOML avec le modèle découvert, sans toucher au reste : le fichier produit
    # est complet et commenté (nikoforge --print-config en montre le contenu).
    from dataclasses import replace

    final = replace(config, llm=replace(config.llm, model=model))
    write_config(final, target)

    print(file=out)
    print(f"✔ configuration écrite : {target}", file=out)
    print(file=out)
    print("Prochaines étapes :", file=out)
    print("  nikoforge doctor            # vérifie que tout est en place", file=out)
    print('  nikoforge -p "bonjour"      # une tâche, en une commande', file=out)
    print("  nikoforge                   # ou directement le mode interactif", file=out)
    return 0
