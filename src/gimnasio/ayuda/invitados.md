# Invitados

Aquí se registran las personas que vienen al gimnasio **sin ser clientes**, por ejemplo alguien que viene a conocer o un amigo que trae un cliente. El sistema lleva la cuenta de **cuántas veces ha venido cada invitado** y en qué fechas.

## Reglas

- Los invitados **no pagan**.
- No hay límite de invitados por cliente.
- El **documento** identifica a la persona: si un invitado vuelve, se usa el mismo registro y su contador de visitas sube. Nunca se duplica.
- El contador no se escribe a mano: el sistema cuenta las visitas registradas.
- El administrador puede poner un **máximo de visitas al mes** por invitado en Configuración. Por defecto no hay límite (0).

## Registrar una visita (solo con teclado)

1. Escriba el **documento** del invitado y presione **Enter**. Los puntos, espacios y guiones se quitan solos.
   - Si ya vino antes, aparece su nombre con **cuántas visitas lleva** y el cursor pasa directo a **Invitado por** (siga en el paso 3).
   - Si es nuevo, el cursor pasa al **nombre**: escríbalo completo y presione Enter.
2. **Teléfono:** opcional. Presione Enter para seguir.
3. **Invitado por:** si lo trae un cliente, escriba el código o el nombre del cliente y presione **Enter**. Es opcional.
4. Se registra la visita y el formulario queda listo para el siguiente.

También puede pulsar **Registrar visita**. **Limpiar** borra el formulario sin registrar.

Si el documento pertenece a un **cliente** del gimnasio, el sistema avisa: los clientes entran por [Recepción](tema:recepcion) con su código.

## Si el invitado ya vino hoy

Se usa la misma regla que en Recepción: por defecto avisa y pide confirmar antes de registrar otra visita.

## Si llegó al máximo de visitas del mes

Solo pasa si el administrador puso un límite. El sistema avisa y la visita necesita el **usuario y la contraseña de un administrador** (**Autorizar visita**). Si el administrador tiene la sesión abierta, autoriza directamente. Queda en la auditoría.

## Lista de invitados y ficha

Debajo del formulario está la lista de invitados con el total de visitas, las de este mes y la última visita. Busque por nombre (sin importar tildes), documento o teléfono.

Haga doble clic o pulse **Ver visitas…** para abrir la **ficha del invitado**. Muestra el **contador grande** de visitas, las visitas de este mes, la primera y la última, y una tabla con **cada fecha**: hora, cliente que lo invitó, quién la registró y quién la autorizó.

Desde la ficha:

- **Editar datos…:** corrige el nombre o el teléfono. Cambiar el documento solo lo puede hacer el administrador.
- **Eliminar visita…:** elimina una visita registrada por error, con motivo obligatorio. **Recepción** solo puede eliminar visitas **de hoy**; el administrador, de cualquier día y es el único que ve las eliminadas.

## Pestaña Reportes

Elija el reporte, el periodo y pulse **Generar**. Puede exportar a Excel, PDF o imprimir.

| Reporte | Qué muestra |
|---|---|
| Visitas de invitados | Las visitas del periodo. Puede filtrar por el cliente que invitó. |
| Visitas por invitado | Cuántas veces vino cada invitado en el periodo y en total. |
| Invitados por cliente anfitrión | Los clientes que trajeron invitados y cuántos. |

**Recepción** solo ve el reporte de visitas de hoy.

Las visitas de invitados **no cuentan** en la asistencia de los clientes.
