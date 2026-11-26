"""Pantalla de Configuración (solo administrador): parámetros, usuarios, planes y auditoría."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha_hora_local, pesos
from gimnasio.servicios.auditoria import ACCIONES
from gimnasio.servicios.claves import LONGITUD_MINIMA
from gimnasio.servicios.configuracion import PARAMETROS
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio, ErrorValidacion
from gimnasio.servicios.permisos import ROLES, UsuarioActual
from gimnasio.servicios.planes import DURACION_MAXIMA, DatosPlan
from gimnasio.servicios.usuarios import DatosUsuario
from gimnasio.ui.comunes import boton, celda as _celda, confirmar, etiqueta, mostrar_error
from gimnasio.ui.comunes import tabla as _tabla
from gimnasio.ui.dialogos import _DialogoBase, campo_clave
from gimnasio.ui.pagos import campo_pesos


# --- Parámetros -----------------------------------------------------------------

class PestanaParametros(QWidget):
    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios = servicios
        self._actual = actual
        self.editores: dict[str, QWidget] = {}

        contenido = QWidget()
        capa = QVBoxLayout(contenido)
        grupos: dict[str, QFormLayout] = {}
        for p in PARAMETROS:
            if p.grupo not in grupos:
                caja = QGroupBox(p.grupo)
                grupos[p.grupo] = QFormLayout(caja)
                capa.addWidget(caja)
            if p.tipo == "entero":
                editor = QSpinBox()
                editor.setRange(p.minimo, p.maximo)
                editor.setMaximumWidth(140)
            elif p.tipo == "opcion":
                editor = QComboBox()
                for valor, texto in p.opciones:
                    editor.addItem(texto, valor)
            else:
                editor = QLineEdit()
                editor.setMaxLength(p.largo_maximo)
            if p.ayuda:
                editor.setToolTip(p.ayuda)
            self.editores[p.clave] = editor
            grupos[p.grupo].addRow(p.etiqueta, editor)

        caja_logo = QGroupBox("Logo para recibos")
        capa_logo = QHBoxLayout(caja_logo)
        self.etiqueta_logo = QLabel()
        capa_logo.addWidget(self.etiqueta_logo, 1)
        elegir = boton("Elegir imagen…")
        quitar = boton("Quitar")
        capa_logo.addWidget(elegir)
        capa_logo.addWidget(quitar)
        elegir.clicked.connect(self._elegir_logo)
        quitar.clicked.connect(lambda: self._cambiar_logo(None))
        capa.addWidget(caja_logo)
        capa.addStretch()

        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setWidget(contenido)
        principal = QVBoxLayout(self)
        principal.addWidget(desplazable)
        pie = QHBoxLayout()
        self.mensaje = etiqueta("", "mensajeExito")
        pie.addWidget(self.mensaje, 1)
        self.boton_deshacer = boton("Descartar cambios")
        self.boton_guardar = boton("Guardar cambios", principal=True)
        pie.addWidget(self.boton_deshacer)
        pie.addWidget(self.boton_guardar)
        principal.addLayout(pie)
        self.boton_guardar.clicked.connect(self.guardar)
        self.boton_deshacer.clicked.connect(self.cargar)
        self.cargar()

    def cargar(self) -> None:
        valores = self._servicios.configuracion.obtener_todos()
        for clave, editor in self.editores.items():
            valor = valores[clave]
            if isinstance(editor, QSpinBox):
                editor.setValue(int(valor))
            elif isinstance(editor, QComboBox):
                editor.setCurrentIndex(max(0, editor.findData(valor)))
            else:
                editor.setText(str(valor))
        logo = self._servicios.configuracion.ruta_logo()
        self.etiqueta_logo.setText(logo.name if logo else "Sin logo")
        self.mensaje.clear()

    def valores_editados(self) -> dict:
        valores = {}
        for clave, editor in self.editores.items():
            if isinstance(editor, QSpinBox):
                valores[clave] = editor.value()
            elif isinstance(editor, QComboBox):
                valores[clave] = editor.currentData()
            else:
                valores[clave] = editor.text()
        return valores

    def guardar(self) -> None:
        try:
            cambios = self._servicios.configuracion.guardar(self._actual, self.valores_editados())
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self.mensaje.setText(
            f"Se guardaron {len(cambios)} cambio(s)." if cambios else "No había cambios."
        )

    def _elegir_logo(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Elegir logo", "", "Imágenes (*.png *.jpg *.jpeg)")
        if ruta:
            self._cambiar_logo(ruta)

    def _cambiar_logo(self, ruta) -> None:
        try:
            self._servicios.configuracion.guardar_logo(self._actual, ruta)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self.cargar()
        self.mensaje.setText("Logo actualizado." if ruta else "Logo quitado.")


# --- Usuarios -------------------------------------------------------------------

class DialogoUsuario(_DialogoBase):
    """Crear (con contraseña inicial) o editar un usuario."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual,
                 existente: DatosUsuario | None = None, padre: QWidget | None = None):
        super().__init__("Editar usuario" if existente else "Nuevo usuario", "", padre)
        self._servicios = servicios
        self._actual = actual
        self._existente = existente
        self.campo_nombre = QLineEdit(existente.nombre_completo if existente else "")
        self.campo_usuario = QLineEdit(existente.usuario if existente else "")
        self.campo_rol = QComboBox()
        for valor, texto in ROLES.items():
            self.campo_rol.addItem(texto, valor)
        self.campo_rol.setCurrentIndex(
            self.campo_rol.findData(existente.rol if existente else "recepcion")
        )
        self.formulario.addRow("Nombre completo", self.campo_nombre)
        self.formulario.addRow("Usuario", self.campo_usuario)
        self.formulario.addRow("Rol", self.campo_rol)
        self.campo_clave = self.campo_confirmar = None
        if not existente:
            self.campo_clave = campo_clave(f"mínimo {LONGITUD_MINIMA} caracteres")
            self.campo_confirmar = campo_clave()
            self.formulario.addRow("Contraseña inicial", self.campo_clave)
            self.formulario.addRow("Repetir contraseña", self.campo_confirmar)
            self._capa.insertWidget(
                self._capa.count() - 2,
                etiqueta("El usuario deberá cambiarla la primera vez que entre.", "textoSuave"),
            )
        guardar = boton("Guardar", principal=True)
        cancelar = boton("Cancelar")
        self._botones.addWidget(cancelar)
        self._botones.addWidget(guardar)
        cancelar.clicked.connect(self.reject)
        guardar.clicked.connect(self.guardar)

    def guardar(self) -> None:
        nombre, usuario = self.campo_nombre.text(), self.campo_usuario.text()
        rol = self.campo_rol.currentData()
        try:
            if self._existente:
                self._servicios.usuarios.editar(
                    self._actual, self._existente.id,
                    nombre_completo=nombre, usuario=usuario, rol=rol,
                )
            else:
                if self.campo_clave.text() != self.campo_confirmar.text():
                    raise ErrorValidacion("Las contraseñas no coinciden.")
                self._servicios.usuarios.crear(
                    self._actual, nombre, usuario, rol, self.campo_clave.text()
                )
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            return
        self.accept()


