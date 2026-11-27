"""Pantalla y diálogos de Casilleros (sección 3.6): lista con filtros (estado, zona,
sexo del ocupante, vencidos, sugeridos para liberar), asignar, renovar, cambiar,
liberar, historial, movimientos del día y exportación a Excel/PDF.

El catálogo (crear, editar, mantenimiento, corregir vencimiento) solo lo ve el admin;
los servicios igual validan el permiso."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha, fecha_hora_local
from gimnasio.servicios.casilleros import (
    ESTADOS, MOTIVOS_LIBERACION, NOMBRES_VIGENCIA_CASILLERO, SITUACIONES, ZONAS,
    AsignacionRegistrada, FilaCasillero, FiltrosCasilleros, RenovacionRegistrada,
    VigenciaCasillero,
)
from gimnasio.servicios.clientes import NOMBRES_VIGENCIA, SEXOS
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio, ErrorValidacion
from gimnasio.servicios.permisos import Permiso, UsuarioActual
from gimnasio.servicios.autorizaciones import PARA_PAGO
from gimnasio.ui.autorizacion import asegurar_autorizacion, olvidar_autorizacion_si_falla
from gimnasio.ui.comunes import boton, celda, etiqueta, mostrar_error, tabla
from gimnasio.ui.dialogos import _DialogoBase

COLOR_VIGENCIA_CASILLERO = {
    VigenciaCasillero.AL_DIA: "#1e7a3c",
    VigenciaCasillero.POR_VENCER: "#9a6a00",
    VigenciaCasillero.VENCIDO: "#b3261e",
    VigenciaCasillero.SIN_FECHA: "#5f6b7a",
}


def _texto_vigencia(f: FilaCasillero) -> str:
    if f.vigencia is None:
        return ""
    if f.vigencia == VigenciaCasillero.VENCIDO:
        return f"Vencido hace {f.dias_vencido} d"
    if f.vigencia == VigenciaCasillero.POR_VENCER:
        return "Vence hoy" if f.dias == 0 else f"Vence en {f.dias} d"
    return NOMBRES_VIGENCIA_CASILLERO[f.vigencia]


def _combo(opciones: list[tuple[str, object]]) -> QComboBox:
    c = QComboBox()
    for texto, valor in opciones:
        c.addItem(texto, valor)
    return c


class _CamposPeriodo(QWidget):
    """Desde, días y "pagado hasta" calculado. Opcionalmente, el pago del casillero."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual, propuesta):
        super().__init__()
        from gimnasio.ui.pagos import _CamposPago, campo_fecha

        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        fila = QHBoxLayout()
        self.inicio = campo_fecha(propuesta.inicio)
        self.dias = QSpinBox()
        self.dias.setRange(1, 366)
        self.dias.setValue(propuesta.dias)
        self.vence = QLabel()
        self.vence.setObjectName("textoFuerte")
        fila.addWidget(QLabel("Desde"))
        fila.addWidget(self.inicio)
        fila.addWidget(QLabel("Días"))
        fila.addWidget(self.dias)
        fila.addWidget(QLabel("Pagado hasta:"))
        fila.addWidget(self.vence)
        fila.addStretch()
        capa.addLayout(fila)
        self.cobrar = QCheckBox("Registrar el pago del casillero ahora (con recibo)")
        self.pago = _CamposPago("Pago del casillero", propuesta.precio)
        puede_cobrar = actual.puede(Permiso.REGISTRAR_PAGOS)
        self.cobrar.setChecked(puede_cobrar and propuesta.precio > 0)
        self.cobrar.setEnabled(puede_cobrar)
        self.pago.setEnabled(self.cobrar.isChecked())
        self.cobrar.toggled.connect(self.pago.setEnabled)
        capa.addWidget(self.cobrar)
        capa.addWidget(self.pago)
        self.inicio.dateChanged.connect(self._calcular)
        self.dias.valueChanged.connect(self._calcular)
        self._calcular()

    def leer_inicio(self) -> date:
        from gimnasio.ui.pagos import leer_fecha

        return leer_fecha(self.inicio)

    def _calcular(self) -> None:
        from datetime import timedelta

        self.vence.setText(fecha(self.leer_inicio() + timedelta(days=self.dias.value() - 1)))

    def datos_pago(self):
        return self.pago.datos() if self.cobrar.isChecked() else None


class _DialogoConRecibo(_DialogoBase):
    def __init__(self, titulo: str, subtitulo: str, padre: QWidget | None):
        super().__init__(titulo, subtitulo, padre)
        self._autorizacion = None  # clave de administrador para cobrar (Recepción)
        from gimnasio.ui.pagos import abrir_archivo

        self.abrir: Callable[[Path], None] = abrir_archivo
        self.ruta_recibo: Path | None = None

    def _recibo(self, servicios: Servicios, actual: UsuarioActual, pago) -> None:
        if pago is not None and self.abrir_recibo.isChecked():
            from gimnasio.ui.pagos import abrir_recibo

            self.ruta_recibo = abrir_recibo(self, servicios, actual, pago.id, self.abrir)

    def _agregar_casilla_recibo(self) -> None:
        self.abrir_recibo = QCheckBox("Abrir el recibo al guardar para imprimirlo")
        self.abrir_recibo.setChecked(True)
        self._capa.insertWidget(self._capa.indexOf(self.error), self.abrir_recibo)


