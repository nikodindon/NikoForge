# AGENTS.md — NikoForge v3 (dev)

Format d'appel d'outils : XML natif (détecté sur `/props` → `chat_template_caps.supports_tools`), ou repli textuel CDATA (`<tool>`, `<param>`, `<![CDATA[...]]>`). `protocol.py` (machine à états) fait le décodage ; `prompt.py` est engendré depuis `protocol.py`.

Répertoire : `skills/` (chargé par l'agent, non utilisé par la CLI). `python-development.md` est le skill de développement Python.

Workflow : tache → itérations (budget, approbation implicite avant exécution) → rendu (`model`, `user`) → résultat `role="tool"`. C18 corrigé.

Voir `docs/DECISIONS.md` (D1/D2/D3), `ROADMAP.md` (phases), `tests/test_agent_loop.py` (tests natifs).
