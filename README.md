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

## Instalador para Windows

- **Sin instalar nada:** cada push a `main` corre el workflow **Windows** de GitHub Actions (pruebas, ejecutable, instalador, instalación de prueba). El instalador queda en la ejecución → *Artifacts* → `Enforma-Instalador-X.Y.Z`. Con una etiqueta `vX.Y.Z` se publica también como *Release*.
- **En un PC con Windows:** doble clic en `construir.bat` (necesita Python 3.12 e [Inno Setup 6](https://jrsoftware.org/isdl.php)). Deja `dist\Enforma-Instalador-X.Y.Z.exe`.
- La versión está en `src/gimnasio/__init__.py`.
- Manual para el gimnasio: `docs/MANUAL_INSTALACION.md` (va en PDF dentro del instalador).
- Revisar una instalación: `Enforma.exe --diagnostico` (acceso directo en el menú Inicio) o `python scripts/diagnostico.py`.
