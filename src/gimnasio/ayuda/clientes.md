# Clientes

En este módulo se registran los clientes del gimnasio, se buscan y se consulta toda su información en la **ficha del cliente**.

## Cuántos clientes están al día

Arriba de la lista hay una barra con los totales: **Al día** (vigentes y por vencer, es decir, con plan que no ha vencido), **Por vencer**, **Vencidos**, **Sin membresía**, **Inactivos** y el **Total**. Pulse cualquiera de ellos para ver solo esos clientes en la lista. Los totales se actualizan al registrar, modificar o renovar.

## Buscar un cliente

Si el cliente no recuerda su código, búsquelo por su **nombre**, **apellido** o **cédula**: la ficha muestra el código.

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
- **Vigencia:** al día (vigentes y por vencer), vigente, por vencer, vencida o sin membresía.
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
6. Si el cliente quiere casillero, marque **¿Desea casillero?**.
7. Pulse **Guardar**.

Al guardar se abre de una vez el cobro de la **mensualidad**. Si marcó el casillero, ahí mismo elige **a mano** uno de los casilleros libres de su zona, los días y el valor: la mensualidad y el casillero quedan en **un solo recibo con un solo número**. Si no lo quiere, solo paga la mensualidad; más adelante puede pagar un casillero desde [Pagos](tema:pagos) con **Pagar casillero…**.

El formulario muestra el **código que sigue** en el consecutivo (por ejemplo 001001). Ese es el código que el cliente da en [Recepción](tema:recepcion) para entrar. Entrégueselo o anótelo en un lugar donde el cliente lo tenga a mano.

**Código a mano (solo administrador):** el administrador puede borrar el código sugerido y escribir otro, por ejemplo 5000 para un cliente antiguo que ya tenía ese número. El consecutivo **no salta**: el siguiente cliente nuevo seguirá con 001001, y cuando el consecutivo llegue a un código ya usado lo salta solo. El consecutivo también se puede ajustar en [Configuración](tema:configuracion) → Parámetros → Clientes.

**Un cliente, un código.** El documento no puede repetirse. Si inscribe a alguien cuya cédula ya está registrada, el sistema le recuerda su nombre y su **código antiguo** y abre su ficha. Si estaba inactivo, el administrador puede **reactivarlo** ahí mismo y conserva su código; Recepción debe pedírselo al administrador.

Tipos de documento: CC y TI (solo números, de 5 a 11 dígitos), CE, Pasaporte y PPT.

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
- **El administrador** puede cambiar todo, incluso el **código** (si quedó mal o el cliente tenía otro). El código anterior deja de servir en Recepción y el cambio queda en la auditoría.

Cada cambio queda en la auditoría con el valor anterior y el nuevo.

## Cambiar la vigencia a mano (solo administrador)

Para dar días de cortesía, corregir una fecha o asignar una vigencia a un cliente en especial, pulse **Cambiar vigencia…** en la ficha:

1. Escriba la nueva fecha de vencimiento (dd/mm/aaaa). Puede alargarla o acortarla, pero no antes del inicio de la membresía (para quitarla, anúlela desde [Pagos](tema:pagos)).
2. Si el cliente no tiene ninguna membresía, elija también el plan: se crea una membresía sin cobro.
3. Escriba el motivo (obligatorio) y pulse **Guardar**.

El cambio no genera pagos y queda en la auditoría con la fecha anterior, la nueva y el motivo.

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
