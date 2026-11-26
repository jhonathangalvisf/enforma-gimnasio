# Recepción

Recepción es la pantalla de la entrada del gimnasio. Sirve para registrar el ingreso de cada cliente con su **código personal** y para ver de inmediato si puede entrar. Es la primera pantalla que se abre y está pensada para usarse **solo con el teclado**.

## Registrar el ingreso de un cliente

1. El cliente le dice su **código** (el número de 6 dígitos que le dio el gimnasio).
2. Escríbalo en el campo **Código del cliente** y presione **Enter**. No hace falta escribir los ceros de la izquierda: "57" es lo mismo que "000057".
3. Aparece una **tarjeta grande** con el resultado y el ingreso queda guardado.
4. El campo se limpia solo y queda listo para el siguiente cliente.

El campo de código está **siempre seleccionado**: no hace falta hacer clic en él. Si más adelante se usa un lector USB, este escribe el código y presiona Enter por usted.

## Qué significan los colores

La tarjeta siempre trae un **título y un ícono**, además del color, para que se entienda aunque no se distinga bien el color.

| Color | Título | Qué significa | ¿Puede entrar? |
|---|---|---|---|
| Verde | BIENVENIDO | La membresía está vigente. | Sí |
| Amarillo | POR VENCER | Le quedan pocos días de plan (5 o menos por defecto). Dice "Tu plan vence el dd/mm/aaaa (faltan X días)". | Sí |
| Amarillo | BIENVENIDO · SALDO PENDIENTE | Está vigente pero debe dinero de un abono. | Sí, recuérdele el saldo |
| Amarillo | BIENVENIDO · CASILLERO VENCIDO | La membresía está bien, pero el casillero ya no está pagado. | Sí, ofrézcale renovar el casillero |
| Rojo + sonido | MEMBRESÍA VENCIDA | Su plan ya terminó. | No, salvo que renueve o se autorice |
| Rojo + sonido | SIN MEMBRESÍA | Nunca ha tenido un plan, o todos están anulados. | No, salvo que renueve o se autorice |
| Rojo + sonido | SU PLAN AÚN NO INICIA | Pagó un plan que empieza en una fecha futura. | No, salvo que se autorice |
| Rojo + sonido | CLIENTE INACTIVO | El administrador inactivó al cliente. | No, salvo que un administrador lo autorice |

El último día del plan el cliente **todavía puede entrar** (le quedan 0 días y la tarjeta sale amarilla).

## Qué muestra la tarjeta

- Foto, nombre y código.
- Plan, fecha de vencimiento y días que le quedan.
- Casillero asignado y hasta cuándo está pagado ("vence en N días" o "vencido hace N días · sugerido liberar").
- Saldo pendiente, si debe algo.
- **Alertas** que alguien dejó en su ficha (por ejemplo "falta copia del documento"). Las críticas aparecen primero.
- Un saludo de **cumpleaños**, si cumple años hoy.

## Cuando la tarjeta sale roja

Aparecen dos botones:

- **Renovar ahora (F2):** abre la renovación de la membresía con el último plan del cliente ya elegido. Registre el pago y, al guardar, el ingreso de ese momento pasa a "permitido". No aparece para clientes inactivos. Ver [Pagos y membresías](tema:pagos).
- **Ingreso autorizado (F3):** deja entrar al cliente sin renovar. Pide el **usuario y la contraseña de un administrador** y, si quiere, un motivo (por ejemplo "paga mañana"). Queda en la auditoría a nombre del administrador que autorizó. Si un administrador tiene la sesión abierta, su usuario ya aparece escrito y solo pone la contraseña.

Si la contraseña del administrador se escribe mal varias veces, ese usuario se bloquea igual que en el inicio de sesión.

## Si el cliente ya entró hoy

Si el cliente ya registró un ingreso hoy, la tarjeta dice **"Ya ingresó hoy a las HH:MM"**. Por defecto el sistema pregunta:

- Presione **Enter** (con el campo vacío) para registrar otro ingreso.
- Presione **Esc** para cancelar.

El administrador puede cambiar esta regla en Configuración para que **no permita** un segundo ingreso o para que lo registre **sin avisar**.

## Cliente que no recuerda su código

Presione **F6** (buscar manual) y escriba el documento, el nombre, el apellido o el teléfono. Si hay varios resultados, elija el correcto con las flechas y Enter. El ingreso se registra igual que con el código.

Si escribe un código que no existe, la tarjeta dice que no se encontró y suena la alerta.

## La lista de la derecha

Muestra los **últimos ingresos del día** y el **contador de asistentes de hoy** (cuenta personas distintas; si alguien entra dos veces cuenta una sola). Los intentos rechazados quedan guardados pero no cuentan como asistentes.

## Atajos de teclado

| Tecla | Qué hace |
|---|---|
| **Enter** | Registra el código escrito. Con el campo vacío confirma un segundo ingreso del día. |
| **Esc** | Cancela el segundo ingreso o borra lo escrito. |
| **F2** | Renovar ahora (tarjeta roja). |
| **F3** | Ingreso autorizado (tarjeta roja). |
| **F4** | Abre la ficha del cliente de la tarjeta. |
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
