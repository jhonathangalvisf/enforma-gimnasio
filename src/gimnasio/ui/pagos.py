"""Pantallas de membresías y pagos: renovar o registrar membresía, registrar pagos
(abonos, casillero u otro), recibos en PDF, anulaciones (solo admin) y cierre de caja."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QLocale, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha, fecha_hora_local, pesos
from gimnasio.servicios.clientes import FilaMembresia
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio
from gimnasio.servicios.pagos import (
    CONCEPTOS, METODOS, MONTO_MAXIMO, DatosPago, MembresiaRegistrada, PagoRegistrado,
    calcular_fecha_fin,
)
from gimnasio.servicios.permisos import Permiso, UsuarioActual
from gimnasio.ui.comunes import boton, celda, etiqueta, mostrar_error, tabla
from gimnasio.ui.dialogos import _DialogoBase

LOCAL_CO = QLocale(QLocale.Language.Spanish, QLocale.Country.Colombia)


def campo_pesos(valor: int = 0) -> QSpinBox:
    """Pesos sin decimales con separador de miles: $ 120.000."""
    c = QSpinBox()
    c.setLocale(LOCAL_CO)
    c.setRange(0, MONTO_MAXIMO)
    c.setGroupSeparatorShown(True)
    c.setPrefix("$ ")
    c.setSingleStep(1000)
    c.setMinimumWidth(140)
    c.setValue(valor)
    return c


def campo_fecha(valor: date) -> QDateEdit:
    c = QDateEdit(QDate(valor.year, valor.month, valor.day))
    c.setCalendarPopup(True)
    c.setDisplayFormat("dd/MM/yyyy")
    return c


def leer_fecha(campo: QDateEdit) -> date:
    q = campo.date()
    return date(q.year(), q.month(), q.day())


def abrir_archivo(ruta: Path) -> None:
    """Abre el PDF con el programa predeterminado de Windows (desde ahí se imprime)."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta)))


def abrir_recibo(padre: QWidget, servicios: Servicios, actual: UsuarioActual, pago_id: int,
                 abrir: Callable[[Path], None] | None = None) -> Path | None:
    try:
        ruta = servicios.pagos.generar_recibo(actual, pago_id)
    except ErrorNegocio as e:
        mostrar_error(padre, e)
        return None
    (abrir or abrir_archivo)(ruta)
    return ruta


def pedir_motivo(padre: QWidget, titulo: str, texto: str) -> str | None:
    valor, ok = QInputDialog.getText(padre, titulo, texto)
    return valor if ok else None


class _CamposPago(QGroupBox):
    """Monto, método y referencia (obligatoria con tarjeta o transferencia)."""

    def __init__(self, titulo: str, monto: int = 0):
        super().__init__(titulo)
        capa = QHBoxLayout(self)
        self.monto = campo_pesos(monto)
        self.metodo = QComboBox()
        for valor, texto in METODOS.items():
            self.metodo.addItem(texto, valor)
        self.referencia = QLineEdit()
        self.referencia.setMaxLength(60)
        self.referencia.setPlaceholderText("N.º de aprobación o transacción")
        capa.addWidget(QLabel("Monto"))
        capa.addWidget(self.monto)
        capa.addWidget(QLabel("Método"))
        capa.addWidget(self.metodo)
        self.etiqueta_referencia = QLabel("Referencia")
        capa.addWidget(self.etiqueta_referencia)
        capa.addWidget(self.referencia, 1)
        self.metodo.currentIndexChanged.connect(self._al_cambiar_metodo)
        self._al_cambiar_metodo()

    def _al_cambiar_metodo(self) -> None:
        efectivo = self.metodo.currentData() == "efectivo"
        self.referencia.setEnabled(not efectivo)
        self.etiqueta_referencia.setEnabled(not efectivo)
        if efectivo:
            self.referencia.clear()

    def datos(self) -> DatosPago:
        return DatosPago(self.monto.value(), self.metodo.currentData(), self.referencia.text())


