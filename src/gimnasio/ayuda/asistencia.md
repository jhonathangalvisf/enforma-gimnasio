# Asistencia

Aquí se registra el ingreso de **un cliente** por su código, se consulta su historial, se corrigen los ingresos que se registraron por error y se saca el reporte de asistencia de ese cliente.

**Nada se carga solo al abrir la pantalla:** el historial y los reportes aparecen únicamente cuando usted los pide. Los reportes de **todos** los clientes (del día, por rango, franja horaria, ranking y clientes que no vienen) están en el módulo [Reportes](tema:reportes).

La pantalla tiene tres pestañas: **Registrar ingreso**, **Historial del cliente** y **Reportes del cliente**.

## Pestaña Registrar ingreso

Funciona igual que [Recepción](tema:recepcion):

1. Escriba el **código del cliente** (o páselo con el lector) y presione **Enter**.
2. Aparece la tarjeta con el semáforo: **verde** puede entrar, **amarillo** puede entrar con aviso (por vencer, saldo pendiente, alertas), **rojo** no puede entrar.
3. Si el cliente **ya ingresó hoy**, se avisa: presione **Enter** para registrar otro ingreso o **Esc** para cancelar.

Atajos: **F2** Renovar, **F3** Autorizar (clave del administrador), **F4** Ficha, **F6** Buscar por documento o nombre (también con el botón **Buscar por documento o nombre (F6)…**, para cuando el cliente no recuerda su código). **Ctrl +** y **Ctrl −** cambian el tamaño de la letra.

Aquí no se muestra la lista de ingresos del día.

## Pestaña Historial del cliente

Escriba el **código del cliente** y pulse **Consultar** (o Enter). Se ven sus ingresos con fecha, hora, plan, resultado, casillero que tenía en ese momento, quién lo registró y estado.

- **Todo el historial** viene marcado. El administrador puede desmarcarlo y elegir **Desde / Hasta**.
- **Resultado:** "Solo ingresos" (los que entraron), "Ingresos y rechazos" o un resultado en particular.
- **Ver eliminadas** (solo administrador).

**Recepción** siempre ve el historial completo del cliente.

### Qué significa cada resultado

| Resultado | Qué pasó |
|---|---|
| Permitido | Entró con el plan vigente. |
| Por vencer | Entró, pero le quedan pocos días. |
| Vencido | Fue rechazado: plan vencido, sin membresía o plan que aún no inicia. |
| Inactivo | Fue rechazado porque el cliente está inactivo. |
| Autorizado | Fue rechazado y luego un administrador autorizó su ingreso. |

Los intentos rechazados quedan guardados para el historial, pero **no cuentan como asistencia** ni en los reportes.

### Eliminar un ingreso registrado por error

1. Seleccione el registro en la tabla.
2. Pulse **Eliminar registro…**.
3. Escriba el **motivo** (es obligatorio).

El registro no se borra del todo: queda marcado como eliminado, con quién lo eliminó y por qué, y el administrador lo puede ver con **Ver eliminadas**. **Recepción** solo puede eliminar ingresos **de hoy**; el administrador, de cualquier día.

## Pestaña Reportes del cliente

Escriba el **código del cliente** y pulse **Generar** (o Enter). Por defecto sale **todo el historial**; el administrador puede desmarcarlo y elegir un periodo. Luego puede **Exportar a Excel…**, **Exportar a PDF…** o **Imprimir**.

Los intentos rechazados y los registros eliminados no salen en el reporte.

## Preguntas frecuentes

**Un cliente entró dos veces el mismo día, ¿cuenta doble?**
En el contador de asistentes de hoy cuenta una sola persona. En su historial aparecen los dos ingresos.

**¿Por qué cada ingreso guarda el casillero?**
Para que los reportes viejos sigan mostrando qué casillero tenía el cliente ese día, aunque después lo haya cambiado o liberado.
