# Especificación — Sistema de gestión del gimnasio Enforma

Aplicación de escritorio para Windows, de un solo puesto (1 PC), sin nube, para gestionar clientes, membresías, pagos, asistencia, casilleros e invitados. Reemplaza al software actual conservando todas sus funciones.

---

## 1. Contexto y alcance

- **Usuarios del sistema:** personal del gimnasio (administrador y recepción). Los clientes **no** inician sesión: se identifican en recepción con un código o QR.
- **Volumen:** más de 10.000 clientes, con crecimiento. Todas las búsquedas deben responder en menos de 200 ms.
- **Equipo:** 1 PC con Windows 10/11. Sin nube. Backups locales cifrados.
- **Idioma y región:** español de Colombia. Moneda COP sin decimales (`$ 120.000`), fechas `dd/mm/aaaa`, zona horaria America/Bogota.
- **Identificación del cliente:** código numérico único ahora; lector QR/código de barras USB (actúa como teclado) después; huella dactilar en una fase final.

## 2. Roles y permisos

| Acción | Recepción | Administrador |
|---|:-:|:-:|
| Iniciar sesión, registrar asistencia (módulo Recepción) | ✔ | ✔ |
| Consultar clientes | ✔ | ✔ |
| Inscribir clientes nuevos | Con clave de administrador, cada vez | ✔ |
| Modificar clientes | ✔ (datos de contacto) | ✔ (todo) |
| Activar / inactivar clientes | ✖ | ✔ |
| Registrar pagos y membresías (incluido el cobro del casillero) | Con clave de administrador, cada vez | ✔ |
| Módulo Pagos (su caja de hoy, consultas) y pestaña Pagos de la ficha | Con clave de administrador, cada vez que se abre | Con su clave, cada vez que se abre (que no quede a la vista) |
| Anular pagos | ✖ | ✔ |
| Eliminar asistencias | Solo las del día actual, con motivo | Cualquiera, con motivo |
| Asignar casillero | ✔ | ✔ |
| Liberar casillero | ✔ | ✔ |
| Registrar invitados y su asistencia | ✔ | ✔ |
| Reportes | Básicos (asistencia del día, casilleros, por vencer, invitados del día) | Todos |
| Planes, precios, casilleros (crear/editar), configuración | ✖ | ✔ |
| Usuarios, auditoría, backups y restauración | ✖ | ✔ |
| Importar datos del programa anterior | ✖ | ✔ (una vez, con copia previa) |
| Ayuda | ✔ | ✔ |

Los permisos se validan en la capa de servicios, no solo ocultando botones. La "clave de administrador" es el usuario y la contraseña de un administrador activo: el servicio entrega una autorización que vive en memoria, vence pronto y se gasta con la operación (un cobro; la inscripción y su primer cobro; o el módulo Pagos mientras esté abierto). Queda en la auditoría quién autorizó.

## 3. Requisitos funcionales por módulo

### 3.1 Acceso y seguridad (nuevo)
- RF-A1: Inicio de sesión con usuario y contraseña (hash argon2).
- RF-A2: Bloqueo temporal tras 5 intentos fallidos (configurable) y cierre de sesión por inactividad (configurable, por defecto 15 min en pantallas administrativas; la pantalla de Recepción permanece abierta).
- RF-A3: Gestión de usuarios (solo admin): crear, editar, desactivar, restablecer contraseña. No se eliminan usuarios.
- RF-A4: Auditoría de acciones sensibles (ver 5.1).

### 3.2 Clientes (del software actual + mejoras)
- RF-C1: **Registrar** cliente: código (autogenerado, no editable), tipo y número de documento (único), nombres, apellidos, sexo, fecha de nacimiento, dirección, foto opcional, notas, varios teléfonos y correos, contacto de emergencia, autorización de tratamiento de datos (fecha).
- RF-C2: **Consultar**: ficha completa con pestañas: Datos, Contactos, Membresías, Pagos, Asistencias, Casillero, Alertas.
- RF-C3: **Modificar** datos (con registro en auditoría de qué campo cambió).
- RF-C4: **Activar / inactivar** (solo admin). Un cliente inactivo no puede ingresar (rojo en Recepción). Al inactivar un cliente que tiene casillero, el sistema pide liberar el casillero. **Los clientes no se eliminan nunca.**
- RF-C5: **Listas y búsquedas**: por nombre, apellido, documento, código, teléfono, correo; filtros por estado (activo/inactivo), por vigencia (vigente, por vencer, vencida, sin membresía), por sexo, por plan, por rango de fecha de registro, por cumpleaños del mes, por "sin asistir hace N días". Orden por cualquier columna. Exportar a Excel y PDF.
- RF-C6: Búsqueda global instantánea (Ctrl+K) que acepta código, documento, nombre, teléfono o correo y abre la ficha.
- RF-C7: Impresión de carnet con foto, nombre, código y QR.

