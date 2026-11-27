# Primeros pasos

Bienvenido al sistema del gimnasio. Esta página explica cómo está organizada la aplicación y los atajos de teclado que sirven en todas partes.

## Entrar al sistema

1. Escriba su **usuario** y presione **Enter**.
2. Escriba su **contraseña** y presione **Enter**.

Si el administrador le creó la cuenta o le restableció la contraseña, el sistema le pedirá cambiarla la primera vez que entre. La contraseña debe tener al menos 8 caracteres.

Si se equivoca varias veces seguidas (5 por defecto), el usuario queda **bloqueado unos minutos** (15 por defecto). Durante ese tiempo no entra ni con la contraseña correcta: espere o pida ayuda al administrador.

## Cómo está organizada la pantalla

- **Arriba:** el nombre del gimnasio, la **búsqueda de clientes** (Ctrl+K), su nombre y rol, y los botones **Cambiar contraseña** y **Cerrar sesión**.
- **Debajo, a veces:** una **barra amarilla** con avisos de las copias de seguridad, por ejemplo si la última copia tiene más de 2 días (ver [Copias de seguridad](tema:backups)). Si usted es de Recepción y la ve, avise al administrador.
- **A la izquierda:** el menú con los módulos. Cada persona ve solo los módulos que su rol puede usar.
- **En el centro:** la pantalla del módulo elegido.

| Módulo | Para qué sirve |
|---|---|
| [Recepción](tema:recepcion) | Registrar la entrada de los clientes con su código. |
| [Clientes](tema:clientes) | Registrar, buscar y consultar clientes, con su ficha completa. |
| [Asistencia](tema:asistencia) | Consultar y corregir los ingresos, y sus reportes. |
| [Casilleros](tema:casilleros) | Asignar, renovar y liberar casilleros. |
| [Invitados](tema:invitados) | Registrar visitas de invitados y contar cuántas veces han venido. |
| [Pagos](tema:pagos) | Ver la caja del día; las membresías y los pagos se registran en la ficha del cliente. |
| [Reportes](tema:reportes) | Todos los reportes con filtros, en pantalla, Excel o PDF. |
| [Configuración](tema:configuracion) | Parámetros, planes, usuarios y auditoría (solo administrador). |
| [Copias de seguridad](tema:backups) | Copias cifradas, disco externo y restauración (solo administrador). |
| Ayuda | Esta explicación. |

## Los dos roles

- **Recepción:** registra ingresos, clientes, membresías, pagos, casilleros e invitados, y ve los reportes del día. No puede anular pagos, cambiar precios, borrar asistencias de días anteriores ni entrar a Configuración.
- **Administrador:** puede hacer todo, incluidas las anulaciones, los descuentos, los reportes de ingresos, la configuración, los usuarios, la auditoría y las copias de seguridad.

El sistema revisa los permisos cada vez que alguien hace algo. Si un usuario intenta una acción que no le corresponde, aparece un aviso y no se hace nada.

## Qué nunca se borra

Para que siempre haya historial, el sistema **no borra** clientes, usuarios, pagos ni membresías:

- Los clientes y usuarios se **inactivan**.
- Los pagos y membresías se **anulan** con un motivo (solo el administrador).
- Las asistencias y las visitas de invitados se **eliminan** con un motivo, pero quedan guardadas y el administrador las puede ver.
- Los casilleros se **liberan**, y queda en el historial quién lo tenía y hasta cuándo.

Todo esto queda en la **auditoría**, que el administrador consulta en Configuración.

## Atajos de teclado generales

| Tecla | Qué hace |
|---|---|
| **F1** | Abre la ayuda del módulo o ventana en el que está. |
| **Ctrl+K** | Va a la búsqueda de clientes de la barra superior. Escriba código, documento, nombre, teléfono o correo y presione Enter. |
| **Enter** | En los formularios, pasa al siguiente campo o confirma. |
| **Esc** | Cierra la ventana o cancela. |

Cada módulo tiene además sus propios atajos; están explicados en su página de ayuda.

## Cambiar su contraseña

Pulse **Cambiar contraseña** en la barra superior, escriba la actual y dos veces la nueva. Si olvidó su contraseña, el administrador se la puede restablecer desde [Usuarios](tema:usuarios).

## Cierre de sesión por inactividad

Si nadie toca el teclado ni el ratón durante un tiempo (15 minutos por defecto), la sesión se cierra sola para proteger los datos. **La pantalla de Recepción nunca se cierra sola**, para que el ingreso de clientes no se interrumpa.

## Fechas y dinero

- Las fechas se escriben y se muestran como **dd/mm/aaaa** (por ejemplo 05/03/2026) y en hora de Colombia.
- Los valores se muestran en pesos sin decimales, por ejemplo **$ 85.000**.

## Cómo usar esta ayuda

- Elija un tema en la lista de la izquierda.
- Escriba una palabra en el **buscador** (por ejemplo "saldo" o "casillero vencido"): la lista muestra solo los temas que la contienen y la palabra aparece resaltada en el texto.
- En cualquier pantalla, presione **F1** para abrir directamente la ayuda de ese módulo.
