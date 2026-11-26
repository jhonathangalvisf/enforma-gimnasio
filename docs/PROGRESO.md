# Progreso

## Fase 11 — Instalador y puesta en marcha ✅ (26/11/2026)

> La Fase 10 (importar datos del software actual) se saltó por ahora: el dueño todavía no tiene las exportaciones. El carnet con QR también sigue pendiente.

### Qué se hizo
- **Rutas dentro del ejecutable** (`gimnasio/rutas.py`): migraciones, ayuda, sonido, ícono y logo se buscan en la carpeta interna de PyInstaller (`sys._MEIPASS`) o en el proyecto. `db/migraciones.py` ya no lee `alembic.ini` (tiene tildes y en Windows Python lo leería con la codificación del sistema; con `LANG=C` el .exe fallaba al migrar). `alembic.ini` sigue para la línea de comandos.
- **PyInstaller** (`empaquetado/enforma.spec`): modo carpeta (arranca rápido y menos falsos positivos de antivirus), sin consola, sin UPX, ícono y propiedades del .exe con la versión. Incluye migraciones, ayuda, recursos, `tzdata`, fuentes de reportlab y los submódulos de Alembic/SQLAlchemy que las migraciones importan en tiempo de ejecución. Nuevo `gimnasio/__main__.py` como punto de entrada.
- **Instalador Inno Setup** (`empaquetado/enforma.iss`, en español): `C:\Program Files\Enforma`, accesos directos en el menú Inicio (Enforma, Manual de instalación y respaldo, Diagnóstico de Enforma, Desinstalar) y en el escritorio (opcional), pide cerrar Enforma si está abierto (`AppMutex`), al actualizar borra solo `_internal` de la versión anterior, abre Enforma al final con el usuario que instaló (no como administrador) y el desinstalador avisa que los datos no se borran. `AppId` fijo para que las versiones nuevas actualicen la misma instalación.
- **Datos fuera de la instalación:** siguen en `%APPDATA%\Enforma` (Fase 0). Instalar, actualizar o desinstalar nunca los toca (probado en el workflow).
- **Instancia única** (`ui/instancia.py`): candado `QLockFile` en la carpeta de datos + canal `QLocalServer`. Una segunda copia avisa a la abierta, que trae al frente su ventana (inicio de sesión o principal, también si estaba minimizada) y se cierra. Un candado de un programa que se cerró mal se libera solo. En Windows crea el mutex `EnformaGimnasioAplicacion` que usa el instalador.
- **Ícono y logo** a partir del logo del gimnasio que envió el dueño: `recursos/enforma.ico` (16 a 256 px, "en" con la figura en blanco sobre el azul del logo), ventana y barra de tareas (con `AppUserModelID` propio). `recursos/logo_enforma.png` es el **logo por defecto de los recibos** si el admin nunca eligió otro; si lo quita, no hay logo.
- **Versión 1.0.0** en `gimnasio/__init__.py` (única fuente: `pyproject.toml` la lee de ahí). Se ve en el inicio de sesión y en la barra de estado.
- **Registro de errores** (`gimnasio/registro.py`): `<datos>/logs/enforma.log` (1 MB × 5, rota solo) con arranque, versión, migraciones, copias y errores inesperados (tipo, mensaje recortado y archivo/línea del código, **sin variables ni datos de clientes**); `fallos.log` con `faulthandler` para caídas dentro de Qt. Un error no atrapado muestra un mensaje en lugar de cerrar el programa sin decir nada. Si la base no se puede preparar, avisa y no abre.
- **Diagnóstico** (`gimnasio/diagnostico.py`, `Enforma.exe --diagnostico`, acceso directo en el menú Inicio y `scripts/diagnostico.py`): versión, archivos del programa, zona horaria, carpeta de datos, base (integridad y esquema), **prueba real de DPAPI**, contraseña de copias guardada y protegida, y verificación de la última copia en una carpeta temporal. Guarda el informe en `logs/diagnostico.txt`. `verificar_backup.py` comparte sus funciones.
- **Prueba de humo** (`gimnasio/prueba_humo.py`, `Enforma.exe --prueba-humo`): sobre el .exe ya empaquetado y en una carpeta temporal con datos inventados, prueba migraciones, argon2, cliente + membresía + abono, ingreso en Recepción, recibo PDF, reportes Excel y PDF, copia cifrada y verificada, los 11 temas de ayuda, la ventana principal de Qt y DPAPI.
- **GitHub Actions** (`.github/workflows/windows.yml`, `windows-latest`): job de **pruebas** (toda la suite en Windows, incluidas las de DPAPI real) y job de **instalador**: manual en PDF → PyInstaller → prueba de humo del .exe → Inno Setup → instala en silencio → revisa archivos y accesos directos → `--solo-migrar`, `--diagnostico` (exige "Protección DPAPI: funciona") y prueba de humo del programa instalado → instancia única con la interfaz abierta → desinstala y comprueba que los datos siguen. Sube el instalador como artifact (90 días) y, con una etiqueta `vX.Y.Z`, lo publica como Release.
- **`construir.bat`**: lo mismo en el PC del dueño con doble clic (crea `.venv`, instala, manual, PyInstaller, prueba de humo, Inno Setup si está instalado).
- **Manual de instalación y respaldo** (`docs/MANUAL_INSTALACION.md`, va en PDF dentro del instalador con `empaquetado/manual_pdf.py`): requisitos, instalar (aviso de SmartScreen), primer arranque, copias de seguridad, diagnóstico y **pasos para verificar DPAPI en el PC del gimnasio**, verificar y restaurar, cambio de computador, actualizar, desinstalar, dónde están los datos, problemas frecuentes, prueba en Windows Sandbox y puesta en marcha en paralelo.
- Ayuda: el tema Copias de seguridad menciona el Diagnóstico.
- `tests/test_dpapi_windows.py` (6 pruebas, solo Windows): proteger/recuperar, archivo sin la clave en claro, archivo alterado, entropía propia de Enforma, diagnóstico y servicio de copias con DPAPI. `tests/test_instalacion.py` (24 pruebas): rutas en desarrollo y empaquetado, versión, contenido del spec, del .iss y del workflow, registro de errores sin variables locales, instancia única (dos copias, carpetas distintas, candado abandonado), traer al frente, versión visible, logo por defecto, diagnóstico (instalación nueva, base, última copia buena y dañada, clave ilegible, archivos faltantes), `main --diagnostico` y `--solo-migrar`, y el manual en PDF. **448 pruebas pasan en Linux** (+6 de DPAPI que solo corren en Windows).

