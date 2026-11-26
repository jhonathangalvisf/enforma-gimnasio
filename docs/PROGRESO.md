# Progreso

## Fase 1 — Acceso, roles, auditoría y configuración ✅ (26/11/2026)

### Qué se hizo
- **Servicios** (`servicios/`), únicos que tocan la base:
  - `permisos.py`: la tabla de la sección 2 como lista de permisos por rol; `exigir()` en cada servicio.
  - `sesion.py`: login con argon2 (rehash automático si cambian los parámetros), bloqueo temporal tras N intentos, cierre de sesión, cambio de contraseña propia y `ControlInactividad`.
  - `usuarios.py`: primer administrador, crear, editar, desactivar/activar y restablecer contraseña. Sin método para borrar.
  - `auditoria.py`: registro (con el mismo commit de la acción) y visor con filtros por fechas de Bogotá, usuario, acción y texto.
  - `configuracion.py`: parámetros tipados con validación (por vencer, asistencia duplicada, inactividad, intentos, minutos de bloqueo, datos del gimnasio, prefijo y consecutivo de recibos) y logo para recibos.
  - `contenedor.py`: arma todos los servicios sobre la misma fábrica de sesiones.
- **Migración `0002`**: columna `usuarios.debe_cambiar_clave`.
- **Interfaz** (`ui/`): login (solo teclado: Enter pasa a la contraseña y Enter entra), primer arranque que pide crear el administrador, cambio obligatorio de contraseña temporal, ventana principal con barra lateral, búsqueda global con Ctrl+K (sin datos aún), usuario actual y cierre de sesión; Configuración con pestañas Parámetros, Usuarios y Auditoría. Los módulos de fases futuras muestran "se construye en la Fase N".
- `python -m gimnasio.app` ahora abre la interfaz; `--solo-migrar` solo prepara la base.
- 83 pruebas pytest (54 nuevas): permisos por rol, bloqueo y desbloqueo, inactividad, usuarios que no se borran, último administrador, auditoría sin contraseñas, configuración y pantallas en modo offscreen.

### Decisiones
- **Bloqueo:** 5 intentos y 15 minutos (los dos configurables). Durante el bloqueo ni la clave correcta entra. El mensaje para usuario inexistente o clave mala es el mismo, y se verifica contra un hash de relleno para no delatar qué usuarios existen.
- **Contraseñas:** mínimo 8 caracteres, sin otras reglas. Los usuarios creados por el admin y las claves restablecidas obligan a cambiarla al entrar.
- **Siempre queda un administrador activo:** nadie puede desactivarse a sí mismo ni quitarse el rol de admin, y no se puede desactivar ni degradar al último admin activo.
- **Permisos contra la base:** cada operación de administración relee al usuario; si lo desactivaron o le cambiaron el rol con la sesión abierta, se rechaza de inmediato.
- **Inactividad:** cuenta teclas, clics y rueda del ratón. En Recepción nunca cierra la sesión (RF-A2). El tiempo nuevo aplica desde el siguiente inicio de sesión.
- **Consecutivo de recibos:** solo puede aumentar desde Configuración, para no repetir números.
- **Lectura de configuración:** cualquier usuario con sesión puede leer parámetros (Recepción necesita el umbral de "por vencer"); solo el admin los cambia y queda en auditoría con valor anterior y nuevo.
- El logo se copia a la carpeta de datos (`%APPDATA%\Enforma\logo.png`), PNG o JPG de máximo 2 MB.

### Pendientes / para fases siguientes
- Pregunta abierta 7 (cuántos usuarios de recepción y turnos): se asumió un usuario por persona; se crean desde Configuración → Usuarios.
- Tamaño de letra ajustable (sección 6, accesibilidad): se agrega junto con Recepción en la Fase 4.
- La búsqueda global (Ctrl+K) se conecta a clientes en la Fase 2.

## Fase 0 — Base del proyecto ✅ (26/11/2026)

### Qué se hizo
- Estructura `src/gimnasio/` (db, modelos, servicios, ui, reportes, backup, ayuda, recursos), `scripts/`, `tests/`, `migraciones/`.
- `requirements.in` (dependencias directas) y `requirements.txt` con versiones fijas resueltas para Windows + Python 3.12.
- `config.py`: datos en `%APPDATA%\Enforma` (fuera de la carpeta de instalación); se puede cambiar con `ENFORMA_DATOS` o `ENFORMA_DB_URL`.
- Motor SQLite con `journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL` y `busy_timeout` en cada conexión.
- Los 16 modelos de la sección 5 con CHECK, claves foráneas, todos los índices obligatorios y los índices únicos parciales `uq_casillero_activo` y `uq_cliente_casillero_activo`.
- Alembic configurado (modo batch para SQLite) y migración inicial `0001_esquema_inicial`.
- `scripts/seed_datos.py`: 12.000 clientes falsos (Faker es_CO) con contactos, planes, membresías, pagos (incluye abonos y anulados), casilleros con historial, asistencias de 90 días (incluye eliminadas con motivo), invitados con visitas y alertas.
- 29 pruebas pytest: reglas de casilleros (ORM y SQL directo), esquema vs modelos, índices, pragmas, restricciones, UTC y coherencia del seed.

### Resultados medidos (base con 12.000 clientes)
- Seed completo: ~10 s (≈ 12.000 clientes, 95.000 membresías, 100.000 pagos, 230.000 asistencias).
- Consultas directas: código, documento y teléfono < 0,1 ms; apellido por prefijo ~1,4 ms; nombre "contiene" ~2,8 ms. La medición formal con la búsqueda real va en la Fase 2.

### Decisiones
- **Código del cliente = identificador único** (confirmado por el dueño): 6 dígitos con ceros a la izquierda, protegido además con un CHECK en la base.
- Restricciones extra en la base (además de la sección 5): referencia obligatoria en tarjeta/transferencia, motivo obligatorio al anular pagos o eliminar asistencias, montos > 0, `fecha_fin >= fecha_inicio`, liberación de casillero no anterior a la asignación.
- Montos en pesos enteros (COP sin decimales). Fechas-hora con el tipo `FechaHoraUTC`: rechaza fechas sin zona horaria y guarda en UTC. `asistencias.fecha` es el día local de Bogotá.
- La vigencia no se guarda en ninguna tabla.
- Se agregaron `ix_alertas_cliente_id_activa`, `ix_invitado_asistencias_fecha` y `ix_casillero_asignaciones_fecha_asignacion` para Recepción y reportes por día.
- Se usa `PySide6-Essentials` en lugar de `PySide6` completo (evita WebEngine, el instalador queda más liviano). Si luego se necesitan gráficas (QtCharts) se agrega `PySide6-Addons`.
- Usuarios del seed: `admin`, `recepcion1`, `recepcion2` con clave de prueba `Enforma2026!` (solo bases de prueba).

### Pendientes / para fases siguientes
- Fase 1: login, roles, auditoría, configuración y ventana principal.
- Fase 11: con PyInstaller, la ruta de `alembic.ini` y `migraciones/` debe empaquetarse junto al ejecutable (`db/migraciones.py` hoy la busca en la raíz del proyecto).
- Preguntas abiertas de la sección 13: se resuelven en sus fases.
