"""Punto de arranque: python -m gimnasio.app

En la Fase 0 solo prepara la base de datos. La ventana principal llega en la Fase 1.
"""

from __future__ import annotations

from gimnasio.config import ruta_base_datos
from gimnasio.db.migraciones import actualizar_esquema


def main() -> None:
    actualizar_esquema()
    print(f"Base de datos lista en {ruta_base_datos()}")
    print("La interfaz gráfica se construye en la Fase 1.")


if __name__ == "__main__":
    main()