### 3.3 Planes, membresías y pagos (nuevo)
- RF-P1: Planes configurables (nombre, duración en días, precio, activo): mensual, quincenal, trimestral, por días, etc.
- RF-P2: Registrar membresía: plan, fecha de inicio, fecha de fin calculada, precio pactado (permite descuento con motivo, solo admin).
- RF-P3: Registrar pago: monto, método (**efectivo, tarjeta, transferencia**), referencia (obligatoria en tarjeta y transferencia), concepto (membresía, casillero, otro), usuario y fecha/hora automáticos. Soporta pago parcial y saldo pendiente.
- RF-P4: Recibo imprimible en PDF con consecutivo. Si la mensualidad y el casillero se pagan juntos, van en un solo recibo con un solo número y los dos conceptos; solo casillero = recibo propio con el siguiente consecutivo.
- RF-P5: Anular pago (solo admin) con motivo obligatorio. Nunca se borra.
- RF-P6: **Cierre de caja diario** por usuario y método de pago.
- RF-P7: Renovación rápida desde la ficha del cliente y desde la alerta roja de Recepción.

### 3.4 Recepción y alertas de ingreso (nuevo, pantalla principal)
- RF-R1: Un campo de código siempre enfocado. Acepta digitación o lector USB (termina con Enter). Tras cada ingreso, el campo se limpia y se re-enfoca.
- RF-R2: Al ingresar un código, muestra una **tarjeta grande** con foto, nombre, código, plan, fecha de vencimiento, días restantes, casillero asignado y alertas manuales activas.
- RF-R3: Colores y sonido:
  - **Verde:** vigente.
  - **Amarillo:** vence en N días o menos (N configurable, por defecto 5). Mensaje: "Tu plan vence el dd/mm/aaaa (faltan X días)".
  - **Rojo + sonido de alerta:** vencido, sin membresía o cliente inactivo. Botones: "Renovar ahora" y "Ingreso autorizado" (requiere contraseña de admin y queda en auditoría).
- RF-R4: Si el cliente ya registró asistencia hoy, avisa "Ya ingresó hoy a las HH:MM" y pide confirmar si se quiere registrar de nuevo (configurable).
- RF-R5: El ingreso se guarda con el resultado (permitido, por vencer, vencido, inactivo, autorizado).
- RF-R6: Muestra a un lado el listado de los últimos ingresos del día y el contador de asistentes de hoy.
- RF-R7: Alertas manuales: el admin o recepción dejan una nota a un cliente (ej. "falta documento"), con nivel (info, advertencia, crítica), que aparece al ingresar hasta que se marque como resuelta.
- RF-R8: Cumpleaños: si hoy cumple años, la tarjeta lo muestra.

### 3.5 Asistencia (del software actual + mejoras)
- RF-S1: **Registro diario** (desde Recepción; también manual por documento o nombre).
- RF-S2: **Consultas** por cliente, por día, por rango de fechas, por resultado, por sexo, por plan.
- RF-S3: **Eliminar** un registro de asistencia: eliminación lógica con motivo y auditoría (reglas en la sección 2). Los eliminados no cuentan en reportes, pero se pueden ver en la auditoría.
- RF-S4: **Reportes de asistencia:** del día, por rango, por cliente, por franja horaria, ranking de asistencia, clientes que no vienen hace N días. **Cada línea muestra el casillero que tenía asignado el cliente ese día.** Exportar a Excel y PDF e imprimir.

### 3.6 Casilleros (del software actual)
- RF-L1: Catálogo de casilleros (número, zona: hombres / mujeres / mixto, estado: disponible / ocupado / mantenimiento). Alta y edición solo admin.
- RF-L2: **Asignar** casillero a un cliente. **Regla: un cliente tiene como máximo un casillero activo y un casillero pertenece como máximo a un cliente activo.** Se refuerza con índices únicos parciales en la base de datos, no solo en el código.
- RF-L3: **Consultar de quién es** un casillero y **qué casillero tiene** un cliente.
- RF-L4: **Liberar** casillero (queda historial con fecha, usuario y motivo).
- RF-L5: **Listas:** casilleros ocupados, disponibles, en mantenimiento; **por sexo** (según la zona del casillero y según el sexo del cliente que lo ocupa); **por día** (asignados o liberados en una fecha); **de clientes con membresía vencida** (para poder liberarlos), con días de vencimiento.
- RF-L6: El casillero aparece en la tarjeta de Recepción, en la ficha del cliente y en los reportes de asistencia.
- RF-L7: Al inactivar un cliente, o al vencer su membresía más de X días (configurable), el sistema sugiere liberar su casillero (no lo libera solo sin confirmación).

