# Reportes

El módulo Reportes reúne en un solo lugar todos los informes del gimnasio: clientes, ingresos de dinero, asistencia, casilleros e invitados. Todos se pueden ver en pantalla, **exportar a Excel o PDF** e **imprimir**.

## Cómo sacar un reporte

1. En la lista de la izquierda, elija el reporte. Están agrupados por tema.
2. Ponga los **filtros**. Cambian según el reporte: periodo, día, número de días, plan, sexo, método de pago, usuario, concepto, cliente, etc.
3. Para el periodo puede usar las opciones rápidas: **Este mes, Mes anterior, Últimos 30 días, Últimos 12 meses, Este año, Hoy** o **Personalizado** (elige las fechas desde y hasta).
4. Pulse **Generar** o presione **Enter**.
5. Revise la vista previa. Abajo aparecen los totales.
6. Si lo necesita, pulse **Exportar a Excel…**, **Exportar a PDF…** o **Imprimir** (**Ctrl+P**, abre el PDF para imprimirlo).

La vista previa muestra hasta 2.000 filas para que la pantalla no se ponga lenta. **Excel y PDF llevan todas las filas.** Cada exportación queda en la auditoría.

Los archivos llevan arriba el título, los filtros usados y la fecha en que se generaron. En Excel los valores en pesos siguen siendo números, así que se pueden sumar.

## Qué reportes hay

### Clientes

| Reporte | Para qué sirve |
|---|---|
| Clientes por vencer | Clientes activos cuyo plan vence en los próximos N días, con teléfono, saldo y casillero. Sirve para llamarlos y que renueven. |
| Clientes vencidos | Clientes activos con el plan vencido sin renovar, con los días de vencido. N = vencidos en los últimos N días (0 = todos). |
| Clientes morosos (saldo pendiente) | Membresías con abonos incompletos y cuánto deben. |
| Nuevos, renovaciones y bajas por mes | Resumen mes a mes: clientes nuevos, renovaciones, clientes inactivados y clientes que se vencieron y no renovaron. |
| Clientes nuevos (detalle) | Clientes registrados en el periodo con su primera membresía. |
| Renovaciones (detalle) | Membresías vendidas a clientes que ya habían tenido otra. |
| Bajas (detalle) | Clientes inactivados (con el motivo) y clientes cuya última membresía venció en el periodo sin renovar. |

**Nuevo** es un cliente registrado en el periodo. **Renovación** es una membresía que no es la primera del cliente. **Baja** se cuenta de dos formas por separado: inactivado por el administrador, o vencido sin renovar. Si un cliente renueva después, deja de contar como baja.

### Ingresos (dinero)

| Reporte | Para qué sirve |
|---|---|
| Ingresos: detalle de pagos | Cada pago del periodo. |
| Ingresos por día | Total de cada día, separado por método de pago. |
| Ingresos por método de pago | Efectivo, tarjeta y transferencia. |
| Ingresos por usuario | Lo que recibió cada persona de recepción. |
| Ingresos por plan | Lo vendido por cada plan, casilleros y otros conceptos. |
| Pagos anulados | Pagos anulados en el periodo, quién los anuló y por qué. |
| Cierre de caja | Pagos de un día con totales por método y por usuario. |

Los pagos **anulados no suman** en ningún total.

### Asistencia, casilleros e invitados

Son los mismos reportes que están en cada módulo: ver [Asistencia](tema:asistencia), [Casilleros](tema:casilleros) e [Invitados](tema:invitados).

## Qué puede ver Recepción

Recepción ve solo estos reportes:

- **Clientes por vencer** (con teléfono, para llamarlos).
- **Cierre de caja:** solo el suyo de hoy.
- **Asistencia del día:** solo hoy.
- **Casilleros:** todas las listas.
- **Visitas de invitados:** solo hoy.

Los reportes de ingresos, morosos, vencidos, movimientos de clientes y los demás son **solo del administrador**.

## Preguntas frecuentes

**¿Por qué un reporte de todo el año tarda un poco?**
Los reportes con decenas de miles de filas pueden tardar uno o dos segundos. Los de un mes salen casi de inmediato.

**¿Dónde quedan los archivos exportados?**
En la carpeta que usted elija al exportar.
