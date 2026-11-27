"""Hoja de estilos de la aplicación: sobria, azul y gris, con buen contraste."""

AZUL = "#1f4e79"
AZUL_OSCURO = "#163a5c"
AZUL_CLARO = "#e8f0f8"
GRIS_FONDO = "#f4f6f8"
GRIS_BORDE = "#cfd6de"
TEXTO = "#1d2733"
TEXTO_SUAVE = "#5b6775"
ROJO = "#b42318"
VERDE = "#1e7b34"

HOJA_ESTILOS = f"""
QWidget {{
    font-family: "Segoe UI", "Noto Sans", Arial, sans-serif;
    font-size: 10.5pt;
    color: {TEXTO};
}}
QMainWindow, QDialog {{ background: {GRIS_FONDO}; }}

#barraSuperior {{ background: {AZUL}; }}
#barraSuperior QLabel {{ color: white; }}
#tituloApp {{ font-size: 14pt; font-weight: 600; }}
#usuarioActual {{ color: #dbe7f3; }}
#busquedaGlobal {{
    background: white; border: 1px solid {AZUL_OSCURO}; border-radius: 4px;
    padding: 6px 10px; min-width: 180px;
}}
#barraSuperior QPushButton {{
    background: transparent; color: white; border: 1px solid #8fb0cf;
    border-radius: 4px; padding: 5px 12px;
}}
#barraSuperior QPushButton:hover {{ background: {AZUL_OSCURO}; }}

#navegacion {{
    background: white; border: none; border-right: 1px solid {GRIS_BORDE};
    outline: 0; padding-top: 8px;
}}
#navegacion::item {{ padding: 11px 18px; border-left: 4px solid transparent; }}
#navegacion::item:hover {{ background: {AZUL_CLARO}; }}
#navegacion::item:selected {{
    background: {AZUL_CLARO}; color: {AZUL}; font-weight: 600;
    border-left: 4px solid {AZUL};
}}

#tituloPantalla {{ font-size: 16pt; font-weight: 600; color: {AZUL}; }}
#textoSuave {{ color: {TEXTO_SUAVE}; }}
#mensajeError {{ color: {ROJO}; font-weight: 600; }}
#mensajeExito {{ color: {VERDE}; font-weight: 600; }}
#tarjeta {{ background: white; border: 1px solid {GRIS_BORDE}; border-radius: 6px; }}
#contadorInvitado {{ font-size: 30pt; font-weight: 700; color: {AZUL}; }}
#contadorTexto {{ font-size: 12pt; font-weight: 600; color: {AZUL}; }}
#avisoLimite {{ color: {ROJO}; font-weight: 600; }}
#avisoBackup {{ background: #fff4d6; border-bottom: 1px solid #e3c46b; }}
#avisoBackup QLabel {{ color: #6b4e00; font-weight: 600; }}
#avisoClave {{ color: {ROJO}; font-weight: 600; }}

QLineEdit, QSpinBox, QComboBox, QDateEdit {{
    background: white; border: 1px solid {GRIS_BORDE}; border-radius: 4px; padding: 5px 7px;
}}
/* Números sin flechas visibles: se escribe o se usan las teclas ↑ ↓. (Con
   setButtonSymbols(NoButtons) Qt no dibuja el texto bajo esta hoja de estilos.) */
QSpinBox::up-button, QSpinBox::down-button {{ width: 0px; border: none; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QDateEdit:focus {{
    border: 1px solid {AZUL};
}}
QPushButton {{
    background: white; border: 1px solid {GRIS_BORDE}; border-radius: 4px; padding: 6px 14px;
}}
QPushButton:hover {{ border-color: {AZUL}; }}
QPushButton:disabled {{ color: #9aa5b1; }}
QPushButton[principal="true"] {{
    background: {AZUL}; color: white; border: 1px solid {AZUL}; font-weight: 600;
}}
QPushButton[principal="true"]:hover {{ background: {AZUL_OSCURO}; }}

QTabWidget::pane {{ border: 1px solid {GRIS_BORDE}; background: white; top: -1px; }}
QTabBar::tab {{
    background: {GRIS_FONDO}; border: 1px solid {GRIS_BORDE}; padding: 7px 16px;
    border-bottom: none; margin-right: 2px;
}}
QTabBar::tab:selected {{ background: white; color: {AZUL}; font-weight: 600; }}

QTableView {{
    background: white; border: 1px solid {GRIS_BORDE}; gridline-color: #e6eaee;
    selection-background-color: {AZUL_CLARO}; selection-color: {TEXTO};
    alternate-background-color: #fafbfc;
}}
QHeaderView::section {{
    background: {GRIS_FONDO}; border: none; border-bottom: 1px solid {GRIS_BORDE};
    padding: 6px; font-weight: 600;
}}
QGroupBox {{
    border: 1px solid {GRIS_BORDE}; border-radius: 6px; margin-top: 14px; padding: 10px;
    background: white; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {AZUL}; }}
QStatusBar {{ background: white; border-top: 1px solid {GRIS_BORDE}; }}

#temasAyuda {{ background: white; border: 1px solid {GRIS_BORDE}; outline: 0; }}
#temasAyuda::item {{ padding: 7px 10px; }}
#temasAyuda::item:selected {{ background: {AZUL_CLARO}; color: {TEXTO}; border-left: 4px solid {AZUL}; }}
#textoAyuda {{ background: white; border: 1px solid {GRIS_BORDE}; }}
"""