### 3.7 Invitados (del software actual)
- RF-I1: **Registrar** invitado: nombre, documento (único), teléfono.
- RF-I2: **Registrar asistencia de un invitado** (fecha/hora, usuario y, opcional, el cliente que lo invita).
- RF-I3: **Ver cuántas veces ha asistido** cada invitado y el detalle de sus visitas. Lista de invitados con total de visitas y última visita.
- RF-I4: Búsqueda por nombre, documento o teléfono. Si un invitado ya existe (mismo documento), se reutiliza el registro.
- RF-I5: Reporte de invitados por rango de fechas y por cliente anfitrión.
- RF-I6 (por confirmar): límite de invitaciones por cliente al mes y cobro por invitado.

### 3.8 Reportes (del software actual + nuevos)
Asistencia (3.5), casilleros (3.6), invitados (3.7) y además:
- Clientes por vencer en los próximos N días (con teléfono, para llamarlos).
- Clientes vencidos y morosos (saldo pendiente).
- Ingresos por rango, por método de pago, por usuario, por plan.
- Cierre de caja.
- Nuevos clientes por mes, renovaciones y bajas.
- Todos exportables a Excel y PDF, e imprimibles.

### 3.9 Ayuda (del software actual)
- RF-H1: Módulo de Ayuda dentro de la aplicación que **explica cómo funciona cada módulo** (clientes, asistencia, casilleros, invitados, pagos, recepción, reportes, backups, usuarios).
- RF-H2: Ayuda contextual: la tecla F1 abre la ayuda del módulo en el que se encuentre el usuario.
- RF-H3: Contenido en archivos Markdown dentro de la aplicación, con buscador, para poder actualizarlo sin tocar la lógica.

### 3.10 Configuración y backups (nuevo)
- RF-K1: Parámetros: umbral de "por vencer", política de asistencia duplicada, tiempo de inactividad, datos del gimnasio (nombre, NIT, dirección, logo para recibos), consecutivo de recibos.
- RF-K2: Backups (ver sección 8) y restauración desde la interfaz.
- RF-K3: Visor de auditoría con filtros (solo admin).

## 4. Reglas de negocio

- RN-01 **Código de cliente:** numérico, único, de 6 dígitos con ceros a la izquierda. Se sugiere el consecutivo (parámetro `codigo_siguiente`, que salta los códigos ya usados); solo el administrador puede asignar un código manual (no mueve el consecutivo) o cambiar el código de un cliente (auditado). Un cliente tiene un solo código: si se inscribe un documento ya registrado se recupera su código antiguo (y se reactiva si estaba inactivo). Aparte se genera un `qr_token` aleatorio (`secrets.token_urlsafe`). Recepción acepta cualquiera de los dos.
- RN-02 **Dos estados independientes:** el *estado administrativo* (activo/inactivo, lo cambia el admin) y la *vigencia* (calculada a partir de la última membresía no anulada: vigente, por vencer, vencida, sin membresía). Nunca se guarda la vigencia, siempre se calcula.
- RN-03 **Fechas de membresía:** `fecha_fin = fecha_inicio + duracion_dias - 1` (inclusive). Puede ingresar hasta el día de `fecha_fin` incluido. Excepción: el administrador puede ajustar a mano la fecha fin con "Cambiar vigencia" (con motivo y auditado).
- RN-04 **Renovación anticipada:** si el cliente aún está vigente, la nueva membresía inicia el día siguiente a la `fecha_fin` actual (configurable). Si ya está vencido, inicia hoy o en la fecha que se elija.
- RN-05 **Cliente inactivo** no puede ingresar, aunque tenga membresía vigente.
- RN-06 **Casilleros:** un cliente ↔ un casillero activo, reforzado por índices únicos parciales (ver 5).
- RN-07 **Nada financiero se borra:** pagos y membresías se anulan con motivo. *Única excepción (aprobada por el dueño):* el administrador puede borrar pagos antiguos hasta una fecha, con clave de seguridad, copia cifrada y Excel previos y registro en la auditoría; nunca la última membresía de un cliente ni la numeración de recibos.
- RN-08 **Asistencias** se eliminan de forma lógica y quedan auditadas.
- RN-09 **Clientes y usuarios no se eliminan**, solo se inactivan.
- RN-10 **Invitado:** el documento identifica a la persona; las visitas se cuentan desde `invitado_asistencias` (no se guarda un contador, se calcula). *Única excepción:* `invitados.visitas_anteriores`, un número fijo traído del programa anterior para las visitas sin fecha; nunca se actualiza y se suma al total.
- RN-11 **Instantánea del casillero:** cada asistencia guarda el número de casillero que el cliente tenía en ese momento, para que los reportes históricos no cambien si después se libera.