class DialogoClaveTemporal(_DialogoBase):
    def __init__(self, servicios: Servicios, actual: UsuarioActual, objetivo: DatosUsuario,
                 padre: QWidget | None = None):
        super().__init__(
            "Restablecer contraseña",
            f"Asigne una contraseña temporal a {objetivo.nombre_completo}. Se quitará el "
            "bloqueo si lo tiene y deberá cambiarla al entrar.",
            padre,
        )
        self._servicios, self._actual, self._objetivo = servicios, actual, objetivo
        self.campo_clave = campo_clave(f"mínimo {LONGITUD_MINIMA} caracteres")
        self.campo_confirmar = campo_clave()
        self.formulario.addRow("Contraseña temporal", self.campo_clave)
        self.formulario.addRow("Repetir", self.campo_confirmar)
        guardar = boton("Restablecer", principal=True)
        cancelar = boton("Cancelar")
        self._botones.addWidget(cancelar)
        self._botones.addWidget(guardar)
        cancelar.clicked.connect(self.reject)
        guardar.clicked.connect(self.guardar)

    def guardar(self) -> None:
        try:
            if self.campo_clave.text() != self.campo_confirmar.text():
                raise ErrorValidacion("Las contraseñas no coinciden.")
            self._servicios.usuarios.restablecer_clave(
                self._actual, self._objetivo.id, self.campo_clave.text()
            )
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            return
        self.accept()


