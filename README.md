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
```
