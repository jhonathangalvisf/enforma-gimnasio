# Sistema de gestión del gimnasio Enforma (app de escritorio, Windows)

Antes de programar cualquier módulo, lee `docs/ESPECIFICACION.md` (requisitos, reglas de negocio y modelo de datos) y `docs/PROGRESO.md` (qué fases están terminadas). El plan por fases está en `docs/PLAN_Y_PROMPTS.md`.

## Stack
- Python 3.12, PySide6 (Qt), SQLAlchemy 2, Alembic, SQLite (modo WAL, foreign_keys=ON)
- argon2-cffi (contraseñas), cryptography (backups cifrados), openpyxl (Excel), reportlab (PDF), qrcode (carnets)
- Pruebas: pytest. Empaquetado: PyInstaller + Inno Setup.

## Estructura
```
src/gimnasio/
  app.py          # arranque
  config.py       # rutas y parámetros
  db/             # engine, sesión, migraciones (Alembic en /migraciones)
  modelos/        # tablas SQLAlchemy
  servicios/      # lógica de negocio y permisos (único lugar que toca la BD)
  ui/             # pantallas PySide6 (nunca acceden directo a la BD)
  reportes/       # consultas y exportación Excel/PDF
  backup/         # backups cifrados y restauración
  ayuda/          # contenido de ayuda en Markdown, un archivo por módulo
  recursos/       # iconos, sonidos, estilos
scripts/          # seed_datos.py (12.000 clientes falsos), verificar_backup.py
tests/
docs/
```

## Reglas obligatorias
- Todo el texto visible y los comentarios en **español**. Nombres de código claros y consistentes.
- La UI llama a `servicios/`; los servicios validan **permisos por rol** y registran **auditoría**. Nunca confiar solo en ocultar botones.
- **Clientes, usuarios, pagos y membresías no se borran**: se inactivan o se anulan con motivo. Las asistencias se eliminan de forma lógica con motivo.
- **Casilleros:** un cliente ↔ un casillero activo. Debe estar reforzado con índices únicos parciales en la BD y probado con tests.
- La vigencia del cliente (vigente / por vencer / vencida / sin membresía) **se calcula**, nunca se guarda. El estado activo/inactivo es independiente.
- Cada cambio de tablas lleva una **migración Alembic**. No modificar tablas a mano.
- Fechas guardadas en UTC y mostradas en America/Bogota, formato `dd/mm/aaaa`. Moneda COP sin decimales.
- Las contraseñas con argon2. Ningún dato real de clientes en el repositorio ni en los logs. Los backups siempre cifrados.
- Cada servicio nuevo viene con pruebas pytest (pagos, vencimientos, asistencia, casilleros, invitados, permisos, backups).
- La pantalla de Recepción debe funcionar solo con teclado: campo de código siempre enfocado; un lector USB escribe el código y presiona Enter.
- Rendimiento: búsquedas < 200 ms con 12.000 clientes; verificarlo con `scripts/seed_datos.py`.
- La huella dactilar se hace al final y detrás de la interfaz `LectorHuella`; no se acopla el sistema a un proveedor.

## Forma de trabajar
1. Para cada fase, primero propón un plan breve y espera mi aprobación.
2. Implementa, ejecuta las pruebas y arregla lo que falle.
3. Al terminar, actualiza `docs/PROGRESO.md` (qué se hizo, decisiones, pendientes) y haz un commit con un mensaje claro.
4. Si algo de la especificación es ambiguo (ver sección 13 de `docs/ESPECIFICACION.md`), pregúntame en lugar de suponer.

## Comandos (actualizar cuando existan)
- Entorno: `py -3.12 -m venv .venv` y `.venv\Scripts\activate`
- Instalar: `pip install -r requirements.txt` y luego `pip install -e .` (registra el paquete `gimnasio`)
- Ejecutar: `python -m gimnasio.app` (actualiza la base y abre la interfaz; `--solo-migrar` solo prepara la base)
- Pruebas: `pytest -q` (las de pantallas usan Qt en modo offscreen; en Linux sin pantalla: `QT_QPA_PLATFORM=offscreen pytest -q`)
- Migraciones: `alembic upgrade head`
- Datos de prueba: `python scripts/seed_datos.py --db datos_prueba.db` (sin `--db` usa la base configurada en `%APPDATA%\Enforma`)
- Nueva migración: `alembic revision --autogenerate -m "descripcion"` y revisar el archivo generado
- Regenerar requirements.txt: `uv pip compile requirements.in --python-platform windows --python-version 3.12 -o requirements.txt`