class PestanaUsuarios(QWidget):
    COLUMNAS = ["Nombre", "Usuario", "Rol", "Estado", "Último ingreso"]

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios = servicios
        self._actual = actual
        self._usuarios: dict[int, DatosUsuario] = {}
        capa = QVBoxLayout(self)
        barra = QHBoxLayout()
        self.boton_nuevo = boton("Nuevo usuario", principal=True)
        self.boton_editar = boton("Editar")
        self.boton_clave = boton("Restablecer contraseña")
        self.boton_estado = boton("Desactivar")
        for b in (self.boton_nuevo, self.boton_editar, self.boton_clave, self.boton_estado):
            barra.addWidget(b)
        barra.addStretch()
        capa.addLayout(barra)
        capa.addWidget(etiqueta(
            "Los usuarios no se eliminan: se desactivan y quedan en el historial.", "textoSuave"
        ))
        self.tabla = _tabla(self.COLUMNAS)
        self.tabla.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        capa.addWidget(self.tabla)
        self.boton_nuevo.clicked.connect(self.nuevo)
        self.boton_editar.clicked.connect(self.editar)
        self.boton_clave.clicked.connect(self.restablecer)
        self.boton_estado.clicked.connect(self.cambiar_estado)
        self.tabla.itemSelectionChanged.connect(self._actualizar_botones)
        self.tabla.doubleClicked.connect(self.editar)
        self.cargar()

    def cargar(self) -> None:
        try:
            lista = self._servicios.usuarios.listar(self._actual)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self._usuarios = {u.id: u for u in lista}
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(lista))
        for fila, u in enumerate(lista):
            estado = "Activo" if u.activo else "Inactivo"
            if u.activo and u.bloqueado_hasta:
                estado = "Activo (bloqueo temporal)"
            valores = [
                u.nombre_completo, u.usuario, u.nombre_rol, estado,
                fecha_hora_local(u.ultimo_login) if u.ultimo_login else "Nunca",
            ]
            for col, texto in enumerate(valores):
                orden = None
                if col == 4:
                    orden = u.ultimo_login.isoformat() if u.ultimo_login else ""
                self.tabla.setItem(fila, col, _celda(texto, u.id, orden))
        self.tabla.setSortingEnabled(True)
        self._actualizar_botones()

    def seleccionado(self) -> DatosUsuario | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            return None
        return self._usuarios.get(self.tabla.item(filas[0].row(), 0).data(Qt.ItemDataRole.UserRole))

    def _actualizar_botones(self) -> None:
        u = self.seleccionado()
        for b in (self.boton_editar, self.boton_clave, self.boton_estado):
            b.setEnabled(u is not None)
        self.boton_estado.setText("Activar" if u and not u.activo else "Desactivar")

    def nuevo(self) -> None:
        if DialogoUsuario(self._servicios, self._actual, padre=self).exec() == QDialog.DialogCode.Accepted:
            self.cargar()

    def editar(self) -> None:
        u = self.seleccionado()
        if u and DialogoUsuario(self._servicios, self._actual, u, self).exec() == QDialog.DialogCode.Accepted:
            self.cargar()

    def restablecer(self) -> None:
        u = self.seleccionado()
        if u and DialogoClaveTemporal(self._servicios, self._actual, u, self).exec() == QDialog.DialogCode.Accepted:
            self.cargar()

    def cambiar_estado(self) -> None:
        u = self.seleccionado()
        if not u:
            return
        try:
            if u.activo:
                if not confirmar(self, "Desactivar usuario",
                                 f"¿Desactivar a {u.nombre_completo}? No podrá iniciar sesión."):
                    return
                self._servicios.usuarios.desactivar(self._actual, u.id)
            else:
                self._servicios.usuarios.activar(self._actual, u.id)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self.cargar()


# --- Planes ---------------------------------------------------------------------

