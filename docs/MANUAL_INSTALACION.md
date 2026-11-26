# Manual de instalación y respaldo de Enforma

Este manual explica cómo instalar Enforma en el computador del gimnasio, cómo dejar listas las copias de seguridad, cómo comprobar que todo quedó bien y qué hacer si cambia de computador. El uso diario de cada pantalla está en la **Ayuda** del programa (tecla **F1**).

## 1. Lo que necesita

- Windows 10 u 11 de 64 bits. No hace falta instalar Python ni nada más.
- 4 GB de memoria y 1 GB libre en el disco.
- Una cuenta de Windows con permiso de administrador para instalar (solo para instalar).
- Una memoria USB o disco externo para las copias de seguridad, y otro disco o memoria que el dueño se lleve del local.
- Impresora (opcional) para los recibos y reportes.

**Una sola cuenta de Windows:** los datos del gimnasio se guardan en la cuenta de Windows que abre el programa (`%APPDATA%\Enforma`). Use siempre la misma cuenta en el computador del gimnasio; si entra con otra cuenta, Enforma empezará vacío.

## 2. Instalar

1. Copie el archivo `Enforma-Instalador-1.0.0.exe` al computador (el número cambia con cada versión).
2. Haga doble clic en el archivo.
3. Windows puede mostrar **"Windows protegió su PC"** porque el instalador no tiene firma digital. Pulse **Más información** y luego **Ejecutar de todas formas**. Es normal en programas hechos a la medida.
4. Acepte el aviso de **Control de cuentas de usuario** (pide permiso de administrador).
5. Siga el asistente: deje la carpeta que propone y la casilla **Crear un acceso directo en el escritorio**.
6. Al final, deje marcada **Abrir Enforma ahora** y pulse **Finalizar**.

El instalador crea en el menú Inicio la carpeta **Enforma** con: **Enforma**, **Manual de instalación y respaldo** (este documento), **Diagnóstico de Enforma** y **Desinstalar Enforma**.

## 3. Primer arranque

1. Enforma le pide **crear el usuario administrador**: escriba su nombre, un usuario y una contraseña de al menos 8 caracteres. Guarde esa contraseña.
2. Vaya a **Configuración**:
   - **Parámetros:** nombre, NIT, dirección y teléfono del gimnasio (salen en los recibos). El logo de Enforma ya viene puesto; si quiere otro, cámbielo ahí.
   - **Planes:** ponga los precios y active los planes que usa.
   - **Usuarios:** cree un usuario para cada persona de recepción.
3. Vaya a **Copias de seguridad** y haga lo del punto 4.

## 4. Dejar listas las copias de seguridad

1. **Crear contraseña…**: escriba la contraseña de las copias, **anótela en papel** y guárdela fuera del computador. Sin ella las copias **no se pueden abrir**, ni siquiera el soporte técnico.
2. Conecte la memoria USB o disco externo y pulse **Elegir disco externo…**. Desde ese momento cada copia queda en el computador **y** en ese disco.
3. Pulse **Backup ahora** y espere el mensaje de copia hecha.

Desde ahí las copias son automáticas:

- **Al cerrar Enforma**, sin importar quién lo cierre (espere a que termine la ventana "Haciendo copia de seguridad…" antes de apagar).
- **Todos los días a las 9:00 p. m.** si el programa está abierto (la hora se cambia en Configuración → Parámetros).
- **Una vez por semana**, conecte el disco que se lleva a casa y pulse **Copiar a otro disco…**. El programa se lo recuerda.

Si aparece una barra amarilla arriba (copia de hace más de 2 días, disco desconectado, falta la contraseña), haga lo que dice.

## 5. Comprobar la instalación (Diagnóstico)

Abra **menú Inicio → Enforma → Diagnóstico de Enforma**. Revisa, sin cambiar nada:

| Revisión | Lo que debe decir |
|---|---|
| Archivos del programa | completos (ejecutable) |
| Zona horaria | America/Bogota, con la hora correcta |
| Carpeta de datos | la ruta `C:\Users\<usuario>\AppData\Roaming\Enforma` |
| Base de datos | íntegra, con el número de clientes |
| Protección DPAPI | funciona para el usuario de Windows |
| Contraseña de copias | guardada y protegida con DPAPI |
| Última copia de seguridad | se restauró en una carpeta temporal |

El informe queda también en `%APPDATA%\Enforma\logs\diagnostico.txt`. Si alguna línea dice **FALLA**, envíe ese archivo a soporte.

### Verificar la protección de la contraseña (DPAPI)

La contraseña de las copias se guarda protegida con DPAPI, la protección de Windows que solo deja leerla al **mismo usuario en el mismo computador**. Para confirmarlo en el PC del gimnasio:

1. Cree la contraseña de las copias (punto 4).
2. Abra **Diagnóstico de Enforma**: deben salir en **OK** "Protección DPAPI" y "Contraseña de copias: guardada y protegida con DPAPI".
3. En Enforma pulse **Backup ahora**: la copia se hace **sin pedir** la contraseña.
4. Cierre Enforma, reinicie el computador, ábralo y pulse **Backup ahora** otra vez: tampoco debe pedirla.
5. Vaya a **Restaurar copia…**: ahí **siempre** la pide (eso es lo correcto).
6. Si quiere ver el archivo, está en `%APPDATA%\Enforma\clave_backups.bin`: abierto con el Bloc de notas se ven caracteres sin sentido, nunca la contraseña.