class DialogoMembresia(_DialogoBase):
    """Registrar o renovar una membresía, con el pago (completo o abono) en el mismo paso."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual, cliente_id: int,
                 nombre_cliente: str = "", padre: QWidget | None = None):
        super().__init__("Renovar membresía", nombre_cliente, padre)
        self.setMinimumWidth(640)
        self._servicios, self._actual, self._cliente_id = servicios, actual, cliente_id
        self.resultado: MembresiaRegistrada | None = None
        self.ruta_recibo: Path | None = None
        self.abrir: Callable[[Path], None] = abrir_archivo
        self._planes = {p.id: p for p in servicios.planes.listar(actual, solo_activos=True)}
        propuesta = servicios.pagos.proponer_membresia(actual, cliente_id)
        self._propuesta = propuesta

        self.campo_plan = QComboBox()
        for p in self._planes.values():
            self.campo_plan.addItem(f"{p.descripcion} — {pesos(p.precio)}", p.id)
        if propuesta.plan_id in self._planes:
            self.campo_plan.setCurrentIndex(self.campo_plan.findData(propuesta.plan_id))
        self.campo_inicio = campo_fecha(propuesta.fecha_inicio)
        self.etiqueta_fin = etiqueta("")
        self.campo_precio = campo_pesos()
        self.campo_precio.setEnabled(actual.puede(Permiso.APLICAR_DESCUENTOS))
        self.campo_motivo = QLineEdit()
        self.campo_motivo.setMaxLength(200)
        self.campo_motivo.setPlaceholderText("Obligatorio si cambia el precio del plan")
        self.formulario.addRow("Plan", self.campo_plan)
        self.formulario.addRow("Inicia", self.campo_inicio)
        self.formulario.addRow("Vence", self.etiqueta_fin)
        self.formulario.addRow("Precio", self.campo_precio)
        self.etiqueta_motivo = QLabel("Motivo del descuento")
        self.formulario.addRow(self.etiqueta_motivo, self.campo_motivo)
        if not self.campo_precio.isEnabled():
            self.campo_precio.setToolTip("Solo el administrador puede cambiar el precio.")
        avisos = []
        if propuesta.fin_actual:
            avisos.append(f"Su membresía actual vence el {fecha(propuesta.fin_actual)}.")
        if propuesta.saldo_pendiente:
            avisos.append(f"⚠ Tiene un saldo pendiente de {pesos(propuesta.saldo_pendiente)}.")
        if not propuesta.cliente_activo:
            avisos.append("✖ El cliente está inactivo: el administrador debe activarlo primero.")
        if not self._planes:
            avisos.append("No hay planes activos. El administrador los crea en Configuración → Planes.")
        self.avisos = etiqueta("\n".join(avisos), "textoSuave")
        self._capa.insertWidget(self._capa.indexOf(self.error), self.avisos)
        self.pago = _CamposPago("Pago ahora")
        self.sin_pago = QCheckBox("Registrar sin pago (queda todo el valor como saldo pendiente)")
        self.abrir_recibo = QCheckBox("Abrir el recibo al guardar para imprimirlo")
        self.abrir_recibo.setChecked(True)
        for w in (self.pago, self.sin_pago, self.abrir_recibo):
            self._capa.insertWidget(self._capa.indexOf(self.error), w)

        self.boton_guardar = boton("Registrar", principal=True)
        cancelar = boton("Cancelar")
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_guardar)
        cancelar.clicked.connect(self.reject)
        self.boton_guardar.clicked.connect(self.guardar)
        self.campo_plan.currentIndexChanged.connect(self._al_cambiar_plan)
        self.campo_inicio.dateChanged.connect(self._actualizar_fin)
        self.campo_precio.valueChanged.connect(self._al_cambiar_precio)
        self.sin_pago.toggled.connect(lambda v: self.pago.setEnabled(not v))
        self._al_cambiar_plan()

    def plan_elegido(self):
        return self._planes.get(self.campo_plan.currentData())

    def _al_cambiar_plan(self) -> None:
        plan = self.plan_elegido()
        if plan:
            self.campo_precio.setValue(plan.precio)
            self.pago.monto.setValue(plan.precio)
        self._actualizar_fin()
        self._al_cambiar_precio()

    def _actualizar_fin(self) -> None:
        plan = self.plan_elegido()
        self.etiqueta_fin.setText(
            fecha(calcular_fecha_fin(leer_fecha(self.campo_inicio), plan.duracion_dias))
            + "  (puede entrar hasta ese día inclusive)" if plan else "—"
        )

    def _al_cambiar_precio(self) -> None:
        plan = self.plan_elegido()
        distinto = bool(plan) and self.campo_precio.value() != plan.precio
        self.campo_motivo.setVisible(distinto)
        self.etiqueta_motivo.setVisible(distinto)
        if self.pago.monto.value() > self.campo_precio.value():
            self.pago.monto.setValue(self.campo_precio.value())

    def guardar(self) -> None:
        plan = self.plan_elegido()
        if plan is None:
            self.mostrar_error("Elija un plan.")
            return
        sin_pago = self.sin_pago.isChecked() or self.campo_precio.value() == 0
        try:
            self.resultado = self._servicios.pagos.registrar_membresia(
                self._actual, self._cliente_id, plan.id,
                fecha_inicio=leer_fecha(self.campo_inicio),
                precio_pactado=self.campo_precio.value(),
                motivo_descuento=self.campo_motivo.text(),
                pago=None if sin_pago else self.pago.datos(),
            )
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            return
        if self.resultado.pago and self.abrir_recibo.isChecked():
            self.ruta_recibo = abrir_recibo(self, self._servicios, self._actual,
                                            self.resultado.pago.id, self.abrir)
        self.accept()


class DialogoPago(_DialogoBase):
    """Abono a una membresía (si se indica) o pago de casillero u otro concepto."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual, cliente_id: int,
                 membresia: FilaMembresia | None = None, nombre_cliente: str = "",
                 padre: QWidget | None = None):
        super().__init__("Registrar abono" if membresia else "Registrar pago", nombre_cliente, padre)
        self.setMinimumWidth(600)
        self._servicios, self._actual, self._cliente_id = servicios, actual, cliente_id
        self._membresia = membresia
        self.resultado: PagoRegistrado | None = None
        self.ruta_recibo: Path | None = None
        self.abrir: Callable[[Path], None] = abrir_archivo
        self.campo_concepto = QComboBox()
        if membresia:
            self.campo_concepto.addItem(CONCEPTOS["membresia"], "membresia")
            self.campo_concepto.setEnabled(False)
            self.formulario.addRow("Membresía", QLabel(
                f"{membresia.plan}, {fecha(membresia.fecha_inicio)} al {fecha(membresia.fecha_fin)}"))
            self.formulario.addRow("Saldo pendiente", QLabel(pesos(membresia.saldo)))
        else:
            # El casillero se cobra al asignarlo o renovarlo (pestaña Casillero de la
            # ficha), para que el pago corra su fecha de vencimiento.
            self.campo_concepto.addItem(CONCEPTOS["otro"], "otro")
        self.formulario.addRow("Concepto", self.campo_concepto)
        self.pago = _CamposPago("Pago", membresia.saldo if membresia else 0)
        self.abrir_recibo = QCheckBox("Abrir el recibo al guardar para imprimirlo")
        self.abrir_recibo.setChecked(True)
        for w in (self.pago, self.abrir_recibo):
            self._capa.insertWidget(self._capa.indexOf(self.error), w)
        self.boton_guardar = boton("Registrar pago", principal=True)
        cancelar = boton("Cancelar")
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_guardar)
        cancelar.clicked.connect(self.reject)
        self.boton_guardar.clicked.connect(self.guardar)

    def guardar(self) -> None:
        try:
            self.resultado = self._servicios.pagos.registrar_pago(
                self._actual, self._cliente_id, self.pago.datos(),
                concepto=self.campo_concepto.currentData(),
                membresia_id=self._membresia.id if self._membresia else None,
            )
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            return
        if self.abrir_recibo.isChecked():
            self.ruta_recibo = abrir_recibo(self, self._servicios, self._actual,
                                            self.resultado.id, self.abrir)
        self.accept()