### Verificado en Linux (el .exe de Windows lo construye el workflow)
- El mismo spec empaquetado para Linux: `--solo-migrar`, `--diagnostico` y `--prueba-humo` pasan **sin Python del sistema y con `LANG=C`** (así apareció el problema de `alembic.ini`); con la interfaz abierta, una segunda copia se cierra en 0,9 s y la primera queda registrada como "ya estaba abierto".

### Primera corrida en Windows (GitHub Actions)
- **Instalador:** todo en verde: PyInstaller, prueba de humo del .exe, Inno Setup, instalación silenciosa, diagnóstico con **"Protección DPAPI: funciona"**, prueba de humo del programa instalado, instancia única con la interfaz abierta y desinstalación conservando los datos.
- **Pruebas:** 451 de 455 pasaron; las 6 de DPAPI real pasaron. Las 4 que fallaron eran **errores reales de la Fase 9 que solo aparecen en Windows**, ya corregidos:
  - **Restaurar una copia fallaba en Windows:** la URL de la base trae `C%3A/...` y Alembic la guarda en configparser, que trata el `%` como interpolación. Ahora se escapa (`db/migraciones.py`) y hay una prueba con una URL de Windows.
  - `verificar_backup.py` dejaba abierta la base temporal (`with sqlite3.connect()` no cierra la conexión) y Windows no dejaba borrarla. Ahora usa `closing()`, igual que el diagnóstico.

### Criterios de aceptación (sección 12)
| # | Criterio | Estado | Cómo se comprueba |
|---|---|---|---|
| 1 | Búsquedas < 200 ms con 12.000 clientes | ✅ | `test_rendimiento_clientes.py` en cada ejecución (peor caso medido 52 ms) y `scripts/medir_busqueda.py` |
| 2 | Casillero duplicado falla incluso en la base | ✅ | Índices únicos parciales; `test_casilleros.py` (ORM y SQL directo) y `test_servicio_casilleros.py` |
| 3 | Tarjeta roja con sonido, amarilla ≤ 5 días con fecha, verde | ✅ | `test_asistencia.py` (verde, amarillo, rojo) y `test_ui_recepcion.py`; el sonido va en el .exe y la prueba de humo revisa que exista |
| 4 | Recepción no anula pagos ni inactiva clientes; el admin sí, auditado | ✅ | `test_pagos.py::test_anular_pago_solo_admin_con_motivo`, `test_clientes.py`, `test_permisos.py` |
| 5 | Pago anulado no suma en caja pero se ve con motivo | ✅ | `test_pagos.py::test_cierre_de_caja` |
| 6 | Reporte de asistencia con el casillero de ese día aunque se libere | ✅ | `test_asistencia.py::test_instantanea_del_casillero_no_cambia_al_liberar` |
| 7 | Invitado con el mismo documento no se duplica y su contador sube | ✅ | `test_invitados.py::test_mismo_documento_no_duplica_y_el_contador_aumenta` |
| 8 | Backup se crea, cifra, restaura en temporal y pasa `integrity_check` | ✅ | `test_backups.py::test_ida_y_vuelta_crear_cifrar_restaurar_comparar`; también la prueba de humo y el diagnóstico sobre el .exe |
| 9 | Todas las pantallas con Ayuda y F1 correcta | ✅ | `test_ui_ayuda.py` (F1 en cada módulo, en diálogos modales y en Usuarios) |
| 10 | El instalador funciona en un Windows limpio sin Python | ⏳ | El workflow instala y prueba el .exe en `windows-latest` (el .exe lleva su propio Python, no usa el del runner). La confirmación final en un Windows **realmente** limpio (Windows Sandbox o el PC del gimnasio) la hace el dueño con la sección 12 del manual |

### Decisiones
- **Datos por cuenta de Windows** (`%APPDATA%\Enforma`, recomendado en el plan, sin objeción del dueño): el PC del gimnasio debe usar siempre la misma cuenta. Así lo dice el manual.
- **Instalador sin firma digital** (recomendado en el plan, sin objeción): Windows muestra "editor desconocido"; el manual explica "Más información → Ejecutar de todas formas".
- **Instalación para todos los usuarios en Program Files** (pide administrador una vez); el programa corre como usuario normal.
- **Modo carpeta** en lugar de un solo .exe; **sin UPX**.
- **Diagnóstico en el propio .exe** en lugar de un `verificar_dpapi.py` suelto: el PC del gimnasio no tiene Python. `scripts/diagnostico.py` hace lo mismo en desarrollo.
- El logo del gimnasio queda como logo por defecto de los recibos.

### Pendientes
- **En el PC del gimnasio:** instalar, abrir el Diagnóstico y seguir "Verificar la protección de la contraseña (DPAPI)" del manual; probar en Windows Sandbox si es Windows Pro (criterio 10).
- Fase 10 (importador) cuando el dueño tenga las exportaciones; carnet con QR cuando lo pida; Fase 12 (huella) opcional.

## Fase 9 — Copias de seguridad y restauración ✅ (26/11/2026)

### Qué se hizo
- **Núcleo** (`src/gimnasio/backup/`):
  - `paquete.py`: instantánea con la API de backup de SQLite (sirve con la base en uso, incluye lo que está en el WAL), `PRAGMA integrity_check` sobre la copia, zip con la base, las fotos de los clientes, el logo y un `manifiesto.json` (versión del esquema y conteos). Recibos y reportes no van: se regeneran.
  - `cifrado.py`: formato `.enfbak` = encabezado JSON sin cifrar (fecha, tipo, revisión, parámetros de scrypt, sal y nonce; nunca datos de clientes) + zip cifrado con **AES-256-GCM**, clave derivada con **scrypt** (n=2^15, r=8, p=1). El encabezado va como datos asociados de GCM: cualquier cambio en el encabezado o en el contenido hace fallar el descifrado.
  - `rotacion.py`: 7 diarias, 4 semanales y 12 mensuales (la más reciente de cada grupo, en días de Bogotá; se cuentan días *con copia*).
  - `protector.py`: guarda la contraseña de backups protegida con **DPAPI de Windows** (ctypes, sin dependencias) en `<datos>/clave_backups.bin`, que no entra en las copias. Fuera de Windows (desarrollo/pruebas) se guarda sin protección y la pantalla lo dice.