## 5. Modelo de datos (SQLite, SQLAlchemy 2, migraciones con Alembic)

Todas las tablas llevan `id` entero autoincremental. Las marcas de tiempo se guardan en UTC y se muestran en America/Bogota. `PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;`

```
usuarios(id, nombre_completo, usuario UNIQUE, hash_clave, rol CHECK IN ('admin','recepcion'),
         activo, intentos_fallidos, bloqueado_hasta, ultimo_login, creado_en)

clientes(id, codigo UNIQUE, qr_token UNIQUE, tipo_documento, documento UNIQUE,
         nombres, apellidos, sexo CHECK IN ('M','F','O'), fecha_nacimiento, direccion, foto_ruta,
         estado CHECK IN ('activo','inactivo'), notas,
         autoriza_datos_en, autoriza_biometria_en,
         creado_en, actualizado_en, creado_por)

contactos(id, cliente_id FK, tipo CHECK IN ('telefono','email','emergencia'),
          valor, nombre_contacto, principal)

planes(id, nombre, duracion_dias, precio, activo)

membresias(id, cliente_id FK, plan_id FK, fecha_inicio, fecha_fin, precio_pactado,
           estado CHECK IN ('activa','anulada'), motivo_descuento, creado_por, creado_en)

pagos(id, consecutivo UNIQUE, cliente_id FK, membresia_id FK NULL,
      concepto CHECK IN ('membresia','casillero','otro'), monto,
      metodo CHECK IN ('efectivo','tarjeta','transferencia'), referencia,
      fecha_hora, usuario_id FK, anulado, motivo_anulacion, anulado_por, anulado_en)

asistencias(id, cliente_id FK, fecha_hora, fecha, 
            resultado CHECK IN ('permitido','por_vencer','vencido','inactivo','autorizado'),
            casillero_numero NULL,           -- instantánea (RN-11)
            usuario_id FK, eliminada, motivo_eliminacion, eliminada_por, eliminada_en)

casilleros(id, numero UNIQUE, zona CHECK IN ('hombres','mujeres','mixto'),
           estado CHECK IN ('disponible','ocupado','mantenimiento'), notas)

casillero_asignaciones(id, casillero_id FK, cliente_id FK,
                       fecha_asignacion, fecha_liberacion NULL,
                       asignado_por, liberado_por, motivo_liberacion)
   -- UNIQUE INDEX uq_casillero_activo ON (casillero_id) WHERE fecha_liberacion IS NULL
   -- UNIQUE INDEX uq_cliente_casillero_activo ON (cliente_id) WHERE fecha_liberacion IS NULL

invitados(id, nombre, documento UNIQUE, telefono, creado_en, creado_por)

invitado_asistencias(id, invitado_id FK, fecha_hora, fecha, cliente_anfitrion_id FK NULL,
                     usuario_id FK, eliminada, motivo_eliminacion)

alertas(id, cliente_id FK, mensaje, nivel CHECK IN ('info','advertencia','critica'),
        activa, fecha_inicio, fecha_fin NULL, creada_por, creada_en, resuelta_por, resuelta_en)

biometria(id, cliente_id FK, dedo, plantilla_cifrada BLOB, proveedor, creado_en)   -- RESERVADA

auditoria(id, fecha_hora, usuario_id FK, accion, entidad, entidad_id, detalle_json)

backups_log(id, fecha_hora, tipo CHECK IN ('automatico','manual'), ruta, tamano_bytes, resultado, detalle)

config(clave PK, valor)
```

