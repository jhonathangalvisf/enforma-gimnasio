# Asistencia

Aquí se consultan los ingresos de los clientes, se corrigen los que se registraron por error y se sacan los reportes de asistencia. Los ingresos se registran en [Recepción](tema:recepcion).

La pantalla tiene dos pestañas: **Registros** y **Reportes**.

## Pestaña Registros

Muestra los ingresos con fecha, hora, código, cliente, plan, resultado, casillero que tenía en ese momento, quién lo registró y estado.

Filtros:

- **Desde / Hasta:** el periodo a consultar.
- **Código del cliente** (opcional): solo los ingresos de ese cliente.
- **Resultado:** "Solo ingresos" (los que entraron), "Ingresos y rechazos" o un resultado en particular (permitido, por vencer, vencido, inactivo, autorizado).
- **Sexo** y **plan**.
- **Ver eliminadas** (solo administrador).

Pulse **Consultar** para ver los resultados.

**Recepción** solo puede consultar el **día de hoy** o el **historial completo de un cliente** (escribiendo su código). El administrador consulta cualquier fecha.

### Qué significa cada resultado

| Resultado | Qué pasó |
|---|---|
| Permitido | Entró con el plan vigente. |
| Por vencer | Entró, pero le quedan pocos días. |
| Vencido | Fue rechazado: plan vencido, sin membresía o plan que aún no inicia. |
| Inactivo | Fue rechazado porque el cliente está inactivo. |
| Autorizado | Fue rechazado y luego un administrador autorizó su ingreso. |

Los intentos rechazados quedan guardados para el historial, pero **no cuentan como asistencia** ni en los reportes.

### Registrar un ingreso manual

Pulse **Registrar ingreso manual (documento o nombre)…**. Lo lleva a Recepción con la búsqueda por documento o nombre abierta. Sirve cuando el cliente no recuerda su código.

### Eliminar un ingreso registrado por error

1. Seleccione el registro en la tabla.
2. Pulse **Eliminar registro…**.
3. Escriba el **motivo** (es obligatorio).

El registro no se borra del todo: queda marcado como eliminado, con quién lo eliminó y por qué, y el administrador lo puede ver con **Ver eliminadas**. **Recepción** solo puede eliminar ingresos **de hoy**; el administrador, de cualquier día.

## Pestaña Reportes

Elija el tipo de reporte, ponga los filtros y pulse **Generar**. Luego puede **Exportar a Excel…**, **Exportar a PDF…** o **Imprimir**.

| Reporte | Qué muestra |
|---|---|
| Asistencia del día | Todos los ingresos de un día con el casillero de cada cliente. |
| Asistencia por rango de fechas | Los ingresos de un periodo. |
| Asistencia de un cliente | Los ingresos de un cliente en un periodo. |
| Asistencia por franja horaria | Cuántos ingresos hubo en cada hora del día (hora de Colombia). Sirve para saber las horas pico. |
| Ranking de asistencia | Los clientes que más vinieron en el periodo. |
| Clientes que no vienen hace N días | Clientes activos que no han venido en los últimos N días, con su teléfono para llamarlos. |

**Recepción** solo ve la **Asistencia del día** de hoy. Estos mismos reportes también están en el módulo [Reportes](tema:reportes).

## Preguntas frecuentes

**Un cliente entró dos veces el mismo día, ¿cuenta doble?**
En el contador de asistentes de hoy cuenta una sola persona. En la lista de registros aparecen los dos ingresos.

**¿Por qué cada ingreso guarda el casillero?**
Para que los reportes viejos sigan mostrando qué casillero tenía el cliente ese día, aunque después lo haya cambiado o liberado.
