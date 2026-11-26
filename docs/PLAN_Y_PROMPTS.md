# Plan por fases y prompts para Claude Code

## 0. Preparación (una sola vez)

1. Instala **Python 3.12** (marca "Add to PATH") y **Git for Windows**.
2. Crea la carpeta del proyecto, por ejemplo `C:\proyectos\gimnasio`, y dentro la subcarpeta `docs`.
3. Copia los archivos así:
   - `CLAUDE.md` → en la raíz de `gimnasio`
   - `ESPECIFICACION.md` y `PLAN_Y_PROMPTS.md` → en `gimnasio\docs`
4. Abre una terminal en la carpeta y ejecuta `git init`.
5. En la app de escritorio de Claude Code abre **esa carpeta** como proyecto. Claude Code leerá `CLAUDE.md` automáticamente en cada sesión.
6. Usa Visual Studio Code (con la extensión de Python) o Visual Studio como editor para revisar el código.

> Si prefieres C# / .NET (WPF) en Visual Studio en lugar de Python, dímelo antes de empezar: la especificación sirve igual, solo cambia la sección de tecnología y el `CLAUDE.md`.

## 1. Cómo trabajar cada fase

- **Una sesión por fase.** Al terminar y hacer commit, abre una sesión nueva para la siguiente.
- Empieza cada fase pidiendo un **plan** y aprobándolo. Luego pide implementar.
- Al cerrar cada fase: ejecuta las pruebas, **abre la aplicación y pruébala tú**, haz commit y verifica que `docs/PROGRESO.md` quedó actualizado.
- Si algo no te convence, corrígelo en esa misma fase antes de avanzar.
- No cambies la especificación a mitad de fase sin actualizar `docs/ESPECIFICACION.md`.

## 2. Fases y prompts

Cada prompt asume que Claude ya leyó `CLAUDE.md`.

### Fase 0 — Base del proyecto
> Lee `CLAUDE.md` y `docs/ESPECIFICACION.md`. Propón un plan y, cuando lo apruebe, crea la estructura de carpetas, el entorno virtual, `requirements.txt`, la configuración de Alembic, **todos los modelos SQLAlchemy de la sección 5** con sus restricciones e índices (incluidos los índices únicos parciales de casilleros), la migración inicial y `scripts/seed_datos.py` que genere 12.000 clientes falsos en español de Colombia con contactos, membresías, pagos, asistencias, casilleros e invitados. Agrega pruebas que demuestren que un cliente no puede tener dos casilleros activos y un casillero no puede tener dos clientes activos. Crea `docs/PROGRESO.md`.

**Listo cuando:** `pytest` pasa, la base se crea con `alembic upgrade head` y el seed carga en pocos minutos.

### Fase 1 — Acceso, roles, auditoría y configuración
> Implementa el login, los roles admin y recepción, bloqueo por intentos fallidos, cierre por inactividad, gestión de usuarios, auditoría y el módulo de configuración (sección 3.1 y 3.10). Crea la ventana principal con la barra de navegación lateral y búsqueda global (aún sin datos), con estilo empresarial sobrio. Pruebas de permisos por rol.

### Fase 2 — Clientes
> Implementa el módulo de Clientes (sección 3.2): registrar, consultar con pestañas, modificar, activar/inactivar (solo admin, pidiendo liberar casillero si lo tiene), múltiples contactos, y listas con búsquedas y filtros. Búsqueda instantánea con tabla fluida para 12.000 filas. Exportar a Excel. Mide y reporta los tiempos de búsqueda con el seed.

### Fase 3 — Planes, membresías y pagos
> Implementa planes, membresías (con la regla RN-03 y RN-04) y pagos en efectivo, tarjeta y transferencia (sección 3.3), recibo en PDF con consecutivo, anulación de pagos (solo admin, con motivo), renovación rápida y cierre de caja diario. Pruebas del cálculo de vencimientos y de saldos.

### Fase 4 — Recepción y asistencia
> Implementa la pantalla de Recepción (sección 3.4) con tarjeta verde, amarilla y roja, sonido de alerta, ingreso autorizado con contraseña de admin, alertas manuales y cumpleaños; y el módulo de Asistencia (sección 3.5): registro, consultas, eliminación lógica con motivo y reportes que incluyan el casillero. Debe funcionar solo con teclado y con un lector USB simulado.

