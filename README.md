# Enforma — Sistema de gestión del gimnasio

Aplicación de escritorio para Windows (un solo PC, sin nube) para clientes, membresías, pagos, asistencia, casilleros e invitados.

- Requisitos: `docs/ESPECIFICACION.md`
- Plan por fases: `docs/PLAN_Y_PROMPTS.md`
- Avance: `docs/PROGRESO.md`

## Puesta en marcha (Windows)
```
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
alembic upgrade head
pytest -q
python scripts/seed_datos.py --db datos_prueba.db
python -m gimnasio.app
```

La primera vez que se abre con una base vacía pide crear el administrador. Para probar con la base de datos falsa: `set ENFORMA_DB_URL=sqlite:///datos_prueba.db` antes de `python -m gimnasio.app` (usuarios `admin`, `recepcion1`, `recepcion2`, clave `Enforma2026!`).
