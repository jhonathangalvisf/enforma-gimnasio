"""Pantalla de Recepción (sección 3.4): funciona solo con teclado y también con botones.

El campo de código está siempre enfocado. Un lector USB escribe el código y presiona
Enter. La tarjeta grande se pone verde, amarilla o roja (con sonido) y siempre lleva
texto e ícono, no solo color. La tarjeta ocupa todo el ancho (sin lista lateral de
ingresos: esa lista está en Asistencia).

Cada atajo tiene además un botón grande (la usan personas mayores): ningún botón toma
el foco, así el lector sigue escribiendo en el campo de código.

Atajos: Enter registra · Enter vacío confirma un segundo ingreso del día · Esc cancela ·
F2 Renovar ahora · F3 Ingreso autorizado · F4 Ver ficha · F5 Activar cliente (inactivo) ·
F6 Buscar por documento o nombre · F11 Pantalla completa · Ctrl + / Ctrl − / Ctrl 0
tamaño de letra.
"""

from __future__ import annotations

import dataclasses
import sys
from collections.abc import Callable

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha, fecha_hora_local
from gimnasio.rutas import recurso
from gimnasio.servicios.asistencia import (
    AMARILLO, DUPLICADO_BLOQUEADO, DUPLICADO_CONFIRMAR, RECHAZADO, ROJO, VERDE,
    ResultadoIngreso, TarjetaIngreso,
)
from gimnasio.servicios.autorizaciones import PARA_ACTIVACION
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio
from gimnasio.servicios.permisos import Permiso, UsuarioActual
from gimnasio.ui.autorizacion import pedir_autorizacion
from gimnasio.ui.comunes import boton, etiqueta, mostrar_error
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
        self.foto.setFixedSize(150, 185)
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
            w.setWordWrap(True)  # en pantallas pequeñas el texto baja de renglón
            datos.addWidget(w)
        datos.addStretch()
        # En cuadrícula de dos columnas: así la tarjeta cabe en pantallas angostas.
        self.botones = QGridLayout()
        self.botones.setSpacing(10)
        self.boton_renovar = boton("Renovar ahora (F2)", principal=True)
        self.boton_autorizar = boton("Ingreso autorizado (F3)")
        self.boton_activar = boton("Activar cliente (F5)", principal=True)
        self.boton_ficha = boton("Ver ficha (F4)")
        self._orden_botones = (self.boton_renovar, self.boton_autorizar, self.boton_activar,
                               self.boton_ficha)
        for i, b in enumerate(self._orden_botones):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # el foco no sale del campo de código
            b.setObjectName("botonRecepcion")
            # Se agregan todos desde el inicio para que queden dentro de la tarjeta (un
            # botón sin padre se abriría como ventana aparte al mostrarlo).
            self.botones.addWidget(b, i // 2, i % 2)
        self.botones.setColumnStretch(2, 1)
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

    def mostrar_botones(self, renovar: bool, autorizar: bool, ficha: bool,
                        activar: bool = False) -> None:
        visibles = {self.boton_renovar: renovar, self.boton_autorizar: autorizar,
                    self.boton_activar: activar, self.boton_ficha: ficha}
        # Se acomodan solo los visibles, para que no queden huecos en la cuadrícula.
        for b in self._orden_botones:
            self.botones.removeWidget(b)
        i = 0
        for b in self._orden_botones:
            b.setVisible(visibles[b])
            if visibles[b]:
                self.botones.addWidget(b, i // 2, i % 2)
                i += 1

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
        for b in self._orden_botones:
            b.setStyleSheet(f"font-size: {round(15 * e)}pt; padding: 12px 22px;")


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
        # Botones grandes con lo mismo que hacen las teclas (más fácil que recordarlas).
        self.boton_registrar = self._boton_accion("✔  Registrar (Enter)", principal=True)
        self.boton_buscar = self._boton_accion("🔍  Buscar por nombre o cédula (F6)")
        self.boton_pantalla = self._boton_accion("⛶  Pantalla completa (F11)")
        self.boton_letra_menos = self._boton_accion("A−")
        self.boton_letra_mas = self._boton_accion("A+")
        self.boton_letra_menos.setToolTip("Letra más pequeña (Ctrl −)")
        self.boton_letra_mas.setToolTip("Letra más grande (Ctrl +)")

        encabezado = QHBoxLayout()
        encabezado.setSpacing(10)
        encabezado.addWidget(etiqueta("Recepción", "tituloPantalla"))
        encabezado.addSpacing(12)
        encabezado.addWidget(self.boton_pantalla)
        encabezado.addStretch()
        # Solo el número de asistentes; la lista de ingresos del día está en Asistencia.
        self.contador = etiqueta("")
        self.contador.setObjectName("contadorAsistentes")
        encabezado.addWidget(self.contador)
        capa.addLayout(encabezado)

        self.campo = QLineEdit()
        self.campo.setObjectName("campoCodigo")
        self.campo.setPlaceholderText("Código del cliente")
        self.campo.setMaxLength(64)
        self.campo.returnPressed.connect(self.procesar)
        capa.addWidget(self.campo)

        # Una sola fila bajo el campo, para que la tarjeta quede grande.
        acciones = QHBoxLayout()
        acciones.setSpacing(10)
        acciones.addWidget(self.boton_registrar)
        acciones.addWidget(self.boton_buscar)
        acciones.addStretch()
        acciones.addWidget(QLabel("Letra:"))
        acciones.addWidget(self.boton_letra_menos)
        acciones.addWidget(self.boton_letra_mas)
        capa.addLayout(acciones)
        self.boton_registrar.clicked.connect(self.procesar)
        self.boton_buscar.clicked.connect(lambda: self.buscar_manual())
        self.boton_pantalla.clicked.connect(self.pantalla_completa.emit)
        self.boton_letra_menos.clicked.connect(lambda: self.cambiar_escala(-PASO_ESCALA))
        self.boton_letra_mas.clicked.connect(lambda: self.cambiar_escala(PASO_ESCALA))

        self.tarjeta = TarjetaRecepcion()
        capa.addWidget(self.tarjeta, 1)

        self.tarjeta.boton_renovar.clicked.connect(lambda: self.renovar())
        self.tarjeta.boton_autorizar.clicked.connect(self.autorizar)
        self.tarjeta.boton_activar.clicked.connect(self.activar)
        self.tarjeta.boton_ficha.clicked.connect(self.ver_ficha)
        contexto = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for tecla, accion in (
            ("F2", self.renovar), ("F3", self.autorizar), ("F4", self.ver_ficha),
            ("F5", self.activar),
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

    def _boton_accion(self, texto: str, principal: bool = False) -> QPushButton:
        b = boton(texto, principal)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # el foco no sale del campo de código
        return b

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
        for b in (self.boton_registrar, self.boton_buscar, self.boton_pantalla,
                  self.boton_letra_menos, self.boton_letra_mas):
            b.setStyleSheet(f"font-size: {round(14 * self.escala)}pt; padding: 10px 18px;")
        self.boton_letra_menos.setEnabled(self.escala > ESCALA_MIN)
        self.boton_letra_mas.setEnabled(self.escala < ESCALA_MAX)
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
            self.tarjeta.mostrar_botones(False, False, True,
                                         activar=self._puede_activar(self.ultimo.tarjeta))

    def _puede_activar(self, t: TarjetaIngreso) -> bool:
        """Activar se ofrece cuando el cliente está inactivo. El administrador lo hace
        directo; Recepción, con la clave de un administrador."""
        return (bool(t.cliente_id) and not t.activo
                and (self._actual.puede(Permiso.ACTIVAR_CLIENTES)
                     or self._actual.puede(Permiso.REGISTRAR_PAGOS)))

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
            # Renovar se ofrece para cualquier cliente activo (también para pagar antes
            # de que venza), no solo cuando se le niega el ingreso.
            renovar=bool(t.cliente_id) and t.activo
            and self._actual.puede(Permiso.REGISTRAR_PAGOS),
            autorizar=rechazado,
            ficha=self._actual.puede(Permiso.VER_CLIENTES),
            activar=self._puede_activar(t),
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

    # --- acciones de la tarjeta ---------------------------------------------------
    def _rechazo_actual(self) -> ResultadoIngreso | None:
        if self.ultimo is None or self.ultimo.estado != RECHAZADO:
            return None
        return self.ultimo

    def renovar(self, autorizacion=None) -> None:
        r = self.ultimo
        if r is None or (self.tarjeta.boton_renovar.isHidden() and autorizacion is None):
            self._avisar("Primero digite o pase el código de un cliente activo; luego F2 "
                         "renueva su membresía.")
            return
        from gimnasio.ui.pagos import DialogoMembresia

        try:
            dialogo = DialogoMembresia(self._servicios, self._actual, r.tarjeta.cliente_id,
                                       r.tarjeta.nombre_completo, padre=self,
                                       autorizacion=autorizacion)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        if self.abrir is not None:
            dialogo.abrir = self.abrir
        if dialogo.exec():
            if r.estado == RECHAZADO:
                try:
                    self.mostrar(self._servicios.asistencia.confirmar_tras_renovar(
                        self._actual, r.asistencia_id))
                except ErrorNegocio as e:
                    mostrar_error(self, e)
            else:
                self.refrescar_tarjeta()  # la nueva vigencia queda a la vista
        self.enfocar()

    def _avisar(self, texto: str) -> None:
        self.tarjeta.aviso.setText(texto)
        self.tarjeta.aviso.show()
        self.enfocar()

    def activar(self) -> None:
        """Activa al cliente inactivo de la tarjeta (con la clave de un administrador si
        es Recepción) y abre enseguida el cobro de la mensualidad."""
        r = self.ultimo
        if r is None or self.tarjeta.boton_activar.isHidden():
            return
        ok, autorizacion = pedir_autorizacion(self, self._servicios, self._actual,
                                              PARA_ACTIVACION)
        if not ok:
            self.enfocar()
            return
        try:
            self._servicios.clientes.activar(self._actual, r.tarjeta.cliente_id, autorizacion)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            self.enfocar()
            return
        self.refrescar_tarjeta()
        self.tarjeta.mostrar_botones(
            renovar=self._actual.puede(Permiso.REGISTRAR_PAGOS), autorizar=False,
            ficha=self._actual.puede(Permiso.VER_CLIENTES))
        self._avisar("✔ Cliente activado. Ahora cobre la mensualidad.")
        if self._actual.puede(Permiso.REGISTRAR_PAGOS):
            # La misma clave sirve para este cobro (no se vuelve a pedir).
            self.renovar(autorizacion)
        # Si no se cobró, la clave no queda sirviendo para otra cosa.
        self._servicios.autorizaciones.revocar(autorizacion)

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
