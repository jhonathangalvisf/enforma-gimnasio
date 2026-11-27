# Recepción

Recepción es la pantalla de la entrada del gimnasio. Sirve para registrar el ingreso de cada cliente con su **código personal** y para ver de inmediato si puede entrar. Es la primera pantalla que se abre y se puede usar **solo con el teclado** o con sus **botones grandes**.

## Registrar el ingreso de un cliente

1. El cliente le dice su **código** (el número de 6 dígitos que le dio el gimnasio).
2. Escríbalo en el campo **Código del cliente** y presione **Enter**. No hace falta escribir los ceros de la izquierda: "57" es lo mismo que "000057".
3. Aparece una **tarjeta grande** con el resultado y el ingreso queda guardado.
4. El campo se limpia solo y queda listo para el siguiente cliente.

El campo de código está **siempre seleccionado**: no hace falta hacer clic en él. Si más adelante se usa un lector USB, este escribe el código y presiona Enter por usted.

## Los botones de arriba

Debajo del campo de código hay botones grandes que hacen lo mismo que las teclas, por si prefiere el ratón:

- **Registrar ingreso (Enter):** registra el código escrito.
- **Buscar por nombre o cédula (F6):** para el cliente que no recuerda su código.
- **Pantalla completa (F11):** oculta el menú y la barra.
- **A− Letra / A+ Letra:** achica o agranda la letra de la pantalla.

Pulsar un botón no saca el cursor del campo de código: puede seguir escribiendo el siguiente código enseguida.

Arriba a la derecha está el **contador de asistentes de hoy** (cuenta personas distintas; si alguien entra dos veces cuenta una sola; los intentos rechazados no cuentan).

## Qué significan los colores

La tarjeta siempre trae un **título y un ícono**, además del color, para que se entienda aunque no se distinga bien el color.

| Color | Título | Qué significa | ¿Puede entrar? |
|---|---|---|---|
| Verde | BIENVENIDO | La membresía está vigente. | Sí |
| Amarillo | POR VENCER | Le quedan pocos días de plan (5 o menos por defecto). Dice "Tu plan vence el dd/mm/aaaa (faltan X días)". | Sí |
| Amarillo | BIENVENIDO · SALDO PENDIENTE | Está vigente pero quedó debiendo dinero de antes (hoy ya no se reciben abonos). | Sí, recuérdele el saldo |
| Amarillo | BIENVENIDO · CASILLERO VENCIDO | La membresía está bien, pero el casillero ya no está pagado. | Sí, ofrézcale renovar el casillero |
| Rojo + sonido | MEMBRESÍA VENCIDA | Su plan ya terminó. | No, salvo que renueve o se autorice |
| Rojo + sonido | SIN MEMBRESÍA | Nunca ha tenido un plan, o todos están anulados. | No, salvo que renueve o se autorice |
| Rojo + sonido | SU PLAN AÚN NO INICIA | Pagó un plan que empieza en una fecha futura. | No, salvo que se autorice |
| Rojo + sonido | CLIENTE INACTIVO | El cliente está inactivo. | No, salvo que se active (F5) o un administrador lo autorice |

El último día del plan el cliente **todavía puede entrar** (le quedan 0 días y la tarjeta sale amarilla).

## Qué muestra la tarjeta

- Foto, nombre y código.
- Plan, fecha de vencimiento y días que le quedan.
- Casillero asignado y hasta cuándo está pagado ("vence en N días" o "vencido hace N días · sugerido liberar").
- Saldo pendiente, si debe algo.
- **Alertas** que alguien dejó en su ficha (por ejemplo "falta copia del documento"). Las críticas aparecen primero.
- Un saludo de **cumpleaños**, si cumple años hoy.

## Cuando la tarjeta sale roja

Según el caso aparecen estos botones:

