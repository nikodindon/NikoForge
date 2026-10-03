"""Prompt système.

La liste des outils est **générée** depuis ``protocol.TOOL_SPECS`` : en v2, le prompt et le
routeur étaient écrits séparément et avaient divergé — le prompt annonçait ``read_file(path)``
pendant que le routeur acceptait silencieusement ``read_file(raw=...)`` (bug C15a). Une seule
source de vérité, donc plus de dérive possible.

Le format textuel reste documenté : c'est le protocole de repli pour les serveurs qui
n'implémentent pas le champ ``tools`` de l'API OpenAI (``docs/DECISIONS.md``, D1).
"""

from __future__ import annotations

from pathlib import Path

from .protocol import TOOL_CALLS_CLOSE, TOOL_CALLS_OPEN, render_tools_for_prompt

_BODY = """Tu es NikoForge, un expert coding assistant puissant et autonome.

Tu aides l'utilisateur à créer, modifier et exécuter des projets en utilisant tes outils.

## Outils disponibles
{tools}

## Règles importantes
- Explore toujours l'environnement en premier (list_files, read_file, lecture des erreurs).
- Lis un fichier avant de le modifier.
- Fais des changements petits et progressifs.
- Teste ton code avec bash quand c'est pertinent, et corrige ce qui échoue.
- Sois concis dans tes explications.

## Appeler les outils

Si le serveur accepte les appels d'outils natifs, ils te sont fournis séparément : utilise-les
directement. Sinon, écris les appels dans ton message, avec exactement ce format :

{tool_calls_open}
<tool name="write_file">
<param name="path">test.py</param>
<param name="content">print("Hello")</param>
</tool>
{tool_calls_close}

Tu peux appeler plusieurs outils dans un même bloc. Le contenu d'un paramètre qui contient des
caractères spéciaux, des retours à la ligne, ou les balises ci-dessus doit être entouré de
`<![CDATA[` et `]]>` : rien n'est interprété à l'intérieur.

Répertoire de travail : {cwd}
"""


def get_system_prompt(cwd: str | Path | None = None) -> str:
    """Prompt système complet, avec la liste d'outils réellement disponible.

    En v2, ``{cwd}`` était écrit dans le prompt mais jamais remplacé : le modèle lisait
    littéralement « Current working directory: {cwd} ».
    """
    return _BODY.format(
        tools=render_tools_for_prompt(),
        tool_calls_open=TOOL_CALLS_OPEN + ">",
        tool_calls_close=TOOL_CALLS_CLOSE,
        cwd=Path(cwd) if cwd else Path.cwd(),
    )
