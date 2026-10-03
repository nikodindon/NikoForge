# Protocole d'appel d'outils natif (NikoForge v3)

Regle : le serveur `llama-server` annonce parfois `capabilities: ["completion"]` (faux) tout en acceptant parfaitement `tools` natif. Toujours verifier :
1. `GET /v1/props` -> `chat_template_caps.supports_tools`
2. `GET /v1/models` -> `capabilities`
3. Un vrai appel (`doctor` ou E2E) confirme le mode.

Repli : texte XML avec `<![CDATA[...]]>`. Parser machine a etat (`protocol.py`) ; regex v2 supprimee (bug C1).