class DialogoPlan(_DialogoBase):
    def __init__(self, servicios: Servicios, actual: UsuarioActual,
                 existente: DatosPlan | None = None, padre: QWidget | None = None):
        super().__init__(
            "Editar plan" if existente else "Nuevo plan",
            "Cambiar el precio o la duración no modifica las membresías ya registradas.",
            padre,
        )
        self._servicios, self._actual, self._existente = servicios, actual, existente
        self.campo_nombre = QLineEdit(existente.nombre if existente else "")
        self.campo_nombre.setMaxLength(60)
        self.campo_dias = QSpinBox()
        self.campo_dias.setRange(1, DURACION_MAXIMA)
        self.campo_dias.setValue(existente.duracion_dias if existente else 30)
        self.campo_dias.setSuffix(" días")
        self.campo_precio = campo_pesos(existente.precio if existente else 0)
        self.formulario.addRow("Nombre", self.campo_nombre)
        self.formulario.addRow("Duración", self.campo_dias)
        self.formulario.addRow("Precio", self.campo_precio)
        guardar = boton("Guardar", principal=True)
        cancelar = boton("Cancelar")
        self._botones.addWidget(cancelar)
        self._botones.addWidget(guardar)
        cancelar.clicked.connect(self.reject)
        guardar.clicked.connect(self.guardar)

    def guardar(self) -> None:
        argumentos = (self.campo_nombre.text(), self.campo_dias.value(), self.campo_precio.value())
        try:
            if self._existente:
                self._servicios.planes.editar(self._actual, self._existente.id, *argumentos)
            else:
                self._servicios.planes.crear(self._actual, *argumentos)
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            return
        self.accept()


class PestanaPlanes(QWidget):
    COLUMNAS = ["Plan", "Duración", "Precio", "Estado"]

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios, self._actual = servicios, actual
        self._planes: dict[int, DatosPlan] = {}
        capa = QVBoxLayout(self)
        barra = QHBoxLayout()
        self.boton_nuevo = boton("Nuevo plan", principal=True)
        self.boton_editar = boton("Editar")
        self.boton_estado = boton("Desactivar")
        for b in (self.boton_nuevo, self.boton_editar, self.boton_estado):
            barra.addWidget(b)
        barra.addStretch()
        capa.addLayout(barra)
        capa.addWidget(etiqueta(
            "Los planes no se eliminan: se desactivan y dejan de ofrecerse. Los planes de "
            "ejemplo vienen sin precio y desactivados: póngales el precio y actívelos.",
            "textoSuave",
        ))
        self.tabla = _tabla(self.COLUMNAS)
        self.tabla.horizontalHeader().setSortIndicator(1, Qt.SortOrder.AscendingOrder)
        capa.addWidget(self.tabla)
        self.boton_nuevo.clicked.connect(self.nuevo)
        self.boton_editar.clicked.connect(self.editar)
        self.boton_estado.clicked.connect(self.cambiar_estado)
        self.tabla.itemSelectionChanged.connect(self._actualizar_botones)
        self.tabla.doubleClicked.connect(self.editar)
        self.cargar()

    def cargar(self) -> None:
        try:
            lista = self._servicios.planes.listar(self._actual)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self._planes = {p.id: p for p in lista}
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(lista))
        for fila, p in enumerate(lista):
            dias = "1 día" if p.duracion_dias == 1 else f"{p.duracion_dias} días"
            self.tabla.setItem(fila, 0, _celda(p.nombre, p.id))
            self.tabla.setItem(fila, 1, _celda(dias, orden=p.duracion_dias))
            self.tabla.setItem(fila, 2, _celda(pesos(p.precio), orden=p.precio))
            self.tabla.setItem(fila, 3, _celda("Activo" if p.activo else "Inactivo"))
        self.tabla.setSortingEnabled(True)
        self._actualizar_botones()

    def seleccionado(self) -> DatosPlan | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            return None
        return self._planes.get(self.tabla.item(filas[0].row(), 0).data(Qt.ItemDataRole.UserRole))

    def _actualizar_botones(self) -> None:
        p = self.seleccionado()
        self.boton_editar.setEnabled(p is not None)
        self.boton_estado.setEnabled(p is not None)
        self.boton_estado.setText("Activar" if p and not p.activo else "Desactivar")

    def nuevo(self) -> None:
        if DialogoPlan(self._servicios, self._actual, padre=self).exec() == QDialog.DialogCode.Accepted:
            self.cargar()

    def editar(self) -> None:
        p = self.seleccionado()
        if p and DialogoPlan(self._servicios, self._actual, p, self).exec() == QDialog.DialogCode.Accepted:
            self.cargar()

    def cambiar_estado(self) -> None:
        p = self.seleccionado()
        if not p:
            return
        if p.activo is False and p.precio == 0 and not confirmar(
            self, "Activar plan", f"El plan {p.nombre} tiene precio $ 0. ¿Activarlo así?"
        ):
            return
        try:
            self._servicios.planes.cambiar_activo(self._actual, p.id, not p.activo)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self.cargar()