- **`servicios/backups.py`** (`ServicioBackups`): crear copia (preparar → ejecutar → registrar, para correr la parte pesada en otro hilo sin compartir conexiones), escritura a temporal + relectura con SHA-256 + `os.replace`, copia en el PC (`<datos>/backups`) y en el disco externo/USB si está configurado y conectado (si no, queda en el PC y avisa), rotación por destino, "Copiar a otro disco" (3.ª copia, recordatorio semanal), verificar, restaurar, estado para los avisos y `toca_copia_diaria`. Todo queda en `backups_log` (una fila por destino) y en la auditoría (`backup_creado`, `backup_fallido`, `backup_restaurado`, `backup_copiado_externo`, `backup_clave_configurada/cambiada`).
- **Restaurar:** descifra y revisa en una carpeta temporal (integridad, que tenga usuarios, que la versión del esquema la conozca el programa), relee al usuario (si lo desactivaron no restaura), hace una copia **"antes de restaurar"** del estado actual (se guardan las 5 últimas), cierra el motor, reemplaza base, fotos y logo, borra `-wal`/`-shm`, corre las migraciones (una copia de una versión anterior se actualiza sola), vuelve a poner el historial de copias que no estaba en la copia y registra la restauración. La interfaz vuelve al inicio de sesión.
- **Migración `0007`:** `backups_log.tipo` acepta `seguridad`, CHECK de `resultado` (`exitoso`/`fallido`) e índice por fecha. Probada ida y vuelta (upgrade/downgrade).
- **Parámetros:** `backup_hora` (21 = 9:00 p. m., en Configuración → Parámetros → Copias de seguridad) y `backup_destino` (oculto en Parámetros; se elige desde la pantalla de copias). Nuevo campo `oculto` en `Parametro`.
- **Interfaz:**
  - Módulo **Copias de seguridad** (solo admin, `ui/backups.py`): estado (última copia buena, hora diaria, disco externo conectado o no, contraseña, última copia fuera del local), Backup ahora, Elegir/Quitar disco externo, Copiar a otro disco, Crear/Cambiar contraseña (con advertencia y casilla "la guardé en un lugar seguro"), lista de copias (PC, disco externo y "antes de restaurar") con Verificar, Restaurar y Restaurar desde un archivo, e Historial de intentos.
  - **Barra amarilla** bajo la barra superior: copia buena de más de 2 días o ninguna (todos; Recepción con "Avise al administrador"), falta contraseña, disco desconectado y recordatorio semanal (solo admin). No toma el foco: el campo de código de Recepción sigue listo. Se oculta en pantalla completa.
  - **Copia diaria** en segundo plano (`QThread`) revisada cada minuto en `Aplicacion`, también con la pantalla de inicio de sesión abierta; si falla, reintenta cada hora. **Copia al cerrar** en `app.py` con ventana de espera, sin importar quién cierre.
- `scripts/verificar_backup.py`: restaura la última copia (del PC y del disco externo configurado, o `--archivo`/`--carpeta`) en una carpeta temporal y comprueba integridad, esquema y datos; código de salida 0/1. `scripts/medir_backup.py`: mide crear, verificar y restaurar con la base de prueba.
- Ayuda: tema **Copias de seguridad** reescrito (contraseña, cuándo se hacen, 3-2-1, rotación, avisos, verificar, restaurar, cambio de PC, preguntas frecuentes); parámetro nuevo en Configuración y módulo nuevo en Primeros pasos.
- 38 pruebas nuevas (424 en total): ida y vuelta (crear, cifrar, restaurar, comparar; criterio 8 de la sección 12), clave incorrecta, archivo y encabezado alterados, PC + USB, USB desconectado, sin contraseña, permisos de Recepción, alerta de 2 días, copia diaria y reintento, rotación (unidad y con archivos), tercera copia y recordatorio, restaurar (estado, fotos, copia previa, historial, auditoría), clave incorrecta sin tocar nada, copia de versión nueva rechazada, copia de versión vieja actualizada, usuario desactivado, CHECKs de la tabla, el script de verificación y las pantallas.

### Resultados medidos (base de prueba de 59 MB: 12.000 clientes, 100.000 pagos, 231.000 asistencias)
| Operación | Tiempo |
|---|---:|
| Crear copia (instantánea + integridad + zip + cifrado + escritura verificada) | 3,3 s |
| Archivo resultante | 15,4 MB |
| Verificar copia | 1,2 s |
| Restaurar (incluye la copia previa) | 4,7 s |

### Decisiones
- **Contraseña guardada con DPAPI** (confirmado por el dueño): las copias automáticas no la piden; para restaurar siempre se escribe. Cambiarla no recifra las copias viejas (siguen con la anterior). En otro PC hay que crearla de nuevo.
- **Hora diaria 9:00 p. m.** por defecto (confirmado). Si el programa está cerrado a esa hora, cuenta la copia al cerrar.
- **Copia al cerrar sin importar quién cierre** (confirmado), también desde la pantalla de inicio de sesión. Sin contraseña queda registrada como fallida.
- **Aviso de más de 2 días para todos** (confirmado): Recepción ve "Avise al administrador"; los demás avisos solo el admin.
- Las copias "antes de restaurar" no cuentan para la alerta ni para la rotación 7/4/12; se guardan las 5 últimas en `backups/antes_de_restaurar/`.
- La copia del disco que se lleva fuera del local no se rota (el programa no la controla).
- Las copias se escriben enteras en memoria (archivo de ~15 MB con 12.000 clientes); si la base crece mucho se puede pasar a cifrado por bloques.
- Capturas en `/mnt/project-files/fase9/`.

### Pendientes / para fases siguientes
- Fase 11: probar DPAPI en el PC del gimnasio (la protección real solo existe en Windows; aquí se probó con un protector falso) e incluir el manual breve de respaldo.
- Lista del dueño (PLAN, sección 4): hacer una copia, restaurarla en otra carpeta con `verificar_backup.py`, guardar la contraseña en lugar seguro y llevar una copia semanal fuera del local.

## Fase 8 — Ayuda integrada ✅ (26/11/2026)