### Fase 5 — Casilleros
> Implementa el módulo de Casilleros (sección 3.6): catálogo, asignar, consultar de quién es, liberar, historial, y las listas por sexo, por día y de clientes vencidos. Integra el casillero en Recepción, en la ficha del cliente y en la instantánea de asistencia (RN-11). Antes de empezar, pregúntame lo que sigue ambiguo de la sección 13 sobre casilleros.

### Fase 6 — Invitados
> Implementa el módulo de Invitados (sección 3.7): registro, reutilización por documento, registro de asistencia, conteo de visitas, lista con total de visitas y reportes. Pregúntame antes por límites y cobro de invitados.

### Fase 7 — Reportes
> Implementa el módulo de Reportes (sección 3.8) con filtros, vista previa, exportación a Excel y PDF e impresión. Respeta los permisos de recepción vs administrador.

### Fase 8 — Ayuda integrada y carnet con QR
> Implementa el módulo de Ayuda (sección 3.9) con un archivo Markdown por módulo, buscador y ayuda contextual con F1. Redacta el contenido de cada módulo en lenguaje sencillo (te pasaré los textos de la ayuda del software actual como base). Implementa la impresión del carnet con foto, nombre, código y QR (qrcode), y el soporte de QR en Recepción.

### Fase 9 — Backups y restauración
> Implementa los backups de la sección 8: API de backup de SQLite, verificación de integridad, compresión y cifrado con contraseña, destino configurable, ejecución automática al cerrar y a la hora diaria, rotación 7/4/12, alertas si falta backup, restauración desde la interfaz con copia de seguridad previa, y `scripts/verificar_backup.py`. Pruebas de ida y vuelta (crear, cifrar, restaurar, comparar).

### Fase 10 — Migración desde el software actual
> Construye el importador de la sección 10 con vista previa, mapeo de columnas, detección de duplicados, reporte de errores y modo de prueba. Te entregaré los archivos exportados del software actual. Impórtalos primero en una base de prueba y muéstrame el reporte.

> **Adelanta esta fase** si ya tienes las exportaciones: así pruebas el sistema con tus datos reales (en una copia) desde antes.

### Fase 11 — Instalador y puesta en marcha
> Prepara el empaquetado con PyInstaller y el instalador con Inno Setup, datos de la aplicación fuera de la carpeta de instalación, instancia única, ícono y accesos directos, y un manual breve de instalación y de respaldo. Revisa los criterios de aceptación de la sección 12 uno por uno y reporta cuáles pasan.

**Puesta en marcha recomendada:** instalar en el PC del gimnasio, importar los datos, usar el sistema nuevo **en paralelo** con el actual 1 a 2 semanas, comparar resultados y recién entonces dejar el actual.

### Fase 12 (opcional) — Huella dactilar
> Diseña la interfaz `LectorHuella` y una implementación para el lector que compré (modelo: ____). Agrega el enrolamiento en la ficha del cliente con registro de la autorización, la identificación en Recepción como alternativa al código y las pruebas con un lector simulado. Si el SDK no es compatible con Python, propón un puente en .NET.

## 3. Antes de comprar el lector de huella

Antes de comprarlo, verifica: que tenga SDK para Windows 10/11, ejemplos en Python o .NET, que permita guardar y comparar plantillas en tu propia base (no solo dentro del dispositivo) y que la licencia no cobre por cliente.

## 4. Lista de verificación del dueño al final

- [ ] Probé el ingreso con códigos vigentes, por vencer, vencidos e inactivos.
- [ ] Probé asignar casilleros y confirmé que no permite duplicados.
- [ ] Registré invitados y comprobé el conteo de visitas.
- [ ] Hice un backup, lo restauré en otra carpeta y funcionó.
- [ ] Guardé la contraseña de los backups en un lugar seguro.
- [ ] Tengo una copia semanal fuera del local.
- [ ] Los datos importados coinciden con el software anterior.
- [ ] Mis empleados saben usar Recepción y la Ayuda.
