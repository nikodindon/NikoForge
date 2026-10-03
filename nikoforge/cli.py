"""Interface en ligne de commande de NikoForge.

Codes de sortie (exploitables dans un script ou une intégration continue) :

===  ==========================================================================
0    succès
1    échec d'exécution (tâche sans résultat, ou ``doctor`` a trouvé un bloquant)
2    erreur d'usage ou de configuration (argument invalide, TOML illisible…)
3    serveur injoignable ou aucun modèle disponible
===  ==========================================================================

Le mode par défaut est le **REPL interactif** (D2 de ``docs/DECISIONS.md``) ; ``-p`` exécute
une tâche unique et rend la main. La v2 exigeait ``-i`` pour l'interactif et n'avait aucun
code de sortie exploitable (bloquant C17).
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from . import __version__
from .config import Config, ConfigError, load_config, render_toml
from .protocol import ToolCall
from .server import pick_model, probe, suggest_server_command
from .ui import NikoForgeUI

PROG = "nikoforge"

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_SERVER = 3

EPILOG = """\
exemples:
  nikoforge                                    mode interactif (défaut)
  nikoforge -p "analyse les logs de /var/log"  une tâche, puis quitter
  nikoforge doctor                             diagnostic de l'installation
  nikoforge init                               écrit la configuration (~/.config/nikoforge)
  nikoforge --print-config                     configuration effective, commentée
  nikoforge --model mon-modele --cwd ~/projet  surcharge ponctuelle

codes de sortie:
  0 succès · 1 échec d'exécution · 2 usage/configuration · 3 serveur injoignable