### Qué se hizo
- **Contenido** (`src/gimnasio/ayuda/*.md`): 11 temas redactados desde cero en lenguaje sencillo, según cómo quedó cada módulo: Primeros pasos y atajos, Recepción, Clientes, Asistencia, Casilleros, Invitados, Pagos (membresías, abonos, recibos y caja), Reportes, Configuración (parámetros, planes y auditoría), Usuarios y Copias de seguridad. Cada tema explica para qué sirve, los pasos de cada tarea, qué significan colores y avisos, qué puede hacer Recepción y qué solo el administrador, atajos y preguntas frecuentes. Los temas se enlazan entre sí con `[Texto](tema:clave)`.
- **`servicios/ayuda.py`**: catálogo de temas con el permiso que los muestra (el mismo del módulo), lectura de los Markdown (se pueden corregir sin tocar la lógica), buscador sin tildes ni mayúsculas que exige todas las palabras y ordena por relevancia (el título pesa más), fragmento de contexto y tema para F1 (si el usuario no puede ver el del módulo, abre Primeros pasos).
- **`ui/ayuda.py`**: `VisorAyuda` (temas a la izquierda, texto a la derecha, buscador que filtra la lista con el número de coincidencias y resalta las palabras en el texto, enlaces entre temas), `PantallaAyuda` (menú → Ayuda, ya no dice "próximamente") y `DialogoAyuda` (ventana aparte, no modal, que abre F1).
- **F1 contextual**: un filtro de teclado en la aplicación abre la ayuda del módulo activo, también dentro de diálogos modales (fichas, renovaciones, casilleros, usuarios…), donde se abre encima del diálogo para poder usarla. El tema se elige por el archivo de la pantalla (`TEMA_POR_ARCHIVO`) o por `TEMA_AYUDA` / `tema_ayuda()`; en Configuración, la pestaña Usuarios abre el tema Usuarios. F1 reutiliza la misma ventana. Al cerrarla en Recepción, el campo de código vuelve a quedar enfocado.
- `pyproject.toml` empaqueta `ayuda/*.md`.
- 28 pruebas nuevas (386 en total): cada tema tiene archivo y contenido, cada módulo del menú tiene tema, permisos por rol, enlaces válidos, búsqueda, F1 en cada módulo para admin y recepción (criterio 9 de la sección 12), F1 dentro de un diálogo modal, pestaña Usuarios, resaltado sin tildes y la ventana no modal.

### Decisiones
- **Sin textos del software actual** (confirmado por el dueño): la ayuda se escribió desde cero.
- **Carnet con QR y soporte QR en Recepción: quedan para después** (respuesta del dueño). Los clientes se identifican dando su código personal. El `qr_token` sigue existiendo en la base y Recepción ya lo acepta, por si se retoma.
- Recepción ve los temas de sus módulos; Configuración, Usuarios y Copias de seguridad solo el administrador.
- Usuarios tiene tema propio (RF-H1 lo nombra aparte) aunque vive dentro de Configuración.
- F1 abre una ventana aparte en lugar de cambiar de módulo, para no perder lo que se estaba haciendo (sobre todo en Recepción).
- Capturas en `/mnt/project-files/fase8/`.

### Pendientes / para fases siguientes
- Fase 9: completar el tema "Copias de seguridad" (hoy describe cómo funcionará).
- Fase 11: incluir `ayuda/*.md` en el ejecutable de PyInstaller (`ServicioAyuda` acepta otra carpeta).
- Carnet con foto y código (y QR) cuando el dueño lo pida.
- Al cambiar una pantalla en fases futuras, actualizar su archivo de ayuda.

## Fase 7 — Reportes ✅ (26/11/2026)

### Qué se hizo
- **`servicios/reportes.py`**: catálogo único de 27 reportes en 5 grupos. Cada reporte declara si Recepción puede abrirlo; el servicio lo valida (y los servicios de cada módulo mantienen sus límites de "solo hoy").
  - **Clientes:** por vencer en los próximos N días (con teléfono, saldo y casillero), vencidos (con días de vencido; N = últimos N días, 0 = todos), morosos (cada membresía con saldo, con totales), resumen mensual de nuevos, renovaciones y bajas, y el detalle de nuevos, renovaciones y bajas.
  - **Ingresos:** detalle de pagos, por día, por método, por usuario y por plan (con filtros de método, usuario, concepto y plan), pagos anulados (quién y por qué) y cierre de caja. Los anulados no suman y se indican en el encabezado.
  - **Asistencia, casilleros e invitados:** reutilizan los reportes de las Fases 4, 5 y 6 (del día, rango, cliente, franja, ranking, ausentes; lista, vencidos, sugeridos para liberar, por día; visitas, por invitado, por anfitrión).
  - Exportar a Excel y PDF queda en la auditoría (`reporte_exportado`, con reporte, formato y filas).
- **Exportación** (`reportes/exportar.py`): título, filtros y fecha de generación arriba (Excel también), fila de totales en negrita, columnas de dinero como `$ 1.234.567` (en Excel siguen siendo números), números con separador de miles. Los nombres de hoja con caracteres no permitidos se limpian.
- **Pantalla Reportes** (`ui/reportes.py`): lista por grupos a la izquierda, filtros que cambian según el reporte, periodos rápidos (este mes, mes anterior, últimos 30 días, últimos 12 meses, este año, hoy), Enter genera, vista previa con totales abajo, Excel, PDF e Imprimir (Ctrl+P, abre el PDF). La vista previa muestra hasta 2.000 filas; Excel y PDF llevan todas.
- `scripts/seed_datos.py` registra en la auditoría la inactivación de los clientes inactivos (el reporte de bajas la lee de ahí).
- `scripts/medir_reportes.py`: mide cada reporte con un mes y con un año.
- 34 pruebas nuevas (358 en total): permisos de Recepción en el servicio, límites de "solo hoy", cada reporte con datos conocidos, filtros, anulados, exportación con totales y formato de pesos, y la pantalla.

### Resultados medidos (base de prueba: 12.000 clientes, 95.000 membresías, 100.000 pagos)
| Reporte | Un mes | Un año |
|---|---:|---:|
| Clientes por vencer / vencidos / morosos | 84 / 99 / 146 ms | — |
| Nuevos, renovaciones y bajas por mes | 53 ms | 227 ms |
| Ingresos por día, método o usuario | 18 ms | ~210 ms |
| Ingresos por plan | 29 ms | 362 ms |
| Detalle de pagos (7.116 / 86.904 filas) | 177 ms | 1,8 s |
| Renovaciones detalle (6.495 / 79.186 filas) | 209 ms | 1,1 s |
| Cierre de caja | 8 ms | — |

Los reportes de un mes están en la meta de 200 ms o muy cerca. Los de un año con resumen tardan 0,2 a 0,4 s, y los de detalle con decenas de miles de filas 1 a 2 s (traer tantas filas toma ese tiempo). Los resúmenes de ingresos suman en la base y solo unen las tablas que necesitan (bajaron de ~1,1 s a ~0,2 s por año). La asistencia por rango de un año (230.000 filas, Fase 4) tarda varios segundos; la vista previa se limita para que la pantalla no se trabe.

