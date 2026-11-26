"""Pantalla de Recepción (sección 3.4): se usa solo con teclado.

El campo de código está siempre enfocado. Un lector USB escribe el código y presiona
Enter. La tarjeta grande se pone verde, amarilla o roja (con sonido) y siempre lleva
texto e ícono, no solo color.

Atajos: Enter registra · Enter vacío confirma un segundo ingreso del día · Esc cancela ·
F2 Renovar ahora · F3 Ingreso autorizado · F4 Ver ficha · F6 Buscar por documento o
nombre · F11 Pantalla completa · Ctrl + / Ctrl − / Ctrl 0 tamaño de letra.
"""

from __future__ import annotations

import dataclasses
import sys
from collections.abc import Callable

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha, fecha_hora_local
from gimnasio.rutas import recurso
from gimnasio.servicios.asistencia import (
    AMARILLO, DUPLICADO_BLOQUEADO, DUPLICADO_CONFIRMAR, RECHAZADO, RESULTADOS, ROJO, VERDE,
    ResultadoIngreso, TarjetaIngreso,
)
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio
from gimnasio.servicios.permisos import Permiso, UsuarioActual
from gimnasio.ui.comunes import boton, celda, etiqueta, mostrar_error, tabla
from gimnasio.ui.dialogos import _DialogoBase, campo_clave

RUTA_SONIDO = recurso("alerta.wav")
NEUTRO = "neutro"
COLORES = {  # fondo, borde y texto de la tarjeta
    VERDE: ("#e7f5ea", "#1e7b34", "#14532d"),
    AMARILLO: ("#fff6db", "#b58105", "#6b4a00"),
    ROJO: ("#fde8e6", "#b42318", "#7a1a12"),
    NEUTRO: ("#ffffff", "#cfd6de", "#1d2733"),
}
ICONOS = {VERDE: "✔", AMARILLO: "⚠", ROJO: "✖", NEUTRO: "?"}
ICONOS_NIVEL = {"critica": "⛔", "advertencia": "⚠", "info": "ℹ"}
ESCALA_MIN, ESCALA_MAX, PASO_ESCALA = 0.8, 1.6, 0.1
CLAVE_ESCALA = "recepcion/escala"