Aucun fichier de configuration n'est nécessaire : les valeurs par défaut visent un
llama-server sur http://127.0.0.1:8080/v1 et le modèle est découvert automatiquement.
"""


# --------------------------------------------------------------------------- #
# Analyse des arguments
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    # `argument_default=SUPPRESS` est indispensable, et non cosmétique : depuis Python 3.9,
    # argparse exécute chaque sous-commande dans un espace de noms NEUF puis recopie toutes
    # ses valeurs dans le parent — y compris ses défauts. Sans SUPPRESS,
    # `nikoforge --base-url http://ailleurs doctor` perdait `--base-url` (le sous-parser
    # réécrivait None par-dessus). Avec SUPPRESS, une option non fournie n'existe simplement
    # pas dans l'espace de noms, et les surcharges utilisent `getattr(..., None)`.
    common = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    common.add_argument(
        "-c", "--config", metavar="FICHIER", help="fichier de configuration TOML à charger"
    )
    common.add_argument(
        "--cwd", metavar="DOSSIER", help="répertoire de travail de l'agent (défaut : courant)"
    )
    common.add_argument("--base-url", metavar="URL", help="URL du serveur (finissant par /v1)")
    common.add_argument("--model", metavar="NOM", help="nom du modèle (défaut : découvert)")
    common.add_argument("--api-key", metavar="CLE", help="clé d'API envoyée au serveur")
    common.add_argument("--temperature", type=float, metavar="T", help="0.0 précis … 1.0 créatif")
    common.add_argument("--max-tokens", type=int, metavar="N", help="longueur maximale d'un tour")
    common.add_argument("--timeout", type=float, metavar="S", help="délai maximal par requête")
    common.add_argument("--context", type=int, metavar="N", help="fenêtre de contexte en tokens")
    common.add_argument(
        "--max-iterations", type=int, metavar="N", help="allers-retours maximaux par tâche"
    )

    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "NikoForge — agent de coding local, exécuté sur un serveur compatible OpenAI "
            "(llama-server)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
        parents=[common],
    )
    parser.add_argument(
        "-p", "--print", dest="prompt", metavar="PROMPT", help="exécute la tâche et quitte"
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="(déprécié, sans effet) le mode interactif est désormais le défaut",
    )
    parser.add_argument("--version", action="store_true", help="affiche la version et quitte")
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="affiche la configuration effective en TOML commenté et quitte",
    )
    parser.add_argument(
        "--print-system-prompt",
        action="store_true",
        help="affiche le prompt système envoyé au modèle et quitte",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="alias de la sous-commande `init` (assistant de configuration)",
    )
    parser.add_argument(
        "--force", action="store_true", help="avec init : écrase une configuration existante"
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="avec init : accepte les valeurs proposées, sans question",
    )
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        help="(déprécié) le test du serveur est désormais systématique",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="{doctor,init}")

    doctor = subparsers.add_parser(
        "doctor",
        help="diagnostique l'installation et affiche ce qu'il faut corriger",
        parents=[common],
    )
    doctor.set_defaults(command="doctor")

    init = subparsers.add_parser(
        "init",
        help="assistant de premier lancement : écrit la configuration",
        parents=[common],
    )
    init.add_argument("--force", action="store_true", help="écrase une configuration existante")
    init.add_argument(
        "-y", "--yes", action="store_true", help="accepte les valeurs proposées, sans question"
    )
    init.set_defaults(command="init")

    return parser


COMMANDS = ("doctor", "init")


def rewrite_legacy_prompt(argv: Sequence[str]) -> tuple[list[str], bool]:
    """Compatibilité v2 : ``nikoforge "tâche"`` vaut ``nikoforge -p "tâche"``.

    Traité **avant** ``argparse`` parce que la sous-commande et le prompt sont tous deux des
    positionnels : ``argparse`` tenterait de lire ``"dis bonjour"`` comme un nom de
    sous-commande. Seule la forme documentée de la v2 est reconnue (le prompt en premier
    argument) ; les formes mélangées utilisent ``-p``.

    Retourne ``(arguments, notice_à_afficher)``.
    """
    if argv and not argv[0].startswith("-") and argv[0] not in COMMANDS:
        return ["-p", *argv], True
    return list(argv), False


def _overrides(args: argparse.Namespace) -> dict:
    """Convertit les arguments CLI en table d'overrides pour ``config.apply_overrides``.

    Les arguments non fournis valent ``None`` et sont ignorés : un drapeau absent ne doit
    jamais écraser une valeur venue du fichier ou de l'environnement.
    """
    return {
        "llm": {
            "base_url": getattr(args, "base_url", None),
            "model": getattr(args, "model", None),
            "api_key": getattr(args, "api_key", None),
            "temperature": getattr(args, "temperature", None),
            "max_tokens": getattr(args, "max_tokens", None),
            "timeout": getattr(args, "timeout", None),
        },
        "context": {"max_tokens": getattr(args, "context", None)},
        "agent": {"max_iterations": getattr(args, "max_iterations", None)},
        "workdir": getattr(args, "cwd", None),
    }


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #


def _default_config_path() -> Path:
    from .config import user_config_path

    return user_config_path()


def _run_doctor(config: Config, stream: TextIO) -> int:
    from .doctor import render_summary_line, run_doctor

    report = run_doctor(config)
    print(render_summary_line(config, report), file=stream)
    print("─" * 68, file=stream)
    print(report.render(), file=stream)
    return report.exit_code


def _run_init(
    config: Config, *, force: bool, assume_yes: bool, stream: TextIO
) -> int:
    from .wizard import run_init

    interactive = not assume_yes and sys.stdin.isatty()
    return run_init(
        config,
        _default_config_path(),
        force=force,
        interactive=interactive,
        stream=stream,
    )


def _preflight(config: Config, stream: TextIO) -> tuple[int | None, Config]:
    """Vérifie que le serveur répond avant de lancer quoi que ce soit.

    Corrige le bloquant B2 : la v2 découvrait le serveur éteint au milieu de la première
    itération, avec pour seul message « ✗ Pas de réponse du modèle ».
    Retourne ``(code_de_sortie, config)`` ; ``code_de_sortie`` vaut ``None`` s'il faut continuer.
    """
    result = probe(config.llm.base_url)

    if not result.ok:
        print(f"✖ serveur injoignable : {config.llm.base_url} — {result.error}", file=stream)
        print(f"  {result.detail}", file=stream)
        print(file=stream)
        print("  Lancez le serveur, par exemple :", file=stream)
        for line in suggest_server_command(config.llm.base_url).splitlines():
            print(f"    {line}", file=stream)
        print(file=stream)
        print("  Diagnostic complet : nikoforge doctor", file=stream)
        return EXIT_SERVER, config

    if config.llm.model:
        if result.models and config.llm.model not in result.models:
            print(
                f"⚠ le modèle « {config.llm.model} » n'est pas annoncé par le serveur "
                f"(annoncés : {', '.join(result.models)}) — il est utilisé tel quel.",
                file=stream,
            )
        return None, config

    model, warning = pick_model(result)
    if model is None:
        print(f"✖ le serveur répond ({config.llm.base_url}) mais n'annonce aucun modèle", file=stream)
        print("  Chargez un modèle : llama-server -m /chemin/vers/modele.gguf", file=stream)
        return EXIT_SERVER, config

    if warning:
        print(f"⚠ {warning}", file=stream)

    return None, dataclasses.replace(config, llm=dataclasses.replace(config.llm, model=model))


def _print_help(stream: TextIO) -> None:
    print(
        "Commandes du mode interactif :\n"
        "  quit / exit / q   quitter\n"
        "  stats             statistiques de la session\n"
        "  clear             effacer l'écran\n"
        "  help              cette aide",
        file=stream,
    )


def _make_approver(stream: TextIO, policy) -> Callable[[ToolCall], bool]:
    """Demande confirmation avant une action qui modifie le disque ou exécute une commande.

    Corrige C9 : en v2, la question « Continuer ? (o/n/q) » était posée **après** que les
    outils aient été exécutés. Autoriser ne servait donc à rien.
    """

    def approve(call: ToolCall) -> bool:
        rendered = ", ".join(f"{key}={value!r}" for key, value in call.arguments.items())
        print(f"\n⚠  {call.name}({rendered})", file=stream)
        try:
            answer = input("   autoriser ? (o = oui, a = toujours, n = non) [o] : ")
        except (EOFError, KeyboardInterrupt):
            print(file=stream)
            return False
        answer = answer.strip().lower()
        if answer in {"a", "toujours"}:
            policy.allow_always(call.name)
            print(f"   ({call.name} sera autorisé pour le reste de la session)", file=stream)
            return True
        return answer in {"", "o", "oui", "y", "yes"}

    return approve


def _run_once(config: Config, prompt: str, stream: TextIO) -> int:
    from .agent import Agent, ApprovalPolicy

    # `-p` : la consigne a été tapée explicitement, donc elle s'exécute sans reprendre
    # confirmation à chaque écriture. Le mode interactif, lui, demande (voir _run_repl).
    agent = Agent(config, policy=ApprovalPolicy(auto_approve=True), stream=stream, echo=False)
    NikoForgeUI.print_task(prompt)

    started = time.monotonic()
    result = agent.run(prompt)
    elapsed = time.monotonic() - started

    stats = agent.get_stats()
    NikoForgeUI.print_status_bar(
        model=config.llm.model,
        current_tokens=stats["context_stats"]["estimated_tokens"],
        max_tokens=config.context.max_tokens,
        iteration=stats["iteration"],
        elapsed_time=elapsed,
    )

    if result.text:
        print(result.text, file=stream)

    NikoForgeUI.print_stats(stats)

    if result.stop_reason == "error":
        print(f"✖ {result.error}", file=stream)
        return EXIT_FAILURE
    if not result.ok:
        detail = {
            "no_response": "le modèle n'a rien produit",
            "max_iterations": (
                f"budget d'itérations épuisé ({result.iterations}) après "
                f"{result.tool_calls} appel(s) d'outil — le travail déjà effectué reste sur "
                "le disque. Augmentez --max-iterations, ou découpez la tâche"
            ),
            "cancelled": "tâche interrompue",
            "denied": "action refusée",
        }.get(result.stop_reason, result.stop_reason)
        print(f"✖ {detail}.", file=stream)
        print(f"  ({result.summary()})", file=stream)
        return EXIT_FAILURE

    NikoForgeUI.print_completion()
    return EXIT_OK


def _run_repl(config: Config, stream: TextIO, assume_yes: bool) -> int:
    from .agent import Agent, ApprovalPolicy

    if stream.isatty():
        NikoForgeUI.clear_screen()

    # Sans terminal, on ne peut pas poser la question : on l'annonce au lieu de bloquer.
    interactive_input = stream.isatty() and not assume_yes
    policy = ApprovalPolicy(auto_approve=assume_yes or not stream.isatty())
    approver = _make_approver(stream, policy) if interactive_input else None

    agent = Agent(config, policy=policy, approver=approver, stream=stream)
    NikoForgeUI.print_logo()
    NikoForgeUI.print_header(
        model=config.llm.model,
        base_url=config.llm.base_url,
        max_tokens=config.context.max_tokens,
    )
    NikoForgeUI.print_welcome()

    started = time.monotonic()
    while True:
        try:
            task = NikoForgeUI.print_prompt()
        except (EOFError, KeyboardInterrupt):
            # Correctif C17 : en v2, `Ctrl+D` ou `< /dev/null` produisait une trace Python.
            print(file=stream)
            NikoForgeUI.print_success("Au revoir !")
            return EXIT_OK

        if not task:
            continue

        lowered = task.lower()
        if lowered in {"quit", "exit", "q"}:
            NikoForgeUI.print_success("Au revoir !")
            return EXIT_OK
        if lowered == "stats":
            NikoForgeUI.print_stats(agent.get_stats())
            continue
        if lowered == "clear":
            if stream.isatty():
                NikoForgeUI.clear_screen()
            continue
        if lowered == "help":
            _print_help(stream)
            continue

        NikoForgeUI.print_task(task)
        try:
            result = agent.run(task)
        except KeyboardInterrupt:
            print("\n(tour interrompu)\n", file=stream)
            continue

        print(file=stream)
        if result.stop_reason == "error":
            print(f"✖ {result.error}", file=stream)
        elif not result.ok:
            print(f"✖ {result.summary()}", file=stream)
        else:
            print(f"✓ {result.summary()}", file=stream)

        stats = agent.get_stats()
        NikoForgeUI.print_status_bar(
            model=config.llm.model,
            current_tokens=stats["context_stats"]["estimated_tokens"],
            max_tokens=config.context.max_tokens,
            iteration=stats["iteration"],
            elapsed_time=time.monotonic() - started,
        )


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #


def main(argv: Sequence[str] | None = None, stream: TextIO | None = None) -> int:
    out = sys.stdout if stream is None else stream
    parser = build_parser()

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    raw_argv, legacy_prompt = rewrite_legacy_prompt(raw_argv)
    args = parser.parse_args(raw_argv)

    if args.version:
        print(f"{PROG} {__version__}", file=out)
        return EXIT_OK

    if args.interactive:
        print(
            "note : -i/--interactive est déprécié, le mode interactif est désormais le défaut.",
            file=sys.stderr,
        )

    if legacy_prompt:
        print(
            'note : `nikoforge "..."` est déprécié, utilisez `nikoforge -p "..."`.',
            file=sys.stderr,
        )

    try:
        config = load_config(getattr(args, "config", None), _overrides(args))
    except ConfigError as exc:
        print(f"✖ configuration : {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.command == "doctor":
        return _run_doctor(config, out)

    if args.command == "init" or args.init:
        return _run_init(config, force=args.force, assume_yes=args.yes, stream=out)

    if args.print_config:
        print(render_toml(config), end="", file=out)
        return EXIT_OK

    if args.print_system_prompt:
        from .prompt import get_system_prompt

        print(get_system_prompt(), file=out)
        return EXIT_OK

    exit_code, config = _preflight(config, out)
    if exit_code is not None:
        return exit_code

    if args.prompt:
        return _run_once(config, args.prompt, out)

    return _run_repl(config, out, assume_yes=bool(getattr(args, "yes", False)))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
