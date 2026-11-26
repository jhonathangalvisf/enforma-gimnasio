# Clientes

En este módulo se registran los clientes del gimnasio, se buscan y se consulta toda su información en la **ficha del cliente**.

## Buscar un cliente

Escriba en el buscador de la pantalla (o presione **Ctrl+F** para ir a él). La lista se actualiza mientras escribe. Puede buscar por:

- **Código** (con o sin los ceros de la izquierda).
- **Documento** o **teléfono** (desde 3 números, busca los que empiezan así).
- **Nombre o apellido**, sin importar tildes ni mayúsculas ("jose" encuentra a "José").
- **Correo**.

Con 1 o 2 números solo busca el código exacto, para no mostrar miles de teléfonos.

Desde cualquier pantalla también puede usar **Ctrl+K** (la búsqueda de la barra superior): si hay un solo resultado abre la ficha de una vez; si hay varios, muestra una lista para elegir.

## Filtros

Debajo del buscador hay filtros que se pueden combinar:

- **Estado:** activo o inactivo.
- **Vigencia:** vigente, por vencer, vencida o sin membresía.
- **Sexo** y **plan**.
- **Cumpleaños** de un mes.
- **Sin asistir hace N días** (incluye a quienes nunca han venido).
- **Registrados desde / hasta** una fecha (dd/mm/aaaa).

**Limpiar filtros** los quita todos. Haga clic en el título de una columna para ordenar por ella.

La **vigencia** no se escribe a mano: el sistema la calcula cada vez con la última membresía no anulada. El **estado** (activo o inactivo) es aparte y solo lo cambia el administrador.

## Registrar un cliente nuevo

1. Pulse **Nuevo cliente** o presione **Ctrl+N**.
2. Llene los datos. Los marcados con * son obligatorios: tipo y número de documento, nombres, apellidos y sexo.
3. Teléfonos y correos: puede poner varios separados por coma; **el primero es el principal**.
4. Si quiere, agregue fecha de nacimiento (dd/mm/aaaa), dirección, contacto de emergencia, notas y una **foto** (PNG o JPG de máximo 5 MB).
5. Marque la **autorización de tratamiento de datos** cuando el cliente la firme: se guarda la fecha.
6. Pulse **Guardar**.

El sistema le asigna un **código de 6 dígitos** que no se puede cambiar. Ese es el código que el cliente da en [Recepción](tema:recepcion) para entrar. Entrégueselo o anótelo en un lugar donde el cliente lo tenga a mano.

Tipos de documento: CC y TI (solo números, de 5 a 11 dígitos), CE, Pasaporte y PPT. El documento no puede repetirse: si ya existe, el sistema avisa.

## La ficha del cliente

Se abre con doble clic en la lista, con **Ver ficha**, con Ctrl+K o con F4 en Recepción. Arriba muestra el nombre, el código, la vigencia y un aviso si tiene saldo pendiente. Tiene estas pestañas:

| Pestaña | Qué tiene |
|---|---|
| **Datos** | Datos personales, foto y autorización de datos. |
| **Contactos** | Teléfonos, correos y contacto de emergencia. |
| **Membresías** | Todos sus planes con lo pagado y el saldo. Aquí se renueva (**Ctrl+R**) y se registran abonos. Ver [Pagos](tema:pagos). |
| **Pagos** | Todos sus pagos, con sus recibos. |
| **Asistencias** | Sus ingresos al gimnasio. |
| **Casillero** | El casillero que tiene y su historial. Ver [Casilleros](tema:casilleros). |
| **Alertas** | Notas que aparecen en Recepción cada vez que entra. |

## Modificar los datos

Pulse **Modificar datos** en la ficha (o use el menú del clic derecho en la lista).

- **Recepción** puede cambiar teléfonos, correos, contacto de emergencia, dirección, la foto y registrar la autorización de datos.
- **El administrador** puede cambiar todo, menos el código.

Cada cambio queda en la auditoría con el valor anterior y el nuevo.

## Alertas del cliente

En la pestaña **Alertas**, pulse **Nueva alerta…**, escriba el mensaje (por ejemplo "falta copia del documento") y elija el nivel: **información**, **advertencia** o **crítica**. Si solo aplica unos días, marque **Solo hasta una fecha** y elija el último día. La alerta aparece en la tarjeta de Recepción cada vez que el cliente entra, hasta que alguien pulse **Marcar como resuelta**. Las alertas no se borran.

## Inactivar o activar un cliente (solo administrador)

Pulse **Inactivar cliente…** en la ficha y escriba el motivo. Un cliente inactivo **no puede entrar** (sale rojo en Recepción) aunque tenga plan vigente. Si tiene casillero, el sistema pregunta si lo libera o lo conserva.

Los clientes **nunca se borran**: así se conserva su historial de pagos y asistencias. Para que vuelva, use **Activar cliente**.

## Exportar la lista (solo administrador)

**Exportar a Excel** o **Exportar a PDF** guarda la lista tal como está filtrada. Queda en la auditoría porque contiene datos personales.

## Atajos de teclado

| Tecla | Qué hace |
|---|---|
| **Ctrl+N** | Nuevo cliente. |
| **Ctrl+F** | Ir al buscador. |
| **Ctrl+K** | Búsqueda rápida desde cualquier pantalla. |
| **Ctrl+R** | En la ficha: renovar membresía. |
| **F1** | Esta ayuda. |