### Decisiones
- **Bajas** (confirmado por el dueño): se cuentan por separado los clientes **inactivados** por el administrador (fecha y motivo desde la auditoría) y los clientes **activos que se vencieron y no renovaron** (mes en que terminó su última membresía). Si un cliente renueva, deja de contar como baja.
- **Renovación:** una membresía no anulada que no es la primera del cliente, contada en la fecha en que se vendió. **Nuevo:** cliente registrado en el periodo.
- **Recepción** (confirmado por el dueño) ve: asistencia de hoy, casilleros (todas las listas), visitas de invitados de hoy, su propio cierre de caja de hoy y **clientes por vencer con teléfono**. Ingresos, morosos, vencidos, movimientos de clientes y los demás, solo el administrador.
- Por vencer y vencidos solo incluyen clientes activos; morosos incluye inactivos (con la columna Estado).
- "Imprimir" genera el PDF y lo abre con el programa predeterminado de Windows, igual que en las fases anteriores.
- Sin cambios de tablas: no hay migración nueva.
- Capturas en `/mnt/project-files/fase7/`.

### Pendientes / para fases siguientes
- Fase 8 (Ayuda): texto de ayuda del módulo Reportes.
- Si se necesitan reportes anuales de detalle más rápidos, agregar un índice que cubra los pagos (requiere migración).

## Fase 6 — Invitados ✅ (26/11/2026)

### Qué se hizo
- **Migración `0006`**: `invitados.busqueda` (nombre sin tildes, se llena al guardar y para los existentes), `invitado_asistencias.eliminada_por`, `eliminada_en` y `autorizada_por` (FK a usuarios) e índice por cliente anfitrión.
- **`servicios/invitados.py`** (permisos y auditoría en el servicio):
  - Registrar invitado (nombre, documento, teléfono). El documento se normaliza (sin puntos, espacios ni guiones) y es único: si ya existe **se reutiliza el mismo registro** (completa el teléfono si faltaba). Avisa si el documento es de un cliente.
  - Corregir nombre y teléfono (Recepción); cambiar el documento solo el administrador.
  - Registrar visita (fecha/hora, usuario y, opcional, el cliente anfitrión). Si ya vino hoy se usa el mismo parámetro de Recepción (`asistencia_duplicada`: avisar y confirmar por defecto).
  - **Contador de visitas** (pedido del dueño, RN-10): nunca se guarda, se cuenta desde `invitado_asistencias` sin las eliminadas. La ficha trae total, visitas del mes, primera y última visita y el detalle de cada fecha (hora, anfitrión, quién la registró y quién autorizó).
  - Eliminar visita con motivo (lógica). Recepción solo las de hoy; el admin cualquiera y es el único que ve las eliminadas.
  - Búsqueda por nombre (sin tildes), documento o teléfono; lista con total, visitas del mes y última visita.
  - Reportes (RF-I5): visitas por rango (opcional: solo las de un cliente anfitrión), visitas por invitado (en el periodo y en total) e invitados por cliente anfitrión. Excel, PDF e impresión (auditados). Recepción solo ve las visitas de hoy.
- **Pantalla Invitados** (`ui/invitados.py`), solo con teclado: documento + Enter (si existe muestra "lleva N visitas", si es nuevo pide el nombre) → teléfono → anfitrión (código o nombre + Enter) → registra. Lista con búsqueda instantánea; doble clic abre la **ficha con el contador grande y la tabla de fechas**. Pestaña Reportes.
- Parámetro nuevo (grupo Invitados): **máximo de visitas de un invitado al mes**, 0 = sin límite (valor por defecto). Al llegar al máximo se avisa y la visita necesita usuario y contraseña de un administrador (si el admin tiene la sesión abierta, autoriza directamente); queda en la auditoría.
- `scripts/medir_invitados.py` y el seed llena `invitados.busqueda`.
- 31 pruebas nuevas (324 en total): reutilización por documento y contador que aumenta (criterio 7 de la sección 12), detalle de fechas, duplicado, límite y autorización, eliminación, permisos, reportes, exportación y pantallas.

### Resultados medidos (base de prueba con 12.000 clientes, 800 invitados y 1.830 visitas)
| Operación | Peor tiempo |
|---|---:|
| Documento + Enter (ficha con contador) | 4 ms |
| Registrar visita | 4 ms |
| Lista de invitados / búsqueda | 6 ms |
| Reporte de visitas (90 días) | 19 ms |
| Reportes por invitado y por anfitrión (90 días) | 7 ms |

### Decisiones
- **Los invitados no pagan** y **no hay límite de invitados por cliente** (respuesta del dueño, sección 13 punto 4 y RF-I6).
- El límite por persona quedó como parámetro apagado (0); quien autoriza al pasarlo es un administrador.
- El anfitrión es opcional. Un invitado no puede ser su propio anfitrión (mismo documento).
- Las visitas de invitados no cuentan en la asistencia de clientes ni en sus reportes.
- Capturas en `/mnt/project-files/fase6/`.

### Pendientes / para fases siguientes
- Fase 7 (Reportes): sumar los reportes de invitados al módulo general de reportes.
- Fase 8 (Ayuda): texto de ayuda del módulo Invitados.
- Si el dueño quiere más adelante cobrar a los invitados, se necesita permitir pagos sin cliente (hoy `pagos.cliente_id` es obligatorio).

## Fase 5 — Casilleros ✅ (26/11/2026)

### Qué se hizo
- **Migración `0005`**: `casillero_asignaciones.fecha_vencimiento` (último día pagado, inclusive), `pagos.casillero_asignacion_id` (FK, con CHECK: solo pagos de concepto "casillero") e índice por fecha de liberación para la lista "por día".
- **`servicios/casilleros.py`** (con permisos y auditoría en cada acción):
  - Catálogo solo admin: crear, crear varios (rango con dígitos y prefijo, omite los existentes), editar número/zona/notas, mantenimiento con nota y habilitar. Un casillero ocupado no pasa a mantenimiento ni a una zona que no corresponda al sexo de quien lo ocupa.
  - Asignar con **vencimiento propio**: desde, días (por defecto 30) y pago opcional en la misma transacción (recibo de concepto "Casillero 015"). Si el pago falla no queda la asignación.
  - Renovar: si sigue al día, el periodo nuevo empieza el día siguiente al vencimiento; si ya venció, empieza hoy. No permite acortar.
  - Cambiar de casillero conservando lo pagado (la asignación anterior queda en el historial con "Cambio al casillero X").
  - Liberar con motivo (vencido, ya no lo quiere, cliente inactivo u otro con detalle). No se borra nada.
  - Corregir vencimiento (solo admin, con motivo), por ejemplo tras anular un pago de casillero.
  - Consultas: de quién es un casillero (historial), qué casillero tiene un cliente, libres por zona compatible.
  - Listas (RF-L5): por estado, zona, sexo del ocupante, casilleros vencidos (con días), por vencer, clientes con membresía vencida o sin membresía, **sugeridos para liberar**, y asignados/liberados por día. Exportación a Excel y PDF (auditada) e impresión.
