"""Ficha del cliente con pestañas: Datos, Contactos, Membresías, Pagos, Asistencias,
Casillero y Alertas. Desde aquí se modifica, se cambia la foto y (solo el admin)
se activa o inactiva."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QTabWidget, QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha, fecha_hora_local, pesos
from gimnasio.servicios.clientes import (
    ESTADOS, SEXOS, TIPOS_DOCUMENTO, ErrorCasilleroAsignado, FichaCliente,
)
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio
from gimnasio.servicios.permisos import Permiso, UsuarioActual
from gimnasio.ui.clientes import COLOR_VIGENCIA, texto_vigencia
from gimnasio.ui.comunes import boton, celda, etiqueta, mostrar_error, tabla

RESULTADOS = {
    "permitido": "Permitido", "por_vencer": "Por vencer", "vencido": "Vencido",
    "inactivo": "Inactivo", "autorizado": "Autorizado por admin",
}
CONCEPTOS = {"membresia": "Membresía", "casillero": "Casillero", "otro": "Otro"}
METODOS = {"efectivo": "Efectivo", "tarjeta": "Tarjeta", "transferencia": "Transferencia"}
NIVELES = {"info": "Información", "advertencia": "Advertencia", "critica": "Crítica"}
ZONAS = {"hombres": "Hombres", "mujeres": "Mujeres", "mixto": "Mixto"}

# Decisión al inactivar un cliente con casillero.
LIBERAR, CONSERVAR, CANCELAR = "liberar", "conservar", "cancelar"


def _pedir_motivo(padre: QWidget, ficha_nombre: str) -> str | None:
    texto, ok = QInputDialog.getText(
        padre, "Inactivar cliente",
        f"Motivo para inactivar a {ficha_nombre} (queda en la auditoría):",
    )
    return texto if ok else None


def _preguntar_casillero(padre: QWidget, numero: str) -> str:
    caja = QMessageBox(padre)
    caja.setWindowTitle("El cliente tiene casillero")
    caja.setText(f"El cliente tiene asignado el casillero {numero}.\n"
                 "¿Desea liberarlo al inactivarlo?")
    liberar = caja.addButton("Liberar e inactivar", QMessageBox.ButtonRole.AcceptRole)
    conservar = caja.addButton("Inactivar sin liberar", QMessageBox.ButtonRole.DestructiveRole)
    caja.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
    caja.setDefaultButton(liberar)
    caja.exec()
    if caja.clickedButton() is liberar:
        return LIBERAR
    if caja.clickedButton() is conservar:
        return CONSERVAR
    return CANCELAR


def cambiar_estado(
    padre: QWidget, servicios: Servicios, actual: UsuarioActual, cliente_id: int,
    pedir_motivo: Callable[[QWidget, str], str | None] = _pedir_motivo,
    preguntar_casillero: Callable[[QWidget, str], str] = _preguntar_casillero,
) -> bool:
    """Activa o inactiva (pidiendo motivo y qué hacer con el casillero). True si cambió."""
    try:
        ficha = servicios.clientes.obtener_ficha(actual, cliente_id)
        if not ficha.activo:
            servicios.clientes.activar(actual, cliente_id)
            return True
        motivo = pedir_motivo(padre, ficha.nombre_completo)
        if motivo is None:
            return False
        try:
            servicios.clientes.inactivar(actual, cliente_id, motivo)
        except ErrorCasilleroAsignado as e:
            decision = preguntar_casillero(padre, e.numero)
            if decision == CANCELAR:
                return False
            servicios.clientes.inactivar(
                actual, cliente_id, motivo, liberar_casillero=decision == LIBERAR
            )
    except ErrorNegocio as e:
        mostrar_error(padre, e)
        return False
    return True


def _formulario(filas: list[tuple[str, str]]) -> QWidget:
    contenedor = QWidget()
    capa = QFormLayout(contenedor)
    capa.setContentsMargins(16, 16, 16, 16)
    capa.setSpacing(8)
    for nombre, valor in filas:
        texto = QLabel(valor or "—")
        texto.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        texto.setWordWrap(True)
        capa.addRow(f"{nombre}:", texto)
    return contenedor


def _tabla_con(columnas: list[str], filas: list[list], vacio: str) -> QWidget:
    contenedor = QWidget()
    capa = QVBoxLayout(contenedor)
    capa.setContentsMargins(8, 8, 8, 8)
    if not filas:
        capa.addWidget(etiqueta(vacio, "textoSuave"))
        capa.addStretch()
        return contenedor
    t = tabla(columnas)
    t.setSortingEnabled(False)
    t.setRowCount(len(filas))
    for i, fila in enumerate(filas):
        for j, valor in enumerate(fila):
            t.setItem(i, j, valor if not isinstance(valor, str) else celda(valor))
    # Se conserva el orden del servicio (lo más reciente primero) hasta que el
    # usuario haga clic en una columna.
    t.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
    t.setSortingEnabled(True)
    capa.addWidget(t)
    return contenedor


class DialogoFicha(QDialog):
    def __init__(self, servicios: Servicios, actual: UsuarioActual, cliente_id: int,
                 padre: QWidget | None = None):
        super().__init__(padre)
        self._servicios = servicios
        self._actual = actual
        self._cliente_id = cliente_id
        self.cambio = False  # True si se modificó algo (para refrescar la lista)
        self.setMinimumSize(900, 640)
        self._capa = QVBoxLayout(self)
        self._capa.setContentsMargins(24, 20, 24, 20)
        self._contenido: QWidget | None = None
        self.cargar()

    def cargar(self) -> None:
        self.ficha = self._servicios.clientes.obtener_ficha(self._actual, self._cliente_id)
        f = self.ficha
        self.setWindowTitle(f"Cliente {f.codigo} — {f.nombre_completo}")
        if self._contenido is not None:
            self._capa.removeWidget(self._contenido)
            self._contenido.deleteLater()
        self._contenido = QWidget()
        capa = QVBoxLayout(self._contenido)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.addLayout(self._cabecera(f))
        self.pestanas = QTabWidget()
        self._agregar_pestanas(f)
        capa.addWidget(self.pestanas, 1)
        capa.addLayout(self._botones(f))
        self._capa.addWidget(self._contenido)

    # --- construcción ---------------------------------------------------------
    def _cabecera(self, f: FichaCliente) -> QHBoxLayout:
        cabecera = QHBoxLayout()
        self.foto = QLabel()
        self.foto.setFixedSize(110, 135)
        self.foto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.foto.setStyleSheet("background: white; border: 1px solid #cfd6de;")
        imagen = QPixmap(str(f.foto)) if f.foto else QPixmap()
        if imagen.isNull():
            self.foto.setText("Sin foto")
        else:
            self.foto.setPixmap(imagen.scaled(
                self.foto.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        cabecera.addWidget(self.foto)
        datos = QVBoxLayout()
        datos.addWidget(etiqueta(f.nombre_completo, "tituloPantalla"))
        datos.addWidget(etiqueta(f"Código {f.codigo}   ·   {f.tipo_documento} {f.documento}"))
        self.etiqueta_vigencia = etiqueta(self._texto_vigencia(f))
        self.etiqueta_vigencia.setStyleSheet(
            f"color: {COLOR_VIGENCIA[f.vigencia]}; font-weight: 600; font-size: 12pt;"
        )
        datos.addWidget(self.etiqueta_vigencia)
        estado = "Activo" if f.activo else "✖ INACTIVO: no puede ingresar"
        self.etiqueta_estado = etiqueta(f"Estado: {estado}")
        if not f.activo:
            self.etiqueta_estado.setStyleSheet("color: #b42318; font-weight: 600;")
        datos.addWidget(self.etiqueta_estado)
        extra = [f"Casillero: {f.casillero}" if f.casillero else "Sin casillero"]
        if f.cumple_hoy:
            extra.append("🎂 ¡Hoy cumple años!")
        datos.addWidget(etiqueta("   ·   ".join(extra), "textoSuave"))
        datos.addStretch()
        cabecera.addLayout(datos, 1)
        return cabecera

    @staticmethod
    def _texto_vigencia(f: FichaCliente) -> str:
        texto = texto_vigencia(f.vigencia, f.dias_restantes)
        if f.fecha_fin:
            texto += f"   ·   {f.plan_actual}, vence el {fecha(f.fecha_fin)}"
        return texto

    def _agregar_pestanas(self, f: FichaCliente) -> None:
        self.pestanas.addTab(_formulario([
            ("Código", f.codigo),
            ("Documento", f"{TIPOS_DOCUMENTO.get(f.tipo_documento, f.tipo_documento)} {f.documento}"),
            ("Nombres", f.nombres),
            ("Apellidos", f.apellidos),
            ("Sexo", SEXOS.get(f.sexo, f.sexo)),
            ("Fecha de nacimiento", fecha(f.fecha_nacimiento) if f.fecha_nacimiento else ""),
            ("Dirección", f.direccion),
            ("Notas", f.notas),
            ("Estado", ESTADOS.get(f.estado, f.estado)),
            ("Autorización de datos",
             fecha_hora_local(f.autoriza_datos_en) if f.autoriza_datos_en else "No registrada"),
            ("Registrado", f"{fecha_hora_local(f.creado_en)} por {f.creado_por}"),
            ("Última modificación", fecha_hora_local(f.actualizado_en)),
        ]), "Datos")
        self.pestanas.addTab(_formulario([
            ("Teléfono principal", f.telefonos[0] if f.telefonos else ""),
            ("Otros teléfonos", ", ".join(f.telefonos[1:])),
            ("Correo principal", f.correos[0] if f.correos else ""),
            ("Otros correos", ", ".join(f.correos[1:])),
            *[(f"Emergencia {i}", f"{e.nombre} — {e.telefono}")
              for i, e in enumerate(f.emergencias, start=1)],
        ]), "Contactos")
        self.pestanas.addTab(_tabla_con(
            ["Plan", "Inicio", "Fin", "Precio pactado", "Estado", "Motivo de descuento"],
            [[m.plan, celda(fecha(m.fecha_inicio), orden=m.fecha_inicio),
              celda(fecha(m.fecha_fin), orden=m.fecha_fin),
              celda(pesos(m.precio_pactado), orden=m.precio_pactado),
              "Anulada" if m.estado == "anulada" else "Activa", m.motivo_descuento or ""]
             for m in f.membresias],
            "No tiene membresías registradas. El registro de membresías llega en la Fase 3.",
        ), f"Membresías ({len(f.membresias)})")
        self.pestanas.addTab(_tabla_con(
            ["Recibo", "Fecha", "Concepto", "Monto", "Método", "Referencia", "Usuario", "Estado"],
            [[celda(str(p.consecutivo), orden=p.consecutivo),
              celda(fecha_hora_local(p.fecha_hora), orden=p.fecha_hora),
              CONCEPTOS.get(p.concepto, p.concepto), celda(pesos(p.monto), orden=p.monto),
              METODOS.get(p.metodo, p.metodo), p.referencia or "", p.usuario,
              f"Anulado: {p.motivo_anulacion}" if p.anulado else "Válido"]
             for p in f.pagos],
            "No tiene pagos registrados. El registro de pagos llega en la Fase 3.",
        ), f"Pagos ({len(f.pagos)})")
        self.pestanas.addTab(_tabla_con(
            ["Fecha y hora", "Resultado", "Casillero", "Registró"],
            [[celda(fecha_hora_local(a.fecha_hora), orden=a.fecha_hora),
              RESULTADOS.get(a.resultado, a.resultado), a.casillero_numero or "", a.usuario]
             for a in f.asistencias],
            "No tiene asistencias registradas.",
        ), f"Asistencias ({len(f.asistencias)})")
        casillero = QWidget()
        capa = QVBoxLayout(casillero)
        capa.addWidget(etiqueta(
            f"Casillero actual: {f.casillero}" if f.casillero else "No tiene casillero asignado.",
        ))
        capa.addWidget(_tabla_con(
            ["Casillero", "Zona", "Asignado", "Liberado", "Motivo de liberación"],
            [[h.numero, ZONAS.get(h.zona, h.zona),
              celda(fecha_hora_local(h.fecha_asignacion), orden=h.fecha_asignacion),
              fecha_hora_local(h.fecha_liberacion) if h.fecha_liberacion else "En uso",
              h.motivo_liberacion or ""]
             for h in f.historial_casilleros],
            "Sin historial de casilleros.",
        ), 1)
        self.pestanas.addTab(casillero, "Casillero")
        activas = sum(1 for a in f.alertas if a.activa)
        self.pestanas.addTab(_tabla_con(
            ["Mensaje", "Nivel", "Desde", "Hasta", "Estado"],
            [[a.mensaje, NIVELES.get(a.nivel, a.nivel),
              celda(fecha(a.fecha_inicio), orden=a.fecha_inicio),
              fecha(a.fecha_fin) if a.fecha_fin else "", "Activa" if a.activa else "Resuelta"]
             for a in f.alertas],
            "No tiene alertas. Las alertas manuales se crean desde Recepción (Fase 4).",
        ), f"Alertas ({activas})")

    def _botones(self, f: FichaCliente) -> QHBoxLayout:
        fila = QHBoxLayout()
        self.boton_modificar = boton("Modificar datos", principal=True)
        self.boton_foto = boton("Cambiar foto…")
        fila.addWidget(self.boton_modificar)
        fila.addWidget(self.boton_foto)
        self.boton_estado = None
        if self._actual.puede(Permiso.ACTIVAR_CLIENTES):
            self.boton_estado = boton("Inactivar cliente…" if f.activo else "Activar cliente")
            self.boton_estado.clicked.connect(self.cambiar_estado)
            fila.addWidget(self.boton_estado)
        fila.addStretch()
        cerrar = boton("Cerrar")
        cerrar.clicked.connect(self.accept)
        fila.addWidget(cerrar)
        self.boton_modificar.clicked.connect(self.modificar)
        self.boton_foto.clicked.connect(self.cambiar_foto)
        return fila

    # --- acciones -------------------------------------------------------------
    def modificar(self) -> None:
        from gimnasio.ui.cliente_formulario import DialogoCliente

        if DialogoCliente(self._servicios, self._actual, self.ficha, padre=self).exec():
            self.cambio = True
            self.cargar()

    def cambiar_foto(self, ruta: str | None = None) -> None:
        if not ruta:
            ruta, _ = QFileDialog.getOpenFileName(
                self, "Elegir foto del cliente", "", "Imágenes (*.png *.jpg *.jpeg)"
            )
            if not ruta:
                return
        try:
            self._servicios.clientes.cambiar_foto(self._actual, self._cliente_id, ruta)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self.cambio = True
        self.cargar()

    def cambiar_estado(self) -> None:
        if cambiar_estado(self, self._servicios, self._actual, self._cliente_id):
            self.cambio = True
            self.cargar()
