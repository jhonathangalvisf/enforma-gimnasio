# Copias de seguridad (backups)

Una copia de seguridad (backup) es una copia de **toda** la información del gimnasio: clientes, membresías, pagos, asistencias, casilleros, invitados, usuarios, configuración, las **fotos** de los clientes y el logo. Sirve para recuperar los datos si el computador se daña, se pierde, le entra un virus o alguien borra algo por error.

La pantalla **Copias de seguridad** es **solo para el administrador**. Recepción no la ve, pero las copias automáticas se hacen igual cuando Recepción cierra el programa.

## Lo primero: crear la contraseña de las copias

Las copias van **cifradas**: sin la contraseña nadie puede abrirlas, ni siquiera si se roban el disco.

1. Vaya a **Copias de seguridad** y pulse **Crear contraseña…**.
2. Escriba una contraseña de al menos 8 caracteres y repítala.
3. **Anótela en papel y guárdela en un lugar seguro fuera del computador** (por ejemplo, con los papeles del negocio). Marque la casilla **La anoté y la guardé en un lugar seguro** y pulse **Guardar**.

> **Muy importante:** si pierde esta contraseña, las copias **no se pueden recuperar**. Nadie, ni el soporte técnico, puede abrirlas sin ella.

El programa guarda la contraseña **protegida por Windows** en este computador, para hacer las copias automáticas sin preguntarla. Para **restaurar** siempre la pide.

Si cambia la contraseña con **Cambiar contraseña…**, las copias nuevas usan la nueva y las que ya existían **siguen abriéndose con la anterior**. Guarde también la anterior mientras tenga copias viejas.

## Cuándo se hacen las copias

- **Al cerrar el programa**, quien sea que lo cierre. Aparece la ventana "Haciendo copia de seguridad antes de cerrar…": espere unos segundos y no apague el computador.
- **A la hora diaria** (por defecto las **9:00 p. m.**), si el programa está abierto. Se hace en segundo plano: Recepción sigue funcionando normal. La hora se cambia en [Configuración](tema:configuracion) → Parámetros → Copias de seguridad.
- Con el botón **Backup ahora**, cuando el administrador quiera (por ejemplo, antes de un cambio grande).

Cada copia se revisa para comprobar que la base está completa (revisión de integridad), se comprime, se cifra y, después de escribirla, se vuelve a leer para confirmar que quedó bien en el disco.

## Dónde se guardan (regla 3-2-1)

Lo recomendable es tener **tres copias en dos lugares distintos, y una fuera del local**:

1. **En este PC:** siempre se guarda una en la carpeta de datos del programa (`%APPDATA%\Enforma\backups`).
2. **En un disco externo o memoria USB** conectado al computador: pulse **Elegir disco externo…** y elija una carpeta del disco. Desde ese momento cada copia se guarda también allí.
3. **En un disco que el dueño se lleve del local:** conecte ese disco, pulse **Copiar a otro disco…** y elija una carpeta. Se copia la copia más reciente. El programa le **recuerda cada semana** que haga esta copia.

Si el disco externo **no está conectado** cuando toca hacer la copia, la copia queda en el PC y aparece el aviso "El disco externo de las copias no está conectado". Conéctelo y pulse **Backup ahora**. Para dejar de usar el disco externo, pulse **Quitar disco externo**.

### Cuántas copias se guardan

Se guardan solas, y las más viejas se borran solas:

- la última copia de cada uno de los **7 días** más recientes,
- la última de cada una de las **4 semanas** más recientes,
- la última de cada uno de los **12 meses** más recientes.

Si se hacen varias copias el mismo día, se queda la última de ese día. Si el gimnasio cierra unos días, no se pierden copias: se cuentan los días que tienen copia. Las copias del disco que se lleva fuera del local **no se borran solas**.

## La pantalla Copias de seguridad

Arriba se ve el estado:

| Dato | Qué significa |
|---|---|
| Última copia buena | Fecha y hora de la última copia que salió bien. Si tiene más de 2 días, dice "tiene más de 2 días". |
| Copia diaria | A qué hora se hace la copia automática. |
| Disco externo o USB | La carpeta elegida y si está **conectado** o **no disponible**. |
| Contraseña | Si ya se creó. |
| Última copia fuera del local | Cuándo se usó por última vez **Copiar a otro disco…**. |