- **Zonas por sexo** (decisión del dueño): hombres solo M, mujeres solo F, mixto para todos (sexo "Otro" solo mixto). Se bloquea en el servicio.
- **Sugerencia de liberar** (RF-L7): cliente inactivo o casillero vencido hace más de N días (parámetro `casillero_dias_liberar`, 15 por defecto). Se muestra en la lista, la ficha y Recepción; nunca se libera solo. Al inactivar un cliente sigue la pregunta de la Fase 2 (liberar o conservar).
- **Recepción**: la tarjeta muestra "Casillero 015 pagado hasta…", "vence en N días" o "vencido hace N días · sugerido liberar". Si la membresía está vigente pero el casillero vencido, la tarjeta pasa a amarillo ("BIENVENIDO · CASILLERO VENCIDO") y deja entrar. La instantánea del casillero en cada asistencia (RN-11) sigue igual.
- **Pantalla Casilleros** (`ui/casilleros.py`): totales (disponibles, ocupados, mantenimiento, vencidos, sugeridos), filtros, búsqueda por número o cliente, Asignar (busca el cliente), Renovar, Cambiar, Liberar, Historial, Ficha; para el admin además Nuevo, Crear varios, Editar, Mantenimiento y Corregir vencimiento. Doble clic asigna o renueva. Pestaña "Asignados y liberados por día".
- **Ficha del cliente**: pestaña Casillero con Asignar (solo ofrece casilleros de su zona), Renovar, Cambiar, Liberar y el historial con "pagado hasta" y quién liberó.
- Parámetros nuevos (grupo Casilleros): días que cubre el pago (30), precio sugerido (0 = sin precio) y días para sugerir liberar (15).
- `scripts/seed_datos.py`: asignaciones con vencimiento (algunas vencidas) y zonas coherentes con el sexo.
- 36 pruebas nuevas (293 en total): reglas puras, catálogo, permisos, zonas, un cliente ↔ un casillero desde el servicio, pago todo-o-nada, renovar, cambiar, liberar, listas, sugerencias, exportación, Recepción y pantallas.

### Resultados medidos (base de prueba con 12.000 clientes y 240 casilleros)
| Operación | Peor tiempo |
|---|---:|
| Lista completa de casilleros | 49 ms |
| Vencidos / membresía vencida / búsqueda | ~10 ms |
| Resumen (totales) | 10 ms |
| Tarjeta de Recepción con casillero | 9 ms |

### Decisiones
- **Sección 13, punto 1:** "por día" = asignados o liberados en una fecha; "vencidos" = casilleros con su propio vencimiento pasado (y aparte, la lista de clientes con membresía vencida). **El casillero tiene vencimiento propio**, independiente de la membresía (confirmado por el dueño).
- **Sección 13, punto 2:** zonas hombres / mujeres / mixto según el sexo del cliente (confirmado por el dueño).
- "Eliminar" un casillero de un cliente = **liberar** (queda historial con fecha, usuario y motivo). Los casilleros del catálogo no se borran: se ponen en mantenimiento.
- El cobro del casillero se hace al asignarlo o renovarlo, para que el pago corra la fecha. El diálogo "Registrar pago" de la ficha ahora solo ofrece "Otro".
- Anular un pago de casillero no cambia la fecha automáticamente: el admin usa "Corregir vencimiento" con motivo.
- Las asignaciones anteriores a la Fase 5 quedan "sin fecha" hasta que se renueven (no hay datos reales todavía).
- Para "por vencer" del casillero se usa el mismo umbral de días que las membresías.

### Pendientes / para fases siguientes
- Reportes generales de casilleros dentro del módulo Reportes (Fase 7) reutilizando `ServicioCasilleros.listado`.
- Contenido de ayuda del módulo Casilleros (Fase 8).

## Fase 4 — Recepción y asistencia ✅ (26/11/2026)

### Qué se hizo
- **`servicios/asistencia.py`** (Recepción y Asistencia, con permisos y auditoría):
  - Código de 6 dígitos (también sin ceros a la izquierda) o `qr_token`.
  - Tarjeta: foto, nombre, código, plan, vencimiento, días restantes, casillero, alertas activas (críticas primero), cumpleaños y saldo pendiente. **Verde** vigente; **amarillo** por vencer (umbral configurable, "Tu plan vence el dd/mm/aaaa (faltan X días)") o con saldo pendiente; **rojo** vencido, sin membresía, membresía que aún no inicia o cliente inactivo.
  - Cada intento queda guardado con su resultado (RF-R5) y la instantánea del casillero (RN-11).
  - Asistencia duplicada según el parámetro `asistencia_duplicada` (por defecto avisar y confirmar).
  - **Ingreso autorizado**: usuario y contraseña de un administrador activo (`ServicioSesion.verificar_administrador`); los fallos cuentan para el bloqueo igual que el login. El intento rechazado pasa a "autorizado" y la auditoría queda a nombre del administrador, con quién lo registró y el motivo.
  - **Renovar ahora**: abre la renovación de la Fase 3 (`DialogoMembresia`) y, si queda vigente, el intento rechazado pasa a "permitido" o "por vencer" (auditado).
  - Resumen del día: asistentes (clientes distintos), ingresos y rechazados, y los últimos ingresos.
  - Eliminación lógica con motivo: recepción solo las del día; el admin cualquiera. Auditada.
  - Consultas por cliente, día, rango, resultado, sexo y plan (el plan de la membresía que cubría ese día).
  - Reportes: del día, por rango, por cliente, por franja horaria, ranking y "no vienen hace N días" (con teléfono y vigencia). Cada línea de asistencia muestra su casillero. Exportación a Excel y PDF (auditada) e impresión.
- **`servicios/alertas.py`**: crear y resolver alertas manuales (info, advertencia, crítica) con fecha final opcional. No se borran. Nuevo permiso `GESTIONAR_ALERTAS` (admin y recepción).
- **Pantalla Recepción** (`ui/recepcion.py`), solo teclado: campo de código siempre enfocado (los botones no toman el foco), Enter registra, Enter vacío confirma el segundo ingreso, Esc cancela, F2 Renovar ahora, F3 Ingreso autorizado, F4 ficha, F6 búsqueda manual por documento o nombre, F11 pantalla completa (oculta barra y menú), Ctrl + / Ctrl − / Ctrl 0 tamaño de letra (se recuerda en el PC). Tarjeta con ícono y texto además del color. Sonido de alerta (`recursos/alerta.wav` con `winsound` en Windows) en rojo, código no encontrado y duplicado bloqueado. Lista lateral con los últimos ingresos y el contador de hoy.
- **Pantalla Asistencia** (`ui/asistencia.py`): pestaña Registros (filtros, eliminar con motivo, registrar ingreso manual) y pestaña Reportes (vista previa, Excel, PDF, imprimir).
- **Ficha del cliente**: pestaña Alertas con "Nueva alerta…" y "Marcar como resuelta".
- `scripts/medir_asistencia.py`: mide Recepción y reportes sobre una copia de la base del seed.
- Corregido: la prueba del visor de auditoría fallaba según la hora real porque `ServicioUsuarios` no usaba el reloj inyectado; ahora sí.
- 50 pruebas nuevas (257 en total), incluido un lector USB simulado (teclas + Enter) y la ventana principal.