# --- Cierre de caja -----------------------------------------------------------------

class PantallaPagos(QWidget):
    """Cierre de caja diario por usuario y método. Recepción ve el suyo de hoy."""

    COLUMNAS = ["Recibo", "Hora", "Cliente", "Concepto", "Método", "Referencia", "Monto",
                "Usuario", "Estado"]

    def __init__(self, servicios: Servicios, actual: UsuarioActual,
                 pedir: Callable[[QWidget, str, str], str | None] = pedir_motivo):
        super().__init__()
        self._servicios, self._actual, self._pedir = servicios, actual, pedir
        self.abrir: Callable[[Path], None] = abrir_archivo
        general = actual.puede(Permiso.CIERRE_CAJA_GENERAL)
        principal = QVBoxLayout(self)
        principal.setContentsMargins(24, 20, 24, 20)
        principal.addWidget(etiqueta("Pagos", "tituloPantalla"))
        principal.addWidget(etiqueta(
            "Las membresías y los pagos se registran desde la ficha del cliente (búsquela con "
            "Ctrl+K). Aquí se ve la caja del día y se consultan los pagos; los anulados no "
            "suman.", "textoSuave"))
        self.pestanas = QTabWidget()
        principal.addWidget(self.pestanas, 1)
        cierre = QWidget()
        capa = QVBoxLayout(cierre)
        self.pestanas.addTab(cierre, "Cierre de caja")
        filtros = QHBoxLayout()
        self.campo_dia = campo_fecha(servicios.pagos.hoy())
        self.campo_dia.setEnabled(general)
        self.campo_usuario = QComboBox()
        if general:
            self.campo_usuario.addItem("Todos los usuarios", None)
            try:
                for u in servicios.usuarios.listar(actual):
                    self.campo_usuario.addItem(u.usuario, u.id)
            except ErrorNegocio:
                pass
        else:
            self.campo_usuario.addItem(actual.usuario, actual.id)
            self.campo_usuario.setEnabled(False)
        self.boton_actualizar = boton("Actualizar", principal=True)
        filtros.addWidget(QLabel("Día"))
        filtros.addWidget(self.campo_dia)
        filtros.addWidget(QLabel("Usuario"))
        filtros.addWidget(self.campo_usuario)
        filtros.addWidget(self.boton_actualizar)
        filtros.addStretch()
        capa.addLayout(filtros)

        tarjetas = QHBoxLayout()
        self.totales: dict[str, QLabel] = {}
        for clave, titulo in [*METODOS.items(), ("total", "Total del día"), ("anulados", "Anulados")]:
            tarjeta = QWidget()
            tarjeta.setObjectName("tarjeta")
            interior = QVBoxLayout(tarjeta)
            interior.addWidget(etiqueta(titulo, "textoSuave"))
            valor = etiqueta("$ 0", "tituloPantalla")
            interior.addWidget(valor)
            self.totales[clave] = valor
            tarjetas.addWidget(tarjeta)
        capa.addLayout(tarjetas)

        capa.addWidget(etiqueta("Por usuario", "textoSuave"))
        self.tabla_usuarios = tabla(["Usuario", *METODOS.values(), "Total", "Pagos"])
        self.tabla_usuarios.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.tabla_usuarios.setMaximumHeight(140)
        capa.addWidget(self.tabla_usuarios)
        capa.addWidget(etiqueta("Pagos del día", "textoSuave"))
        self.tabla = tabla(self.COLUMNAS)
        self.tabla.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        capa.addWidget(self.tabla, 1)
        botones = QHBoxLayout()
        self.boton_recibo = boton("Ver / imprimir recibo")
        botones.addWidget(self.boton_recibo)
        self.boton_anular = None
        if actual.puede(Permiso.ANULAR_PAGOS):
            self.boton_anular = boton("Anular pago…")
            self.boton_anular.clicked.connect(self.anular)
            botones.addWidget(self.boton_anular)
        botones.addStretch()
        capa.addLayout(botones)
        self.boton_actualizar.clicked.connect(self.actualizar)
        self.boton_recibo.clicked.connect(self.ver_recibo)
        self.tabla.doubleClicked.connect(self.ver_recibo)
        self.cierre = None
        self.actualizar()

        from gimnasio.ui.pagos_consulta import PestanaConsultaPagos, PestanaDepuracion

        self.consulta = PestanaConsultaPagos(servicios, actual)
        self.pestanas.addTab(self.consulta, "Consultar pagos")
        self.depuracion = None
        if actual.puede(Permiso.DEPURAR_PAGOS):
            self.depuracion = PestanaDepuracion(servicios, actual)
            self.pestanas.addTab(self.depuracion, "Borrar pagos antiguos")

    def showEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        super().showEvent(evento)
        self.actualizar()

    def actualizar(self) -> None:
        try:
            self.cierre = self._servicios.pagos.cierre_caja(
                self._actual, leer_fecha(self.campo_dia), self.campo_usuario.currentData())
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        c = self.cierre
        for metodo in METODOS:
            self.totales[metodo].setText(pesos(c.por_metodo[metodo]))
        self.totales["total"].setText(pesos(c.total))
        self.totales["anulados"].setText(f"{c.anulados_cantidad} · {pesos(c.anulados_monto)}")
        self.tabla_usuarios.setSortingEnabled(False)
        self.tabla_usuarios.setRowCount(len(c.por_usuario))
        for i, t in enumerate(c.por_usuario):
            valores = [t.usuario, *(pesos(t.por_metodo[m]) for m in METODOS), pesos(t.total),
                       str(t.cantidad)]
            for j, v in enumerate(valores):
                self.tabla_usuarios.setItem(i, j, celda(v))
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(c.filas))
        for i, f in enumerate(c.filas):
            valores = [
                celda(f.recibo, f.pago_id), celda(fecha_hora_local(f.fecha_hora)[-5:], orden=f.fecha_hora),
                celda(f"{f.cliente_codigo} · {f.cliente_nombre}"), celda(CONCEPTOS[f.concepto]),
                celda(METODOS[f.metodo]), celda(f.referencia), celda(pesos(f.monto), orden=f.monto),
                celda(f.usuario),
                celda(f"Anulado: {f.motivo_anulacion}" if f.anulado else "Válido"),
            ]
            for j, item in enumerate(valores):
                if f.anulado:
                    item.setForeground(Qt.GlobalColor.darkRed)
                self.tabla.setItem(i, j, item)
        self.tabla.setSortingEnabled(True)

    def pago_seleccionado(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            return None
        return self.tabla.item(filas[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def ver_recibo(self) -> None:
        pago_id = self.pago_seleccionado()
        if pago_id:
            abrir_recibo(self, self._servicios, self._actual, pago_id, self.abrir)

    def anular(self) -> None:
        pago_id = self.pago_seleccionado()
        if not pago_id:
            return
        fila = next(f for f in self.cierre.filas if f.pago_id == pago_id)
        motivo = self._pedir(self, "Anular pago",
                             f"Motivo para anular el recibo {fila.recibo} por {pesos(fila.monto)}:")
        if motivo is None:
            return
        try:
            self._servicios.pagos.anular_pago(self._actual, pago_id, motivo)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self.actualizar()
