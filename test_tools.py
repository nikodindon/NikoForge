#!/usr/bin/env python3
"""
Test simple des outils NikoForge sans passer par le LLM
"""

import sys
sys.path.insert(0, '.')

from core.tools import Tools, format_tool_result

def main():
    print("🔥 Test des outils NikoForge\n")

    tools = Tools(base_dir=".")

    # Test 1: list_files
    print("1. Test list_files:")
    result = tools.list_files(".")
    print(format_tool_result(result))
    print()

    # Test 2: read_file
    print("2. Test read_file (hello.py):")
    result = tools.read_file("hello.py")
    print(format_tool_result(result))
    print()

    # Test 3: write_file
    print("3. Test write_file (test.txt):")
    result = tools.write_file("test.txt", "Contenu de test\nLigne 2\nLigne 3")
    print(format_tool_result(result))
    print()

    # Test 4: read_file (vérifier le fichier créé)
    print("4. Test read_file (test.txt):")
    result = tools.read_file("test.txt")
    print(format_tool_result(result))
    print()

    # Test 5: bash
    print("5. Test bash (ls -la):")
    result = tools.bash("ls -la")
    print(format_tool_result(result))
    print()

    # Test 6: edit_file
    print("6. Test edit_file (modifier test.txt):")
    result = tools.edit_file("test.txt", "Ligne 2", "Ligne modifiée")
    print(format_tool_result(result))
    print()

    # Test 7: Vérifier l'édition
    print("7. Vérifier l'édition (test.txt):")
    result = tools.read_file("test.txt")
    print(format_tool_result(result))
    print()

    print("✓ Tous les tests terminés !")

if __name__ == "__main__":
    main()