### Resultados medidos (base de prueba con 12.000 clientes y 230.000 asistencias)
| Operación | Filas | Peor tiempo |
|---|---:|---:|
| Ingreso por código (lector) | 1 | 3 ms |
| Resumen del día (lista lateral) | 1 | 8 ms |
| Consulta de hoy | 1.355 | 12 ms |
| Consulta de 30 días (primera página) | 76.770 | 23 ms |
| Reporte del día | 1.355 | 47 ms |
| Reporte por franja (30 días) | 12 | 90 ms |
| Ranking (30 días) | 50 | 92 ms |
| No vienen hace 30 días | 675 | 24 ms |

La consulta de 30 días tardaba ~410 ms ordenando por hora; ordenar primero por día (usa el índice `ix_asistencias_fecha`) la bajó a ~23 ms sin migración.

### Decisiones
- **Asistencia duplicada (sección 13, punto 3):** avisar y pedir confirmación (confirmado por el dueño). Configurable en Parámetros (avisar / bloquear / permitir).
- **Saldo pendiente:** entra con aviso amarillo (aprobado en la Fase 3).
- Los intentos rechazados (vencido o inactivo) se guardan, pero **no cuentan** como asistentes, ni en reportes, ni en el filtro "sin asistir hace N días" de Clientes. El aviso de "ya ingresó hoy" solo mira ingresos efectivos. Al autorizar o renovar, el mismo registro cambia de resultado (no se crea otro).
- "Sin membresía" y "membresía que aún no inicia" se guardan con el resultado `vencido` (la base no tiene otro valor).
- El ingreso autorizado aplica también a clientes inactivos (lo decide el administrador). "Renovar ahora" no aparece para inactivos.
- Recepción consulta la asistencia de hoy o el historial de un cliente, y solo ve el reporte del día (sección 2: reportes básicos). El admin, todo, incluidas las asistencias eliminadas.
- La franja horaria usa la hora de Bogotá (UTC−5 fijo, Colombia no tiene horario de verano).
- No hubo cambios de tablas, así que no hay migración nueva.

### Pendientes / para fases siguientes
- Fase 5: asignar y liberar casilleros desde la ficha y Recepción (la tarjeta ya muestra el casillero y la asistencia guarda la instantánea).
- Fase 7: estos reportes pasan también al módulo Reportes.
- Fase 8: QR del carnet (Recepción ya acepta el `qr_token`).
- Fase 11: empaquetar `recursos/alerta.wav` con PyInstaller.
- Tamaño de letra ajustable: hecho en Recepción; en el resto de pantallas se agrega si se necesita (decirlo en cualquier fase).

## Fase 3 — Planes, membresías y pagos ✅ (26/11/2026)

### Qué se hizo
- **Migración `0004`**: las membresías guardan motivo, usuario y fecha de anulación (con CHECK que exige el motivo) e índice `ix_pagos_membresia_id` para calcular saldos. Las anuladas previas sin motivo reciben uno genérico.
- **`servicios/planes.py`**: crear, editar y activar/desactivar planes (solo admin, auditado). No se borran. Nombre único sin importar tildes ni mayúsculas. Editar precio o duración no toca las membresías ya registradas. Al arrancar, si la base no tiene planes, se crean Mensual (30), Quincenal (15), Trimestral (90) y Día (1) **inactivos y con precio $ 0**: el admin pone el precio y los activa.
- **`servicios/pagos.py`**:
  - RN-03: `fecha_fin = inicio + días − 1`. RN-04: si el cliente sigue vigente la renovación inicia el día siguiente a su fin; si venció, hoy o la fecha elegida. Nuevo parámetro `renovacion_anticipada` (día siguiente / hoy).
  - Renovación rápida (`proponer_membresia`): último plan del cliente si sigue activo, fecha de inicio, fin y precio.
  - Registrar membresía con su primer pago (completo o abono) o sin pago. No se permiten membresías que se crucen (con la política "día siguiente"), ni a clientes inactivos, ni con planes desactivados.
  - Precio distinto al del plan: solo admin y con motivo (nuevo permiso `APLICAR_DESCUENTOS`). Recepción puede iniciar una membresía hasta 30 días atrás; más atrás, solo el admin. Máximo 90 días adelante.
  - Pagos: efectivo, tarjeta o transferencia (referencia obligatoria en los dos últimos); conceptos membresía (abono con saldo), casillero u otro (sin membresía). Ningún pago supera el saldo pendiente.
  - Consecutivo de recibo: el mayor entre el parámetro `recibo_siguiente` y el último usado + 1, en la misma transacción del pago; nunca se repite.
  - Anular pago (solo admin, motivo obligatorio). Anular membresía (solo admin) anula también sus pagos con el mismo motivo. Todo queda en la auditoría.
  - Cierre de caja por día de Bogotá: totales por método y por usuario, lista de pagos con los anulados visibles pero sin sumar. Recepción solo ve el suyo de hoy; el admin, cualquier usuario y fecha (permiso `CIERRE_CAJA_GENERAL`).
  - Saldo pendiente por membresía y por cliente (`saldo_cliente`, para el aviso de Recepción en la Fase 4).
