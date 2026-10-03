"""Point d'entrée ``python -m nikoforge``.

Équivalent de la commande ``nikoforge`` installée par ``console_scripts``.
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
