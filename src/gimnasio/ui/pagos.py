"""Pantallas de membresías y pagos: renovar o registrar membresía, registrar pagos
(saldo antiguo, casillero u otro), recibos en PDF, anulaciones (solo admin) y cierre de caja."""

from __future__ import annotations

import weakref
from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QLocale, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha, fecha_hora_local, pesos
from gimnasio.servicios.clientes import FilaMembresia
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio, ErrorValidacion
from gimnasio.servicios.pagos import (
    CONCEPTOS, METODOS, MONTO_MAXIMO, DatosPago, MembresiaRegistrada, PagoRegistrado,
    calcular_fecha_fin,
)
from gimnasio.servicios.permisos import Permiso, UsuarioActual
from gimnasio.servicios.autorizaciones import (
    PARA_MODULO_PAGOS, PARA_PAGO, Autorizacion,
)
from gimnasio.ui.autorizacion import (
    asegurar_autorizacion, olvidar_autorizacion_si_falla, pedir_clave_siempre,
)
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

    def fijar_monto(self) -> None:
        """El monto no se edita: se cobra el valor completo (no hay abonos)."""
        self.monto.setReadOnly(True)  # (sin NoButtons: con la hoja de estilos ocultaría el texto)
        self.monto.setStyleSheet("background: #eef2f6; font-weight: 600;")
        self.monto.setToolTip("Se cobra el valor completo: no se reciben abonos.")

    def datos(self) -> DatosPago:
        return DatosPago(self.monto.value(), self.metodo.currentData(), self.referencia.text())


