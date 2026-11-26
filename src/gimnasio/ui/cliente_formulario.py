"""Formulario de registro y modificación de clientes.

El código se sugiere con el consecutivo; solo el administrador puede escribir otro
(al inscribir o al corregirlo después). Si la cédula ya existe, no se crea otro
cliente: se ofrece abrir (y, si está inactivo, reactivar) el registro con su código
antiguo. Si quien edita es Recepción, los campos que no son de contacto quedan
bloqueados (el servicio además lo verifica).
"""

from __future__ import annotations

from pathlib import Path

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha, fecha_hora_local, leer_fecha
from gimnasio.servicios.clientes import (
    SEXOS, TIPOS_DOCUMENTO, ContactoEmergencia, DatosCliente, ErrorDocumentoRegistrado,
    FichaCliente,
)
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio
from gimnasio.servicios.permisos import Permiso, UsuarioActual
from gimnasio.servicios.autorizaciones import PARA_INSCRIPCION
from gimnasio.ui.autorizacion import asegurar_autorizacion, olvidar_autorizacion_si_falla
from gimnasio.ui.comunes import boton, etiqueta, mostrar_error
from gimnasio.ui.dialogos import _DialogoBase

CONTACTOS_EMERGENCIA = 2
AVISO_SOLO_ADMIN = "Solo el administrador puede cambiar este dato."


def _preguntar(padre: QWidget, titulo: str, texto: str) -> bool:
    return QMessageBox.question(
        padre, titulo, texto,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    ) == QMessageBox.StandardButton.Yes


def _lista(texto: str) -> list[str]:
    return [p.strip() for p in texto.replace(";", ",").split(",") if p.strip()]


