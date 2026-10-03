"""Le parsing des appels d'outils, **tel qu'implémenté en v2**.

ATTENTION : ce module capture le comportement fautif de l'extraction par expression
régulière (``Agent._extract_tool_calls``). Les tests marqués ``known_issue`` affirment
aujourd'hui la mauvaise réponse ; ils seront inversés en phase 3, quand ``protocol.py``
prendra le relais avec une machine à états et un encodage CDATA.

Voir docs/REFONTE.md, bug C1 et ses trois sous-défauts.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("agent")


def one(content: str) -> dict:
    return {"name": "write_file", "params": {"path": "a.py", "content": content}}


# --------------------------------------------------------------------------- #
# Comportement à préserver : ces tests doivent rester verts après la refonte.
# --------------------------------------------------------------------------- #


def test_single_tool_call_is_parsed(agent):
    response = """
Je crée le fichier.

<tool_calls>
<tool name="write_file">
<param name="path">a.py</param>
<param name="content">print("hi")</param>
</tool>
</tool_calls>
"""
    assert agent._extract_tool_calls(response) == [one('print("hi")')]


def test_several_tools_in_one_block_are_all_parsed(agent):
    response = """
<tool_calls>
<tool name="read_file">
<param name="path">a.py</param>
</tool>
<tool name="bash">
<param name="command">pytest</param>
</tool>
</tool_calls>
"""
    calls = agent._extract_tool_calls(response)
    assert [c["name"] for c in calls] == ["read_file", "bash"]
    assert calls[0]["params"] == {"path": "a.py"}
    assert calls[1]["params"] == {"command": "pytest"}


def test_several_tool_calls_blocks_are_all_parsed(agent):
    response = """
D'abord je liste.

<tool_calls>
<tool name="list_files">
<param name="path">.</param>
</tool>
</tool_calls>

Puis je lis.

<tool_calls>
<tool name="read_file">
<param name="path">a.py</param>
</tool>
</tool_calls>
"""
    calls = agent._extract_tool_calls(response)
    assert [c["name"] for c in calls] == ["list_files", "read_file"]


def test_surrounding_prose_is_ignored(agent):
    """Le principe du format : le modèle peut réfléchir longuement avant la balise."""
    response = (
        "Réflexion " * 200
        + '\n<tool_calls>\n<tool name="list_files">\n<param name="path">.</param>\n</tool>\n</tool_calls>\n'
        + "Conclusion " * 200
    )
    assert agent._extract_tool_calls(response) == [
        {"name": "list_files", "params": {"path": "."}}
    ]


def test_no_tool_call_yields_empty_list(agent):
    assert agent._extract_tool_calls("Je n'ai besoin d'aucun outil, voici la réponse.") == []


def test_tool_without_parameters_yields_empty_params(agent):
    response = '<tool_calls>\n<tool name="list_files">\n</tool>\n</tool_calls>'
    assert agent._extract_tool_calls(response) == [{"name": "list_files", "params": {}}]


def test_multiline_parameter_preserves_inner_newlines(agent):
    content = "ligne 1\nligne 2\nligne 3"
    response = (
        "<tool_calls>\n<tool name=\"write_file\">\n"
        '<param name="path">a.txt</param>\n'
        f'<param name="content">{content}</param>\n'
        "</tool>\n</tool_calls>"
    )
    assert agent._extract_tool_calls(response)[0]["params"]["content"] == content


def test_unknown_tool_name_is_passed_through(agent):
    """Le parser ne valide pas les noms : le routage s'en charge (`_execute_tool`)."""
    response = '<tool_calls>\n<tool name="ftp_upload">\n<param name="host">x</param>\n</tool>\n</tool_calls>'
    calls = agent._extract_tool_calls(response)
    assert calls[0]["name"] == "ftp_upload"


def test_tool_outside_a_tool_calls_block_is_ignored(agent):
    """Sans la balise englobante, rien n'est exécuté : garde-fou contre les exemples en prose."""
    response = '<tool name="bash">\n<param name="command">rm -rf /</param>\n</tool>'
    assert agent._extract_tool_calls(response) == []


def test_single_quoted_attribute_is_not_recognised(agent):
    """Le motif exige des guillemets doubles. Un modèle qui utilise des quotes simples
    produit silencieusement zéro appel (comportement à préserver ou à tolérer en phase 3)."""
    response = "<tool_calls>\n<tool name='read_file'>\n<param name='path'>a.py</param>\n</tool>\n</tool_calls>"
    assert agent._extract_tool_calls(response) == []


# --------------------------------------------------------------------------- #
# known_issue : bugs reproduits. À INVERSER en phase 3.
# --------------------------------------------------------------------------- #


@pytest.mark.known_issue
def test_nested_closing_tag_truncates_the_written_file(agent):
    """Bug C1a — le contenu est coupé au premier `</tool>` imbriqué.

    Conséquence réelle : écrire un fichier HTML, du SVG, ou simplement un Markdown qui
    documente le format d'outil produit un fichier tronqué, et `write_file` répond
    « ✓ Fichier écrit ». La perte est silencieuse.
    """
    content = 'AVANT\n<tool name="x">\n<param name="y">Z</param>\n</tool>\nAPRES'
    response = (
        '<tool_calls>\n<tool name="write_file">\n'
        '<param name="path">d.md</param>\n'
        f'<param name="content">{content}</param>\n'
        "</tool>\n</tool_calls>"
    )
    parsed = agent._extract_tool_calls(response)[0]["params"]["content"]

    assert "APRES" not in parsed, "BUG C1a : le contenu ne devrait PAS être tronqué"
    assert parsed == 'AVANT\n<tool name="x">\n<param name="y">Z', "comportement fautif de la v2"
    assert parsed != content


@pytest.mark.known_issue
def test_leading_whitespace_of_content_is_stripped(agent):
    """Bug C1b — `.strip()` est appliqué à *tous* les paramètres, y compris `content`.

    Un modèle qui indente correctement son code en début de valeur produit un fichier qui
    ne compile pas (`IndentationError` en Python), sans le moindre avertissement.
    """
    response = (
        '<tool_calls>\n<tool name="write_file">\n'
        '<param name="path">code.py</param>\n'
        '<param name="content">    indentation = True\n'
        "    return indentation\n"
        "</param>\n</tool>\n</tool_calls>"
    )
    parsed = agent._extract_tool_calls(response)[0]["params"]["content"]

    assert parsed == "indentation = True\n    return indentation", "comportement fautif de la v2"
    assert parsed.startswith("indentation"), "BUG C1b : l'indentation de tête devrait survivre"
    assert not parsed.endswith("\n"), "BUG C1b : le saut de ligne final devrait survivre"


@pytest.mark.known_issue
def test_xml_entities_are_not_decoded(agent):
    """Bug C1c — un modèle qui échappe correctement son contenu écrit des entités littérales.

    Il fait ce qu'on lui demande (le XML l'exige) et le fichier sur disque contient
    `&lt;div&gt;` au lieu de `<div>`.
    """
    response = (
        '<tool_calls>\n<tool name="write_file">\n'
        '<param name="path">x.html</param>\n'
        '<param name="content">&lt;div&gt;&amp;nbsp;&lt;/div&gt;</param>\n'
        "</tool>\n</tool_calls>"
    )
    parsed = agent._extract_tool_calls(response)[0]["params"]["content"]

    assert parsed == "&lt;div&gt;&amp;nbsp;&lt;/div&gt;", "comportement fautif de la v2"
    assert "<div>" not in parsed, "BUG C1c : les entités devraient être décodées"
