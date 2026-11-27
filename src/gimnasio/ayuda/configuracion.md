# Configuración

Configuración es **solo para el administrador**. Tiene cuatro pestañas: **Parámetros**, **Usuarios**, **Planes** y **Auditoría**. Los usuarios se explican en [Usuarios](tema:usuarios).

## Parámetros

Son los ajustes del sistema. Cambie los valores y pulse **Guardar cambios**; **Descartar cambios** vuelve a los guardados. Si deja el ratón encima de un campo, aparece una explicación. Cada cambio queda en la auditoría con el valor anterior y el nuevo.

### Membresías y asistencia

| Parámetro | Qué hace | Por defecto |
|---|---|---|
| Días para avisar "por vencer" | Cuántos días antes del vencimiento la tarjeta de Recepción sale amarilla. | 5 |
| Si el cliente ya ingresó hoy | **Avisar y pedir confirmación**, **No permitir un segundo ingreso** o **Registrar sin avisar**. También aplica a invitados. | Avisar |
| Si renueva antes de vencer | La nueva membresía inicia **el día siguiente al vencimiento** o **hoy** (pierde los días que le quedaban). | Día siguiente |

### Clientes

| Parámetro | Qué hace | Por defecto |
|---|---|---|
| Siguiente código de cliente | Código que se sugiere al inscribir. Los códigos ya usados se saltan solos. 0 = seguir después del código más alto. Se actualiza solo con cada inscripción. | 0 |

### Casilleros

| Parámetro | Qué hace | Por defecto |
|---|---|---|
| Días que cubre el pago del casillero | Días que se proponen al asignar o renovar. Se puede cambiar en cada caso. | 30 |
| Precio sugerido del casillero | Valor que se propone al cobrar. 0 = sin precio sugerido. | 0 |
| Sugerir liberar tras días vencido | Después de cuántos días vencido se marca "sugerido liberar". | 15 |

### Invitados

| Parámetro | Qué hace | Por defecto |
|---|---|---|
| Máximo de visitas de un invitado al mes | Al llegar a este número, la visita necesita la contraseña de un administrador. 0 = sin límite. | 0 |

### Seguridad

| Parámetro | Qué hace | Por defecto |
|---|---|---|
| Cerrar sesión tras minutos sin uso | Cierra la sesión si nadie usa el programa. No aplica a Recepción. Rige desde el siguiente inicio de sesión. | 15 |
| Intentos fallidos antes de bloquear | Contraseñas equivocadas seguidas antes de bloquear al usuario. | 5 |
| Minutos de bloqueo | Cuánto dura el bloqueo. | 15 |

### Copias de seguridad

| Parámetro | Qué hace | Por defecto |
|---|---|---|
| Hora de la copia diaria | Hora del día (0 a 23) en que se hace la copia automática si el programa está abierto. Además siempre se hace al cerrar. | 21 (9:00 p. m.) |

El disco externo, la contraseña y la restauración se manejan en [Copias de seguridad](tema:backups).

### Datos del gimnasio y recibos

- **Nombre, NIT, dirección y teléfono:** salen en los recibos y en los reportes.
- **Logo para recibos:** pulse **Elegir imagen…** (PNG o JPG de máximo 2 MB) o **Quitar**.
- **Prefijo de recibos:** el texto que va antes del número, por ejemplo "R-".
- **Siguiente número de recibo:** solo puede **aumentar**, para no repetir números ya entregados.

## Planes

Aquí se crean los planes que se venden. Cada plan tiene **nombre**, **duración** en días y **precio**.

- **Nuevo plan:** crea uno. El nombre no se puede repetir.
- **Editar** (o doble clic): cambia nombre, duración o precio. Las membresías ya vendidas **no cambian**.
- **Desactivar / Activar:** un plan desactivado deja de ofrecerse al renovar, pero las membresías que ya tienen ese plan siguen igual.

Los planes **no se borran**. Si no hay ningún plan activo para vender, el sistema deja listos los planes del gimnasio: Mensual (30 días), Quincena (15), Semana (7), Trimestre (90), Semestre (180) y Año (365), **activos y con precio de $1** (en el recibo lo que importa es qué plan eligió el cliente). Puede cambiarles el precio cuando quiera. Un plan con precio $0 no se puede vender.

## Auditoría

La auditoría es el registro de las acciones importantes: inicios de sesión (y los fallidos), cambios de datos de clientes, pagos y anulaciones, ingresos autorizados, asistencias eliminadas, movimientos de casilleros, cambios de configuración, exportaciones de reportes, etc.

Para buscar:

1. Elija el periodo (**Desde / Hasta**).
2. Si quiere, elija un **usuario** y una **acción**.
3. Escriba una palabra para **buscar en el detalle** (por ejemplo un código de cliente).
4. Pulse **Buscar**.

Cada línea muestra la fecha y hora, quién lo hizo, la acción y el detalle (por ejemplo, en un cambio de datos, el valor anterior y el nuevo). La auditoría **no guarda contraseñas** y no se puede modificar.

## Importar datos del programa anterior

Trae los datos del programa viejo del gimnasio (el de dBase, carpeta **DB3** con archivos `.DBF`). Solo el administrador lo ve. La carpeta original **no se modifica**: se copia a la carpeta de datos (`importaciones`) y se lee la copia.

1. Pulse **Elegir carpeta…** y busque la carpeta **DB3** (la que tiene `ENCLIE.DBF`).
2. Pulse **Probar sin guardar**. No se guarda nada; se crea un **informe en Excel** con el resumen y la hoja **Problemas** (fila por fila: qué estaba mal y qué se hizo). Ábralo con **Abrir informe en Excel**.
3. Si está de acuerdo, pulse **Importar de verdad**. Antes se hace una **copia de seguridad** (configure primero la contraseña de las copias); si la copia falla, no se importa nada. Solo se puede importar **una vez**.

Qué se trae:

- **Clientes** activos e inactivos, con el **mismo código** del programa anterior (por ejemplo, el 245 queda `000245`), documento, nombres, sexo, nacimiento, dirección, teléfono y acudiente. Los códigos nuevos siguen después del más alto.
- **Vigencia:** a cada cliente se le crea una membresía del plan **«Programa anterior»** que termina en su fecha de vencimiento, con **valor $0 y sin pagos** (los valores del programa viejo no eran reales). Así Recepción ve el color correcto desde el primer día.
- **Asistencias** con una hora aproximada según la franja (mañana 7:00, tarde 3:00 p. m., noche 7:00 p. m.).
- **Casilleros** con su zona (hombres, mujeres o mixto) y los ocupados con su cliente y fecha de vencimiento.
- **Invitados** con su número de visitas. Las fechas de la primera y la última visita quedan como visitas; las demás se suman al contador como «del programa anterior sin fecha».

Qué **no** se trae: los pagos (sus valores no eran reales), los datos de salud y las medidas.

Clientes **«Sin documento»**: si un cliente no tenía cédula, la tenía mal escrita o repetida con otro cliente, queda con el tipo «Sin documento (pendiente)». Búsquelos en el informe y escriba el documento correcto en su ficha (Modificar). Si dos códigos son la misma persona, inactive el que sobra.
