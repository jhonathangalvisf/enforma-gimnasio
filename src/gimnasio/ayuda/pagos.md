# Pagos, membresías y caja

Este tema explica cómo se venden y renuevan las membresías, cómo se registran los pagos y abonos, cómo se imprimen los recibos y cómo se hace el cierre de caja.

**Las membresías y los pagos se registran desde la ficha del cliente.** Búsquela con **Ctrl+K**. El módulo **Pagos** del menú muestra la caja del día.

## Membresía y plan

- Un **plan** es lo que se vende: por ejemplo Mensual (30 días), Quincenal (15), Trimestral (90) o Día (1). El administrador los crea y les pone precio en [Configuración](tema:configuracion) → Planes.
- Una **membresía** es un plan vendido a un cliente, con fecha de inicio y de vencimiento.
- El vencimiento se calcula solo: **inicio + días del plan − 1**. Por ejemplo, un plan de 30 días que empieza el 01/03/2026 vence el 30/03/2026, y el cliente puede entrar hasta ese día inclusive.

## Vender o renovar una membresía

1. Abra la ficha del cliente y vaya a la pestaña **Membresías**.
2. Pulse **Renovar membresía (Ctrl+R)**. Desde Recepción, con la tarjeta roja, también puede presionar **F2**.
3. Ya viene elegido el último plan del cliente. Cámbielo si hace falta.
4. Revise la fecha en que **inicia**. Debajo aparece hasta cuándo **vence**.
5. En **Pago ahora** ponga el **monto**, el **método** (efectivo, tarjeta o transferencia) y la **referencia** (obligatoria con tarjeta o transferencia: el número de aprobación o de la transacción).
6. Pulse **Registrar**. Si dejó marcada la casilla, se abre el recibo para imprimirlo.

### Cuándo empieza la nueva membresía

- Si el cliente **todavía está vigente**, la nueva membresía empieza **el día siguiente** a su vencimiento actual, para que no pierda días. (El administrador puede cambiar esta regla para que empiece hoy.)
- Si **ya está vencido**, empieza **hoy** o en la fecha que se elija.
- Recepción puede poner una fecha de inicio de hasta 30 días atrás; más atrás solo el administrador. Nunca más de 90 días adelante.
- No se pueden vender membresías a clientes inactivos ni con planes desactivados.

### Abonos (pago parcial)

Si el cliente no paga todo, escriba en el monto solo lo que pagó: la diferencia queda como **saldo pendiente**. También puede marcar **Registrar sin pago** para que todo quede como saldo.

Cuando traiga el resto, en la pestaña **Membresías** seleccione la membresía y pulse **Registrar abono…**. Ningún pago puede ser mayor que el saldo.

Un cliente con saldo **puede entrar**: en Recepción la tarjeta sale amarilla con "SALDO PENDIENTE", y la ficha muestra el aviso arriba.

### Precio distinto o descuento (solo administrador)

Solo el administrador puede cambiar el **precio** del plan en una venta. Cuando el precio es distinto, el sistema pide el **motivo** del descuento y queda en la auditoría.

## Otros pagos

En la pestaña **Pagos** de la ficha, **Registrar otro pago…** sirve para cobros que no son membresía ni casillero (concepto "Otro"). El pago del casillero se registra al asignarlo o renovarlo en [Casilleros](tema:casilleros).

## Recibos

Cada pago tiene un **recibo con número consecutivo** (por ejemplo R-000123) que nunca se repite. El recibo trae el logo y los datos del gimnasio, el cliente, el concepto, las fechas, el método, el valor, el saldo que quedó y quién atendió.

Para verlo o reimprimirlo, seleccione el pago y pulse **Ver / imprimir recibo** (en la ficha o en la pantalla Pagos). Se abre en el visor de PDF del computador, desde donde se imprime. Los recibos se guardan en la carpeta de datos del programa.

El recibo no es una factura electrónica.

## Anular un pago o una membresía (solo administrador)

Los pagos y las membresías **no se borran**: se anulan con un **motivo** obligatorio.

- **Anular pago…:** en la ficha (pestaña Pagos) o en la pantalla Pagos. El pago deja de sumar en la caja y en los reportes, y su recibo se reimprime con la marca "ANULADO".
- **Anular membresía…:** en la pestaña Membresías. Anula también todos sus pagos con el mismo motivo.

Si se anula un pago de casillero, la fecha del casillero no cambia sola: el administrador la ajusta con **Corregir vencimiento** en Casilleros.

## Cierre de caja (pantalla Pagos)

Muestra los pagos de un día con totales por **método** (efectivo, tarjeta, transferencia), el **total del día**, los **anulados** (se ven pero no suman), la tabla **por usuario** y la lista de **pagos del día**.

- **Recepción** ve solo **su propia caja de hoy**.
- **El administrador** elige cualquier **día** y cualquier **usuario** (o todos), y pulsa **Actualizar**.

Al final del turno, compare el efectivo que hay en la caja con el total de "Efectivo" de su cierre. El cierre también está en [Reportes](tema:reportes), con exportación a Excel y PDF.

## Preguntas frecuentes

**Me equivoqué en el monto de un pago.**
Pida al administrador que lo anule con el motivo y registre el pago otra vez.

**El cliente quiere pagar por adelantado.**
Renueve normalmente: si todavía está vigente, la nueva membresía empieza cuando termine la actual.

**No aparece ningún plan al renovar.**
No hay planes activos. El administrador debe activarlos en Configuración → Planes.