class DialogoAsignarCasillero(_DialogoConRecibo):
    """Asignar un casillero. Desde la ficha se elige el casillero (solo los de su zona);
    desde la pantalla de Casilleros se busca el cliente."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual, *,
                 cliente_id: int | None = None, nombre_cliente: str = "",
                 sexo: str | None = None, casillero_id: int | None = None,
                 numero: str = "", zona: str = "", padre: QWidget | None = None):
        super().__init__("Asignar casillero", nombre_cliente or (
            f"Casillero {numero} · zona {ZONAS.get(zona, zona).lower()}" if numero else ""), padre)
        self.setMinimumWidth(640)
        self._servicios, self._actual = servicios, actual
        self.cliente_id, self._casillero_fijo = cliente_id, casillero_id
        self.resultado: AsignacionRegistrada | None = None
        self.campo_casillero = QComboBox()
        if casillero_id is None:
            for cid, num, z in servicios.casilleros.libres(actual, sexo):
                self.campo_casillero.addItem(f"{num}  ·  {ZONAS[z]}", cid)
            if self.campo_casillero.count() == 0:
                self.campo_casillero.addItem("No hay casilleros libres de su zona", None)
            self.formulario.addRow("Casillero", self.campo_casillero)
        if cliente_id is None:
            self.campo_cliente = QLineEdit()
            self.campo_cliente.setPlaceholderText("Código, documento, nombre o teléfono + Enter")
            self.etiqueta_cliente = etiqueta("Ningún cliente elegido.", "textoSuave")
            self.campo_cliente.returnPressed.connect(self.buscar_cliente)
            self.formulario.addRow("Cliente", self.campo_cliente)
            self.formulario.addRow("", self.etiqueta_cliente)
        self.periodo = _CamposPeriodo(servicios, actual, servicios.casilleros.proponer(actual))
        self._capa.insertWidget(self._capa.indexOf(self.error), self.periodo)
        self._agregar_casilla_recibo()
        cancelar = boton("Cancelar")
        self.boton_guardar = boton("Asignar casillero", principal=True)
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_guardar)
        cancelar.clicked.connect(self.reject)
        self.boton_guardar.clicked.connect(self.guardar)

    def buscar_cliente(self, elegir: Callable | None = None) -> int | None:
        from gimnasio.ui.clientes import DialogoElegirCliente

        texto = self.campo_cliente.text().strip()
        if not texto:
            return None
        try:
            filas = self._servicios.clientes.buscar_rapido(self._actual, texto)
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            return None
        if not filas:
            self.mostrar_error(f"No se encontró ningún cliente con «{texto}».")
            return None
        fila = filas[0]
        if len(filas) > 1:
            dialogo = DialogoElegirCliente(filas, texto, padre=self, texto_boton="Elegir")
            if not (elegir or dialogo.exec)():
                return None
            fila = next(f for f in filas if f.id == dialogo.cliente_id)
        self.cliente_id = fila.id
        self.etiqueta_cliente.setText(
            f"{fila.codigo} · {fila.nombre_completo} · {SEXOS.get(fila.sexo, fila.sexo)}")
        self.error.hide()
        return fila.id

    def guardar(self) -> None:
        casillero_id = self._casillero_fijo or self.campo_casillero.currentData()
        try:
            if casillero_id is None:
                raise ErrorValidacion("Elija el casillero.")
            if self.cliente_id is None:
                raise ErrorValidacion("Busque y elija el cliente.")
            pago = self.periodo.datos_pago()
            if pago is not None and not asegurar_autorizacion(self, PARA_PAGO):
                return
            self.resultado = self._servicios.casilleros.asignar(
                self._actual, casillero_id, self.cliente_id,
                fecha_inicio=self.periodo.leer_inicio(), dias=self.periodo.dias.value(),
                pago=pago, autorizacion=self._autorizacion if pago is not None else None,
            )
        except ErrorNegocio as e:
            olvidar_autorizacion_si_falla(self, e)
            self.mostrar_error(str(e))
            return
        self._recibo(self._servicios, self._actual, self.resultado.pago)
        self.accept()


class DialogoRenovarCasillero(_DialogoConRecibo):
    def __init__(self, servicios: Servicios, actual: UsuarioActual, asignacion_id: int,
                 numero: str, nombre_cliente: str = "", padre: QWidget | None = None):
        propuesta = servicios.casilleros.proponer(actual, asignacion_id)
        antes = (f"pagado hasta el {fecha(propuesta.vence_actual)}"
                 if propuesta.vence_actual else "sin fecha de vencimiento")
        super().__init__(f"Renovar casillero {numero}",
                         f"{nombre_cliente} · hoy está {antes}.", padre)
        self.setMinimumWidth(640)
        self._servicios, self._actual, self._asignacion_id = servicios, actual, asignacion_id
        self.resultado: RenovacionRegistrada | None = None
        self.periodo = _CamposPeriodo(servicios, actual, propuesta)
        self._capa.insertWidget(self._capa.indexOf(self.error), self.periodo)
        self._agregar_casilla_recibo()
        cancelar = boton("Cancelar")
        self.boton_guardar = boton("Renovar", principal=True)
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_guardar)
        cancelar.clicked.connect(self.reject)
        self.boton_guardar.clicked.connect(self.guardar)

    def guardar(self) -> None:
        pago = self.periodo.datos_pago()
        if pago is not None and not asegurar_autorizacion(self, PARA_PAGO):
            return
        try:
            self.resultado = self._servicios.casilleros.renovar(
                self._actual, self._asignacion_id, fecha_inicio=self.periodo.leer_inicio(),
                dias=self.periodo.dias.value(), pago=pago,
                autorizacion=self._autorizacion if pago is not None else None,
            )
        except ErrorNegocio as e:
            olvidar_autorizacion_si_falla(self, e)
            self.mostrar_error(str(e))
            return
        self._recibo(self._servicios, self._actual, self.resultado.pago)
        self.accept()


class DialogoLiberarCasillero(_DialogoBase):
    """Confirma la liberación con un motivo (queda en el historial)."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual, asignacion_id: int,
                 numero: str, nombre_cliente: str, motivo_sugerido: str = "",
                 padre: QWidget | None = None):
        super().__init__(f"Liberar casillero {numero}",
                         f"Lo tiene {nombre_cliente}. El casillero quedará disponible y en el "
                         "historial quedan la fecha, quién lo liberó y el motivo.", padre)
        self._servicios, self._actual, self._asignacion_id = servicios, actual, asignacion_id
        self.campo_motivo = _combo([(m, m) for m in MOTIVOS_LIBERACION])
        if motivo_sugerido.startswith("Vencido"):
            self.campo_motivo.setCurrentIndex(0)
        elif motivo_sugerido == "Cliente inactivo":
            self.campo_motivo.setCurrentIndex(2)
        self.campo_detalle = QLineEdit()
        self.campo_detalle.setMaxLength(150)
        self.campo_detalle.setPlaceholderText("Detalle (obligatorio si elige «Otro»)")
        self.formulario.addRow("Motivo", self.campo_motivo)
        self.formulario.addRow("Detalle", self.campo_detalle)
        cancelar = boton("Cancelar")
        self.boton_guardar = boton("Liberar casillero", principal=True)
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_guardar)
        cancelar.clicked.connect(self.reject)
        self.boton_guardar.clicked.connect(self.guardar)

    def motivo(self) -> str:
        base, detalle = self.campo_motivo.currentData(), self.campo_detalle.text().strip()
        if base == "Otro":
            return detalle
        return f"{base}: {detalle}" if detalle else base

    def guardar(self) -> None:
        try:
            self._servicios.casilleros.liberar(self._actual, self._asignacion_id, self.motivo())
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            return
        self.accept()