- **Renovar ahora (F2):** abre la renovación de la membresía del cliente que está en la tarjeta, con su último plan ya elegido. Sirve para la tarjeta roja y también para pagar por adelantado a un cliente al día (la nueva membresía empieza el día siguiente al vencimiento). Registre el pago (Recepción necesita la clave de un administrador). Si el ingreso había sido negado, al guardar pasa a "permitido". No aparece para clientes inactivos; si pulsa F2 sin un cliente en la tarjeta, un aviso le dice qué hacer. Ver [Pagos y membresías](tema:pagos).
- **Ingreso autorizado (F3):** deja entrar al cliente sin renovar. Pide el **usuario y la contraseña de un administrador** y, si quiere, un motivo (por ejemplo "paga mañana"). Queda en la auditoría a nombre del administrador que autorizó. Si un administrador tiene la sesión abierta, su usuario ya aparece escrito y solo pone la contraseña.

- **Activar cliente (F5):** solo aparece cuando la tarjeta dice **CLIENTE INACTIVO**. Pide la **clave de un administrador**, activa al cliente (conserva su mismo código) y abre enseguida **Renovar membresía** para cobrarle la mensualidad, sin volver a pedir la clave. Al guardar el pago, el ingreso pasa a "permitido". Si cancela el cobro, el cliente queda activo y puede cobrarle después con **F2**.
- **Ver ficha (F4):** abre la ficha del cliente.

Un cliente con **membresía vencida** sigue activo: para él se usa **Renovar ahora (F2)**, no Activar.

Si la contraseña del administrador se escribe mal varias veces, ese usuario se bloquea igual que en el inicio de sesión.

## Si el cliente ya entró hoy

Si el cliente ya registró un ingreso hoy, la tarjeta dice **"Ya ingresó hoy a las HH:MM"**. Por defecto el sistema pregunta:

- Presione **Enter** (con el campo vacío) para registrar otro ingreso.
- Presione **Esc** para cancelar.

El administrador puede cambiar esta regla en Configuración para que **no permita** un segundo ingreso o para que lo registre **sin avisar**.

## Cliente que no recuerda su código

Presione **F6** (buscar manual) y escriba el documento, el nombre, el apellido o el teléfono. Si hay varios resultados, elija el correcto con las flechas y Enter. El ingreso se registra igual que con el código.

Si escribe un código que no existe, la tarjeta dice que no se encontró y suena la alerta.

## ¿Dónde está la lista de ingresos de hoy?

Recepción ya no muestra la lista al lado de la tarjeta, para que la tarjeta se vea grande. Los ingresos del día están en el módulo **Asistencia**.

## Atajos de teclado

| Tecla | Qué hace |
|---|---|
| **Enter** | Registra el código escrito. Con el campo vacío confirma un segundo ingreso del día. |
| **Esc** | Cancela el segundo ingreso o borra lo escrito. |
| **F2** | Renovar ahora (cliente de la tarjeta). |
| **F3** | Ingreso autorizado (tarjeta roja). |
| **F4** | Abre la ficha del cliente de la tarjeta. |
| **F5** | Activar cliente (solo si la tarjeta dice CLIENTE INACTIVO). |
| **F6** | Busca un cliente por documento, nombre o teléfono. |
| **F11** | Pantalla completa: oculta el menú y la barra. Presione F11 otra vez para volver. |
| **Ctrl +** / **Ctrl −** / **Ctrl 0** | Agranda, achica o deja normal la letra. El tamaño se recuerda en este computador. |
| **F1** | Abre esta ayuda. |

## Preguntas frecuentes

**¿Por qué Recepción no cierra la sesión sola como las demás pantallas?**
Para que la entrada del gimnasio nunca se interrumpa. Si se aleja del computador, use **Cerrar sesión**.

**El cliente pagó pero sale rojo.**
Revise en su ficha (F4) que la membresía no esté anulada y que la fecha de inicio no sea futura.

**¿Dónde veo todos los ingresos de hoy?**
En el módulo [Asistencia](tema:asistencia) o en [Reportes](tema:reportes) → "Asistencia del día".
