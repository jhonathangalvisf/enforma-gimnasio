"""Ventana principal: barra superior (búsqueda Ctrl+K, usuario, cerrar sesión),
navegación lateral y área de pantallas. Controla el cierre por inactividad."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QStackedWidget, QVBoxLayout, QWidget,
)

from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.permisos import Permiso, UsuarioActual
from gimnasio.servicios.sesion import ControlInactividad
from gimnasio.servicios.errores import ErrorNegocio
from gimnasio.ui.cliente_ficha import DialogoFicha
from gimnasio.ui.clientes import DialogoElegirCliente, PantallaClientes
from gimnasio.ui.comunes import boton, etiqueta, mostrar_error
from gimnasio.ui.configuracion import PantallaConfiguracion
from gimnasio.ui.dialogos import DialogoCambiarClave
from gimnasio.ui.pagos import PantallaPagos

INTERVALO_REVISION_MS = 15_000


@dataclass(frozen=True)
class Modulo:
    clave: str
    titulo: str
    permiso: Permiso
    descripcion: str
    fase: int | None = None  # fase en la que se construye (None = ya disponible)


MODULOS: tuple[Modulo, ...] = (
    Modulo("recepcion", "Recepción", Permiso.REGISTRAR_ASISTENCIA,
           "Ingreso de clientes con el código o el lector: tarjeta verde, amarilla o roja.", 4),
    Modulo("clientes", "Clientes", Permiso.VER_CLIENTES,
           "Registro, consulta y modificación de clientes con búsqueda instantánea."),
    Modulo("asistencia", "Asistencia", Permiso.REGISTRAR_ASISTENCIA,
           "Consulta de asistencias por día y por cliente.", 4),
    Modulo("casilleros", "Casilleros", Permiso.ASIGNAR_CASILLERO,
           "Asignación, liberación e historial de casilleros.", 5),
    Modulo("invitados", "Invitados", Permiso.REGISTRAR_INVITADOS,
           "Registro de invitados y conteo de visitas.", 6),
    Modulo("pagos", "Pagos", Permiso.REGISTRAR_PAGOS,
           "Membresías, pagos, recibos y cierre de caja."),
    Modulo("reportes", "Reportes", Permiso.REPORTES_BASICOS,
           "Reportes con filtros, exportación a Excel y PDF.", 7),
    Modulo("configuracion", "Configuración", Permiso.CONFIGURACION,
           "Parámetros, usuarios, planes y auditoría."),
    Modulo("ayuda", "Ayuda", Permiso.AYUDA,
           "Explicación de cada módulo en lenguaje sencillo (F1).", 8),
)


class PantallaProximamente(QWidget):
    def __init__(self, modulo: Modulo):
        super().__init__()
        capa = QVBoxLayout(self)
        capa.setContentsMargins(24, 20, 24, 20)
        capa.addWidget(etiqueta(modulo.titulo, "tituloPantalla"))
        capa.addWidget(etiqueta(modulo.descripcion, "textoSuave"))
        tarjeta = QWidget()
        tarjeta.setObjectName("tarjeta")
        interior = QVBoxLayout(tarjeta)
        interior.setContentsMargins(24, 24, 24, 24)
        interior.addWidget(etiqueta(f"Este módulo se construye en la Fase {modulo.fase}."))
        capa.addSpacing(12)
        capa.addWidget(tarjeta)
        capa.addStretch()


class FiltroActividad(QObject):
    """Cualquier tecla, clic o rueda del ratón en la aplicación cuenta como actividad."""

    EVENTOS = {QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel}

    def __init__(self, control: ControlInactividad):
        super().__init__()
        self._control = control

    def eventFilter(self, objeto, evento) -> bool:  # noqa: N802 (nombre de Qt)
        if evento.type() in self.EVENTOS:
            self._control.registrar_actividad()
        return False


class VentanaPrincipal(QMainWindow):
    # True si el cierre fue por inactividad.
    sesion_cerrada = Signal(bool)
    salir = Signal()

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios = servicios
        self.actual = actual
        self._cerrando_sesion = False
        nombre = servicios.configuracion.obtener("gimnasio_nombre") or "Enforma"
        self.setWindowTitle(f"{nombre} — Gestión del gimnasio")
        self.resize(1280, 800)

        central = QWidget()
        capa = QVBoxLayout(central)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(0)
        capa.addWidget(self._crear_barra_superior(nombre))
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(0)
        self.navegacion = QListWidget()
        self.navegacion.setObjectName("navegacion")
        self.navegacion.setFixedWidth(210)
        self.pantallas = QStackedWidget()
        cuerpo.addWidget(self.navegacion)
        cuerpo.addWidget(self.pantallas, 1)
        capa.addLayout(cuerpo, 1)
        self.setCentralWidget(central)

        self.pantalla_clientes: PantallaClientes | None = None
        self.pantalla_pagos: PantallaPagos | None = None
        self.ficha_abierta: DialogoFicha | None = None
        self._indices: dict[str, int] = {}
        for modulo in MODULOS:
            if not actual.puede(modulo.permiso):
                continue  # los servicios igual validan el permiso
            pantalla = self._crear_pantalla(modulo)
            self._indices[modulo.clave] = self.pantallas.addWidget(pantalla)
            item = QListWidgetItem(modulo.titulo)
            item.setData(Qt.ItemDataRole.UserRole, modulo.clave)
            self.navegacion.addItem(item)
        self.navegacion.currentRowChanged.connect(self.pantallas.setCurrentIndex)
        self.navegacion.setCurrentRow(0)
        self.statusBar().showMessage(f"Bienvenido, {actual.nombre_completo}.", 5000)

        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.enfocar_busqueda)

        minutos = servicios.configuracion.obtener("minutos_inactividad")
        self.control_inactividad = ControlInactividad(minutos)
        self._filtro = FiltroActividad(self.control_inactividad)
        QApplication.instance().installEventFilter(self._filtro)
        self._temporizador = QTimer(self)
        self._temporizador.setInterval(INTERVALO_REVISION_MS)
        self._temporizador.timeout.connect(self.revisar_inactividad)
        self._temporizador.start()

    # --- construcción -------------------------------------------------------
    def _crear_barra_superior(self, nombre: str) -> QWidget:
        barra = QWidget()
        barra.setObjectName("barraSuperior")
        capa = QHBoxLayout(barra)
        capa.setContentsMargins(18, 10, 18, 10)
        capa.addWidget(etiqueta(nombre, "tituloApp"))
        capa.addSpacing(24)
        self.busqueda = QLineEdit()
        self.busqueda.setObjectName("busquedaGlobal")
        self.busqueda.setPlaceholderText("Buscar cliente por código, nombre, documento, teléfono o correo  (Ctrl+K)")
        self.busqueda.returnPressed.connect(self.buscar)
        capa.addWidget(self.busqueda, 1)
        capa.addSpacing(24)
        self.etiqueta_usuario = etiqueta(
            f"{self.actual.nombre_completo} · {self.actual.nombre_rol}", "usuarioActual"
        )
        self.etiqueta_usuario.setWordWrap(False)
        capa.addWidget(self.etiqueta_usuario)
        self.boton_clave = boton("Cambiar contraseña")
        self.boton_cerrar = boton("Cerrar sesión")
        self.boton_clave.clicked.connect(self.cambiar_clave)
        self.boton_cerrar.clicked.connect(lambda: self.cerrar_sesion(False))
        capa.addWidget(self.boton_clave)
        capa.addWidget(self.boton_cerrar)
        return barra

    def _crear_pantalla(self, modulo: Modulo) -> QWidget:
        if modulo.clave == "configuracion":
            return PantallaConfiguracion(self._servicios, self.actual)
        if modulo.clave == "clientes":
            self.pantalla_clientes = PantallaClientes(self._servicios, self.actual)
            self.pantalla_clientes.abrir_ficha.connect(self.abrir_ficha)
            return self.pantalla_clientes
        if modulo.clave == "pagos":
            self.pantalla_pagos = PantallaPagos(self._servicios, self.actual)
            return self.pantalla_pagos
        return PantallaProximamente(modulo)

    # --- acciones -----------------------------------------------------------
    def modulos_visibles(self) -> list[str]:
        return list(self._indices)

    def ir_a(self, clave: str) -> None:
        if clave in self._indices:
            self.navegacion.setCurrentRow(self._indices[clave])

    def modulo_actual(self) -> str | None:
        item = self.navegacion.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def enfocar_busqueda(self) -> None:
        self.busqueda.setFocus()
        self.busqueda.selectAll()

    def buscar(self) -> int | None:
        """Búsqueda global: un resultado abre la ficha; varios muestran la lista."""
        texto = self.busqueda.text().strip()
        if not texto:
            return None
        try:
            filas = self._servicios.clientes.buscar_rapido(self.actual, texto)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        if not filas:
            self.statusBar().showMessage(f"No se encontró ningún cliente con «{texto}».", 5000)
            return None
        cliente_id = filas[0].id
        if len(filas) > 1:
            dialogo = DialogoElegirCliente(filas, texto, padre=self)
            if not dialogo.exec():
                return None
            cliente_id = dialogo.cliente_id
        self.busqueda.clear()
        self.abrir_ficha(cliente_id)
        return cliente_id

    def abrir_ficha(self, cliente_id: int) -> None:
        try:
            dialogo = DialogoFicha(self._servicios, self.actual, cliente_id, padre=self)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self.ficha_abierta = dialogo
        dialogo.exec()
        self.ficha_abierta = None
        if dialogo.cambio and getattr(self, "pantalla_clientes", None):
            self.pantalla_clientes.actualizar()
        if dialogo.cambio and getattr(self, "pantalla_pagos", None):
            self.pantalla_pagos.actualizar()

    def cambiar_clave(self) -> None:
        dialogo = DialogoCambiarClave(self._servicios, self.actual, padre=self)
        if dialogo.exec():
            self.statusBar().showMessage("Contraseña cambiada.", 4000)

    def revisar_inactividad(self) -> None:
        if self.control_inactividad.vencido(en_recepcion=self.modulo_actual() == "recepcion"):
            self.cerrar_sesion(True)

    def cerrar_sesion(self, por_inactividad: bool) -> None:
        if self._cerrando_sesion:
            return
        self._cerrando_sesion = True
        self._detener()
        self._servicios.sesion.cerrar_sesion(self.actual, por_inactividad=por_inactividad)
        self.close()
        self.sesion_cerrada.emit(por_inactividad)

    def _detener(self) -> None:
        self._temporizador.stop()
        app = QApplication.instance()
        if app:
            app.removeEventFilter(self._filtro)

    def closeEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        if not self._cerrando_sesion:
            # Cerrar con la X equivale a cerrar sesión y salir.
            self._cerrando_sesion = True
            self._detener()
            self._servicios.sesion.cerrar_sesion(self.actual)
            self.salir.emit()
        evento.accept()
