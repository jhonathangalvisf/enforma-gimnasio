# Copias de seguridad (backups)

Una copia de seguridad (backup) es una copia de toda la información del gimnasio: clientes, membresías, pagos, asistencias, casilleros, invitados y configuración. Sirve para recuperar los datos si el computador se daña, se pierde o se borra algo por error.

> **Esta función se construye en la próxima fase del proyecto.** Esta página se completará cuando esté lista. Mientras tanto, esto es lo que va a hacer.

## Cómo va a funcionar

- Las copias se hacen **solas al cerrar el programa** y a una **hora diaria**, y también con un botón **Backup ahora** (solo administrador).
- Cada copia se revisa para comprobar que está completa, se comprime y se **cifra con una contraseña**. Sin esa contraseña nadie puede leerla.
- El destino se elige: un **disco externo o una memoria USB**. Si no está conectado, el sistema avisa.
- Se guardan **7 copias diarias, 4 semanales y 12 mensuales**; las más viejas se borran solas.
- Si la última copia buena tiene **más de 2 días**, aparece un aviso al iniciar.
- La **restauración** se hará desde el programa, y antes de restaurar se hace una copia del estado actual por si acaso.

## Recomendaciones (regla 3-2-1)

- Tenga **tres copias**: una en el computador, otra en el disco externo y otra en un disco que el dueño **se lleve del local** (el programa lo recordará cada semana).
- **Guarde la contraseña de las copias en un lugar seguro.** Si se pierde, las copias **no se pueden recuperar**.
