"""Permite `python -m gimnasio` y es el punto de entrada del ejecutable (PyInstaller)."""

import sys

from gimnasio.app import main

if __name__ == "__main__":
    sys.exit(main())
