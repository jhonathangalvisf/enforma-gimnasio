"""Pestañas del módulo Pagos: consultar pagos (por cliente y por fecha de pago) y
borrar pagos antiguos (solo el administrador con la clave de seguridad)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QStackedWidget, QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha, fecha_hora_local, pesos
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio
from gimnasio.servicios.pagos import CONCEPTOS, METODOS, ConsultaPagos, FiltrosPagos
from gimnasio.servicios.permisos import Permiso, UsuarioActual
from gimnasio.ui.comunes import boton, celda, confirmar, etiqueta, mostrar_error, tabla
from gimnasio.ui.dialogos import campo_clave
from gimnasio.ui.pagos import abrir_archivo, abrir_recibo, campo_fecha, leer_fecha


class PestanaConsultaPagos(QWidget):
    """Pagos por cliente y/o rango de fechas de pago, con exportación y recibos.
    Recepción solo consulta los pagos de un cliente."""

    COLUMNAS = ["Fecha y hora", "Recibo", "Cliente", "Concepto", "Detalle", "Método",
                "Referencia", "Monto", "Registró", "Estado"]

    def __init__(self, servicios: Servicios, actual: UsuarioActual,
                 autorizacion: Callable[[], object] = lambda: None):
        super().__init__()
        self._servicios, self._actual = servicios, actual
        # La autorización del administrador con la que Recepción abrió el módulo.
        self._autorizacion = autorizacion
        self.abrir: Callable[[Path], None] = abrir_archivo
        self.elegir_ruta: Callable[[str, str], str | None] = self._elegir_ruta
        self.cliente_id: int | None = None
        self.consulta: ConsultaPagos | None = None
        self._general = actual.puede(Permiso.REPORTES_TODOS)
        capa = QVBoxLayout(self)

        fila1 = QHBoxLayout()
        self.campo_cliente = QLineEdit()
        self.campo_cliente.setPlaceholderText("Código, nombre o documento del cliente")
        self.boton_cliente = boton("Buscar cliente")
        self.boton_quitar_cliente = boton("Todos los clientes")
        self.etiqueta_cliente = etiqueta("", "textoSuave")
        fila1.addWidget(QLabel("Cliente"))
        fila1.addWidget(self.campo_cliente, 1)
        fila1.addWidget(self.boton_cliente)
        fila1.addWidget(self.boton_quitar_cliente)
        self.boton_quitar_cliente.setVisible(self._general)
        capa.addLayout(fila1)
        capa.addWidget(self.etiqueta_cliente)

        fila2 = QHBoxLayout()
        hoy = servicios.pagos.hoy()
        self.campo_desde = campo_fecha(hoy.replace(day=1))
        self.campo_hasta = campo_fecha(hoy)
        self.todas_fechas = QCheckBox("Todas las fechas")
        self.campo_metodo = QComboBox()
        self.campo_metodo.addItem("Todos los métodos", None)
        for clave, texto in METODOS.items():
            self.campo_metodo.addItem(texto, clave)
        self.campo_concepto = QComboBox()
        self.campo_concepto.addItem("Todos los conceptos", None)
        for clave, texto in CONCEPTOS.items():
            self.campo_concepto.addItem(texto, clave)
        self.boton_consultar = boton("Consultar", principal=True)
        for texto, w in (("Fecha de pago desde", self.campo_desde), ("hasta", self.campo_hasta)):
            fila2.addWidget(QLabel(texto))
            fila2.addWidget(w)
        fila2.addWidget(self.todas_fechas)
        fila2.addWidget(self.campo_metodo)
        fila2.addWidget(self.campo_concepto)
        fila2.addWidget(self.boton_consultar)
        fila2.addStretch()
        capa.addLayout(fila2)

        self.resumen = etiqueta(
            "Elija un cliente para ver sus pagos." if not self._general
            else "Elija los filtros y presione Consultar.", "textoSuave")
        capa.addWidget(self.resumen)
        self.tabla = tabla(self.COLUMNAS)
        capa.addWidget(self.tabla, 1)
        botones = QHBoxLayout()
        self.boton_recibo = boton("Ver / imprimir recibo")
        self.boton_excel = boton("Exportar a Excel")
        self.boton_pdf = boton("Exportar a PDF")
        for b in (self.boton_recibo, self.boton_excel, self.boton_pdf):
            botones.addWidget(b)
        botones.addStretch()
        capa.addLayout(botones)

        self.campo_cliente.returnPressed.connect(self.buscar_cliente)
        self.boton_cliente.clicked.connect(self.buscar_cliente)
        self.boton_quitar_cliente.clicked.connect(self.quitar_cliente)
        self.todas_fechas.toggled.connect(self._al_cambiar_todas)
        self.boton_consultar.clicked.connect(self.consultar)
        self.boton_recibo.clicked.connect(self.ver_recibo)
        self.tabla.doubleClicked.connect(self.ver_recibo)
        self.boton_excel.clicked.connect(lambda: self.exportar("xlsx"))
        self.boton_pdf.clicked.connect(lambda: self.exportar("pdf"))

    def _al_cambiar_todas(self, todas: bool) -> None:
        self.campo_desde.setEnabled(not todas)
        self.campo_hasta.setEnabled(not todas)

    def filtros(self) -> FiltrosPagos:
        todas = self.todas_fechas.isChecked()
        return FiltrosPagos(
            cliente_id=self.cliente_id,
            desde=None if todas else leer_fecha(self.campo_desde),
            hasta=None if todas else leer_fecha(self.campo_hasta),
            metodo=self.campo_metodo.currentData(), concepto=self.campo_concepto.currentData(),
        )

    def buscar_cliente(self) -> None:
        texto = self.campo_cliente.text().strip()
        if not texto:
            return
        try:
            filas = self._servicios.clientes.buscar_rapido(self._actual, texto)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        if not filas:
            self.etiqueta_cliente.setText(f"No se encontró ningún cliente con «{texto}».")
            return
        elegido = filas[0]
        if len(filas) > 1:
            from gimnasio.ui.clientes import DialogoElegirCliente

            dialogo = DialogoElegirCliente(filas, texto, padre=self, texto_boton="Elegir")
            if not dialogo.exec():
                return
            elegido = next(f for f in filas if f.id == dialogo.cliente_id)
        self.elegir_cliente(elegido.id, f"{elegido.codigo} · {elegido.nombres} {elegido.apellidos}")

    def elegir_cliente(self, cliente_id: int, descripcion: str) -> None:
        self.cliente_id = cliente_id
        self.etiqueta_cliente.setText(f"Pagos de {descripcion}")
        self.campo_cliente.clear()
        self.todas_fechas.setChecked(True)  # por cliente, por defecto todo su historial
        self.consultar()

    def quitar_cliente(self) -> None:
        self.cliente_id = None
        self.etiqueta_cliente.setText("")

    def consultar(self) -> None:
        try:
            self.consulta = self._servicios.pagos.consultar_pagos(
                self._actual, self.filtros(), autorizacion=self._autorizacion())
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        c = self.consulta
        texto = f"{c.cantidad} pagos válidos · total {pesos(c.total)}"
        if c.anulados_cantidad:
            texto += f" · {c.anulados_cantidad} anulados por {pesos(c.anulados_monto)} (no suman)"
        if c.truncada:
            texto += f" · se muestran los {len(c.filas)} más recientes (exporte para verlos todos)"
        self.resumen.setText(texto)
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(c.filas))
        for i, f in enumerate(c.filas):
            valores = [
                celda(fecha_hora_local(f.fecha_hora), f.pago_id, orden=f.fecha_hora),
                celda(f.recibo), celda(f"{f.cliente_codigo} · {f.cliente_nombre}"),
                celda(CONCEPTOS[f.concepto]), celda(f.detalle), celda(METODOS[f.metodo]),
                celda(f.referencia), celda(pesos(f.monto), orden=f.monto), celda(f.usuario),
                celda(f"Anulado: {f.motivo_anulacion}" if f.anulado else "Válido"),
            ]
            for j, item in enumerate(valores):
                if f.anulado:
                    item.setForeground(Qt.GlobalColor.darkRed)
                self.tabla.setItem(i, j, item)
        self.tabla.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
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

    def _elegir_ruta(self, formato: str, sugerido: str) -> str | None:
        filtro = "Excel (*.xlsx)" if formato == "xlsx" else "PDF (*.pdf)"
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar consulta", sugerido, filtro)
        return ruta or None

    def exportar(self, formato: str) -> Path | None:
        carpeta = self._servicios.reportes.carpeta_reportes()
        sugerido = str(carpeta / f"consulta_pagos_{self._servicios.pagos.hoy():%Y%m%d}.{formato}")
        ruta = self.elegir_ruta(formato, sugerido)
        if not ruta:
            return None
        try:
            destino = self._servicios.pagos.exportar_consulta(
                self._actual, self.filtros(), ruta, formato, autorizacion=self._autorizacion())
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        self.abrir(destino)
        return destino


class PestanaDepuracion(QWidget):
    """Borrar pagos hasta una fecha. Bloqueada con la clave de seguridad del dueño."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual,
                 confirmar_borrado: Callable[[QWidget, str, str], bool] = confirmar):
        super().__init__()
        self._servicios, self._actual = servicios, actual
        self._confirmar = confirmar_borrado
        self._clave: str | None = None  # solo en memoria mientras está abierto
        capa = QVBoxLayout(self)
        capa.addWidget(etiqueta(
            "Aquí se borran los pagos antiguos hasta la fecha que usted elija. Antes de borrar "
            "se hace siempre una copia de seguridad cifrada y un Excel con todo lo que se quita. "
            "Se conservan la última membresía de cada cliente y sus pagos, y la numeración de "
            "recibos nunca se repite.", "textoSuave"))
        self.paginas = QStackedWidget()
        capa.addWidget(self.paginas, 1)

        # Página 0: crear la clave de seguridad.
        crear = QGroupBox("Crear la clave de seguridad")
        f0 = QFormLayout(crear)
        self.campo_clave_admin = campo_clave("su contraseña de inicio de sesión")
        self.campo_nueva = campo_clave("mínimo 8 caracteres, distinta de su contraseña")
        self.campo_confirmar = campo_clave()
        f0.addRow("Contraseña de administrador", self.campo_clave_admin)
        f0.addRow("Nueva clave de seguridad", self.campo_nueva)
        f0.addRow("Repetir clave", self.campo_confirmar)
        self.boton_crear = boton("Guardar clave", principal=True)
        f0.addRow("", self.boton_crear)
        self.paginas.addWidget(_envolver(crear))

        # Página 1: pedir la clave.
        pedir = QGroupBox("Apartado protegido")
        f1 = QFormLayout(pedir)
        self.campo_clave = campo_clave("clave de seguridad")
        self.boton_entrar = boton("Entrar", principal=True)
        f1.addRow("Clave de seguridad", self.campo_clave)
        f1.addRow("", self.boton_entrar)
        self.paginas.addWidget(_envolver(pedir))

        # Página 2: elegir la fecha y borrar.
        trabajo = QWidget()
        c2 = QVBoxLayout(trabajo)
        f2 = QFormLayout()
        hoy = servicios.pagos.hoy()
        self.campo_corte = campo_fecha(hoy.replace(year=hoy.year - 1))
        self.campo_motivo = QLineEdit()
        self.campo_motivo.setMaxLength(200)
        self.campo_motivo.setPlaceholderText("Por ejemplo: aligerar historial de años anteriores")
        f2.addRow("Borrar pagos hasta el (incluido)", self.campo_corte)
        f2.addRow("Motivo", self.campo_motivo)
        c2.addLayout(f2)
        fila = QHBoxLayout()
        self.boton_vista = boton("Ver qué se borraría")
        self.boton_borrar = boton("Borrar pagos…")
        self.boton_borrar.setEnabled(False)
        self.boton_cambiar_clave = boton("Cambiar clave de seguridad")
        self.boton_salir = boton("Cerrar apartado")
        for b in (self.boton_vista, self.boton_borrar):
            fila.addWidget(b)
        fila.addStretch()
        fila.addWidget(self.boton_cambiar_clave)
        fila.addWidget(self.boton_salir)
        c2.addLayout(fila)
        self.vista = etiqueta("", None)
        c2.addWidget(self.vista)
        self.resultado = etiqueta("", "mensajeExito")
        c2.addWidget(self.resultado)
        c2.addStretch()
        self.paginas.addWidget(trabajo)

        self.error = etiqueta("", "mensajeError")
        capa.addWidget(self.error)
        self.boton_crear.clicked.connect(self.crear_clave)
        self.campo_confirmar.returnPressed.connect(self.crear_clave)
        self.boton_entrar.clicked.connect(self.entrar)
        self.campo_clave.returnPressed.connect(self.entrar)
        self.boton_vista.clicked.connect(self.ver_vista)
        self.boton_borrar.clicked.connect(self.borrar)
        self.boton_salir.clicked.connect(self.bloquear)
        self.boton_cambiar_clave.clicked.connect(self._ir_a_cambiar_clave)
        self.campo_corte.dateChanged.connect(lambda *_: self.boton_borrar.setEnabled(False))
        self.bloquear()

    # --- estados ----------------------------------------------------------------------
    def bloquear(self) -> None:
        self._clave = None
        for c in (self.campo_clave, self.campo_clave_admin, self.campo_nueva,
                  self.campo_confirmar):
            c.clear()
        self.vista.clear()
        self.resultado.clear()
        self.error.clear()
        self.boton_borrar.setEnabled(False)
        try:
            tiene = self._servicios.depuracion.tiene_clave(self._actual)
        except ErrorNegocio as e:
            self.error.setText(str(e))
            return
        self._cambiando = False
        self.campo_clave_admin.setPlaceholderText("su contraseña de inicio de sesión")
        self.paginas.setCurrentIndex(1 if tiene else 0)

    def hideEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        # Al salir de la pestaña o del módulo, se vuelve a pedir la clave.
        super().hideEvent(evento)
        if self._clave is not None:
            self.bloquear()

    def _ir_a_cambiar_clave(self) -> None:
        self._cambiando = True
        self.campo_clave_admin.setPlaceholderText("clave de seguridad actual")
        self.paginas.setCurrentIndex(0)

    @property
    def abierto(self) -> bool:
        return self._clave is not None and self.paginas.currentIndex() == 2

    # --- acciones ---------------------------------------------------------------------
    def crear_clave(self) -> None:
        self.error.clear()
        try:
            self._servicios.depuracion.configurar_clave(
                self._actual, self.campo_clave_admin.text(), self.campo_nueva.text(),
                self.campo_confirmar.text())
        except ErrorNegocio as e:
            self.error.setText(str(e))
            return
        self.bloquear()
        self.resultado.setText("Clave de seguridad guardada.")

    def entrar(self) -> None:
        self.error.clear()
        clave = self.campo_clave.text()
        try:
            self._servicios.depuracion.comprobar_clave(self._actual, clave)
        except ErrorNegocio as e:
            self.campo_clave.clear()
            self.error.setText(str(e))
            return
        self._clave = clave
        self.campo_clave.clear()
        self.resultado.clear()
        self.paginas.setCurrentIndex(2)

    def ver_vista(self):
        self.error.clear()
        try:
            v = self._servicios.depuracion.vista_previa(
                self._actual, self._clave or "", leer_fecha(self.campo_corte))
        except ErrorNegocio as e:
            self.error.setText(str(e))
            return None
        if not v.pagos:
            self.vista.setText(f"No hay pagos para borrar hasta el {fecha(v.corte)}.")
            self.boton_borrar.setEnabled(False)
            return v
        periodo = ""
        if v.primer_pago and v.ultimo_pago:
            periodo = (f" (del {fecha_hora_local(v.primer_pago)[:10]} al "
                       f"{fecha_hora_local(v.ultimo_pago)[:10]})")
        anulados = f" (incluye {v.anulados} anulados)" if v.anulados else ""
        texto = (f"Se borrarían {v.pagos} pagos{periodo} por {pesos(v.monto_validos)}{anulados} "
                 f"y {v.membresias} membresías ya terminadas.")
        if v.pagos_conservados:
            texto += (f"\nSe conservan {v.pagos_conservados} pagos de ese periodo porque son de "
                      "la última membresía del cliente o de una que sigue vigente.")
        self.vista.setText(texto)
        self.boton_borrar.setEnabled(True)
        return v

    def borrar(self):
        v = self.ver_vista()
        if not v or not v.pagos:
            return None
        if not self.campo_motivo.text().strip():
            self.error.setText("Escriba el motivo de la depuración.")
            return None
        if not self._confirmar(
            self, "Borrar pagos",
            f"Se borrarán {v.pagos} pagos hasta el {fecha(v.corte)}. Antes se hará una copia de "
            "seguridad y un Excel. Esta acción no se puede deshacer desde el sistema "
            "(solo restaurando la copia). ¿Continuar?",
        ):
            return None
        try:
            r = self._servicios.depuracion.depurar(
                self._actual, self._clave or "", v.corte, self.campo_motivo.text())
        except ErrorNegocio as e:
            self.error.setText(str(e))
            return None
        self.boton_borrar.setEnabled(False)
        self.vista.clear()
        self.campo_motivo.clear()
        self.resultado.setText(
            f"Listo: se borraron {r.vista.pagos} pagos. El detalle quedó en {r.excel} y la copia "
            f"de seguridad en {r.copia_seguridad or 'la carpeta de copias'}.")
        return r


def _envolver(caja: QWidget) -> QWidget:
    contenedor = QWidget()
    capa = QVBoxLayout(contenedor)
    capa.addWidget(caja)
    capa.addStretch()
    return contenedor
