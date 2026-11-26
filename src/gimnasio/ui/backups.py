"""Pantalla de Copias de seguridad (solo administrador) y piezas compartidas:
avisos del inicio, copia en segundo plano y ventana de espera al cerrar."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QTabWidget, QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha_hora_local, tamano_archivo
from gimnasio.servicios.backups import (
    TIPO_MANUAL, TIPOS, ArchivoBackup, EstadoBackups, ResultadoBackup, ServicioBackups,
    TareaBackup,
)
from gimnasio.servicios.claves import LONGITUD_MINIMA
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio
from gimnasio.servicios.permisos import UsuarioActual
from gimnasio.ui.comunes import boton, celda, confirmar, etiqueta, mostrar_error, tabla
from gimnasio.ui.dialogos import _DialogoBase, campo_clave

ADVERTENCIA_CLAVE = (
    "Si pierde la contraseña de las copias, las copias NO se pueden recuperar. "
    "Escríbala y guárdela en un lugar seguro fuera del computador."
)


# --- avisos ------------------------------------------------------------------------

def _hace(estado: EstadoBackups) -> str:
    dias = estado.dias_sin_copia
    if dias is None:
        return ""
    return "hoy" if dias == 0 else ("hace 1 día" if dias == 1 else f"hace {dias} días")


def textos_aviso(estado: EstadoBackups, es_admin: bool) -> list[str]:
    """Avisos de la barra amarilla del inicio. Recepción solo ve el de copia vieja."""
    avisos: list[str] = []
    if estado.alerta_antigua:
        if estado.ultima_exitosa is None:
            texto = "No hay ninguna copia de seguridad todavía."
        else:
            texto = (f"La última copia de seguridad buena es del "
                     f"{fecha_hora_local(estado.ultima_exitosa)} ({_hace(estado)}).")
        avisos.append(texto + (" Haga una copia ahora." if es_admin
                               else " Avise al administrador."))
    if not es_admin:
        return avisos
    if not estado.clave_configurada:
        avisos.append("Falta crear la contraseña de las copias de seguridad: sin ella no "
                      "se hacen las copias automáticas.")
    if estado.destino and estado.destino_disponible is False:
        avisos.append(f"El disco externo de las copias no está conectado ({estado.destino}). "
                      "Las copias quedan solo en este PC.")
    if estado.ultima_exitosa is not None and estado.recordatorio_externo:
        avisos.append("Recordatorio semanal: lleve una copia a un disco fuera del local "
                      "(Copias de seguridad → Copiar a otro disco).")
    return avisos


# --- copia en segundo plano --------------------------------------------------------

class HiloBackup(QThread):
    """Corre `ServicioBackups.ejecutar` (solo archivos) fuera del hilo de la interfaz."""

    def __init__(self, servicio: ServicioBackups, tarea: TareaBackup):
        super().__init__()
        self._servicio = servicio
        self._tarea = tarea
        self.resultado: ResultadoBackup | None = None

    def run(self) -> None:  # noqa: D401 - nombre de Qt
        self.resultado = self._servicio.ejecutar(self._tarea)


class VentanaEspera(QDialog):
    """Ventana sin botones mientras se hace la copia (por ejemplo, al cerrar)."""

    def __init__(self, texto: str, padre: QWidget | None = None):
        super().__init__(padre)
        self.setWindowTitle("Copia de seguridad")
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setModal(True)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(28, 22, 28, 22)
        capa.addWidget(etiqueta(texto, "tituloPantalla"))
        capa.addWidget(etiqueta("No apague el computador. Tarda unos segundos.", "textoSuave"))
        self.setMinimumWidth(420)

    def reject(self) -> None:  # Esc no la cierra
        pass


def ejecutar_con_espera(servicio: ServicioBackups, tarea: TareaBackup, texto: str,
                        padre: QWidget | None = None) -> ResultadoBackup:
    """Hace la copia en otro hilo mostrando una ventana de espera, y la registra."""
    espera = VentanaEspera(texto, padre)
    espera.show()
    hilo = HiloBackup(servicio, tarea)
    hilo.start()
    app = QApplication.instance()
    while not hilo.wait(40):
        app.processEvents()
    espera.hide()
    espera.deleteLater()
    servicio.registrar(hilo.resultado)
    return hilo.resultado


# --- diálogos ----------------------------------------------------------------------

class DialogoClaveBackups(_DialogoBase):
    def __init__(self, servicios: Servicios, actual: UsuarioActual, padre=None):
        nueva = not servicios.backups.clave_configurada()
        super().__init__(
            "Crear contraseña de copias" if nueva else "Cambiar contraseña de copias",
            "Con esta contraseña se cifran las copias. Se guarda protegida en este PC para "
            "que las copias automáticas no la pidan; para restaurar siempre se pide.",
            padre,
        )
        self._servicios = servicios
        self._actual = actual
        aviso = etiqueta(ADVERTENCIA_CLAVE, "avisoClave")
        self._capa.insertWidget(2, aviso)
        if not nueva:
            self._capa.insertWidget(3, etiqueta(
                "Las copias que ya existen siguen abriéndose con la contraseña anterior.",
                "textoSuave"))
        self.campo_clave = campo_clave(f"Mínimo {LONGITUD_MINIMA} caracteres")
        self.campo_confirmar = campo_clave("Repita la contraseña")
        self.casilla = QCheckBox("La anoté y la guardé en un lugar seguro")
        self.formulario.addRow("Contraseña", self.campo_clave)
        self.formulario.addRow("Confirmar", self.campo_confirmar)
        self.formulario.addRow("", self.casilla)
        cancelar = boton("Cancelar")
        self.boton_guardar = boton("Guardar", principal=True)
        cancelar.clicked.connect(self.reject)
        self.boton_guardar.clicked.connect(self.guardar)
        self.campo_clave.returnPressed.connect(self.campo_confirmar.setFocus)
        self.campo_confirmar.returnPressed.connect(self.guardar)
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_guardar)

    def guardar(self) -> None:
        if not self.casilla.isChecked():
            self.mostrar_error("Confirme que guardó la contraseña en un lugar seguro.")
            return
        try:
            self._servicios.backups.configurar_clave(
                self._actual, self.campo_clave.text(), self.campo_confirmar.text())
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            return
        self.accept()


class DialogoRestaurar(_DialogoBase):
    def __init__(self, servicios: Servicios, actual: UsuarioActual, archivo: ArchivoBackup,
                 padre=None):
        super().__init__(
            "Restaurar copia de seguridad",
            "Los datos actuales (clientes, pagos, asistencias, fotos…) se reemplazan por los "
            "de esta copia. Antes se hace una copia del estado actual por si acaso. Al "
            "terminar se cierra la sesión.",
            padre,
        )
        self._servicios = servicios
        self._actual = actual
        self._archivo = archivo
        self.resumen = None
        self.formulario.addRow("Archivo", etiqueta(archivo.ruta.name))
        self.formulario.addRow("Fecha", etiqueta(
            fecha_hora_local(archivo.creado) if archivo.creado else "Desconocida"))
        self.formulario.addRow("Contenido", etiqueta(_contenido(archivo)))
        self.campo_clave = campo_clave("Contraseña con la que se hizo la copia")
        self.casilla = QCheckBox("Entiendo que los datos actuales se reemplazan")
        self.formulario.addRow("Contraseña", self.campo_clave)
        self.formulario.addRow("", self.casilla)
        cancelar = boton("Cancelar")
        self.boton_restaurar = boton("Restaurar", principal=True)
        cancelar.clicked.connect(self.reject)
        self.boton_restaurar.clicked.connect(self.restaurar)
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_restaurar)

    def restaurar(self) -> None:
        if not self.campo_clave.text():
            self.mostrar_error("Escriba la contraseña de la copia.")
            return
        if not self.casilla.isChecked():
            self.mostrar_error("Marque la casilla para confirmar que entiende el cambio.")
            return
        self.boton_restaurar.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.resumen = self._servicios.backups.restaurar(
                self._actual, self._archivo.ruta, self.campo_clave.text())
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            self.boton_restaurar.setEnabled(True)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.accept()


def _contenido(archivo: ArchivoBackup) -> str:
    conteos = (archivo.resumen or {}).get("conteos") or {}
    if not conteos:
        return "—"
    numero = lambda n: f"{n:,}".replace(",", ".")  # noqa: E731
    return (f"{numero(conteos.get('clientes', 0))} clientes, "
            f"{numero(conteos.get('pagos', 0))} pagos, "
            f"{numero(conteos.get('asistencias', 0))} asistencias, "
            f"{archivo.resumen.get('fotos', 0)} fotos")


# --- pantalla ----------------------------------------------------------------------

class PantallaBackups(QWidget):
    restaurado = Signal()  # la interfaz debe cerrar la sesión
    estado_cambiado = Signal()  # para actualizar los avisos de la ventana

    COLUMNAS_COPIAS = ["Fecha", "Tipo", "Ubicación", "Tamaño", "Contenido", "Archivo"]
    COLUMNAS_HISTORIAL = ["Fecha", "Tipo", "Resultado", "Archivo o destino", "Detalle"]

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios = servicios
        self._actual = actual
        self._copias: list[ArchivoBackup] = []
        capa = QVBoxLayout(self)
        capa.setContentsMargins(24, 20, 24, 20)
        capa.addWidget(etiqueta("Copias de seguridad", "tituloPantalla"))
        capa.addWidget(etiqueta(
            "Copias cifradas de toda la información del gimnasio. Se hacen solas al cerrar "
            "el programa y a la hora diaria; también con «Backup ahora».", "textoSuave"))

        tarjeta = QWidget()
        tarjeta.setObjectName("tarjeta")
        rejilla = QGridLayout(tarjeta)
        rejilla.setContentsMargins(18, 14, 18, 14)
        rejilla.setHorizontalSpacing(18)
        self.valores: dict[str, QLabel] = {}
        for fila, (clave, texto) in enumerate((
            ("ultima", "Última copia buena"), ("diaria", "Copia diaria"),
            ("destino", "Disco externo o USB"), ("clave", "Contraseña"),
            ("externa", "Última copia fuera del local"),
        )):
            rejilla.addWidget(etiqueta(texto, "textoSuave"), fila, 0)
            self.valores[clave] = etiqueta("")
            rejilla.addWidget(self.valores[clave], fila, 1)
        rejilla.setColumnStretch(1, 1)
        capa.addSpacing(8)
        capa.addWidget(tarjeta)

        botones = QHBoxLayout()
        self.boton_ahora = boton("Backup ahora", principal=True)
        self.boton_destino = boton("Elegir disco externo…")
        self.boton_quitar_destino = boton("Quitar disco externo")
        self.boton_llevar = boton("Copiar a otro disco…")
        self.boton_clave = boton("Contraseña…")
        for b in (self.boton_ahora, self.boton_destino, self.boton_quitar_destino,
                  self.boton_llevar, self.boton_clave):
            botones.addWidget(b)
        botones.addStretch()
        capa.addLayout(botones)
        self.mensaje = etiqueta("", "mensajeExito")
        capa.addWidget(self.mensaje)
        capa.addWidget(etiqueta(ADVERTENCIA_CLAVE, "avisoClave"))

        self.pestanas = QTabWidget()
        pagina = QWidget()
        capa_pagina = QVBoxLayout(pagina)
        self.tabla_copias = tabla(self.COLUMNAS_COPIAS)
        self.tabla_copias.doubleClicked.connect(lambda *_: self.restaurar_seleccionada())
        capa_pagina.addWidget(self.tabla_copias)
        fila_botones = QHBoxLayout()
        self.boton_verificar = boton("Verificar copia…")
        self.boton_restaurar = boton("Restaurar copia…")
        self.boton_archivo = boton("Restaurar desde un archivo…")
        for b in (self.boton_verificar, self.boton_restaurar, self.boton_archivo):
            fila_botones.addWidget(b)
        fila_botones.addStretch()
        capa_pagina.addLayout(fila_botones)
        self.pestanas.addTab(pagina, "Copias guardadas")
        self.tabla_historial = tabla(self.COLUMNAS_HISTORIAL)
        self.pestanas.addTab(self.tabla_historial, "Historial")
        capa.addWidget(self.pestanas, 1)

        self.boton_ahora.clicked.connect(self.backup_ahora)
        self.boton_destino.clicked.connect(lambda: self.elegir_destino())
        self.boton_quitar_destino.clicked.connect(self.quitar_destino)
        self.boton_llevar.clicked.connect(lambda: self.copiar_a_otro_disco())
        self.boton_clave.clicked.connect(self.cambiar_clave)
        self.boton_verificar.clicked.connect(lambda: self.verificar_seleccionada())
        self.boton_restaurar.clicked.connect(self.restaurar_seleccionada)
        self.boton_archivo.clicked.connect(lambda: self.restaurar_archivo())
        self.actualizar()

    # --- datos ---------------------------------------------------------------
    def actualizar(self) -> None:
        estado = self._servicios.backups.estado(self._actual)
        self.estado = estado
        if estado.ultima_exitosa:
            texto = f"{fecha_hora_local(estado.ultima_exitosa)} ({_hace(estado)})"
            if estado.alerta_antigua:
                texto += " — tiene más de 2 días"
        else:
            texto = "Ninguna todavía"
        self.valores["ultima"].setText(texto)
        self.valores["diaria"].setText(
            f"Todos los días a las {estado.hora_diaria:02d}:00 si el programa está abierto, "
            "y al cerrarlo (la hora se cambia en Configuración → Parámetros)")
        if not estado.destino:
            destino = "No configurado: las copias quedan solo en este PC"
        elif estado.destino_disponible:
            destino = f"{estado.destino} (conectado)"
        else:
            destino = f"{estado.destino} — NO DISPONIBLE: conecte el disco"
        self.valores["destino"].setText(destino)
        if not estado.clave_configurada:
            clave = "Sin configurar: las copias automáticas no se pueden hacer"
        elif estado.clave_protegida:
            clave = "Configurada y guardada protegida en este PC"
        else:
            clave = "Configurada (equipo de pruebas: sin protección de Windows)"
        self.valores["clave"].setText(clave)
        self.valores["externa"].setText(
            fecha_hora_local(estado.ultima_copia_externa) if estado.ultima_copia_externa
            else "Nunca")
        self.boton_quitar_destino.setEnabled(bool(estado.destino))
        self.boton_clave.setText("Cambiar contraseña…" if estado.clave_configurada
                                 else "Crear contraseña…")

        self._copias = self._servicios.backups.listar(self._actual)
        t = self.tabla_copias
        t.setSortingEnabled(False)
        t.setRowCount(len(self._copias))
        for fila, copia in enumerate(self._copias):
            fecha = fecha_hora_local(copia.creado) if copia.creado else "Ilegible"
            valores = [
                celda(fecha, fila, copia.creado.timestamp() if copia.creado else 0),
                celda(TIPOS.get(copia.tipo, copia.tipo or "—")),
                celda(copia.ubicacion),
                celda(tamano_archivo(copia.tamano), orden=copia.tamano),
                celda(_contenido(copia)),
                celda(str(copia.ruta)),
            ]
            for columna, item in enumerate(valores):
                t.setItem(fila, columna, item)
        t.setSortingEnabled(True)
        if self._copias:
            t.selectRow(0)

        historial = self._servicios.backups.historial(self._actual)
        h = self.tabla_historial
        h.setSortingEnabled(False)
        h.setRowCount(len(historial))
        for fila, registro in enumerate(historial):
            valores = [
                celda(fecha_hora_local(registro.fecha_hora), orden=registro.fecha_hora.timestamp()),
                celda(TIPOS.get(registro.tipo, registro.tipo)),
                celda("Exitosa" if registro.resultado == "exitoso" else "FALLÓ"),
                celda(registro.ruta or "—"),
                celda(registro.detalle),
            ]
            for columna, item in enumerate(valores):
                h.setItem(fila, columna, item)
        h.setSortingEnabled(True)

    def copia_seleccionada(self) -> ArchivoBackup | None:
        fila = self.tabla_copias.currentRow()
        if fila < 0:
            return None
        indice = self.tabla_copias.item(fila, 0).data(Qt.ItemDataRole.UserRole)
        return self._copias[indice] if indice is not None else None

    # --- acciones ------------------------------------------------------------
    def backup_ahora(self) -> ResultadoBackup | None:
        try:
            tarea = self._servicios.backups.preparar(self._actual, TIPO_MANUAL)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        resultado = ejecutar_con_espera(self._servicios.backups, tarea,
                                        "Haciendo copia de seguridad…", self)
        self.actualizar()
        self.estado_cambiado.emit()
        if not resultado.exitoso:
            QMessageBox.warning(self, "La copia falló", resultado.error)
        elif resultado.avisos:
            self.mensaje.setText("Copia hecha en este PC. " + " ".join(resultado.avisos))
            self.mensaje.setObjectName("mensajeError")
        else:
            self.mensaje.setObjectName("mensajeExito")
            self.mensaje.setText(
                "Copia hecha y verificada: " + ", ".join(str(r) for r in resultado.rutas))
        self.mensaje.style().unpolish(self.mensaje)
        self.mensaje.style().polish(self.mensaje)
        return resultado

    def elegir_destino(self, carpeta: str | None = None) -> None:
        if carpeta is None:
            carpeta = QFileDialog.getExistingDirectory(
                self, "Carpeta del disco externo o USB para las copias")
        if not carpeta:
            return
        try:
            self._servicios.backups.cambiar_destino(self._actual, carpeta)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self.actualizar()
        self.estado_cambiado.emit()
        self.mensaje.setText(f"Las próximas copias también se guardarán en {carpeta}.")

    def quitar_destino(self) -> None:
        if not confirmar(self, "Quitar disco externo",
                         "Las copias quedarán solo en este PC. ¿Continuar?"):
            return
        self._servicios.backups.cambiar_destino(self._actual, None)
        self.actualizar()
        self.estado_cambiado.emit()

    def copiar_a_otro_disco(self, carpeta: str | None = None) -> Path | None:
        if carpeta is None:
            carpeta = QFileDialog.getExistingDirectory(
                self, "Disco que se lleva fuera del local")
        if not carpeta:
            return None
        try:
            destino = self._servicios.backups.copiar_a_otro_disco(self._actual, carpeta)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        self.actualizar()
        self.estado_cambiado.emit()
        self.mensaje.setText(f"Copia guardada en {destino}. Lleve ese disco fuera del local.")
        return destino

    def cambiar_clave(self) -> None:
        if DialogoClaveBackups(self._servicios, self._actual, self).exec():
            self.actualizar()
            self.estado_cambiado.emit()
            self.mensaje.setText("Contraseña de copias guardada.")

    def verificar_seleccionada(self, clave: str | None = None) -> bool:
        copia = self.copia_seleccionada()
        if copia is None:
            QMessageBox.information(self, "Verificar", "Seleccione una copia de la lista.")
            return False
        if clave is None:
            from PySide6.QtWidgets import QInputDialog, QLineEdit

            clave, ok = QInputDialog.getText(
                self, "Verificar copia", "Contraseña con la que se hizo la copia:",
                QLineEdit.EchoMode.Password)
            if not ok or not clave:
                return False
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            resumen = self._servicios.backups.verificar(self._actual, copia.ruta, clave)
        except ErrorNegocio as e:
            QApplication.restoreOverrideCursor()
            mostrar_error(self, e)
            return False
        QApplication.restoreOverrideCursor()
        self.mensaje.setText(f"La copia abre bien y está completa: {resumen.texto()}.")
        return True

    def restaurar_seleccionada(self) -> None:
        copia = self.copia_seleccionada()
        if copia is None:
            QMessageBox.information(self, "Restaurar", "Seleccione una copia de la lista.")
            return
        self._restaurar(copia)

    def restaurar_archivo(self, ruta: str | None = None) -> None:
        if ruta is None:
            ruta, _ = QFileDialog.getOpenFileName(
                self, "Elegir copia de seguridad", "", "Copias de Enforma (*.enfbak)")
        if not ruta:
            return
        from gimnasio.servicios.backups import listar_carpeta

        coincidencias = [c for c in listar_carpeta(Path(ruta).parent, "Archivo")
                         if c.ruta == Path(ruta)]
        if not coincidencias or not coincidencias[0].legible:
            mostrar_error(self, ErrorNegocio("El archivo no es una copia de Enforma válida."))
            return
        self._restaurar(coincidencias[0])

    def _restaurar(self, copia: ArchivoBackup) -> None:
        dialogo = DialogoRestaurar(self._servicios, self._actual, copia, self)
        if dialogo.exec():
            QMessageBox.information(
                self, "Copia restaurada",
                f"Se restauró la copia ({dialogo.resumen.texto()}). "
                "La sesión se cerrará; vuelva a iniciar sesión.")
            self.restaurado.emit()