class _CamposCasillero(QGroupBox):
    """Casillero cobrado junto con la mensualidad (mismo recibo). Si el cliente ya tiene
    uno, se renueva; si no, se elige a mano uno libre de su zona."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual, cliente_id: int):
        super().__init__("Pagar también el casillero (en el mismo recibo)")
        from gimnasio.servicios.casilleros import ZONAS

        self.setCheckable(True)
        self.setChecked(False)
        self.actual_casillero = servicios.casilleros.de_cliente(actual, cliente_id)
        capa = QHBoxLayout(self)
        self.campo_casillero = QComboBox()
        if self.actual_casillero is not None:
            c = self.actual_casillero
            hasta = f"pagado hasta el {fecha(c.vence)}" if c.vence else "sin fecha de vencimiento"
            self.descripcion = QLabel(f"Renovar el casillero {c.numero} ({hasta})")
            propuesta = servicios.casilleros.proponer(actual, c.asignacion_id)
            capa.addWidget(self.descripcion)
        else:
            sexo = servicios.clientes.obtener_ficha(actual, cliente_id).sexo
            self.campo_casillero.addItem("Elija un casillero libre…", None)
            for cid, numero, zona in servicios.casilleros.libres(actual, sexo):
                self.campo_casillero.addItem(f"{numero}  ·  {ZONAS[zona]}", cid)
            if self.campo_casillero.count() == 1:
                self.campo_casillero.setItemText(0, "No hay casilleros libres de su zona")
            propuesta = servicios.casilleros.proponer(actual)
            capa.addWidget(QLabel("Casillero"))
            capa.addWidget(self.campo_casillero, 1)
        self.dias = QSpinBox()
        self.dias.setRange(1, 366)
        self.dias.setValue(propuesta.dias)
        self.monto = campo_pesos(propuesta.precio)
        capa.addWidget(QLabel("Días"))
        capa.addWidget(self.dias)
        capa.addWidget(QLabel("Valor"))
        capa.addWidget(self.monto)

    def datos(self):
        """CasilleroEnRecibo con lo elegido (lanza ErrorValidacion si falta algo)."""
        from gimnasio.servicios.casilleros import CasilleroEnRecibo
        from gimnasio.servicios.errores import ErrorValidacion

        if self.monto.value() <= 0:
            raise ErrorValidacion("Escriba el valor del casillero.")
        if self.actual_casillero is not None:
            return CasilleroEnRecibo(monto=self.monto.value(), dias=self.dias.value(),
                                     asignacion_id=self.actual_casillero.asignacion_id)
        if self.campo_casillero.currentData() is None:
            raise ErrorValidacion("Elija el casillero.")
        return CasilleroEnRecibo(monto=self.monto.value(), dias=self.dias.value(),
                                 casillero_id=self.campo_casillero.currentData())


def plan_sin_precio(plan) -> str:
    """Mensaje si el plan todavía no tiene precio (no se puede vender), o ""."""
    if plan is None or plan.precio > 0:
        return ""
    return (f"El plan «{plan.nombre}» todavía no tiene precio. Un administrador lo pone en "
            "Configuración → Planes (Editar).")


class DialogoMembresia(_DialogoBase):
    """Registrar o renovar una membresía, con su pago completo en el mismo paso (no hay
    abonos: solo se registran membresías pagadas por adelantado).
    Opcionalmente cobra también el casillero en el mismo recibo."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual, cliente_id: int,
                 nombre_cliente: str = "", padre: QWidget | None = None,
                 con_casillero: bool = False, titulo: str = "Renovar membresía",
                 autorizacion: Autorizacion | None = None):
        super().__init__(titulo, nombre_cliente, padre)
        self.setMinimumWidth(640)
        self._servicios, self._actual, self._cliente_id = servicios, actual, cliente_id
        # Recepción cobra con la clave de un administrador (la de la inscripción, si viene).
        self._autorizacion = autorizacion
        self.resultado: MembresiaRegistrada | None = None
        self.resultado_casillero = None
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
            avisos.append("✖ No hay planes para vender. Un administrador los crea y les pone "
                          "precio en Configuración → Planes.")
        self.avisos = etiqueta("\n".join(avisos), "textoSuave")
        self._capa.insertWidget(self._capa.indexOf(self.error), self.avisos)
        self.pago = _CamposPago("Pago completo")
        self.pago.fijar_monto()  # siempre el valor completo, sin abonos
        self.abrir_recibo = QCheckBox("Abrir el recibo al guardar para imprimirlo")
        self.abrir_recibo.setChecked(True)
        self.casillero: _CamposCasillero | None = None
        widgets = [self.pago]
        if actual.puede(Permiso.ASIGNAR_CASILLERO):
            self.casillero = _CamposCasillero(servicios, actual, cliente_id)
            self.casillero.setChecked(con_casillero)
            widgets.append(self.casillero)
        for w in (*widgets, self.abrir_recibo):
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
        self._al_cambiar_plan()

    def plan_elegido(self):
        return self._planes.get(self.campo_plan.currentData())

    def _al_cambiar_plan(self) -> None:
        plan = self.plan_elegido()
        if plan:
            self.campo_precio.setValue(plan.precio)
            self.pago.monto.setValue(plan.precio)
        sin_precio = plan_sin_precio(plan)
        if sin_precio:
            self.mostrar_error(sin_precio)
        else:
            self.error.hide()
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
        self.pago.monto.setValue(self.campo_precio.value())  # se paga completo

    def guardar(self) -> None:
        plan = self.plan_elegido()
        if plan is None:
            self.mostrar_error("Elija un plan." if self._planes else
                               "No hay planes para vender. Un administrador los crea en "
                               "Configuración → Planes.")
            return
        if plan_sin_precio(plan):
            self.mostrar_error(plan_sin_precio(plan))
            return
        con_casillero = self.casillero is not None and self.casillero.isChecked()
        if not asegurar_autorizacion(self, PARA_PAGO):
            return
        comunes = dict(fecha_inicio=leer_fecha(self.campo_inicio),
                       precio_pactado=self.campo_precio.value(),
                       motivo_descuento=self.campo_motivo.text(),
                       autorizacion=self._autorizacion)
        try:
            if con_casillero:
                r = self._servicios.casilleros.mensualidad_con_casillero(
                    self._actual, self._cliente_id, plan.id, pago=self.pago.datos(),
                    casillero=self.casillero.datos(), **comunes)
                self.resultado, self.resultado_casillero = r.membresia, r.casillero
            else:
                self.resultado = self._servicios.pagos.registrar_membresia(
                    self._actual, self._cliente_id, plan.id,
                    pago=self.pago.datos(), **comunes)
        except ErrorNegocio as e:
            olvidar_autorizacion_si_falla(self, e)
            self.mostrar_error(str(e))
            return
        if self.resultado.pago and self.abrir_recibo.isChecked():
            self.ruta_recibo = abrir_recibo(self, self._servicios, self._actual,
                                            self.resultado.pago.id, self.abrir)
        self.accept()