Abajo hay dos pestañas:

- **Copias guardadas:** todas las copias que hay en el PC, en el disco externo y las hechas "antes de restaurar", con fecha, tipo, tamaño y cuántos clientes, pagos, asistencias y fotos tienen.
- **Historial:** cada intento de copia, con su resultado (**Exitosa** o **FALLÓ**) y el motivo cuando falló.

## Avisos al iniciar

Debajo de la barra de arriba aparece una **barra amarilla** cuando hay algo que atender:

- **"La última copia de seguridad buena es del … (hace N días)"** o **"No hay ninguna copia todavía"**: la última copia buena tiene **más de 2 días**. El administrador debe pulsar **Backup ahora**. Recepción también ve este aviso con la frase **"Avise al administrador"**.
- **"Falta crear la contraseña de las copias"**: sin contraseña no se hacen copias automáticas.
- **"El disco externo de las copias no está conectado"**.
- **"Recordatorio semanal: lleve una copia a un disco fuera del local"**.

El botón **Ir a Copias de seguridad** (solo administrador) lleva directo a la pantalla. La barra **no quita el cursor** del campo de código de Recepción.

## Verificar una copia

Para estar tranquilo de que una copia sirve, selecciónela en **Copias guardadas** y pulse **Verificar copia…**. Escriba su contraseña. El programa la abre en una carpeta temporal, sin tocar los datos actuales, y le dice si está completa y qué contiene.

Hay además un comando para el técnico, `python scripts/verificar_backup.py`, que restaura la última copia en una carpeta temporal y comprueba que abre y tiene datos. Conviene hacerlo una vez al mes.

## Restaurar una copia

Restaurar **reemplaza todos los datos actuales** por los de la copia. Úselo solo si se dañó la información o cambió de computador.

1. En **Copias guardadas**, seleccione la copia y pulse **Restaurar copia…** (o doble clic). Si la copia está en otro disco, use **Restaurar desde un archivo…** y busque el archivo `.enfbak`.
2. Revise la fecha y el contenido, escriba la **contraseña con la que se hizo esa copia** y marque **Entiendo que los datos actuales se reemplazan**.
3. Pulse **Restaurar**.

Antes de reemplazar nada, el programa hace **una copia del estado actual** ("antes de restaurar"), por si se equivocó de copia: aparece en la lista con el tipo **Antes de restaurar** y se puede restaurar igual. Se guardan las 5 más recientes.

Al terminar, **se cierra la sesión** y hay que volver a entrar (los usuarios y contraseñas son los que había en la copia). La restauración queda en la auditoría.

El programa **no restaura** si la contraseña es incorrecta, si el archivo está dañado o fue modificado, o si la copia se hizo con una versión más nueva del programa. Una copia de una versión **anterior** sí se puede restaurar: se actualiza sola.

### Pasar a otro computador

1. Instale el programa en el computador nuevo y cree un administrador cualquiera.
2. Vaya a **Copias de seguridad** → **Restaurar desde un archivo…**, elija la copia (por ejemplo, del disco externo) y escriba su contraseña.
3. Entre con su usuario de siempre y **cree de nuevo la contraseña de las copias** (la protección de Windows es de cada computador) y elija otra vez el disco externo.

## Preguntas frecuentes

**¿Puedo abrir la copia con Excel u otro programa?** No. Está cifrada; solo la abre Enforma con la contraseña. Para llevar datos a Excel use [Reportes](tema:reportes).

**La copia al cerrar tarda.** Con unos 12.000 clientes tarda unos 3 a 5 segundos. No apague el computador mientras aparece la ventana.

**Salió "La copia falló".** Mire el motivo en la pestaña **Historial**. Lo más común: falta la contraseña o el disco está lleno. Corríjalo y pulse **Backup ahora**.

**Perdí la contraseña de las copias.** Las copias hechas con ella no se pueden abrir. Cree una contraseña nueva de inmediato (**Cambiar contraseña…**) y pulse **Backup ahora** para tener una copia que sí pueda abrir.

**¿Qué pasa con los recibos y reportes en PDF o Excel?** No van en la copia porque se pueden volver a generar desde el programa.