class DialogoCambiarCasillero(_DialogoBase):
    def __init__(self, servicios: Servicios, actual: UsuarioActual, asignacion_id: int,
                 numero: str, nombre_cliente: str, sexo: str, padre: QWidget | None = None):
        super().__init__(f"Cambiar del casillero {numero}",
                         f"{nombre_cliente} conserva lo que tiene pagado.", padre)
        self._servicios, self._actual, self._asignacion_id = servicios, actual, asignacion_id
        self.resultado: AsignacionRegistrada | None = None
        self.campo_casillero = QComboBox()
        for cid, num, z in servicios.casilleros.libres(actual, sexo):
            self.campo_casillero.addItem(f"{num}  ·  {ZONAS[z]}", cid)
        self.formulario.addRow("Nuevo casillero", self.campo_casillero)
        cancelar = boton("Cancelar")
        self.boton_guardar = boton("Cambiar", principal=True)
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_guardar)
        cancelar.clicked.connect(self.reject)
        self.boton_guardar.clicked.connect(self.guardar)

    def guardar(self) -> None:
        try:
            if self.campo_casillero.currentData() is None:
                raise ErrorValidacion("No hay casilleros libres de su zona.")
            self.resultado = self._servicios.casilleros.cambiar(
                self._actual, self._asignacion_id, self.campo_casillero.currentData())
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            return
        self.accept()