class DialogoPago(_DialogoBase):
    """Pago del saldo que una membresía traía de antes (completo, si se indica) o pago de
    otro concepto."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual, cliente_id: int,
                 membresia: FilaMembresia | None = None, nombre_cliente: str = "",
                 padre: QWidget | None = None):
        super().__init__("Pagar saldo pendiente" if membresia else "Pago de otro concepto", nombre_cliente,
                         padre)
        self.setMinimumWidth(600)
        self._servicios, self._actual, self._cliente_id = servicios, actual, cliente_id
        self._membresia = membresia
        self._autorizacion: Autorizacion | None = None
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
        if not membresia:
            aviso = QLabel("⚠ Este pago NO cambia la vigencia del cliente. Para cobrar la "
                           "mensualidad use «Pagar mensualidad» o «Renovar membresía».")
            aviso.setWordWrap(True)
            aviso.setStyleSheet("color: #8a5300; font-weight: 600;")
            self.formulario.addRow(aviso)
        self.pago = _CamposPago("Pago", membresia.saldo if membresia else 0)
        if membresia:
            self.pago.fijar_monto()  # el saldo se paga completo, sin abonos
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
        if not asegurar_autorizacion(self, PARA_PAGO):
            return
        try:
            self.resultado = self._servicios.pagos.registrar_pago(
                self._actual, self._cliente_id, self.pago.datos(),
                concepto=self.campo_concepto.currentData(),
                membresia_id=self._membresia.id if self._membresia else None,
                autorizacion=self._autorizacion,
            )
        except ErrorNegocio as e:
            olvidar_autorizacion_si_falla(self, e)
            self.mostrar_error(str(e))
            return
        if self.abrir_recibo.isChecked():
            self.ruta_recibo = abrir_recibo(self, self._servicios, self._actual,
                                            self.resultado.id, self.abrir)
        self.accept()


# --- Cierre de caja -----------------------------------------------------------------

class PantallaPagos(QWidget):
    """Cierre de caja diario por usuario y método. Recepción ve el suyo de hoy.

    El módulo está bloqueado para todos (también para el administrador): cada vez que se
    entra, un administrador debe escribir su usuario y clave. Al salir de la pantalla se
    vuelve a bloquear."""

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
            "Ctrl+K); el casillero se puede cobrar aquí con «Pagar casillero…». Aquí se ve la "
            "caja del día y se consultan los pagos; los anulados no suman.", "textoSuave"))
        self.pestanas = QTabWidget()
        principal.addWidget(self.pestanas, 1)
        self.autorizacion: Autorizacion | None = None
        self.desbloqueado = False
        self.panel_bloqueado = QWidget()
        bloqueo = QVBoxLayout(self.panel_bloqueado)
        bloqueo.addStretch()
        bloqueo.addWidget(etiqueta(
            "🔒 El módulo de Pagos necesita la clave de un administrador cada vez que se abre.",
            "textoSuave"), 0, Qt.AlignmentFlag.AlignCenter)
        self.boton_desbloquear = boton("Desbloquear con clave de administrador…", principal=True)
        self.boton_desbloquear.clicked.connect(self.desbloquear)
        bloqueo.addWidget(self.boton_desbloquear, 0, Qt.AlignmentFlag.AlignCenter)
        bloqueo.addStretch()
        principal.addWidget(self.panel_bloqueado, 1)
        self.pestanas.setVisible(self.desbloqueado)
        self.panel_bloqueado.setVisible(not self.desbloqueado)
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
        self.boton_casillero = None
        if actual.puede(Permiso.ASIGNAR_CASILLERO) and actual.puede(Permiso.REGISTRAR_PAGOS):
            self.boton_casillero = boton("Pagar casillero…")
            self.boton_casillero.setToolTip(
                "Cobra solo el casillero, con su propio recibo: asigna uno libre o renueva el "
                "que el cliente ya tiene.")
            self.boton_casillero.clicked.connect(self._al_pulsar_casillero)
            botones.addWidget(self.boton_casillero)
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

        pantalla = weakref.ref(self)  # sin ciclo de referencias con la pestaña
        self.consulta = PestanaConsultaPagos(
            servicios, actual, lambda: pantalla().autorizacion if pantalla() else None)
        self.pestanas.addTab(self.consulta, "Consultar pagos")
        self.depuracion = None
        if actual.puede(Permiso.DEPURAR_PAGOS):
            self.depuracion = PestanaDepuracion(servicios, actual)
            self.pestanas.addTab(self.depuracion, "Borrar pagos antiguos")

    def showEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        super().showEvent(evento)
        if self.desbloqueado:
            self.actualizar()
        else:
            # Primero se ve la pantalla bloqueada y enseguida se pide la clave.
            QTimer.singleShot(0, self.desbloquear)

    def hideEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        super().hideEvent(evento)
        self.bloquear()

    def desbloquear(self) -> bool:
        if self.desbloqueado:
            return True
        ok, autorizacion = pedir_clave_siempre(self, self._servicios, self._actual,
                                               PARA_MODULO_PAGOS)
        if not ok:
            return False
        self.autorizacion = autorizacion
        self.desbloqueado = True
        self.panel_bloqueado.hide()
        self.pestanas.show()
        self.actualizar()
        return True

    def bloquear(self) -> None:
        """Al salir del módulo se olvida la autorización y se vuelve a bloquear."""
        self._servicios.autorizaciones.revocar(self.autorizacion)
        self.autorizacion = None
        self.desbloqueado = False
        self.pestanas.hide()
        self.panel_bloqueado.show()
        self.tabla.setRowCount(0)
        self.tabla_usuarios.setRowCount(0)

    def actualizar(self) -> None:
        if not self.desbloqueado:
            return
        try:
            self.cierre = self._servicios.pagos.cierre_caja(
                self._actual, leer_fecha(self.campo_dia), self.campo_usuario.currentData(),
                autorizacion=self.autorizacion)
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

    def _al_pulsar_casillero(self) -> None:
        self.pagar_casillero()

    def pagar_casillero(self, ejecutar: Callable[[QWidget], bool] | None = None) -> QWidget | None:
        """Pide el cliente y abre asignar (si no tiene casillero) o renovar (si ya tiene).
        `ejecutar` permite a las pruebas reemplazar `exec()` de los diálogos."""
        from gimnasio.ui.casilleros import DialogoAsignarCasillero, DialogoRenovarCasillero
        from gimnasio.ui.clientes import DialogoElegirCliente

        texto = self._pedir(self, "Pagar casillero",
                            "Código, documento o nombre del cliente:")
        if not texto or not texto.strip():
            return None
        try:
            filas = self._servicios.clientes.buscar_rapido(self._actual, texto)
            if not filas:
                mostrar_error(self, ErrorValidacion(f"No se encontró ningún cliente con «{texto}»."))
                return None
            fila = filas[0]
            if len(filas) > 1:
                elegir = DialogoElegirCliente(filas, texto, padre=self, texto_boton="Elegir")
                if not (ejecutar or (lambda d: d.exec()))(elegir):
                    return None
                fila = next(f for f in filas if f.id == elegir.cliente_id)
            tiene = self._servicios.casilleros.de_cliente(self._actual, fila.id)
            if tiene is not None:
                dialogo = DialogoRenovarCasillero(self._servicios, self._actual, tiene.asignacion_id,
                                                  tiene.numero, fila.nombre_completo, padre=self)
            else:
                dialogo = DialogoAsignarCasillero(self._servicios, self._actual, cliente_id=fila.id,
                                                  nombre_cliente=fila.nombre_completo,
                                                  sexo=fila.sexo, padre=self)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        dialogo.abrir = self.abrir
        dialogo.periodo.cobrar.setChecked(True)  # aquí se viene a pagar
        if (ejecutar or (lambda d: d.exec()))(dialogo):
            self.actualizar()
        return dialogo

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