**Índices obligatorios:** `clientes(codigo)`, `clientes(qr_token)`, `clientes(documento)`, `clientes(apellidos, nombres)`, `clientes(estado)`, `contactos(valor)`, `contactos(cliente_id)`, `membresias(cliente_id, fecha_fin)`, `membresias(fecha_fin)`, `pagos(cliente_id)`, `pagos(fecha_hora)`, `asistencias(cliente_id, fecha)`, `asistencias(fecha)`, `invitados(documento)`, `invitado_asistencias(invitado_id)`, `auditoria(fecha_hora)`.

En SQLAlchemy los índices parciales se declaran con `Index(..., unique=True, sqlite_where=text("fecha_liberacion IS NULL"))`.

## 6. Interfaz (empresarial, intuitiva)

- **Tecnología:** PySide6 (Qt). Estilo limpio y sobrio, con una paleta corporativa y tipografía legible.
- **Estructura:** barra de navegación a la izquierda con Recepción, Clientes, Asistencia, Casilleros, Invitados, Pagos, Reportes, Configuración (solo admin) y Ayuda. Arriba: búsqueda global (Ctrl+K), usuario actual y cierre de sesión.
- **Tablas:** orden por columna, filtros, paginación o carga virtual (fluida con 10.000+ filas), exportar a Excel, menú contextual.
- **Recepción:** pantalla pensada para uso rápido con teclado, letra grande, tarjeta de color, foto y sonido. Debe poder usarse a pantalla completa.
- **Formularios:** validaciones claras en español, confirmaciones en acciones destructivas o irreversibles, atajos de teclado y mensajes de éxito discretos.
- **Accesibilidad:** buen contraste, no depender solo del color (la tarjeta incluye texto e ícono) y tamaño de letra ajustable.

## 7. Seguridad y privacidad

- Contraseñas con argon2, bloqueo por intentos fallidos, roles verificados en servicios.
- Auditoría de: inicios de sesión, cambios de datos de clientes, pagos y anulaciones, eliminación de asistencias, cambios de casillero, cambios de configuración, backups y restauraciones.
- **Cifrado en reposo:** BitLocker en el disco de Windows (recomendado como primera medida). Opcional más adelante: SQLCipher, que en Windows puede ser difícil de instalar y empaquetar, por lo que no es prerrequisito.
- Backups **siempre cifrados**.
- Datos personales: guardar la fecha de autorización de tratamiento de datos (Ley 1581 de 2012). Los datos biométricos son sensibles: la autorización debe ser expresa y voluntaria, y el ingreso por huella no puede ser obligatorio. Se recomienda validar el texto de autorización con un abogado.
- Los logs de la aplicación no deben contener datos personales completos.

## 8. Backups (sin nube)

- **Método:** API de backup de SQLite (`sqlite3.Connection.backup`), segura aunque la base esté en uso. Luego verificar con `PRAGMA integrity_check` sobre la copia, comprimir (zip) y cifrar (AES-GCM con clave derivada de una contraseña con scrypt, librería `cryptography`).
- **Destino configurable:** disco externo o USB. Debe detectar si el destino no está disponible y avisar.
- **Cuándo:** automático al cerrar la aplicación y a una hora diaria; botón "Backup ahora" (admin).
- **Rotación:** 7 diarios, 4 semanales y 12 mensuales.
- **Regla 3-2-1:** una copia en el PC, otra en el disco externo y otra en un disco que el dueño se lleve del local (recordatorio semanal en la aplicación).
- **Restauración** desde la interfaz, con un backup de seguridad automático justo antes de restaurar.
- **Alertas:** aviso visible en el inicio si el último backup exitoso tiene más de 2 días.
- **Advertencia al usuario:** si pierde la contraseña de cifrado, los backups no se pueden recuperar. Guardarla en un lugar seguro.
- **Prueba:** comando de verificación que restaura el último backup en una carpeta temporal y comprueba que abre y tiene datos.

## 9. Requisitos no funcionales

- Búsqueda de clientes < 200 ms con 12.000 clientes (y comprobable con el script de datos de prueba).
- Registro de un ingreso en Recepción < 300 ms.
- Arranque de la aplicación < 5 s.
- Funciona sin internet. Una sola instancia abierta a la vez (bloqueo de archivo para evitar dobles aperturas).
- Instalable con un `.exe` (PyInstaller + Inno Setup). Datos de usuario en `%PROGRAMDATA%\Enforma` o `%APPDATA%\Enforma`, no dentro de la carpeta de instalación.
- Pruebas automáticas con pytest para toda la lógica de servicios.
- Código en capas: `ui/` → `servicios/` → `modelos/` y `db/`.

## 10. Migración desde el software actual

