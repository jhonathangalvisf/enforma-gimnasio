"""Módulo Invitados (sección 3.7).

- Registrar visita solo con teclado: documento + Enter. Si el invitado ya existe se
  reutiliza (no se duplica) y se muestra cuántas veces ha venido; si es nuevo se piden
  nombre y teléfono. El cliente que lo invita es opcional (código o nombre + Enter).
- Lista de invitados con total de visitas, visitas del mes y última visita.
- Ficha del invitado con el contador grande y el detalle de cada fecha.
- Reportes por rango de fechas, por invitado y por cliente anfitrión (Excel, PDF, imprimir).
Los invitados no pagan. El límite mensual de visitas es opcional (Configuración).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QTabWidget,
    QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha, fecha_hora_local
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio, ErrorValidacion
from gimnasio.servicios.invitados import (
    DUPLICADO_BLOQUEADO, DUPLICADO_CONFIRMAR, LIMITE_AUTORIZAR, TIPOS_REPORTE, DatosInvitado,
    FichaInvitado, ParametrosReporteInvitados, ResultadoVisita,
)
from gimnasio.servicios.permisos import Permiso, UsuarioActual
from gimnasio.ui.asistencia import _combo, _texto_celda
from gimnasio.ui.comunes import boton, celda, confirmar, etiqueta, mostrar_error, tabla
from gimnasio.ui.dialogos import _DialogoBase, campo_clave
from gimnasio.ui.pagos import abrir_archivo, campo_fecha, leer_fecha, pedir_motivo


def _resumen_contador(f: FichaInvitado) -> str:
    partes = [f"{f.visitas_mes} este mes"]
    if f.limite_mes:
        partes[0] += f" (máximo {f.limite_mes})"
    if f.ultima_visita:
        partes.append(f"última: {fecha(f.ultima_visita)}")
    return " · ".join(partes)


def elegir_anfitrion(padre: QWidget, servicios: Servicios, actual: UsuarioActual,
                     texto: str) -> tuple[int, str] | None:
    """Busca al cliente que invita por código, nombre, documento o teléfono."""
    texto = (texto or "").strip()
    if not texto:
        return None
    filas = servicios.clientes.buscar_rapido(actual, texto)
    if not filas:
        raise ErrorValidacion(f"No se encontró ningún cliente con «{texto}».")
    elegido = filas[0]
    if len(filas) > 1:
        from gimnasio.ui.clientes import DialogoElegirCliente

        dialogo = DialogoElegirCliente(filas, texto, padre=padre, texto_boton="Elegir anfitrión")
        if not dialogo.exec():
            return None
        elegido = next(f for f in filas if f.id == dialogo.cliente_id)
    return elegido.id, f"{elegido.codigo} {elegido.nombre_completo}"


class DialogoAutorizarVisita(_DialogoBase):
    """Contraseña de un administrador cuando el invitado llegó al límite del mes."""

    def __init__(self, ficha: FichaInvitado, padre: QWidget | None = None):
        super().__init__(
            "Autorizar visita",
            f"{ficha.nombre} ya tiene {ficha.visitas_mes} visitas este mes (máximo "
            f"{ficha.limite_mes}). Requiere la contraseña de un administrador; queda en la "
            "auditoría.", padre)
        self.campo_usuario = QLineEdit()
        self.campo_usuario.setPlaceholderText("usuario del administrador")
        self.campo_clave = campo_clave("contraseña")
        self.campo_motivo = QLineEdit()
        self.campo_motivo.setMaxLength(200)
        self.campo_motivo.setPlaceholderText("Opcional, p. ej. «viene a conocer el gimnasio»")
        self.formulario.addRow("Administrador", self.campo_usuario)
        self.formulario.addRow("Contraseña", self.campo_clave)
        self.formulario.addRow("Motivo", self.campo_motivo)
        cancelar = boton("Cancelar")
        self.boton_autorizar = boton("Autorizar visita", principal=True)
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_autorizar)
        cancelar.clicked.connect(self.reject)
        self.boton_autorizar.clicked.connect(self._aceptar)
        self.campo_usuario.returnPressed.connect(self.campo_clave.setFocus)
        self.campo_clave.returnPressed.connect(self.campo_motivo.setFocus)
        self.campo_motivo.returnPressed.connect(self._aceptar)
        self.campo_usuario.setFocus()

    def _aceptar(self) -> None:
        if not self.campo_usuario.text().strip() or not self.campo_clave.text():
            self.mostrar_error("Escriba el usuario y la contraseña del administrador.")
            return
        self.accept()

    def credenciales(self) -> tuple[str, str, str]:
        return self.campo_usuario.text(), self.campo_clave.text(), self.campo_motivo.text()


class DialogoEditarInvitado(_DialogoBase):
    def __init__(self, servicios: Servicios, actual: UsuarioActual, ficha: FichaInvitado,
                 padre: QWidget | None = None):
        super().__init__("Editar invitado", "", padre)
        self._servicios, self._actual, self._id = servicios, actual, ficha.id
        self.ficha: FichaInvitado | None = None
        self.campo_nombre = QLineEdit(ficha.nombre)
        self.campo_documento = QLineEdit(ficha.documento)
        self.campo_telefono = QLineEdit(ficha.telefono)
        if not actual.puede(Permiso.MODIFICAR_CLIENTE_COMPLETO):
            self.campo_documento.setEnabled(False)
            self.campo_documento.setToolTip("Solo el administrador puede cambiar el documento.")
        self.formulario.addRow("Nombre completo", self.campo_nombre)
        self.formulario.addRow("Documento", self.campo_documento)
        self.formulario.addRow("Teléfono", self.campo_telefono)
        cancelar = boton("Cancelar")
        guardar = boton("Guardar", principal=True)
        self._botones.addWidget(cancelar)
        self._botones.addWidget(guardar)
        cancelar.clicked.connect(self.reject)
        guardar.clicked.connect(self.guardar)
        self.campo_telefono.returnPressed.connect(self.guardar)

    def guardar(self) -> None:
        try:
            self.ficha = self._servicios.invitados.modificar(self._actual, self._id, DatosInvitado(
                self.campo_nombre.text(), self.campo_documento.text(), self.campo_telefono.text()))
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            return
        self.accept()


class DialogoFichaInvitado(QDialog):
    """Contador de visitas del invitado y el detalle de fechas (RF-I3)."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual, invitado_id: int,
                 padre: QWidget | None = None):
        super().__init__(padre)
        self._servicios, self._actual, self._id = servicios, actual, invitado_id
        self.pedir_motivo: Callable[[QWidget, str, str], str | None] = pedir_motivo
        self.cambio = False
        self.setWindowTitle("Invitado")
        self.resize(820, 600)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(22, 18, 22, 18)
        self.titulo = etiqueta("", "tituloPantalla")
        self.datos = etiqueta("", "textoSuave")
        self.aviso_cliente = etiqueta("", "textoSuave")
        capa.addWidget(self.titulo)
        capa.addWidget(self.datos)
        capa.addWidget(self.aviso_cliente)

        caja = QWidget()
        caja.setObjectName("tarjeta")
        fila = QHBoxLayout(caja)
        fila.setContentsMargins(18, 12, 18, 12)
        self.numero = etiqueta("0", "contadorInvitado")
        self.numero.setWordWrap(False)
        texto = QVBoxLayout()
        self.contador = etiqueta("", "contadorTexto")
        self.detalle_contador = etiqueta("", "textoSuave")
        self.aviso_limite = etiqueta("", "avisoLimite")
        texto.addWidget(self.contador)
        texto.addWidget(self.detalle_contador)
        texto.addWidget(self.aviso_limite)
        fila.addWidget(self.numero)
        fila.addSpacing(16)
        fila.addLayout(texto, 1)
        capa.addWidget(caja)

        capa.addWidget(etiqueta("Fechas de sus visitas", "contadorTexto"))
        self.tabla = tabla(["#", "Fecha", "Hora", "Cliente que invita", "Registró",
                            "Autorizó (límite)", "Estado"])
        capa.addWidget(self.tabla, 1)
        botones = QHBoxLayout()
        self.boton_editar = boton("Editar datos…")
        self.boton_eliminar = boton("Eliminar visita…")
        cerrar = boton("Cerrar", principal=True)
        botones.addWidget(self.boton_editar)
        botones.addWidget(self.boton_eliminar)
        botones.addStretch()
        botones.addWidget(cerrar)
        capa.addLayout(botones)
        self.boton_editar.clicked.connect(self.editar)
        self.boton_eliminar.clicked.connect(self.eliminar)
        cerrar.clicked.connect(self.accept)
        self.ficha = self.actualizar()

    def actualizar(self) -> FichaInvitado:
        f = self._servicios.invitados.ficha(self._actual, self._id)
        self.ficha = f
        self.setWindowTitle(f"Invitado: {f.nombre}")
        self.titulo.setText(f.nombre)
        self.datos.setText(
            f"Documento {f.documento}" + (f" · Teléfono {f.telefono}" if f.telefono else "")
            + f" · Registrado el {fecha_hora_local(f.creado_en)[:10]} por {f.creado_por}")
        self.aviso_cliente.setText(
            f"Esta persona ya es cliente del gimnasio (código {f.cliente_codigo})."
            if f.cliente_codigo else "")
        self.aviso_cliente.setVisible(bool(f.cliente_codigo))
        self.numero.setText(str(f.total_visitas))
        self.contador.setText(f.texto_contador)
        partes = [_resumen_contador(f)]
        if f.primera_visita:
            partes.append(f"primera: {fecha(f.primera_visita)}")
        self.detalle_contador.setText(" · ".join(partes))
        self.aviso_limite.setText(
            "Llegó al máximo de visitas del mes: la próxima necesita autorización del "
            "administrador." if f.limite_alcanzado else "")
        self.aviso_limite.setVisible(f.limite_alcanzado)

        vigentes = [v for v in f.visitas if not v.eliminada]
        numero = {v.id: len(vigentes) - i for i, v in enumerate(vigentes)}
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(f.visitas))
        for i, v in enumerate(f.visitas):
            n = numero.get(v.id)
            valores = [
                celda(str(n) if n else "", dato=v.id, orden=n or 0),
                celda(fecha(v.fecha), orden=v.fecha_hora), celda(fecha_hora_local(v.fecha_hora)[-5:]),
                celda(v.anfitrion), celda(v.usuario), celda(v.autorizada_por or ""),
                celda(f"Eliminada: {v.motivo_eliminacion}" if v.eliminada else ""),
            ]
            for j, item in enumerate(valores):
                if v.eliminada:
                    item.setForeground(Qt.GlobalColor.darkRed)
                self.tabla.setItem(i, j, item)
        self.tabla.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.tabla.setSortingEnabled(True)
        return f

    def seleccionada(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            return None
        return self.tabla.item(filas[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def editar(self) -> None:
        dialogo = DialogoEditarInvitado(self._servicios, self._actual, self.ficha, padre=self)
        if dialogo.exec():
            self.cambio = True
            self.actualizar()

    def eliminar(self) -> None:
        visita_id = self.seleccionada()
        if visita_id is None:
            mostrar_error(self, ErrorValidacion("Seleccione la visita que desea eliminar."))
            return
        motivo = self.pedir_motivo(self, "Eliminar visita",
                                   "Motivo de la eliminación (queda en la auditoría):")
        if motivo is None:
            return
        try:
            self._servicios.invitados.eliminar_visita(self._actual, visita_id, motivo)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self.cambio = True
        self.actualizar()


class PestanaInvitados(QWidget):
    """Registrar visita (solo teclado) y lista de invitados con su contador."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios, self._actual = servicios, actual
        # Reemplazables en las pruebas.
        self.confirmar: Callable[[QWidget, str, str], bool] = confirmar
        self.pedir_autorizacion: Callable[[FichaInvitado], tuple[str, str, str] | None] = (
            self._pedir_autorizacion)
        self.abrir_ficha: Callable[[int], None] = self._abrir_ficha
        self.ficha_actual: FichaInvitado | None = None
        self.anfitrion: tuple[int, str] | None = None
        self.ultimo_resultado: ResultadoVisita | None = None
        capa = QVBoxLayout(self)
        capa.setContentsMargins(10, 10, 10, 10)

        caja = QGroupBox("Registrar visita de un invitado")
        formulario = QFormLayout(caja)
        self.documento = QLineEdit()
        self.documento.setPlaceholderText("Documento del invitado y Enter")
        self.documento.setMaxLength(30)
        self.nombre = QLineEdit()
        self.nombre.setPlaceholderText("Nombre completo (solo si es nuevo)")
        self.telefono = QLineEdit()
        self.telefono.setPlaceholderText("Teléfono (opcional)")
        self.campo_anfitrion = QLineEdit()
        self.campo_anfitrion.setPlaceholderText(
            "Código o nombre del cliente que lo invita (opcional) y Enter")
        self.etiqueta_anfitrion = etiqueta("", "textoSuave")
        self.estado = etiqueta("Escriba el documento y presione Enter.", "contadorTexto")
        self.detalle = etiqueta("", "textoSuave")
        formulario.addRow("Documento", self.documento)
        formulario.addRow("Nombre", self.nombre)
        formulario.addRow("Teléfono", self.telefono)
        formulario.addRow("Invitado por", self.campo_anfitrion)
        formulario.addRow("", self.etiqueta_anfitrion)
        acciones = QHBoxLayout()
        self.boton_registrar = boton("Registrar visita", principal=True)
        self.boton_limpiar = boton("Limpiar")
        acciones.addWidget(self.estado, 1)
        acciones.addWidget(self.boton_limpiar)
        acciones.addWidget(self.boton_registrar)
        formulario.addRow(acciones)
        formulario.addRow(self.detalle)
        capa.addWidget(caja)

        fila = QHBoxLayout()
        self.busqueda = QLineEdit()
        self.busqueda.setPlaceholderText("Buscar invitado por nombre, documento o teléfono")
        fila.addWidget(self.busqueda, 1)
        self.boton_ver = boton("Ver visitas…")
        fila.addWidget(self.boton_ver)
        capa.addLayout(fila)
        self.tabla = tabla(["Invitado", "Documento", "Teléfono", "Visitas", "Este mes",
                            "Última visita"])
        capa.addWidget(self.tabla, 1)
        self.total = etiqueta("", "textoSuave")
        capa.addWidget(self.total)

        self.documento.returnPressed.connect(self.buscar_documento)
        self.documento.textEdited.connect(lambda _: self._olvidar_invitado())
        self.nombre.returnPressed.connect(self.telefono.setFocus)
        self.telefono.returnPressed.connect(self.campo_anfitrion.setFocus)
        self.campo_anfitrion.returnPressed.connect(self._enter_anfitrion)
        self.campo_anfitrion.textEdited.connect(lambda _: self._olvidar_anfitrion())
        self.boton_registrar.clicked.connect(self.registrar)
        self.boton_limpiar.clicked.connect(self.limpiar)
        self.busqueda.textChanged.connect(lambda _: self.actualizar())
        self.boton_ver.clicked.connect(self.ver_seleccionado)
        self.tabla.cellDoubleClicked.connect(lambda *_: self.ver_seleccionado())
        self.filas = []

    # --- registrar visita ---------------------------------------------------------
    def enfocar(self) -> None:
        self.documento.setFocus()
        self.documento.selectAll()

    def _olvidar_invitado(self) -> None:
        if self.ficha_actual is not None:
            self.ficha_actual = None
            self.nombre.clear()
            self.telefono.clear()
            self.nombre.setEnabled(True)

    def _olvidar_anfitrion(self) -> None:
        self.anfitrion = None
        self.etiqueta_anfitrion.setText("")

    def buscar_documento(self) -> FichaInvitado | None:
        """Enter en el documento: si ya existe muestra su contador; si no, pide el nombre."""
        documento = self.documento.text().strip()
        if not documento:
            return None
        try:
            ficha = self._servicios.invitados.por_documento(self._actual, documento)
            cliente = None if ficha else self._servicios.invitados.cliente_con_documento(
                self._actual, documento)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        self.ficha_actual = ficha
        if ficha is None:
            self.nombre.setEnabled(True)
            self.nombre.clear()
            self.telefono.clear()
            self.estado.setText("Invitado nuevo: escriba el nombre.")
            self.detalle.setText(
                f"Atención: ese documento es del cliente {cliente}." if cliente else "")
            self.nombre.setFocus()
            return None
        self.nombre.setText(ficha.nombre)
        self.nombre.setEnabled(False)
        self.telefono.setText(ficha.telefono)
        self._mostrar_contador(ficha)
        self.campo_anfitrion.setFocus()
        return ficha

    def _mostrar_contador(self, ficha: FichaInvitado, prefijo: str = "") -> None:
        self.estado.setText(f"{prefijo}{ficha.nombre}: {ficha.texto_contador.lower()}")
        detalle = _resumen_contador(ficha)
        if ficha.limite_alcanzado:
            detalle += " · llegó al máximo del mes"
        if ficha.cliente_codigo:
            detalle += f" · ya es cliente (código {ficha.cliente_codigo})"
        self.detalle.setText(detalle)

    def _enter_anfitrion(self) -> None:
        if self.campo_anfitrion.text().strip() and self.anfitrion is None:
            if not self.resolver_anfitrion():
                return
        self.registrar()

    def resolver_anfitrion(self) -> bool:
        try:
            self.anfitrion = elegir_anfitrion(self, self._servicios, self._actual,
                                              self.campo_anfitrion.text())
        except ErrorNegocio as e:
            mostrar_error(self, e)
            self.campo_anfitrion.setFocus()
            return False
        if self.anfitrion is None:
            return False
        self.campo_anfitrion.setText(self.anfitrion[1])
        self.etiqueta_anfitrion.setText(f"Invitado por {self.anfitrion[1]}")
        return True

    def registrar(self) -> ResultadoVisita | None:
        try:
            if self.ficha_actual is None:
                if not self.documento.text().strip():
                    raise ErrorValidacion("Escriba el documento del invitado.")
                existente = self._servicios.invitados.por_documento(
                    self._actual, self.documento.text())
                if existente is None:
                    existente, _ = self._servicios.invitados.registrar(self._actual, DatosInvitado(
                        self.nombre.text(), self.documento.text(), self.telefono.text()))
                self.ficha_actual = existente
            elif self.telefono.text().strip() and not self.ficha_actual.telefono:
                self.ficha_actual, _ = self._servicios.invitados.registrar(
                    self._actual, DatosInvitado(self.ficha_actual.nombre,
                                                self.ficha_actual.documento, self.telefono.text()))
            if self.campo_anfitrion.text().strip() and self.anfitrion is None:
                if not self.resolver_anfitrion():
                    return None
            resultado = self._registrar_visita()
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        self.ultimo_resultado = resultado
        if resultado is not None and resultado.registrada:
            self._mostrar_contador(resultado.ficha, "Visita registrada. ")
            self._limpiar_campos()
            self.actualizar()
        self.enfocar()
        return resultado

    def _registrar_visita(self, **extra) -> ResultadoVisita | None:
        ficha = self.ficha_actual
        anfitrion_id = self.anfitrion[0] if self.anfitrion else None
        r = self._servicios.invitados.registrar_visita(self._actual, ficha.id, anfitrion_id, **extra)
        if r.estado == DUPLICADO_BLOQUEADO:
            raise ErrorValidacion(
                f"{ficha.nombre} ya registró visita hoy a las "
                f"{fecha_hora_local(r.visita_previa_hoy)[-5:]}.")
        if r.estado == DUPLICADO_CONFIRMAR:
            if not self.confirmar(
                self, "Ya vino hoy",
                f"{ficha.nombre} ya registró visita hoy a las "
                f"{fecha_hora_local(r.visita_previa_hoy)[-5:]}. ¿Registrar otra visita?"):
                return r
            return self._registrar_visita(confirmar_duplicado=True, **extra)
        if r.estado == LIMITE_AUTORIZAR:
            credenciales = self.pedir_autorizacion(r.ficha)
            if credenciales is None:
                self._mostrar_contador(r.ficha)
                return r
            usuario, clave, motivo = credenciales
            return self._registrar_visita(
                confirmar_duplicado=True, admin_usuario=usuario, admin_clave=clave,
                motivo_autorizacion=motivo)
        return r

    def _pedir_autorizacion(self, ficha: FichaInvitado) -> tuple[str, str, str] | None:
        dialogo = DialogoAutorizarVisita(ficha, padre=self)
        return dialogo.credenciales() if dialogo.exec() else None

    def _limpiar_campos(self) -> None:
        self.ficha_actual = None
        self.anfitrion = None
        for campo in (self.documento, self.nombre, self.telefono, self.campo_anfitrion):
            campo.clear()
        self.nombre.setEnabled(True)
        self.etiqueta_anfitrion.setText("")

    def limpiar(self) -> None:
        self._limpiar_campos()
        self.estado.setText("Escriba el documento y presione Enter.")
        self.detalle.setText("")
        self.enfocar()

    # --- lista ----------------------------------------------------------------------
    def actualizar(self) -> None:
        try:
            self.filas = self._servicios.invitados.buscar(self._actual, self.busqueda.text())
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(self.filas))
        for i, f in enumerate(self.filas):
            valores = [
                celda(f.nombre, dato=f.id), celda(f.documento), celda(f.telefono),
                celda(str(f.visitas), orden=f.visitas), celda(str(f.visitas_mes), orden=f.visitas_mes),
                celda(fecha(f.ultima_visita) if f.ultima_visita else "Nunca",
                      orden=f.ultima_visita or date.min),
            ]
            for j, item in enumerate(valores):
                self.tabla.setItem(i, j, item)
        self.tabla.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.tabla.setSortingEnabled(True)
        self.total.setText(f"{len(self.filas)} invitados")

    def seleccionado(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            return None
        return self.tabla.item(filas[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def ver_seleccionado(self) -> None:
        invitado_id = self.seleccionado()
        if invitado_id is None:
            mostrar_error(self, ErrorValidacion("Seleccione un invitado de la lista."))
            return
        self.abrir_ficha(invitado_id)

    def _abrir_ficha(self, invitado_id: int) -> None:
        try:
            dialogo = DialogoFichaInvitado(self._servicios, self._actual, invitado_id, padre=self)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        dialogo.exec()
        if dialogo.cambio:
            self.actualizar()


class PestanaReportesInvitados(QWidget):
    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios, self._actual = servicios, actual
        self.reporte_actual = None
        self.anfitrion: tuple[int, str] | None = None
        self.elegir_ruta: Callable[[str, str], str | None] = self._elegir_ruta
        self.abrir: Callable[[Path], None] = abrir_archivo
        hoy = servicios.invitados.hoy()
        todos = actual.puede(Permiso.REPORTES_TODOS)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(10, 10, 10, 10)
        fila = QHBoxLayout()
        self.tipo = _combo([(t, v) for v, t in TIPOS_REPORTE.items() if todos or v == "visitas"])
        self.desde = campo_fecha(hoy.replace(day=1) if todos else hoy)
        self.hasta = campo_fecha(hoy)
        self.campo_anfitrion = QLineEdit()
        self.campo_anfitrion.setPlaceholderText("Cliente anfitrión (opcional)")
        self.campo_anfitrion.setMaximumWidth(260)
        self.boton_generar = boton("Generar", principal=True)
        for w in (self.tipo, QLabel("Desde"), self.desde, QLabel("Hasta"), self.hasta,
                  self.campo_anfitrion, self.boton_generar):
            fila.addWidget(w)
        fila.addStretch()
        capa.addLayout(fila)
        if not todos:
            for w in (self.desde, self.hasta, self.campo_anfitrion):
                w.setEnabled(False)
                w.setToolTip("Recepción ve las visitas de invitados de hoy.")
        self.subtitulo = etiqueta("", "textoSuave")
        capa.addWidget(self.subtitulo)
        self.tabla = tabla([""])
        capa.addWidget(self.tabla, 1)
        abajo = QHBoxLayout()
        abajo.addStretch()
        self.boton_excel = boton("Exportar a Excel…")
        self.boton_pdf = boton("Exportar a PDF…")
        self.boton_imprimir = boton("Imprimir")
        for b in (self.boton_excel, self.boton_pdf, self.boton_imprimir):
            abajo.addWidget(b)
        capa.addLayout(abajo)
        self.tipo.currentIndexChanged.connect(self._al_cambiar_tipo)
        self.campo_anfitrion.textEdited.connect(lambda _: setattr(self, "anfitrion", None))
        self.campo_anfitrion.returnPressed.connect(self.generar)
        self.boton_generar.clicked.connect(self.generar)
        self.boton_excel.clicked.connect(lambda: self.exportar("xlsx"))
        self.boton_pdf.clicked.connect(lambda: self.exportar("pdf"))
        self.boton_imprimir.clicked.connect(self.imprimir)
        self._al_cambiar_tipo()

    def _al_cambiar_tipo(self) -> None:
        self.campo_anfitrion.setVisible(self.tipo.currentData() == "visitas")

    def parametros(self) -> ParametrosReporteInvitados:
        tipo = self.tipo.currentData()
        anfitrion_id = None
        if tipo == "visitas" and self.campo_anfitrion.text().strip():
            if self.anfitrion is None:
                self.anfitrion = elegir_anfitrion(self, self._servicios, self._actual,
                                                  self.campo_anfitrion.text())
                if self.anfitrion:
                    self.campo_anfitrion.setText(self.anfitrion[1])
            anfitrion_id = self.anfitrion[0] if self.anfitrion else None
        if not self._actual.puede(Permiso.REPORTES_TODOS):
            hoy = self._servicios.invitados.hoy()
            return ParametrosReporteInvitados(tipo, hoy, hoy)
        return ParametrosReporteInvitados(tipo, leer_fecha(self.desde), leer_fecha(self.hasta),
                                          anfitrion_id)

    def generar(self):
        try:
            rep = self._servicios.invitados.reporte(self._actual, self.parametros())
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        self.reporte_actual = rep
        self.subtitulo.setText(f"{rep.titulo} · {rep.subtitulo}")
        self.tabla.setSortingEnabled(False)
        self.tabla.clear()
        self.tabla.setColumnCount(len(rep.encabezados))
        self.tabla.setHorizontalHeaderLabels(list(rep.encabezados))
        self.tabla.setRowCount(len(rep.filas))
        for i, fila in enumerate(rep.filas):
            for j, valor in enumerate(fila):
                orden = valor if isinstance(valor, (int, float, date)) else None
                self.tabla.setItem(i, j, celda(_texto_celda(valor), orden=orden))
        self.tabla.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.tabla.setSortingEnabled(True)
        return rep

    @staticmethod
    def _elegir_ruta(sugerido: str, filtro: str) -> str | None:
        ruta, _ = QFileDialog.getSaveFileName(None, "Guardar reporte", sugerido, filtro)
        return ruta or None

    def _nombre(self, formato: str) -> str:
        return f"invitados_{self.tipo.currentData()}_{leer_fecha(self.desde):%Y%m%d}.{formato}"

    def exportar(self, formato: str) -> Path | None:
        filtro = "Excel (*.xlsx)" if formato == "xlsx" else "PDF (*.pdf)"
        sugerido = str(self._servicios.invitados.carpeta_reportes() / self._nombre(formato))
        ruta = self.elegir_ruta(sugerido, filtro)
        if not ruta:
            return None
        if not ruta.lower().endswith(f".{formato}"):
            ruta += f".{formato}"
        return self._exportar(ruta, formato)

    def imprimir(self) -> Path | None:
        ruta = self._servicios.invitados.carpeta_reportes() / self._nombre("pdf")
        destino = self._exportar(str(ruta), "pdf")
        if destino:
            self.abrir(destino)
        return destino

    def _exportar(self, ruta: str, formato: str) -> Path | None:
        try:
            destino = self._servicios.invitados.exportar(
                self._actual, self.parametros(), ruta, formato)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        except OSError:
            mostrar_error(self, ErrorValidacion(
                "No se pudo guardar el archivo. Revise que no esté abierto en otro programa."))
            return None
        self.subtitulo.setText(f"Reporte guardado en {destino}")
        return destino


class PantallaInvitados(QWidget):
    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        capa = QVBoxLayout(self)
        capa.setContentsMargins(24, 20, 24, 20)
        capa.addWidget(etiqueta("Invitados", "tituloPantalla"))
        capa.addWidget(etiqueta(
            "Registre la visita con el documento del invitado: si ya vino antes se reutiliza "
            "su registro y se ve cuántas veces ha venido. Los invitados no pagan.",
            "textoSuave"))
        self.pestanas = QTabWidget()
        self.invitados = PestanaInvitados(servicios, actual)
        self.pestanas.addTab(self.invitados, "Visitas e invitados")
        self.reportes = None
        if actual.puede(Permiso.REPORTES_BASICOS):
            self.reportes = PestanaReportesInvitados(servicios, actual)
            self.pestanas.addTab(self.reportes, "Reportes")
        capa.addWidget(self.pestanas, 1)

    def actualizar(self) -> None:
        self.invitados.actualizar()

    def showEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        super().showEvent(evento)
        self.invitados.actualizar()
        self.invitados.enfocar()