def reproducir_alerta() -> None:
    """Sonido de alerta sin bloquear la pantalla. En Windows usa el archivo WAV."""
    if sys.platform == "win32" and RUTA_SONIDO.exists():
        try:
            import winsound

            winsound.PlaySound(
                str(RUTA_SONIDO),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
            return
        except (ImportError, RuntimeError):
            pass
    QApplication.beep()


class DialogoAutorizacion(_DialogoBase):
    """Usuario y contraseña de un administrador para dejar entrar a un cliente rechazado."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual, asistencia_id: int,
                 nombre_cliente: str, padre: QWidget | None = None):
        super().__init__("Ingreso autorizado",
                         f"{nombre_cliente}: requiere la contraseña de un administrador. "
                         "Queda registrado en la auditoría.", padre)
        self._servicios, self._actual, self._asistencia_id = servicios, actual, asistencia_id
        self.resultado: ResultadoIngreso | None = None
        self.campo_usuario = QLineEdit()
        self.campo_usuario.setPlaceholderText("usuario del administrador")
        if actual.es_admin:
            self.campo_usuario.setText(actual.usuario)
        self.campo_clave = campo_clave("contraseña")
        self.campo_motivo = QLineEdit()
        self.campo_motivo.setMaxLength(200)
        self.campo_motivo.setPlaceholderText("Opcional, p. ej. «paga mañana»")
        self.formulario.addRow("Administrador", self.campo_usuario)
        self.formulario.addRow("Contraseña", self.campo_clave)
        self.formulario.addRow("Motivo", self.campo_motivo)
        cancelar = boton("Cancelar")
        self.boton_autorizar = boton("Autorizar ingreso", principal=True)
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_autorizar)
        cancelar.clicked.connect(self.reject)
        self.boton_autorizar.clicked.connect(self.autorizar)
        # Solo teclado: Enter pasa al siguiente campo y en el motivo autoriza.
        self.campo_usuario.returnPressed.connect(self.campo_clave.setFocus)
        self.campo_clave.returnPressed.connect(self.campo_motivo.setFocus)
        self.campo_motivo.returnPressed.connect(self.autorizar)
        (self.campo_clave if actual.es_admin else self.campo_usuario).setFocus()

    def autorizar(self) -> None:
        try:
            self.resultado = self._servicios.asistencia.autorizar_ingreso(
                self._actual, self._asistencia_id, self.campo_usuario.text(),
                self.campo_clave.text(), self.campo_motivo.text(),
            )
        except ErrorNegocio as e:
            self.campo_clave.clear()
            self.campo_clave.setFocus()
            self.mostrar_error(str(e))
            return
        self.accept()


class TarjetaRecepcion(QFrame):
    """Tarjeta grande con foto, nombre, plan, vencimiento, casillero y alertas."""

    def __init__(self):
        super().__init__()
        self.setObjectName("tarjetaIngreso")
        self.color = NEUTRO
        self.escala = 1.0
        capa = QHBoxLayout(self)
        capa.setContentsMargins(24, 20, 24, 20)
        capa.setSpacing(24)
        self.foto = QLabel()
        self.foto.setFixedSize(180, 220)
        self.foto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        capa.addWidget(self.foto, 0, Qt.AlignmentFlag.AlignTop)
        datos = QVBoxLayout()
        datos.setSpacing(6)
        self.titulo = etiqueta("")
        self.nombre = etiqueta("")
        self.detalle = etiqueta("")
        self.mensaje = etiqueta("")
        self.extra = etiqueta("")
        self.alertas = etiqueta("")
        self.aviso = etiqueta("")
        self.aviso.setObjectName("avisoRecepcion")
        for w in (self.titulo, self.nombre, self.detalle, self.mensaje, self.extra,
                  self.alertas, self.aviso):
            w.setTextFormat(Qt.TextFormat.PlainText)
            datos.addWidget(w)
        datos.addStretch()
        self.botones = QHBoxLayout()
        self.boton_renovar = boton("Renovar ahora (F2)", principal=True)
        self.boton_autorizar = boton("Ingreso autorizado (F3)")
        self.boton_ficha = boton("Ver ficha (F4)")
        for b in (self.boton_renovar, self.boton_autorizar, self.boton_ficha):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # el foco no sale del campo de código
            self.botones.addWidget(b)
        self.botones.addStretch()
        datos.addLayout(self.botones)
        capa.addLayout(datos, 1)
        self.limpiar()

    def limpiar(self, texto: str = "Esperando código…",
                detalle: str = "Digite el código del cliente o páselo por el lector.") -> None:
        self.color = NEUTRO
        self.foto.clear()
        self.foto.setText("")
        self.titulo.setText(texto)
        self.nombre.setText("")
        self.detalle.setText(detalle)
        for w in (self.mensaje, self.extra, self.alertas, self.aviso):
            w.setText("")
            w.hide()
        self.mostrar_botones(False, False, False)
        self.aplicar_estilo()

    def mostrar_botones(self, renovar: bool, autorizar: bool, ficha: bool) -> None:
        self.boton_renovar.setVisible(renovar)
        self.boton_autorizar.setVisible(autorizar)
        self.boton_ficha.setVisible(ficha)

    def mostrar(self, t: TarjetaIngreso, aviso: str = "", color: str | None = None) -> None:
        self.color = color or t.color
        imagen = QPixmap(str(t.foto)) if t.foto else QPixmap()
        if imagen.isNull():
            self.foto.setPixmap(QPixmap())
            self.foto.setText("Sin foto")
        else:
            self.foto.setPixmap(imagen.scaled(
                self.foto.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        self.titulo.setText(f"{ICONOS[self.color]}  {t.titulo}")
        self.nombre.setText(t.nombre_completo)
        partes = [f"Código {t.codigo}"]
        if t.plan:
            partes.append(f"Plan {t.plan}")
        if t.fecha_fin:
            partes.append(f"Vence el {fecha(t.fecha_fin)}")
            if t.dias_restantes is not None and t.dias_restantes >= 0:
                partes.append(f"{t.dias_restantes} días restantes")
        self.detalle.setText("   ·   ".join(partes))
        self.mensaje.setText(t.mensaje)
        self.mensaje.show()
        if t.casillero:
            extra = [("⚠ " if t.casillero_sugerir_liberar else "") + (
                t.casillero_aviso or f"Casillero {t.casillero}")]
        else:
            extra = ["Sin casillero"]
        if t.cumple_hoy:
            extra.append("🎂 ¡Hoy cumple años! Felicítelo.")
        self.extra.setText("   ·   ".join(extra))
        self.extra.show()
        self.alertas.setText("\n".join(
            f"{ICONOS_NIVEL.get(a.nivel, '•')}  {a.mensaje}" for a in t.alertas
        ))
        self.alertas.setVisible(bool(t.alertas))
        self.aviso.setText(aviso)
        self.aviso.setVisible(bool(aviso))
        self.aplicar_estilo()

    def aplicar_estilo(self) -> None:
        fondo, borde, texto = COLORES[self.color]
        e = self.escala
        self.setStyleSheet(
            f"#tarjetaIngreso {{ background: {fondo}; border: 3px solid {borde}; "
            f"border-radius: 10px; }}"
            f"#tarjetaIngreso QLabel {{ background: transparent; color: {texto}; }}"
            f"#avisoRecepcion {{ background: white; border: 2px solid {borde}; "
            f"border-radius: 6px; padding: 8px; font-weight: 600; }}"
        )
        self.foto.setStyleSheet(f"background: white; border: 1px solid {borde}; color: #5b6775;")
        self.titulo.setStyleSheet(f"font-size: {round(26 * e)}pt; font-weight: 700;")
        self.nombre.setStyleSheet(f"font-size: {round(30 * e)}pt; font-weight: 700;")
        self.detalle.setStyleSheet(f"font-size: {round(15 * e)}pt;")
        self.mensaje.setStyleSheet(f"font-size: {round(17 * e)}pt; font-weight: 600;")
        self.extra.setStyleSheet(f"font-size: {round(14 * e)}pt;")
        self.alertas.setStyleSheet(
            f"font-size: {round(14 * e)}pt; font-weight: 600; background: white; "
            f"border-left: 5px solid {borde}; padding: 6px;"
        )
        self.aviso.setStyleSheet(f"font-size: {round(14 * e)}pt;")


class PantallaRecepcion(QWidget):
    abrir_ficha = Signal(int)
    pantalla_completa = Signal()

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios = servicios
        self._actual = actual
        self.ultimo: ResultadoIngreso | None = None
        self.pendiente: int | None = None  # cliente con segundo ingreso por confirmar
        # Reemplazables en las pruebas.
        self.sonar: Callable[[], None] = reproducir_alerta
        self.abrir = None  # visor de recibos (None = el de Windows)
        self._ajustes = QSettings("Enforma", "Gimnasio")

        capa = QVBoxLayout(self)
        capa.setContentsMargins(24, 16, 24, 16)
        capa.setSpacing(12)
        encabezado = QHBoxLayout()
        encabezado.addWidget(etiqueta("Recepción", "tituloPantalla"))
        encabezado.addStretch()
        self.ayuda = etiqueta(
            "Enter registra · F2 Renovar · F3 Autorizar · F4 Ficha · F6 Buscar por nombre "
            "o documento · F11 Pantalla completa · Ctrl + / Ctrl − letra", "textoSuave")
        self.ayuda.setWordWrap(False)
        encabezado.addWidget(self.ayuda)
        capa.addLayout(encabezado)

        self.campo = QLineEdit()
        self.campo.setObjectName("campoCodigo")
        self.campo.setPlaceholderText("Código del cliente")
        self.campo.setMaxLength(64)
        self.campo.returnPressed.connect(self.procesar)
        capa.addWidget(self.campo)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(16)
        self.tarjeta = TarjetaRecepcion()
        cuerpo.addWidget(self.tarjeta, 1)
        lateral = QFrame()
        lateral.setObjectName("tarjeta")
        capa_lateral = QVBoxLayout(lateral)
        capa_lateral.setContentsMargins(14, 12, 14, 12)
        self.contador = etiqueta("")
        self.contador.setObjectName("contadorAsistentes")
        self.subcontador = etiqueta("", "textoSuave")
        capa_lateral.addWidget(self.contador)
        capa_lateral.addWidget(self.subcontador)
        capa_lateral.addWidget(etiqueta("Últimos ingresos de hoy", "textoSuave"))
        self.tabla = tabla(["Hora", "Código", "Cliente", "Resultado", "Casillero"])
        self.tabla.setSortingEnabled(False)
        cabecera = self.tabla.horizontalHeader()
        cabecera.setStretchLastSection(False)
        cabecera.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        capa_lateral.addWidget(self.tabla, 1)
        lateral.setFixedWidth(520)
        cuerpo.addWidget(lateral)
        capa.addLayout(cuerpo, 1)

        self.tarjeta.boton_renovar.clicked.connect(self.renovar)
        self.tarjeta.boton_autorizar.clicked.connect(self.autorizar)
        self.tarjeta.boton_ficha.clicked.connect(self.ver_ficha)
        contexto = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for tecla, accion in (
            ("F2", self.renovar), ("F3", self.autorizar), ("F4", self.ver_ficha),
            ("F6", self.buscar_manual), ("F11", self.pantalla_completa.emit),
            ("Esc", self.cancelar), ("Ctrl++", lambda: self.cambiar_escala(PASO_ESCALA)),
            ("Ctrl+=", lambda: self.cambiar_escala(PASO_ESCALA)),
            ("Ctrl+-", lambda: self.cambiar_escala(-PASO_ESCALA)),
            ("Ctrl+0", lambda: self.cambiar_escala(None)),
        ):
            QShortcut(QKeySequence(tecla), self, activated=accion, context=contexto)

        try:
            escala = float(self._ajustes.value(CLAVE_ESCALA, 1.0))
        except (TypeError, ValueError):
            escala = 1.0
        self._aplicar_escala(escala)
        self.actualizar_lista()

    # --- foco y tamaño de letra ------------------------------------------------
    def enfocar(self) -> None:
        if not self.isVisible():
            return  # al volver a Recepción se enfoca de nuevo
        self.campo.setFocus()
        self.campo.selectAll()

    def showEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        super().showEvent(evento)
        self.actualizar_lista()
        QTimer.singleShot(0, self.enfocar)

    def cambiar_escala(self, paso: float | None) -> None:
        nueva = 1.0 if paso is None else self.escala + paso
        self._aplicar_escala(nueva)
        self._ajustes.setValue(CLAVE_ESCALA, self.escala)

    def _aplicar_escala(self, escala: float) -> None:
        self.escala = round(min(ESCALA_MAX, max(ESCALA_MIN, escala)), 1)
        self.campo.setStyleSheet(
            f"font-size: {round(24 * self.escala)}pt; padding: 8px 12px; "
            "border: 2px solid #1f4e79; border-radius: 6px; background: white;"
        )
        self.contador.setStyleSheet(
            f"font-size: {round(20 * self.escala)}pt; font-weight: 700; color: #1f4e79;"
        )
        self.tarjeta.escala = self.escala
        self.tarjeta.aplicar_estilo()

    # --- registro ---------------------------------------------------------------
    def procesar(self) -> None:
        texto = self.campo.text().strip()
        self.campo.clear()
        self.enfocar()
        if not texto:
            if self.pendiente is not None:
                self.confirmar_duplicado()
            return
        self.pendiente = None
        try:
            resultado = self._servicios.asistencia.registrar_ingreso(self._actual, texto)
        except ErrorNegocio as e:
            self.ultimo = None
            self.tarjeta.limpiar("✖  CÓDIGO NO ENCONTRADO", str(e))
            self.tarjeta.color = ROJO
            self.tarjeta.aplicar_estilo()
            self.sonar()
            return
        self.mostrar(resultado)

    def registrar_cliente(self, cliente_id: int, confirmar: bool = False) -> None:
        try:
            resultado = self._servicios.asistencia.registrar_ingreso_cliente(
                self._actual, cliente_id, confirmar_duplicado=confirmar)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self.mostrar(resultado)

    def confirmar_duplicado(self) -> None:
        cliente_id, self.pendiente = self.pendiente, None
        if cliente_id is not None:
            self.registrar_cliente(cliente_id, confirmar=True)

    def cancelar(self) -> None:
        if self.pendiente is None:
            self.campo.clear()
            return
        self.pendiente = None
        if self.ultimo:
            self.tarjeta.mostrar(self.ultimo.tarjeta, "No se registró un nuevo ingreso.")
            self.tarjeta.mostrar_botones(False, False, True)

    def mostrar(self, r: ResultadoIngreso) -> None:
        self.ultimo = r
        t = r.tarjeta
        previo = fecha_hora_local(r.ingreso_previo)[-5:] if r.ingreso_previo else ""
        aviso, color = "", None
        if r.estado == DUPLICADO_CONFIRMAR:
            self.pendiente = t.cliente_id
            aviso = (f"Ya ingresó hoy a las {previo}. Presione Enter para registrar otro "
                     "ingreso o Esc para cancelar.")
        elif r.estado == DUPLICADO_BLOQUEADO:
            aviso = f"Ya ingresó hoy a las {previo}. No se permite un segundo ingreso."
            color = ROJO
        elif r.ingreso_previo and r.tarjeta.permite_ingreso:
            aviso = f"Segundo ingreso de hoy (el anterior fue a las {previo})."
        self.tarjeta.mostrar(t, aviso, color)
        rechazado = r.estado == RECHAZADO
        self.tarjeta.mostrar_botones(
            renovar=rechazado and t.activo and self._actual.puede(Permiso.REGISTRAR_PAGOS),
            autorizar=rechazado,
            ficha=self._actual.puede(Permiso.VER_CLIENTES),
        )
        if rechazado or r.estado == DUPLICADO_BLOQUEADO:
            self.sonar()
        self.actualizar_lista()
        self.enfocar()

    def actualizar_lista(self) -> None:
        try:
            resumen = self._servicios.asistencia.resumen_del_dia(self._actual)
        except ErrorNegocio:
            return
        self.contador.setText(f"Hoy: {resumen.asistentes} asistentes")
        self.subcontador.setText(
            f"{resumen.ingresos} ingresos · {resumen.rechazados} rechazados"
        )
        self.tabla.setRowCount(len(resumen.ultimos))
        for i, f in enumerate(resumen.ultimos):
            for j, valor in enumerate((
                fecha_hora_local(f.fecha_hora)[-5:], f.codigo, f.nombre,
                RESULTADOS.get(f.resultado, f.resultado), f.casillero or "",
            )):
                item = celda(valor)
                if not f.efectiva:
                    item.setForeground(Qt.GlobalColor.darkRed)
                self.tabla.setItem(i, j, item)

    # --- acciones de la tarjeta ---------------------------------------------------
    def _rechazo_actual(self) -> ResultadoIngreso | None:
        if self.ultimo is None or self.ultimo.estado != RECHAZADO:
            return None
        return self.ultimo

    def renovar(self) -> None:
        r = self._rechazo_actual()
        if r is None or not self.tarjeta.boton_renovar.isVisible():
            return
        from gimnasio.ui.pagos import DialogoMembresia

        try:
            dialogo = DialogoMembresia(self._servicios, self._actual, r.tarjeta.cliente_id,
                                       r.tarjeta.nombre_completo, padre=self)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        if self.abrir is not None:
            dialogo.abrir = self.abrir
        if dialogo.exec():
            try:
                self.mostrar(self._servicios.asistencia.confirmar_tras_renovar(
                    self._actual, r.asistencia_id))
            except ErrorNegocio as e:
                mostrar_error(self, e)
        self.enfocar()

    def autorizar(self) -> None:
        r = self._rechazo_actual()
        if r is None:
            return
        dialogo = DialogoAutorizacion(self._servicios, self._actual, r.asistencia_id,
                                      r.tarjeta.nombre_completo, padre=self)
        if dialogo.exec() and dialogo.resultado:
            self.mostrar(dialogo.resultado)
        self.enfocar()

    def ver_ficha(self) -> None:
        if self.ultimo is None or not self._actual.puede(Permiso.VER_CLIENTES):
            return
        cliente_id = self.ultimo.tarjeta.cliente_id
        self.abrir_ficha.emit(cliente_id)
        self.refrescar_tarjeta()
        self.enfocar()

    def refrescar_tarjeta(self) -> None:
        """Tras cerrar la ficha: muestra los datos al día (alertas, casillero, foto)."""
        if self.ultimo is None:
            return
        try:
            tarjeta = self._servicios.asistencia.tarjeta(self._actual, self.ultimo.tarjeta.cliente_id)
        except ErrorNegocio:
            return
        if self.ultimo.tarjeta.resultado == "autorizado":
            tarjeta = dataclasses.replace(
                tarjeta, resultado="autorizado", titulo=self.ultimo.tarjeta.titulo,
                mensaje=self.ultimo.tarjeta.mensaje)
        self.ultimo = ResultadoIngreso(tarjeta, self.ultimo.estado, self.ultimo.asistencia_id,
                                       self.ultimo.ingreso_previo)
        self.tarjeta.mostrar(tarjeta, self.tarjeta.aviso.text())

    def buscar_manual(self, texto: str | None = None) -> None:
        """Registro manual por documento o nombre (RF-S1)."""
        if texto is None:
            texto, ok = QInputDialog.getText(
                self, "Buscar cliente", "Documento, nombre, apellido o teléfono:")
            if not ok:
                self.enfocar()
                return
        texto = (texto or "").strip()
        if not texto:
            self.enfocar()
            return
        try:
            filas = self._servicios.clientes.buscar_rapido(self._actual, texto)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        if not filas:
            self.tarjeta.limpiar("Sin resultados", f"No se encontró ningún cliente con «{texto}».")
            self.enfocar()
            return
        cliente_id = filas[0].id
        if len(filas) > 1:
            from gimnasio.ui.clientes import DialogoElegirCliente

            dialogo = DialogoElegirCliente(filas, texto, padre=self,
                                           texto_boton="Registrar ingreso")
            if not dialogo.exec():
                self.enfocar()
                return
            cliente_id = dialogo.cliente_id
        self.pendiente = None
        self.registrar_cliente(cliente_id)
        self.enfocar()