# --- Auditoría ------------------------------------------------------------------

class PestanaAuditoria(QWidget):
    COLUMNAS = ["Fecha y hora", "Usuario", "Acción", "Entidad", "Detalle"]

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios = servicios
        self._actual = actual
        capa = QVBoxLayout(self)
        filtros = QHBoxLayout()
        hoy = QDate.currentDate()
        self.desde = QDateEdit(hoy.addDays(-7))
        self.hasta = QDateEdit(hoy)
        for campo in (self.desde, self.hasta):
            campo.setCalendarPopup(True)
            campo.setDisplayFormat("dd/MM/yyyy")
        self.usuario = QComboBox()
        self.accion = QComboBox()
        self.accion.addItem("Todas las acciones", None)
        for clave, texto in ACCIONES.items():
            self.accion.addItem(texto, clave)
        self.texto = QLineEdit()
        self.texto.setPlaceholderText("Buscar en el detalle…")
        self.texto.setMinimumWidth(180)
        self.boton_buscar = boton("Buscar", principal=True)
        for texto, w in (("Desde", self.desde), ("Hasta", self.hasta)):
            filtros.addWidget(QLabel(texto))
            filtros.addWidget(w)
        filtros.addWidget(self.usuario)
        filtros.addWidget(self.accion)
        filtros.addWidget(self.texto, 1)
        filtros.addWidget(self.boton_buscar)
        capa.addLayout(filtros)
        self.resumen = etiqueta("", "textoSuave")
        capa.addWidget(self.resumen)
        self.tabla = _tabla(self.COLUMNAS)
        self.tabla.horizontalHeader().setSortIndicator(0, Qt.SortOrder.DescendingOrder)
        capa.addWidget(self.tabla)
        self.boton_buscar.clicked.connect(self.buscar)
        self.texto.returnPressed.connect(self.buscar)
        self._cargar_usuarios()
        self.buscar()

    def _cargar_usuarios(self) -> None:
        self.usuario.clear()
        self.usuario.addItem("Todos los usuarios", None)
        try:
            for u in self._servicios.usuarios.listar(self._actual):
                self.usuario.addItem(u.usuario, u.id)
        except ErrorNegocio:
            pass

    @staticmethod
    def _fecha(campo: QDateEdit) -> date:
        q = campo.date()
        return date(q.year(), q.month(), q.day())

    def buscar(self) -> None:
        try:
            filas = self._servicios.auditoria.consultar(
                self._actual, desde=self._fecha(self.desde), hasta=self._fecha(self.hasta),
                usuario_id=self.usuario.currentData(), accion=self.accion.currentData(),
                texto=self.texto.text() or None,
            )
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(filas))
        for i, f in enumerate(filas):
            entidad = f.entidad + (f" #{f.entidad_id}" if f.entidad_id else "")
            self.tabla.setItem(i, 0, _celda(fecha_hora_local(f.fecha_hora), orden=(f.fecha_hora.isoformat(), f.id)))
            for col, texto in enumerate([f.usuario, f.descripcion, entidad, f.detalle], start=1):
                self.tabla.setItem(i, col, _celda(texto))
        self.tabla.setSortingEnabled(True)
        self.resumen.setText(f"{len(filas)} registro(s), del más reciente al más antiguo.")


class PantallaConfiguracion(QWidget):
    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        capa = QVBoxLayout(self)
        capa.setContentsMargins(24, 20, 24, 20)
        capa.addWidget(etiqueta("Configuración", "tituloPantalla"))
        self.pestanas = QTabWidget()
        self.parametros = PestanaParametros(servicios, actual)
        self.usuarios = PestanaUsuarios(servicios, actual)
        self.planes = PestanaPlanes(servicios, actual)
        self.auditoria = PestanaAuditoria(servicios, actual)
        self.pestanas.addTab(self.parametros, "Parámetros")
        self.pestanas.addTab(self.usuarios, "Usuarios")
        self.pestanas.addTab(self.planes, "Planes")
        self.pestanas.addTab(self.auditoria, "Auditoría")
        self.pestanas.currentChanged.connect(self._al_cambiar)
        capa.addWidget(self.pestanas)

    def _al_cambiar(self, indice: int) -> None:
        if self.pestanas.widget(indice) is self.auditoria:
            self.auditoria._cargar_usuarios()
            self.auditoria.buscar()
