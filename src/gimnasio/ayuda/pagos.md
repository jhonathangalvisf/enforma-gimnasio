# Pagos, membresías y caja

Este tema explica cómo se venden y renuevan las membresías, cómo se registran los pagos y abonos, cómo se imprimen los recibos y cómo se hace el cierre de caja.

**Las membresías y los pagos se registran desde la ficha del cliente.** Búsquela con **Ctrl+K**. El módulo **Pagos** del menú muestra la caja del día.

## Clave de administrador (Recepción)

Recepción solo puede cobrar con la **clave de un administrador**, y se pide **cada vez**:

- Al **registrar cualquier pago**: mensualidad, abono, casillero u otro (desde la ficha, con **F2** en Recepción o desde Pagos).
- Al **inscribir un cliente nuevo**. La misma clave sirve para cobrar la mensualidad de esa inscripción (y el casillero, si lo pidió): no se pide dos veces.
- Al **abrir el módulo Pagos**. Mientras la pantalla esté abierta se puede ver la caja y consultar; al salir del módulo se vuelve a bloquear.

Aparece una ventana donde el administrador escribe su **usuario y contraseña**. Si se equivoca, cuenta para el bloqueo igual que al iniciar sesión. Si el cobro falla por otro motivo (por ejemplo falta la referencia), al corregirlo no se vuelve a pedir la clave. Cada cobro queda en la auditoría con el administrador que lo autorizó.

Si quien trabaja es administrador, no se le pide nada.

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
6. Si el cliente también paga el **casillero**, marque **Pagar también el casillero (en el mismo recibo)**: si ya tiene uno, se renueva; si no, elija a mano uno libre de su zona. Ponga los días y el valor.
7. Pulse **Registrar**. Si dejó marcada la casilla, se abre el recibo para imprimirlo.

### Mensualidad y casillero en un solo recibo

Cuando se pagan juntos, sale **un solo recibo con un solo número** (por ejemplo R-000123) que trae los dos conceptos, cada uno con su valor, y el **total pagado**. Los dos usan el mismo método de pago. Para cobrar el casillero junto con la mensualidad hay que registrar pago de la mensualidad (no "sin pago").

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

En la pestaña **Pagos** de la ficha, **Pagar mensualidad…** abre la renovación de la membresía (la vigencia se actualiza y sale en el recibo). **Otro concepto (no es mensualidad)…** sirve solo para cobros que no son membresía ni casillero (concepto "Otro"): **no cambia la vigencia**, y su recibo dice hasta qué día está al día el cliente.

### Pagar solo el casillero

En la pantalla **Pagos**, pulse **Pagar casillero…** y escriba el código, documento o nombre del cliente. Si no tiene casillero, elija **a mano** uno libre de su zona; si ya tiene uno, se renueva. Ponga los días y el valor y pulse el botón de guardar. Sale un recibo propio con el **siguiente número consecutivo**. También se puede hacer desde [Casilleros](tema:casilleros) o desde la pestaña Casillero de la ficha.

## Recibos

Cada recibo tiene un **número consecutivo** (por ejemplo R-000123) que nunca se repite. Un recibo puede tener dos conceptos cuando la mensualidad y el casillero se pagan juntos; si después se anula uno de los dos, el recibo lo muestra como ANULADO y el total solo cuenta el otro. El recibo mide **10 cm de alto** (ancho de media carta) y trae el logo y los datos del gimnasio (NIT, dirección, teléfono), el cliente, el concepto, las fechas, el método, el valor, el saldo que quedó y quién atendió.

Para verlo o reimprimirlo, seleccione el pago y pulse **Ver / imprimir recibo** (en la ficha o en la pantalla Pagos). Se abre en el visor de PDF del computador, desde donde se imprime. Los recibos se guardan en la carpeta de datos del programa.

El recibo no es una factura electrónica.

## Anular un pago o una membresía (solo administrador)

Los pagos y las membresías **no se borran**: se anulan con un **motivo** obligatorio.

- **Anular pago…:** en la ficha (pestaña Pagos) o en la pantalla Pagos. El pago deja de sumar en la caja y en los reportes, y su recibo se reimprime con la marca "ANULADO".
- **Anular membresía…:** en la pestaña Membresías. Anula también todos sus pagos con el mismo motivo.

Si se anula un pago de casillero, la fecha del casillero no cambia sola: el administrador la ajusta con **Corregir vencimiento** en Casilleros.

## Cierre de caja (pantalla Pagos)

Muestra los pagos de un día con totales por **método** (efectivo, tarjeta, transferencia), el **total del día**, los **anulados** (se ven pero no suman), la tabla **por usuario** y la lista de **pagos del día**.

- **Recepción** ve solo **su propia caja de hoy**, después de que un administrador escriba su clave.
- **El administrador** elige cualquier **día** y cualquier **usuario** (o todos), y pulsa **Actualizar**.

Al final del turno, compare el efectivo que hay en la caja con el total de "Efectivo" de su cierre. El administrador también tiene el cierre en [Reportes](tema:reportes), con exportación a Excel y PDF.

## Preguntas frecuentes

**Me equivoqué en el monto de un pago.**
Pida al administrador que lo anule con el motivo y registre el pago otra vez.

**El cliente quiere pagar por adelantado.**
Renueve normalmente: si todavía está vigente, la nueva membresía empieza cuando termine la actual.

**No aparece ningún plan al renovar.**
No hay planes activos. El administrador debe activarlos en Configuración → Planes.

## Consultar pagos

En el módulo **Pagos**, pestaña **Consultar pagos**:

- **Por cliente:** escriba el código, el nombre o el documento y presione **Enter** o **Buscar cliente**. Salen todos sus pagos.
- **Por fecha de pago:** quite **Todas las fechas**, elija **desde** y **hasta** y pulse **Consultar**. También puede filtrar por método y concepto.
- Arriba de la tabla sale la cantidad y el total. Los pagos anulados se ven en rojo y **no suman**.
- **Exportar a Excel** o **Exportar a PDF** guarda la consulta. **Ver / imprimir recibo** (o doble clic) abre el recibo del pago elegido.

Recepción solo puede consultar los pagos de un cliente. Las consultas generales son para el administrador.

## Borrar pagos antiguos (solo administrador, con clave de seguridad)

Sirve para dejar en el sistema solo los pagos recientes. Está en la pestaña **Borrar pagos antiguos** y pide una **clave de seguridad** distinta de la contraseña de inicio de sesión.

- **La primera vez** cree la clave: escriba su contraseña de administrador y la nueva clave dos veces. Guárdela bien: para cambiarla hace falta la clave actual.
- Después de 5 intentos fallidos el apartado se bloquea 15 minutos. Al salir de la pestaña se vuelve a pedir la clave.

Para borrar:

1. Elija **Borrar pagos hasta el** (la fecha incluida; tiene que ser anterior a hoy).
2. Pulse **Ver qué se borraría**: dice cuántos pagos, por cuánto dinero y de qué fechas.
3. Escriba el **motivo** y pulse **Borrar pagos…**. Confirme.

Antes de borrar, el programa hace **siempre** una copia de seguridad cifrada y un **Excel** con todos los pagos que se quitan (carpeta `depuraciones` dentro de los datos del programa). Si la copia no se puede hacer, no se borra nada.

Lo que **nunca** se borra: la última membresía de cada cliente y sus pagos, ni una membresía que tenga pagos después de la fecha elegida. Así, la vigencia y el saldo de los clientes quedan igual. La numeración de los recibos sigue sin repetirse.

Si se borró algo por error, la única forma de recuperarlo es [restaurar la copia de seguridad](tema:backups) hecha justo antes.