class DialogoCasillero(_DialogoBase):
    """Crear o editar un casillero del catálogo (solo admin)."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual,
                 fila: FilaCasillero | None = None, padre: QWidget | None = None):
        super().__init__("Editar casillero" if fila else "Nuevo casillero", "", padre)
        self._servicios, self._actual, self._fila = servicios, actual, fila
        self.campo_numero = QLineEdit(fila.numero if fila else "")
        self.campo_numero.setMaxLength(10)
        self.campo_zona = _combo([(t, z) for z, t in ZONAS.items()])
        if fila:
            self.campo_zona.setCurrentIndex(list(ZONAS).index(fila.zona))
        self.campo_notas = QLineEdit(fila.notas if fila else "")
        self.campo_notas.setMaxLength(200)
        self.formulario.addRow("Número", self.campo_numero)
        self.formulario.addRow("Zona", self.campo_zona)
        self.formulario.addRow("Notas", self.campo_notas)
        cancelar = boton("Cancelar")
        self.boton_guardar = boton("Guardar", principal=True)
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_guardar)
        cancelar.clicked.connect(self.reject)
        self.boton_guardar.clicked.connect(self.guardar)

    def guardar(self) -> None:
        c = self._servicios.casilleros
        try:
            if self._fila:
                c.modificar(self._actual, self._fila.casillero_id, self.campo_numero.text(),
                            self.campo_zona.currentData(), self.campo_notas.text())
            else:
                c.crear(self._actual, self.campo_numero.text(), self.campo_zona.currentData(),
                        self.campo_notas.text())
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            return
        self.accept()


class DialogoCrearVarios(_DialogoBase):
    def __init__(self, servicios: Servicios, actual: UsuarioActual, padre: QWidget | None = None):
        super().__init__("Crear varios casilleros",
                         "Por ejemplo, del 1 al 50 con 3 dígitos crea 001 a 050. "
                         "Los que ya existen se omiten.", padre)
        self._servicios, self._actual = servicios, actual
        self.creados: list[str] = []
        self.desde, self.hasta, self.digitos = QSpinBox(), QSpinBox(), QSpinBox()
        for campo, valor in ((self.desde, 1), (self.hasta, 50)):
            campo.setRange(1, 99_999)
            campo.setValue(valor)
        self.digitos.setRange(1, 6)
        self.digitos.setValue(3)
        self.prefijo = QLineEdit()
        self.prefijo.setMaxLength(4)
        self.prefijo.setPlaceholderText("Opcional, ej.: A-")
        self.campo_zona = _combo([(t, z) for z, t in ZONAS.items()])
        for texto, campo in (("Desde", self.desde), ("Hasta", self.hasta),
                             ("Dígitos", self.digitos), ("Prefijo", self.prefijo),
                             ("Zona", self.campo_zona)):
            self.formulario.addRow(texto, campo)
        cancelar = boton("Cancelar")
        self.boton_guardar = boton("Crear", principal=True)
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_guardar)
        cancelar.clicked.connect(self.reject)
        self.boton_guardar.clicked.connect(self.guardar)

    def guardar(self) -> None:
        try:
            self.creados = self._servicios.casilleros.crear_rango(
                self._actual, self.desde.value(), self.hasta.value(),
                self.campo_zona.currentData(), self.digitos.value(), self.prefijo.text())
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            return
        self.accept()


class DialogoHistorial(QDialog):
    def __init__(self, servicios: Servicios, actual: UsuarioActual, casillero_id: int,
                 numero: str, padre: QWidget | None = None):
        super().__init__(padre)
        self.setWindowTitle(f"Historial del casillero {numero}")
        self.setMinimumSize(860, 420)
        capa = QVBoxLayout(self)
        capa.addWidget(etiqueta(f"Historial del casillero {numero}", "tituloPantalla"))
        filas = servicios.casilleros.historial(actual, casillero_id)
        self.tabla = tabla(["Cliente", "Asignado", "Asignó", "Pagado hasta", "Liberado",
                            "Liberó", "Motivo"])
        self.tabla.setRowCount(len(filas))
        for i, h in enumerate(filas):
            valores = [
                celda(f"{h.codigo} · {h.cliente}"),
                celda(fecha_hora_local(h.asignado_en), orden=h.asignado_en), celda(h.asignado_por),
                celda(fecha(h.vence) if h.vence else "", orden=h.vence),
                celda(fecha_hora_local(h.liberado_en) if h.liberado_en else "En uso",
                      orden=h.liberado_en),
                celda(h.liberado_por), celda(h.motivo),
            ]
            for j, v in enumerate(valores):
                self.tabla.setItem(i, j, v)
        if not filas:
            capa.addWidget(etiqueta("Este casillero nunca ha sido asignado.", "textoSuave"))
        capa.addWidget(self.tabla, 1)
        cerrar = boton("Cerrar")
        cerrar.clicked.connect(self.accept)
        fila = QHBoxLayout()
        fila.addStretch()
        fila.addWidget(cerrar)
        capa.addLayout(fila)


# --- pantalla principal ---------------------------------------------------------------

class _Exportador:
    """Botones Excel / PDF / Imprimir comunes a las dos pestañas."""

    def _iniciar_exportador(self, servicios: Servicios, actual: UsuarioActual) -> QHBoxLayout:
        from gimnasio.ui.pagos import abrir_archivo

        self.abrir: Callable[[Path], None] = abrir_archivo
        self.elegir_ruta: Callable[[str, str], str | None] = self._elegir_ruta
        fila = QHBoxLayout()
        self.boton_excel = boton("Exportar a Excel")
        self.boton_pdf = boton("Exportar a PDF")
        self.boton_imprimir = boton("Imprimir")
        for b in (self.boton_excel, self.boton_pdf, self.boton_imprimir):
            b.setEnabled(actual.puede(Permiso.REPORTES_BASICOS))
            fila.addWidget(b)
        self.boton_excel.clicked.connect(lambda: self.exportar("xlsx"))
        self.boton_pdf.clicked.connect(lambda: self.exportar("pdf"))
        self.boton_imprimir.clicked.connect(self.imprimir)
        return fila

    @staticmethod
    def _elegir_ruta(sugerido: str, filtro: str) -> str | None:
        ruta, _ = QFileDialog.getSaveFileName(None, "Guardar lista", sugerido, filtro)
        return ruta or None

    def _exportar_a(self, ruta: Path | str, formato: str) -> Path | None:
        try:
            return self._servicios.casilleros.exportar(
                self._actual, self.TIPO, ruta, formato, **self.parametros_lista())
        except ErrorNegocio as e:
            mostrar_error(self, e)
        except OSError:
            mostrar_error(self, ErrorValidacion(
                "No se pudo guardar el archivo. Revise que no esté abierto en otro programa."))
        return None

    def exportar(self, formato: str) -> Path | None:
        filtro = "Excel (*.xlsx)" if formato == "xlsx" else "PDF (*.pdf)"
        carpeta = self._servicios.casilleros.carpeta_reportes()
        ruta = self.elegir_ruta(str(carpeta / self.nombre_archivo(formato)), filtro)
        if not ruta:
            return None
        if not ruta.lower().endswith(f".{formato}"):
            ruta += f".{formato}"
        return self._exportar_a(ruta, formato)

    def imprimir(self) -> Path | None:
        ruta = self._servicios.casilleros.carpeta_reportes() / self.nombre_archivo("pdf")
        destino = self._exportar_a(ruta, "pdf")
        if destino:
            self.abrir(destino)
        return destino


class PestanaCasilleros(QWidget, _Exportador):
    TIPO = "estado"
    abrir_ficha = Signal(int)
    COLUMNAS = ["Casillero", "Zona", "Estado", "Cliente", "Sexo", "Teléfono", "Pagado hasta",
                "Casillero al día", "Membresía", "Sugerencia", "Notas"]

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios, self._actual = servicios, actual
        self._filas: list[FilaCasillero] = []
        # Se reemplaza en las pruebas para no abrir ventanas modales.
        self.ejecutar: Callable[[QDialog], bool] = lambda d: bool(d.exec())
        capa = QVBoxLayout(self)
        capa.setContentsMargins(8, 8, 8, 8)

        tarjetas = QHBoxLayout()
        self.totales: dict[str, QLabel] = {}
        for clave, titulo in (("total", "Casilleros"), ("disponibles", "Disponibles"),
                              ("ocupados", "Ocupados"), ("mantenimiento", "Mantenimiento"),
                              ("vencidos", "Vencidos"), ("sugeridos", "Sugerido liberar")):
            tarjeta = QWidget()
            tarjeta.setObjectName("tarjeta")
            interior = QVBoxLayout(tarjeta)
            interior.addWidget(etiqueta(titulo, "textoSuave"))
            valor = etiqueta("0", "tituloPantalla")
            interior.addWidget(valor)
            self.totales[clave] = valor
            tarjetas.addWidget(tarjeta)
        capa.addLayout(tarjetas)

        filtros = QHBoxLayout()
        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("Número de casillero, código o nombre del cliente")
        self.buscar.setClearButtonEnabled(True)
        self.estado = _combo([("Todos los estados", None)] + [(t, e) for e, t in ESTADOS.items()])
        self.zona = _combo([("Todas las zonas", None)] + [(t, z) for z, t in ZONAS.items()])
        self.sexo = _combo([("Ocupante: cualquier sexo", None)]
                           + [(f"Ocupante: {t.lower()}", s) for s, t in SEXOS.items()])
        self.situacion = _combo([("Todas las situaciones", None)]
                                + [(t, s) for s, t in SITUACIONES.items()])
        self.boton_buscar = boton("Buscar", principal=True)
        filtros.addWidget(self.buscar, 1)
        filtros.addWidget(self.boton_buscar)
        capa.addLayout(filtros)
        # Los filtros van en su propia fila para que todo quepa en un portátil.
        filtros = QHBoxLayout()
        for w in (self.estado, self.zona, self.sexo, self.situacion):
            filtros.addWidget(w)
        filtros.addStretch()
        capa.addLayout(filtros)

        acciones = QHBoxLayout()
        self.boton_asignar = boton("Asignar…", principal=True)
        self.boton_renovar = boton("Renovar…")
        self.boton_cambiar = boton("Cambiar de casillero…")
        self.boton_liberar = boton("Liberar…")
        self.boton_historial = boton("Historial")
        self.boton_ficha = boton("Ficha del cliente")
        for b in (self.boton_asignar, self.boton_renovar, self.boton_cambiar, self.boton_liberar,
                  self.boton_historial, self.boton_ficha):
            acciones.addWidget(b)
        acciones.addStretch()
        self.es_admin = actual.puede(Permiso.ADMINISTRAR_CATALOGOS)
        self.boton_nuevo = self.boton_varios = self.boton_editar = None
        self.boton_mantenimiento = self.boton_corregir = None
        capa.addLayout(acciones)
        # Los botones del administrador van en una segunda fila para que la pantalla
        # quepa en un portátil.
        acciones = QHBoxLayout()
        if self.es_admin:
            self.boton_nuevo = boton("Nuevo casillero…")
            self.boton_varios = boton("Crear varios…")
            self.boton_editar = boton("Editar…")
            self.boton_mantenimiento = boton("Mantenimiento")
            self.boton_corregir = boton("Corregir vencimiento…")
            for b in (self.boton_nuevo, self.boton_varios, self.boton_editar,
                      self.boton_mantenimiento, self.boton_corregir):
                acciones.addWidget(b)
            acciones.addStretch()
            capa.addLayout(acciones)

        self.tabla = tabla(self.COLUMNAS)
        capa.addWidget(self.tabla, 1)
        pie = self._iniciar_exportador(servicios, actual)
        self.estado_lista = etiqueta("", "textoSuave")
        pie.addStretch()
        pie.addWidget(self.estado_lista)
        capa.addLayout(pie)

        self.boton_buscar.clicked.connect(self.actualizar)
        self.buscar.returnPressed.connect(self.actualizar)
        for combo in (self.estado, self.zona, self.sexo, self.situacion):
            combo.currentIndexChanged.connect(self.actualizar)
        self.tabla.itemDoubleClicked.connect(lambda _: self.accion_principal())
        self.tabla.itemSelectionChanged.connect(self._habilitar)
        self.boton_asignar.clicked.connect(self.asignar)
        self.boton_renovar.clicked.connect(self.renovar)
        self.boton_cambiar.clicked.connect(self.cambiar)
        self.boton_liberar.clicked.connect(self.liberar)
        self.boton_historial.clicked.connect(self.ver_historial)
        self.boton_ficha.clicked.connect(self.ver_ficha)
        if self.es_admin:
            self.boton_nuevo.clicked.connect(self.nuevo)
            self.boton_varios.clicked.connect(self.crear_varios)
            self.boton_editar.clicked.connect(self.editar)
            self.boton_mantenimiento.clicked.connect(self.alternar_mantenimiento)
            self.boton_corregir.clicked.connect(self.corregir)
        self._habilitar()

    # --- datos ----------------------------------------------------------------
    def filtros(self) -> FiltrosCasilleros:
        return FiltrosCasilleros(
            estado=self.estado.currentData(), zona=self.zona.currentData(),
            sexo_cliente=self.sexo.currentData(), situacion=self.situacion.currentData(),
            texto=self.buscar.text(),
        )

    def parametros_lista(self) -> dict:
        return {"filtros": self.filtros()}

    def nombre_archivo(self, formato: str) -> str:
        situacion = self.situacion.currentData() or "todos"
        return f"casilleros_{situacion}_{self._servicios.casilleros.hoy():%Y%m%d}.{formato}"

    def actualizar(self) -> None:
        try:
            self._filas = self._servicios.casilleros.listar(self._actual, self.filtros())
            resumen = self._servicios.casilleros.resumen(self._actual)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        for clave, etiqueta_total in self.totales.items():
            etiqueta_total.setText(str(getattr(resumen, clave)))
        t = self.tabla
        t.setSortingEnabled(False)
        t.setRowCount(len(self._filas))
        for i, f in enumerate(self._filas):
            estado = "Ocupado" if f.ocupado else ESTADOS.get(f.estado, f.estado)
            vig_m = NOMBRES_VIGENCIA[f.vigencia_membresia] if f.vigencia_membresia else ""
            valores = [
                celda(f.numero, dato=f.casillero_id, orden=_orden_numero(f.numero)),
                celda(ZONAS.get(f.zona, f.zona)), celda(estado),
                celda(f"{f.codigo} · {f.cliente}" if f.ocupado else ""),
                celda(SEXOS.get(f.sexo, "") if f.sexo else ""), celda(f.telefono),
                celda(fecha(f.vence) if f.vence else "", orden=f.vence),
                celda(_texto_vigencia(f), orden=f.dias),
                celda(vig_m), celda(f.motivo_sugerencia), celda(f.notas),
            ]
            for j, v in enumerate(valores):
                t.setItem(i, j, v)
            if f.vigencia is not None:
                t.item(i, 7).setForeground(QColor(COLOR_VIGENCIA_CASILLERO[f.vigencia]))
            if f.sugerir_liberar:
                t.item(i, 9).setForeground(QColor("#b3261e"))
            if f.fuera_de_zona:
                t.item(i, 1).setForeground(QColor("#b3261e"))
                t.item(i, 1).setToolTip("Ocupado fuera de su zona: asígnele uno de su zona "
                                        "con «Cambiar de casillero…».")
        t.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        t.setSortingEnabled(True)
        self.estado_lista.setText(f"{len(self._filas)} casilleros en la lista")
        self._habilitar()

    def seleccionado(self) -> FilaCasillero | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            return None
        cid = self.tabla.item(filas[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        return next((f for f in self._filas if f.casillero_id == cid), None)

    def seleccionar(self, numero: str) -> None:
        for i in range(self.tabla.rowCount()):
            if self.tabla.item(i, 0).text() == numero:
                self.tabla.selectRow(i)
                return

    def _habilitar(self) -> None:
        f = self.seleccionado()
        ocupado = bool(f and f.ocupado)
        libre = bool(f and not f.ocupado and f.estado != "mantenimiento")
        a = self._actual
        self.boton_asignar.setEnabled(libre and a.puede(Permiso.ASIGNAR_CASILLERO))
        self.boton_renovar.setEnabled(ocupado and a.puede(Permiso.ASIGNAR_CASILLERO))
        self.boton_cambiar.setEnabled(ocupado and a.puede(Permiso.ASIGNAR_CASILLERO))
        self.boton_liberar.setEnabled(ocupado and a.puede(Permiso.LIBERAR_CASILLERO))
        self.boton_ficha.setEnabled(ocupado)
        self.boton_historial.setEnabled(f is not None)
        if self.es_admin:
            self.boton_editar.setEnabled(f is not None)
            self.boton_mantenimiento.setEnabled(f is not None and not ocupado)
            self.boton_mantenimiento.setText(
                "Habilitar" if f and f.estado == "mantenimiento" else "Mantenimiento")
            self.boton_corregir.setEnabled(ocupado)

    # --- acciones -------------------------------------------------------------
    def _tras(self, dialogo: QDialog, numero: str | None = None) -> bool:
        if not self.ejecutar(dialogo):
            return False
        self.actualizar()
        if numero:
            self.seleccionar(numero)
        return True

    def accion_principal(self) -> None:
        f = self.seleccionado()
        if f is None:
            return
        if f.ocupado:
            self.renovar()
        elif f.estado != "mantenimiento":
            self.asignar()

    def asignar(self) -> bool:
        f = self.seleccionado()
        if f is None or f.ocupado:
            return False
        dialogo = DialogoAsignarCasillero(self._servicios, self._actual,
                                          casillero_id=f.casillero_id, numero=f.numero,
                                          zona=f.zona, padre=self)
        dialogo.abrir = self.abrir
        return self._tras(dialogo, f.numero)

    def renovar(self) -> bool:
        f = self.seleccionado()
        if f is None or not f.ocupado:
            return False
        try:
            dialogo = DialogoRenovarCasillero(self._servicios, self._actual, f.asignacion_id,
                                              f.numero, f.cliente, padre=self)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return False
        dialogo.abrir = self.abrir
        return self._tras(dialogo, f.numero)

    def cambiar(self) -> bool:
        f = self.seleccionado()
        if f is None or not f.ocupado:
            return False
        return self._tras(DialogoCambiarCasillero(
            self._servicios, self._actual, f.asignacion_id, f.numero, f.cliente, f.sexo,
            padre=self))

    def liberar(self) -> bool:
        f = self.seleccionado()
        if f is None or not f.ocupado:
            return False
        return self._tras(DialogoLiberarCasillero(
            self._servicios, self._actual, f.asignacion_id, f.numero, f.cliente,
            f.motivo_sugerencia, padre=self), f.numero)

    def ver_historial(self) -> None:
        f = self.seleccionado()
        if f is not None:
            DialogoHistorial(self._servicios, self._actual, f.casillero_id, f.numero,
                             padre=self).exec()

    def ver_ficha(self) -> None:
        f = self.seleccionado()
        if f is not None and f.cliente_id:
            self.abrir_ficha.emit(f.cliente_id)
            self.actualizar()

    def nuevo(self) -> bool:
        return self._tras(DialogoCasillero(self._servicios, self._actual, padre=self))

    def crear_varios(self) -> bool:
        return self._tras(DialogoCrearVarios(self._servicios, self._actual, padre=self))

    def editar(self) -> bool:
        f = self.seleccionado()
        if f is None:
            return False
        return self._tras(DialogoCasillero(self._servicios, self._actual, f, padre=self))

    def alternar_mantenimiento(self, nota: str | None = None) -> bool:
        from gimnasio.ui.pagos import pedir_motivo

        f = self.seleccionado()
        if f is None:
            return False
        try:
            if f.estado == "mantenimiento":
                self._servicios.casilleros.habilitar(self._actual, f.casillero_id)
            else:
                if nota is None:
                    nota = pedir_motivo(self, "Mantenimiento",
                                        f"¿Qué tiene el casillero {f.numero}? (ej.: chapa dañada)")
                if nota is None:
                    return False
                self._servicios.casilleros.poner_en_mantenimiento(
                    self._actual, f.casillero_id, nota)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return False
        self.actualizar()
        self.seleccionar(f.numero)
        return True

    def corregir(self) -> bool:
        f = self.seleccionado()
        if f is None or not f.ocupado:
            return False
        dialogo = DialogoCorregirVencimiento(self._servicios, self._actual, f, padre=self)
        return self._tras(dialogo, f.numero)


class DialogoCorregirVencimiento(_DialogoBase):
    def __init__(self, servicios: Servicios, actual: UsuarioActual, f: FilaCasillero,
                 padre: QWidget | None = None):
        super().__init__(f"Corregir vencimiento del casillero {f.numero}",
                         f"{f.cliente}. Úselo, por ejemplo, si se anuló el pago del casillero.",
                         padre)
        from gimnasio.ui.pagos import campo_fecha

        self._servicios, self._actual, self._fila = servicios, actual, f
        self.campo_fecha = campo_fecha(f.vence or servicios.casilleros.hoy())
        self.campo_motivo = QLineEdit()
        self.campo_motivo.setMaxLength(200)
        self.formulario.addRow("Pagado hasta", self.campo_fecha)
        self.formulario.addRow("Motivo", self.campo_motivo)
        cancelar = boton("Cancelar")
        self.boton_guardar = boton("Guardar", principal=True)
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_guardar)
        cancelar.clicked.connect(self.reject)
        self.boton_guardar.clicked.connect(self.guardar)

    def guardar(self) -> None:
        from gimnasio.ui.pagos import leer_fecha

        try:
            self._servicios.casilleros.corregir_vencimiento(
                self._actual, self._fila.asignacion_id, leer_fecha(self.campo_fecha),
                self.campo_motivo.text())
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            return
        self.accept()


def _orden_numero(numero: str) -> tuple:
    from gimnasio.servicios.casilleros import _clave_orden

    return _clave_orden(numero)


class PestanaMovimientos(QWidget, _Exportador):
    """Casilleros asignados o liberados en una fecha (lista «por día»)."""

    TIPO = "dia"
    COLUMNAS = ["Hora", "Movimiento", "Casillero", "Zona", "Cliente", "Sexo", "Pagado hasta",
                "Motivo", "Usuario"]

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        from gimnasio.ui.pagos import campo_fecha

        self._servicios, self._actual = servicios, actual
        capa = QVBoxLayout(self)
        capa.setContentsMargins(8, 8, 8, 8)
        fila = QHBoxLayout()
        self.dia = campo_fecha(servicios.casilleros.hoy())
        self.boton_consultar = boton("Consultar", principal=True)
        fila.addWidget(QLabel("Día"))
        fila.addWidget(self.dia)
        fila.addWidget(self.boton_consultar)
        fila.addStretch()
        capa.addLayout(fila)
        self.resumen = etiqueta("", "textoSuave")
        capa.addWidget(self.resumen)
        self.tabla = tabla(self.COLUMNAS)
        capa.addWidget(self.tabla, 1)
        pie = self._iniciar_exportador(servicios, actual)
        pie.addStretch()
        capa.addLayout(pie)
        self.boton_consultar.clicked.connect(self.actualizar)
        self.dia.dateChanged.connect(lambda _: self.actualizar())

    def leer_dia(self) -> date:
        from gimnasio.ui.pagos import leer_fecha

        return leer_fecha(self.dia)

    def poner_dia(self, dia: date) -> None:
        self.dia.setDate(QDate(dia.year, dia.month, dia.day))

    def parametros_lista(self) -> dict:
        return {"dia": self.leer_dia()}

    def nombre_archivo(self, formato: str) -> str:
        return f"casilleros_dia_{self.leer_dia():%Y%m%d}.{formato}"

    def actualizar(self) -> None:
        try:
            movs = self._servicios.casilleros.movimientos(self._actual, self.leer_dia())
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        t = self.tabla
        t.setSortingEnabled(False)
        t.setRowCount(len(movs))
        for i, m in enumerate(movs):
            valores = [
                celda(fecha_hora_local(m.fecha_hora)[-5:], orden=m.fecha_hora), celda(m.tipo),
                celda(m.numero, orden=_orden_numero(m.numero)), celda(ZONAS.get(m.zona, m.zona)),
                celda(f"{m.codigo} · {m.cliente}"), celda(SEXOS.get(m.sexo, m.sexo)),
                celda(fecha(m.vence) if m.vence else "", orden=m.vence), celda(m.motivo),
                celda(m.usuario),
            ]
            for j, v in enumerate(valores):
                t.setItem(i, j, v)
        t.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        t.setSortingEnabled(True)
        asignados = sum(1 for m in movs if m.tipo == "Asignado")
        self.resumen.setText(f"{asignados} asignados · {len(movs) - asignados} liberados")


class PantallaCasilleros(QWidget):
    abrir_ficha = Signal(int)

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        capa = QVBoxLayout(self)
        capa.setContentsMargins(24, 20, 24, 20)
        capa.addWidget(etiqueta("Casilleros", "tituloPantalla"))
        capa.addWidget(etiqueta(
            "Cada casillero tiene su propio vencimiento («pagado hasta»), aparte de la "
            "membresía. Los de hombres son solo para hombres, los de mujeres para mujeres y "
            "los mixtos para todos. Liberar no borra nada: queda en el historial. Doble clic "
            "asigna un casillero libre o renueva uno ocupado.", "textoSuave"))
        self.pestanas = QTabWidget()
        self.casilleros = PestanaCasilleros(servicios, actual)
        self.movimientos = PestanaMovimientos(servicios, actual)
        self.pestanas.addTab(self.casilleros, "Casilleros")
        self.pestanas.addTab(self.movimientos, "Asignados y liberados por día")
        capa.addWidget(self.pestanas, 1)
        self.casilleros.abrir_ficha.connect(self.abrir_ficha.emit)
        self.pestanas.currentChanged.connect(lambda _: self.actualizar())

    def actualizar(self) -> None:
        if self.pestanas.currentWidget() is self.movimientos:
            self.movimientos.actualizar()
        else:
            self.casilleros.actualizar()

    def showEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        super().showEvent(evento)
        self.actualizar()

