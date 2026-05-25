#!/usr/bin/env python3
"""
Test du parser d'outils
"""

import sys
sys.path.insert(0, '.')

from core.agent import Agent

# Test du parser
agent = Agent("config.json")

# Test 1: Format JSON
print("Test 1: Format JSON")
params1 = '''{"path": "test.py", "content": "print(\\"hello\\")"}'''
result1 = agent._parse_tool_params(params1)
print(f"Input: {params1}")
print(f"Output: {result1}")
print()

# Test 2: Format key:value (comme le modèle l'envoie)
print("Test 2: Format key:value")
params2 = """path: index.html
content: <!DOCTYPE html>
<html>
<body>
  <h1>Hello</h1>
</body>
</html>
"""
result2 = agent._parse_tool_params(params2)
print(f"Input (truncated):")
print(params2[:100] + "...")
print(f"Output:")
for k, v in result2.items():
    print(f"  {k}: {v[:50] if len(v) > 50 else v}...")
print()

# Test 3: Format simple
print("Test 3: Format simple")
params3 = "path: test.txt"
result3 = agent._parse_tool_params(params3)
print(f"Input: {params3}")
print(f"Output: {result3}")
print()

print("✓ Tous les tests du parser terminés !")