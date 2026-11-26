# Casilleros

Aquí se manejan los casilleros: a quién se le asigna cada uno, hasta cuándo está pagado, cuándo se renueva y cuándo se libera.

## Reglas importantes

- **Un cliente tiene como máximo un casillero**, y **un casillero tiene como máximo un cliente**. El sistema no deja asignar un segundo.
- El casillero tiene **su propio vencimiento**, distinto al de la membresía. Por defecto cada pago cubre 30 días.
- **Zonas:** los casilleros de la zona **hombres** son solo para hombres, los de **mujeres** solo para mujeres, y los **mixtos** para cualquiera. Al asignar, el sistema solo ofrece los casilleros de la zona que le corresponde al cliente.
- Un casillero **nunca se libera solo**: el sistema sugiere cuáles liberar y una persona lo confirma.

## La pantalla Casilleros

Arriba se ven los totales: **disponibles, ocupados, en mantenimiento, vencidos y sugeridos para liberar**. Debajo, la lista con filtros por estado, zona, sexo de quien lo ocupa y situación (casillero vencido, casillero por vencer, membresía del cliente vencida o sugerido liberar). Puede buscar por número de casillero, código o nombre del cliente.

Haga **doble clic** sobre un casillero para asignarlo (si está libre) o renovarlo (si está ocupado).

## Asignar un casillero

Desde esta pantalla:

1. Seleccione un casillero disponible y pulse **Asignar…**.
2. Escriba el código, documento, nombre o teléfono del cliente y presione **Enter**.
3. Revise la fecha de inicio y los **días** que cubre el pago.
4. Si el cliente paga en ese momento, ponga el **monto** y el **método** de pago (con referencia si es tarjeta o transferencia).
5. Pulse **Asignar casillero**. Si registró pago, se genera el recibo.

También se puede asignar desde la **ficha del cliente**, en la pestaña **Casillero** → **Asignar casillero…**. Ahí solo aparecen los casilleros libres de su zona.

El pago del casillero se registra **al asignarlo o renovarlo**, para que la fecha de vencimiento se mueva con el pago.

## Renovar

Seleccione el casillero y pulse **Renovar…** (o en la ficha, **Renovar casillero…**). Si el casillero todavía está al día, el nuevo periodo empieza el día siguiente al vencimiento; si ya venció, empieza hoy.

## Cambiar de casillero

**Cambiar de casillero…** pasa al cliente a otro casillero libre **conservando lo que ya pagó**. El anterior queda en el historial con la nota "Cambio al casillero X".

## Liberar

Seleccione el casillero y pulse **Liberar…**. Elija el motivo: **vencido**, **ya no lo quiere**, **cliente inactivo** u **otro** (con detalle). El casillero vuelve a quedar disponible y en el historial queda la fecha, quién lo liberó y el motivo.

Cuando se inactiva a un cliente que tiene casillero, el sistema pregunta si se libera o se conserva.

## Sugeridos para liberar

El sistema marca "sugerido liberar" cuando el cliente está **inactivo** o cuando el casillero lleva **vencido más de 15 días** (el administrador cambia este número en Configuración). Aparece en la lista, en la ficha del cliente y en la tarjeta de Recepción. Revise el caso y libérelo si corresponde.

## En Recepción

La tarjeta del cliente muestra "Casillero 015 pagado hasta…", "vence en N días" o "vencido hace N días". Si la membresía está bien pero el casillero venció, la tarjeta sale **amarilla** ("BIENVENIDO · CASILLERO VENCIDO") y el cliente puede entrar: es el momento de ofrecerle renovar.

## Historial y ficha

- **Historial:** todos los clientes que han tenido ese casillero, con fechas, "pagado hasta" y quién lo liberó.
- **Ficha del cliente:** abre la ficha de quien lo ocupa.

## Pestaña "Asignados y liberados por día"

Elija una fecha y pulse **Consultar** para ver qué casilleros se asignaron y cuáles se liberaron ese día.

## Exportar

Las listas se pueden **Exportar a Excel**, **Exportar a PDF** o **Imprimir**.

## Solo el administrador

- **Nuevo casillero…:** crea uno con número, zona y notas.
- **Crear varios…:** crea un rango de una vez (por ejemplo del 1 al 50, con prefijo "A-"). Omite los que ya existen.
- **Editar…:** cambia número, zona o notas. No deja poner en una zona que no corresponda a quien lo ocupa.
- **Mantenimiento:** saca un casillero de uso con una nota (por ejemplo "chapa dañada"). Si está ocupado, primero hay que liberarlo. Cuando está en mantenimiento, el mismo botón dice **Habilitar** y lo vuelve a poner disponible.
- **Corregir vencimiento…:** cambia la fecha "pagado hasta" con un motivo, por ejemplo después de anular un pago de casillero.

Los casilleros no se borran; si ya no se usan, se ponen en mantenimiento.