- **Recibo PDF** (`reportes/recibo.py`, media carta): logo, nombre, NIT, dirección y teléfono del gimnasio; número con prefijo; cliente; concepto con fechas; método y referencia; valor, saldo pendiente justo después de ese pago y quién atendió. Los anulados se reimprimen con marca "ANULADO" y su motivo. Se guardan en `%APPDATA%\Enforma\recibos\` y se abren con el visor de PDF de Windows para imprimir.
- **Interfaz**: Configuración → pestaña **Planes**; en la ficha del cliente, pestaña Membresías (pagado, saldo, observación) con **Renovar membresía (Ctrl+R)**, registrar abono y anular (admin), y pestaña Pagos con registrar pago (casillero u otro), ver/imprimir recibo y anular (admin); aviso de saldo pendiente en la cabecera. Módulo **Pagos** con el cierre de caja del día.
- Corregido: los campos numéricos (Configuración → Parámetros) se veían vacíos porque `setButtonSymbols(NoButtons)` no dibuja el texto con la hoja de estilos; ahora las flechas se ocultan desde el estilo.
- 50 pruebas nuevas (207 en total): fechas RN-03/RN-04 (bisiesto, cambio de año, plan de un día), descuentos y permisos, abonos y saldos, consecutivo, anulaciones, cierre de caja por día y usuario, recibo PDF, migración 0004 y pantallas.

### Resultados medidos (base de prueba con 12.000 clientes)
- Cierre de caja de un día con ~290 pagos: 6,5 ms. Ficha con saldos: 4 ms. Propuesta de renovación: 2 ms.

### Decisiones (aprobadas por el dueño)
- Congelamientos o pausas de membresía: fuera por ahora.
- Abonos permitidos. Un cliente con saldo puede entrar; Recepción mostrará un aviso amarillo (Fase 4).
- Recibo con consecutivo propio y NIT si está configurado; no es factura electrónica.
- El número del recibo se arma con el prefijo **actual**: si se cambia el prefijo, los recibos viejos se reimprimen con el nuevo.

### Pendientes / para fases siguientes
- Fase 4: botón de renovación desde la alerta roja de Recepción (ya existe `DialogoMembresia`) y aviso de saldo pendiente.
- Fase 5: si el casillero tiene cobro propio, usar el concepto "casillero" que ya existe.
- Fase 7: exportar el cierre de caja a Excel/PDF.

## Fase 2 — Clientes ✅ (26/11/2026)

### Qué se hizo
- **Servicio `servicios/clientes.py`** (con permisos por rol y auditoría):
  - Registrar: código de 6 dígitos consecutivo y no editable, `qr_token` aleatorio, documento único, varios teléfonos y correos (el primero es el principal), contactos de emergencia, fecha de autorización de datos.
  - Modificar con auditoría campo por campo (valor anterior → nuevo, solo lo que cambió). Al registrar solo se audita el código, sin copiar datos personales.
  - Activar / inactivar (solo admin, con motivo). Si el cliente tiene casillero, el servicio exige decidir: liberar (queda en el historial con fecha, usuario y motivo, y el casillero vuelve a "disponible") o conservarlo. No existe ningún método para borrar ni para cambiar el código.
  - Foto opcional (PNG/JPG, máx. 5 MB) copiada a `%APPDATA%\Enforma\fotos\<código>.jpg`.
  - Vigencia calculada (vigente, por vencer, vencida, sin membresía) desde la última membresía no anulada y el umbral configurado; nunca se guarda.
  - Búsqueda por código (también sin ceros a la izquierda), documento, teléfono (prefijo), correo, nombre y apellido (sin importar tildes ni mayúsculas). Filtros: estado, vigencia, sexo, plan, rango de fecha de registro, cumpleaños del mes y "sin asistir hace N días". Orden por cualquier columna y paginación en la base.
  - Exportar la lista filtrada a Excel y PDF (`reportes/exportar.py`, genérico para los reportes de la Fase 7).
- **Migración `0003`**: columna `clientes.busqueda` (nombre normalizado). La calcula el modelo al guardar y la migración la llena para los clientes existentes.
- **Interfaz**: pantalla Clientes con buscador instantáneo, dos filas de filtros, tabla con carga virtual (páginas de 200) y orden por columna en la base, menú contextual y exportación; formulario de registro/edición; ficha con pestañas Datos, Contactos, Membresías, Pagos, Asistencias, Casillero y Alertas; Ctrl+K abre la ficha (si hay varios resultados muestra una lista para elegir con Enter). Atajos: Ctrl+N nuevo cliente, Ctrl+F buscar.
- `scripts/medir_busqueda.py`: mide los tiempos de búsqueda sobre una base del seed.
- 157 pruebas pytest (74 nuevas): registro, unicidad, validaciones, permisos por rol, auditoría por campo, inactivación con casillero, vigencia, búsquedas, filtros, orden, exportación, migración, pantallas y rendimiento con 12.000 clientes.

### Resultados medidos (12.000 clientes del seed, conteo + primera página)
| Búsqueda | Resultados | Tiempo |
|---|---:|---:|
| Código exacto | 1 | 3 ms |
| Documento (prefijo) | 7 | 3 ms |
| Teléfono (prefijo) | 81 | 5 ms |
| Apellido «gomez» | 495 | 16 ms |
| Nombre y apellido «maria rodri» | 40 | 22 ms |
| Correo | 8.456 | 16 ms |
| Vigencia "por vencer" | 1.298 | 48 ms |
| Plan | 7.036 | 33 ms |
| Sin asistir hace 30 días | 4.375 | 22 ms |

Peor caso: 52 ms (meta < 200 ms). Exportar los 12.000: Excel ~3 s, PDF ~5 s. La prueba `tests/test_rendimiento_clientes.py` lo verifica en cada ejecución.

### Decisiones
- **Recepción** modifica solo teléfonos, correos, contacto de emergencia y dirección (confirmado). También puede registrar la autorización de datos (no retirarla) y cambiar la foto. El resto solo el admin.
- **Tipos de documento:** CC, TI, CE, PAS (pasaporte) y PPT. CC y TI solo números (5 a 11 dígitos); los demás, de 3 a 20 letras o números. Se guardan sin puntos ni espacios.
- **Teléfonos** se guardan solo con dígitos (y el `+` inicial si lo tienen), entre 7 y 15 dígitos. Correos en minúsculas.
- **Vigencia:** el día de `fecha_fin` quedan 0 días y el cliente sigue "por vencer" (puede ingresar, RN-03).
- **Búsqueda numérica:** con 1 o 2 dígitos solo busca el código exacto; desde 3 dígitos también documento y teléfono por prefijo (evita listar miles de teléfonos).
- **Búsqueda por nombre:** columna normalizada en lugar de calcularla en cada consulta (bajó de ~150 ms a ~20 ms).
- **Exportar la lista de clientes:** solo el admin (contiene datos personales de todos los clientes) y queda en la auditoría con formato y cantidad. Si recepción la necesita, se cambia el permiso.

### Pendientes / para fases siguientes
- Membresías, pagos y alertas se ven en la ficha (solo lectura); se registran en las Fases 3 y 4. La asignación de casilleros va en la Fase 5.
- Carnet con foto y QR (RF-C7): Fase 8.
- Tomar la foto con cámara web: por ahora se elige un archivo.

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