Si el diagnóstico dice que la contraseña "existe pero este usuario de Windows no la puede leer", créela de nuevo en **Copias de seguridad → Cambiar contraseña…** (pasa si se copió la carpeta de datos desde otro computador o usuario).

## 6. Verificar y restaurar copias

- **Verificar:** en Copias de seguridad, seleccione una copia y pulse **Verificar**. Se abre en una carpeta temporal y se revisa sin tocar los datos. Hágalo una vez al mes con una copia del disco externo.
- **Restaurar** (solo si se dañó la información): seleccione la copia y pulse **Restaurar copia…**, o **Restaurar desde un archivo…** si está en otro disco. Escriba la contraseña de esa copia. Antes de reemplazar nada, Enforma guarda una copia "antes de restaurar" por si se equivocó. Al terminar, vuelva a entrar con su usuario.

## 7. Cambiar de computador o reinstalar Windows

1. Lleve la copia más reciente en el disco externo (archivo `.enfbak`) y la contraseña de las copias.
2. Instale Enforma en el computador nuevo (punto 2) y cree un administrador cualquiera.
3. Vaya a **Copias de seguridad → Restaurar desde un archivo…**, elija la copia y escriba su contraseña.
4. Entre con su usuario de siempre, **cree otra vez la contraseña de las copias** (la protección DPAPI es de cada computador) y elija otra vez el disco externo.
5. Abra **Diagnóstico de Enforma** para confirmar que todo está en OK.

## 8. Actualizar a una versión nueva

1. Cierre Enforma (se hace la copia al cerrar).
2. Ejecute el instalador nuevo. Si Enforma sigue abierto, el instalador le pide cerrarlo.
3. Al abrir, Enforma actualiza la base sola. Los datos, fotos y copias se conservan.

## 9. Desinstalar

**Menú Inicio → Enforma → Desinstalar Enforma** (o Configuración de Windows → Aplicaciones). Se quita el programa, pero **los datos del gimnasio no se borran**: quedan en `%APPDATA%\Enforma` y Enforma los vuelve a usar si lo instala de nuevo. Solo si quiere borrar todo, y después de guardar las copias en otro disco, borre esa carpeta a mano.

## 10. Dónde están los datos

Escriba `%APPDATA%\Enforma` en la barra de direcciones del Explorador de archivos:

| Carpeta o archivo | Contenido |
|---|---|
| `enforma.db` | La base de datos (no la abra ni la copie con el programa abierto: use las copias de seguridad) |
| `backups\` | Copias en este computador (y `antes_de_restaurar\`) |
| `fotos\`, `logo.*` | Fotos de clientes y logo elegido |
| `recibos\`, `reportes\` | PDF y Excel generados |
| `logs\` | Registro de errores (sin datos de clientes) y el informe del diagnóstico |
| `clave_backups.bin` | Contraseña de copias protegida con DPAPI (no va dentro de las copias) |

## 11. Problemas frecuentes

- **"Windows protegió su PC" o el antivirus avisa:** el instalador no tiene firma digital. Use **Más información → Ejecutar de todas formas**. Si el antivirus lo bloquea, agregue la carpeta `C:\Program Files\Enforma` a sus excepciones.
- **Abro Enforma y no pasa nada:** ya estaba abierto (quizá minimizado). Enforma no se abre dos veces: la ventana abierta pasa al frente.
- **Sale "Ocurrió un error inesperado":** el detalle queda en `%APPDATA%\Enforma\logs\enforma.log`. Envíe ese archivo a soporte.
- **"No se pudo abrir la base de datos":** abra el Diagnóstico. Si la base está dañada, restaure la última copia (punto 6).
- **Enforma empezó vacío:** entró con otra cuenta de Windows. Cierre sesión y entre con la de siempre.

## 12. Probar en un Windows limpio (antes de instalar en el gimnasio)

Para confirmar que funciona sin Python ni nada instalado, use **Windows Sandbox** (Windows 10/11 Pro):

1. Panel de control → Programas → **Activar o desactivar las características de Windows** → marque **Espacio aislado de Windows** y reinicie.
2. Abra **Espacio aislado de Windows** desde el menú Inicio (es un Windows nuevo y vacío que se borra al cerrarlo).
3. Copie el instalador (Ctrl+C) y péguelo dentro (Ctrl+V). Instálelo, ábralo, cree el administrador, registre un cliente, imprima un recibo en PDF y abra el Diagnóstico.

Si su Windows es Home (no trae Sandbox), haga la prueba directamente en el computador del gimnasio.

## 13. Puesta en marcha recomendada

Instale Enforma en el computador del gimnasio y úselo **en paralelo** con el sistema actual durante 1 a 2 semanas. Compare cada día los ingresos, los pagos y el cierre de caja. Cuando coincidan, deje el sistema anterior.

Lista final del dueño:

- [ ] Probé el ingreso con códigos vigentes, por vencer, vencidos e inactivos.
- [ ] Probé asignar casilleros y confirmé que no permite duplicados.
- [ ] Registré invitados y comprobé el conteo de visitas.
- [ ] Hice un backup, lo verifiqué y lo restauré.
- [ ] El Diagnóstico sale en OK (incluida la protección DPAPI).
- [ ] Guardé la contraseña de los backups en un lugar seguro.
- [ ] Tengo una copia semanal fuera del local.
- [ ] Mis empleados saben usar Recepción y la Ayuda (F1).