- Antes de empezar: pedir al software actual una exportación de clientes, asistencias, casilleros e invitados (Excel o CSV) o el archivo de su base de datos.
- Construir un **importador** con: vista previa, mapeo de columnas, detección de duplicados por documento, reporte de errores por fila y modo de prueba (sin guardar).
- Importar primero a una copia de prueba; nunca tocar los archivos originales.
- Mantener el sistema nuevo **en paralelo** con el actual durante 1 a 2 semanas antes de reemplazarlo.
- **Hecho (Fase 10):** el programa actual es un desarrollo propio en dBase III (carpeta `DB3`, archivos `.DBF`). Se importa desde Configuración → Importar datos (ver `docs/PROGRESO.md`): clientes con su mismo código, vigencia como membresía «Programa anterior» de $0, asistencias, casilleros e invitados. No se importan pagos (valores no reales), datos de salud ni medidas.

## 11. Huella dactilar (fase final, opcional)

- Se diseña una interfaz `LectorHuella` con `enrolar(cliente_id, dedo)` e `identificar() -> cliente_id | None`, con una implementación por proveedor. Así el resto del sistema no depende del lector.
- Se compra el lector solo después de revisar que su SDK sea compatible con Python (o decidir usar un puente en .NET) y con Windows.
- Se guarda la **plantilla** (no la imagen), cifrada, con autorización registrada en `clientes.autoriza_biometria_en`.
- Debe seguir existiendo el ingreso por código/QR como alternativa.

## 12. Criterios de aceptación (resumen)

1. Con 12.000 clientes de prueba, la búsqueda por nombre, documento, código y teléfono responde en menos de 200 ms.
2. Intentar asignar un segundo casillero al mismo cliente, o el mismo casillero a un segundo cliente, falla incluso si se intenta directamente en la base de datos.
3. Un cliente con membresía vencida ve la tarjeta roja con sonido; uno que vence en 5 días o menos, la amarilla con la fecha; uno vigente, la verde.
4. Recepción no puede anular pagos ni inactivar clientes; el admin sí, y queda en la auditoría.
5. Un pago anulado deja de contar en el cierre de caja pero sigue visible con su motivo.
6. El reporte de asistencia muestra el casillero del cliente de ese día, aunque luego lo libere.
7. Un invitado registrado dos veces con el mismo documento no se duplica y su contador de visitas aumenta.
8. Un backup se crea, se cifra, se restaura en una carpeta temporal y la base restaurada pasa `integrity_check`.
9. Todas las pantallas tienen su entrada en la Ayuda y F1 abre la correcta.
10. El instalador funciona en un Windows limpio sin Python instalado.

## 13. Supuestos y preguntas abiertas (confirmar antes o durante la construcción)

1. **Casilleros "por día vencidos":** se interpretó como (a) casilleros asignados o liberados en una fecha y (b) casilleros de clientes con membresía vencida. ¿Es así? ¿El casillero tiene su propio cobro o vencimiento?
2. **Casilleros por sexo:** se interpretó como zona del casillero (hombres/mujeres) y/o sexo del cliente que lo ocupa. ¿Hay vestidores separados?
3. **Asistencia duplicada en el mismo día:** por defecto se avisa y pide confirmación. ¿Se debe bloquear?
4. **Invitados:** ¿se cobran? ¿hay límite por cliente al mes? ¿quién autoriza?
5. **Planes:** ¿qué planes y precios existen hoy? ¿hay descuentos, congelamientos o pausas de membresía?
6. **Pagos:** ¿se permiten abonos? (27/11/2026: no, solo pago completo y anticipado) ¿se necesita consecutivo de recibo y datos fiscales (NIT)? ¿se emite factura electrónica? (fuera de alcance por ahora)
7. **Cuántos usuarios** de recepción habrá (para crear las cuentas) y si hay más de un turno.
8. **Datos a migrar:** ¿desde qué formato se pueden exportar? ¿hay historial de asistencias que se deba conservar?
9. **Ayuda actual:** conviene copiar los textos de la ayuda del software actual como base.
10. **Mensajes de vencimiento por WhatsApp o SMS:** quedan fuera de alcance porque requieren servicios en línea; solo se muestran en pantalla y en el reporte de clientes por vencer (con teléfono para llamarlos).

## 14. Fuera de alcance (por ahora)

Nube, aplicación móvil, portal del cliente, facturación electrónica, control de acceso con torniquete, multisede y múltiples PCs en red (el diseño en capas permite pasar a PostgreSQL más adelante).