class DialogoCliente(_DialogoBase):
    def __init__(self, servicios: Servicios, actual: UsuarioActual,
                 existente: FichaCliente | None = None, padre: QWidget | None = None,
                 preguntar: Callable[[QWidget, str, str], bool] = _preguntar):
        titulo = f"Modificar cliente {existente.codigo}" if existente else "Nuevo cliente"
        subtitulo = (
            "El código se sugiere con el consecutivo."
            if not existente else f"{existente.nombre_completo}"
        )
        super().__init__(titulo, subtitulo, padre)
        self.setMinimumWidth(620)
        self._servicios = servicios
        self._actual = actual
        self._existente = existente
        # Recepción inscribe con la clave de un administrador; la misma sirve para el
        # primer cobro (ver PantallaClientes.cobrar_inscripcion).
        self._autorizacion = None
        self.ficha: FichaCliente | None = None
        self.ruta_foto: str | None = None
        self._preguntar = preguntar
        self.puede_codigo = actual.puede(Permiso.MODIFICAR_CLIENTE_COMPLETO)

        # El formulario base va dentro de un área desplazable (pantallas pequeñas).
        self._capa.removeItem(self.formulario)
        contenido = QWidget()
        interior = QVBoxLayout(contenido)
        interior.setContentsMargins(0, 0, 8, 0)

        caja_datos = QGroupBox("Datos personales")
        datos = QFormLayout(caja_datos)
        self.campo_codigo = QLineEdit()
        self.campo_codigo.setMaxLength(6)
        self.campo_codigo.setMaximumWidth(110)
        self.ayuda_codigo = etiqueta("", "textoSuave")
        codigo = QHBoxLayout()
        codigo.addWidget(self.campo_codigo)
        codigo.addWidget(self.ayuda_codigo, 1)
        datos.addRow("Código", codigo)
        if existente:
            self.campo_codigo.setText(existente.codigo)
            self.ayuda_codigo.setText(
                "Si lo cambia, el código anterior deja de servir en Recepción."
                if self.puede_codigo else ""
            )
        else:
            try:
                self.codigo_sugerido = servicios.clientes.codigo_sugerido(actual)
            except ErrorNegocio as e:
                self.codigo_sugerido = ""
                self.mostrar_error(str(e))
            self.campo_codigo.setText(self.codigo_sugerido)
            self.ayuda_codigo.setText(
                "Consecutivo sugerido. Puede escribir otro (por ejemplo, el de un cliente "
                "antiguo) sin afectar el consecutivo." if self.puede_codigo
                else "Consecutivo asignado automáticamente."
            )
        if not self.puede_codigo:
            self.campo_codigo.setReadOnly(True)
            self.campo_codigo.setEnabled(False)
            self.campo_codigo.setToolTip("Solo el administrador puede asignar otro código.")
        self.campo_tipo = QComboBox()
        for valor, texto in TIPOS_DOCUMENTO.items():
            self.campo_tipo.addItem(f"{valor} — {texto}", valor)
        self.campo_documento = QLineEdit()
        self.campo_documento.setMaxLength(20)
        documento = QHBoxLayout()
        documento.addWidget(self.campo_tipo)
        documento.addWidget(self.campo_documento, 1)
        datos.addRow("Documento *", documento)
        self.campo_nombres = QLineEdit()
        self.campo_nombres.setMaxLength(80)
        self.campo_apellidos = QLineEdit()
        self.campo_apellidos.setMaxLength(80)
        datos.addRow("Nombres *", self.campo_nombres)
        datos.addRow("Apellidos *", self.campo_apellidos)
        self.campo_sexo = QComboBox()
        self.campo_sexo.addItem("Seleccione…", None)
        for valor, texto in SEXOS.items():
            self.campo_sexo.addItem(texto, valor)
        datos.addRow("Sexo *", self.campo_sexo)
        self.campo_nacimiento = QLineEdit()
        self.campo_nacimiento.setPlaceholderText("dd/mm/aaaa")
        self.campo_nacimiento.setInputMask("")
        self.campo_nacimiento.setMaximumWidth(140)
        datos.addRow("Fecha de nacimiento", self.campo_nacimiento)
        self.campo_notas = QPlainTextEdit()
        self.campo_notas.setFixedHeight(64)
        datos.addRow("Notas", self.campo_notas)
        interior.addWidget(caja_datos)

        caja_contacto = QGroupBox("Contacto")
        contacto = QFormLayout(caja_contacto)
        self.campo_direccion = QLineEdit()
        self.campo_direccion.setMaxLength(200)
        contacto.addRow("Dirección", self.campo_direccion)
        self.campo_telefonos = QLineEdit()
        self.campo_telefonos.setPlaceholderText("3001234567, 6041234567  (el primero es el principal)")
        contacto.addRow("Teléfonos", self.campo_telefonos)
        self.campo_correos = QLineEdit()
        self.campo_correos.setPlaceholderText("correo@ejemplo.com  (separe varios con coma)")
        contacto.addRow("Correos", self.campo_correos)
        self.campos_emergencia: list[tuple[QLineEdit, QLineEdit]] = []
        for i in range(CONTACTOS_EMERGENCIA):
            nombre, telefono = QLineEdit(), QLineEdit()
            nombre.setPlaceholderText("Nombre")
            telefono.setPlaceholderText("Teléfono")
            fila = QHBoxLayout()
            fila.addWidget(nombre, 2)
            fila.addWidget(telefono, 1)
            contacto.addRow(f"Emergencia {i + 1}", fila)
            self.campos_emergencia.append((nombre, telefono))
        interior.addWidget(caja_contacto)

        # Inscripción: al guardar se cobra la mensualidad y, si quiere, el casillero
        # (en el mismo recibo). Más adelante se puede pagar desde Pagos.
        self.campo_casillero: QCheckBox | None = None
        if self._existente is None and actual.puede(Permiso.ASIGNAR_CASILLERO):
            caja_casillero = QGroupBox("Casillero")
            capa_casillero = QVBoxLayout(caja_casillero)
            self.campo_casillero = QCheckBox(
                "¿Desea casillero? Se elige uno libre y se cobra junto con la mensualidad, "
                "en el mismo recibo.")
            capa_casillero.addWidget(self.campo_casillero)
            capa_casillero.addWidget(etiqueta(
                "Si no lo quiere ahora, solo paga la mensualidad. Puede pagar un casillero más "
                "adelante desde Pagos.", "textoSuave"))
            interior.addWidget(caja_casillero)

        caja_otros = QGroupBox("Autorización y foto")
        otros = QFormLayout(caja_otros)
        self.campo_autoriza = QCheckBox(
            "El cliente autoriza el tratamiento de sus datos personales (Ley 1581 de 2012)"
        )
        otros.addRow(self.campo_autoriza)
        self.etiqueta_autoriza = etiqueta("", "textoSuave")
        otros.addRow(self.etiqueta_autoriza)
        foto = QHBoxLayout()
        self.etiqueta_foto = QLabel("Sin foto nueva")
        elegir = boton("Elegir foto…")
        elegir.clicked.connect(self._elegir_foto)
        foto.addWidget(self.etiqueta_foto, 1)
        foto.addWidget(elegir)
        otros.addRow("Foto", foto)
        interior.addWidget(caja_otros)
        interior.addStretch()

        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setWidget(contenido)
        desplazable.setMinimumHeight(520)
        self._capa.insertWidget(self._capa.count() - 2, desplazable, 1)

        self.boton_guardar = boton("Guardar", principal=True)
        cancelar = boton("Cancelar")
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_guardar)
        cancelar.clicked.connect(self.reject)
        self.boton_guardar.clicked.connect(self.guardar)

        if existente:
            self._cargar(existente)
            if not actual.puede(Permiso.MODIFICAR_CLIENTE_COMPLETO):
                self._bloquear_campos_no_contacto()
        self.campo_documento.setFocus()

    def _cargar(self, f: FichaCliente) -> None:
        self.campo_tipo.setCurrentIndex(max(0, self.campo_tipo.findData(f.tipo_documento)))
        self.campo_documento.setText(f.documento)
        self.campo_nombres.setText(f.nombres)
        self.campo_apellidos.setText(f.apellidos)
        self.campo_sexo.setCurrentIndex(max(0, self.campo_sexo.findData(f.sexo)))
        self.campo_nacimiento.setText(fecha(f.fecha_nacimiento) if f.fecha_nacimiento else "")
        self.campo_notas.setPlainText(f.notas)
        self.campo_direccion.setText(f.direccion)
        self.campo_telefonos.setText(", ".join(f.telefonos))
        self.campo_correos.setText(", ".join(f.correos))
        for (nombre, telefono), e in zip(self.campos_emergencia, f.emergencias):
            nombre.setText(e.nombre)
            telefono.setText(e.telefono)
        self.campo_autoriza.setChecked(f.autoriza_datos_en is not None)
        if f.autoriza_datos_en:
            self.etiqueta_autoriza.setText(
                f"Autorizado el {fecha_hora_local(f.autoriza_datos_en)}."
            )

    def _bloquear_campos_no_contacto(self) -> None:
        for campo in (self.campo_tipo, self.campo_documento, self.campo_nombres,
                      self.campo_apellidos, self.campo_sexo, self.campo_nacimiento,
                      self.campo_notas):
            campo.setEnabled(False)
            campo.setToolTip(AVISO_SOLO_ADMIN)
        if self.campo_autoriza.isChecked():
            # Recepción puede registrar la autorización, pero no retirarla.
            self.campo_autoriza.setEnabled(False)
            self.campo_autoriza.setToolTip(AVISO_SOLO_ADMIN)
        self.campo_direccion.setFocus()

    def _elegir_foto(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Elegir foto del cliente", "", "Imágenes (*.png *.jpg *.jpeg)"
        )
        if ruta:
            self.ruta_foto = ruta
            self.etiqueta_foto.setText(Path(ruta).name)

    def datos(self) -> DatosCliente:
        return DatosCliente(
            tipo_documento=self.campo_tipo.currentData(),
            documento=self.campo_documento.text(),
            nombres=self.campo_nombres.text(),
            apellidos=self.campo_apellidos.text(),
            sexo=self.campo_sexo.currentData(),
            fecha_nacimiento=leer_fecha(self.campo_nacimiento.text()),
            direccion=self.campo_direccion.text(),
            notas=self.campo_notas.toPlainText(),
            autoriza_datos=self.campo_autoriza.isChecked(),
            telefonos=_lista(self.campo_telefonos.text()),
            correos=_lista(self.campo_correos.text()),
            emergencias=[
                ContactoEmergencia(n.text(), t.text()) for n, t in self.campos_emergencia
            ],
        )

    def guardar(self) -> None:
        clientes = self._servicios.clientes
        try:
            datos = self.datos()
            codigo = self.campo_codigo.text().strip()
            if self._existente:
                if self.puede_codigo and codigo != self._existente.codigo:
                    clientes.cambiar_codigo(self._actual, self._existente.id, codigo)
                clientes.modificar(self._actual, self._existente.id, datos)
                cliente_id = self._existente.id
            else:
                if not asegurar_autorizacion(self, PARA_INSCRIPCION):
                    return
                cliente_id = clientes.registrar(
                    self._actual, datos, codigo=codigo if self.puede_codigo else None,
                    autorizacion=self._autorizacion,
                ).id
        except ErrorDocumentoRegistrado as e:
            self._documento_registrado(e)
            return
        except (ErrorNegocio, ValueError) as e:
            olvidar_autorizacion_si_falla(self, e)
            self.mostrar_error(str(e))
            return
        if self.ruta_foto:
            # Los datos ya quedaron guardados: si la foto falla solo se avisa.
            try:
                clientes.cambiar_foto(self._actual, cliente_id, self.ruta_foto)
            except (ErrorNegocio, OSError) as e:
                mostrar_error(self, e if isinstance(e, ErrorNegocio) else ErrorNegocio(
                    "Los datos se guardaron, pero no se pudo copiar la foto."))
        self.ficha = clientes.obtener_ficha(self._actual, cliente_id)
        self.accept()

    @property
    def autorizacion(self):
        return self._autorizacion

    @property
    def quiere_casillero(self) -> bool:
        return self.campo_casillero is not None and self.campo_casillero.isChecked()

    def _documento_registrado(self, e: ErrorDocumentoRegistrado) -> None:
        """Un cliente tiene un solo código: se abre (y reactiva) el registro antiguo."""
        clientes = self._servicios.clientes
        if e.activo:
            pregunta = (f"{e.nombre} ya está registrado con el código {e.codigo}.\n"
                        "¿Desea abrir su ficha?")
        elif self._actual.puede(Permiso.ACTIVAR_CLIENTES):
            pregunta = (f"{e.nombre} ya estuvo inscrito con el código {e.codigo} y está "
                        "inactivo.\n¿Desea reactivarlo con su mismo código y abrir su ficha?")
        else:
            pregunta = (f"{e.nombre} ya estuvo inscrito con el código {e.codigo} y está "
                        "inactivo. Pida al administrador que lo reactive.\n"
                        "¿Desea abrir su ficha?")
        if not self._preguntar(self, "Cliente ya registrado", pregunta):
            self.mostrar_error(str(e))
            return
        try:
            if not e.activo and self._actual.puede(Permiso.ACTIVAR_CLIENTES):
                clientes.activar(self._actual, e.cliente_id)
            self.ficha = clientes.obtener_ficha(self._actual, e.cliente_id)
        except ErrorNegocio as error:
            self.mostrar_error(str(error))
            return
        self.accept()
