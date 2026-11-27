"""Copias de seguridad: ida y vuelta, cifrado, destinos, rotación, alertas, permisos y
restauración (sección 8 y criterio 8 de la sección 12)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from gimnasio.backup import cifrado, paquete, rotacion
from gimnasio.backup.protector import AlmacenClave
from gimnasio.modelos import Auditoria, BackupLog, Cliente
from gimnasio.servicios.backups import (
    CARPETA_SEGURIDAD, TIPO_AUTOMATICO, TIPO_MANUAL, ErrorBackupNegocio, abrir_y_revisar,
)
from gimnasio.servicios.errores import ErrorPermiso, ErrorValidacion
from tests.conftest import nuevo_cliente

CLAVE = "copias-Enforma-2026"


@pytest.fixture
def con_datos(servicios, admin, sesion, tmp_path):
    """Admin con contraseña de backups, 3 clientes y una foto."""
    for n in (1, 2, 3):
        nuevo_cliente(sesion, n, nombres="Valentina", apellidos=f"Rodríguez {n}",
                      foto_ruta=f"{n:06d}.png" if n == 1 else None)
    sesion.commit()
    fotos = tmp_path / "fotos"
    fotos.mkdir(exist_ok=True)
    (fotos / "000001.png").write_bytes(b"\x89PNG foto de prueba")
    servicios.backups.configurar_clave(admin, CLAVE, CLAVE)
    return servicios


def _contar(motor, tabla: str) -> int:
    with motor.connect() as c:
        return c.execute(text(f"SELECT COUNT(*) FROM {tabla}")).scalar_one()


# --- ida y vuelta ---------------------------------------------------------------

def test_ida_y_vuelta_crear_cifrar_restaurar_comparar(con_datos, admin, motor, tmp_path):
    resultado = con_datos.backups.hacer_backup(admin, TIPO_MANUAL)
    assert resultado.exitoso and not resultado.avisos
    [ruta] = resultado.rutas
    assert ruta.parent == tmp_path / "backups" and ruta.suffix == ".enfbak"

    crudo = ruta.read_bytes()
    assert crudo.startswith(cifrado.MAGICO)
    assert b"Valentina" not in crudo and b"SQLite format" not in crudo  # va cifrado
    encabezado = cifrado.leer_encabezado(ruta)
    assert encabezado.get("tipo") == "manual" and encabezado.get("revision") == "0011"

    destino = tmp_path / "verificacion"
    destino.mkdir()
    resumen = abrir_y_revisar(ruta, CLAVE, destino)
    assert resumen.integra  # criterio 8: la base restaurada pasa integrity_check
    assert resumen.conteos["clientes"] == _contar(motor, "clientes") == 3
    assert resumen.conteos["usuarios"] == 1 and resumen.fotos == 1
    assert (destino / "fotos" / "000001.png").read_bytes() == b"\x89PNG foto de prueba"
    with sqlite3.connect(destino / "enforma.db") as c:
        nombres = {f[0] for f in c.execute("SELECT nombres FROM clientes")}
    assert nombres == {"Valentina"}


def test_registra_log_y_auditoria(con_datos, admin, sesion):
    con_datos.backups.hacer_backup(admin, TIPO_MANUAL)
    [fila] = sesion.scalars(select(BackupLog)).all()
    assert fila.resultado == "exitoso" and fila.tipo == "manual" and fila.tamano_bytes > 0
    assert "3 clientes" in fila.detalle
    acciones = set(sesion.scalars(select(Auditoria.accion)))
    assert {"backup_clave_configurada", "backup_creado"} <= acciones
    detalle = sesion.scalars(select(Auditoria.detalle_json)
                             .where(Auditoria.accion == "backup_creado")).one()
    assert CLAVE not in detalle


def test_clave_incorrecta_y_archivo_alterado(con_datos, admin, tmp_path):
    [ruta] = con_datos.backups.hacer_backup(admin).rutas
    with pytest.raises(ErrorBackupNegocio, match="contraseña no es correcta"):
        con_datos.backups.verificar(admin, ruta, "otra-clave-123")
    datos = bytearray(ruta.read_bytes())
    datos[-10] ^= 0xFF
    alterado = tmp_path / "alterado.enfbak"
    alterado.write_bytes(bytes(datos))
    with pytest.raises(ErrorBackupNegocio, match="modificado o está dañado"):
        con_datos.backups.verificar(admin, alterado, CLAVE)
    otro = tmp_path / "otro.enfbak"
    otro.write_bytes(b"no es un backup")
    with pytest.raises(ErrorBackupNegocio, match="no es una copia"):
        con_datos.backups.verificar(admin, otro, CLAVE)
    assert con_datos.backups.verificar(admin, ruta, CLAVE).integra


def test_encabezado_alterado_se_detecta(con_datos, admin, tmp_path):
    [ruta] = con_datos.backups.hacer_backup(admin).rutas
    datos = ruta.read_bytes().replace(b'"tipo": "manual"', b'"tipo": "automa"')
    alterado = tmp_path / "encabezado.enfbak"
    alterado.write_bytes(datos)
    with pytest.raises(cifrado.ClaveIncorrecta):
        cifrado.descifrar(alterado.read_bytes(), CLAVE)


# --- destinos -------------------------------------------------------------------

def test_copia_en_pc_y_disco_externo(con_datos, admin, tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    con_datos.backups.cambiar_destino(admin, usb)
    resultado = con_datos.backups.hacer_backup(admin)
    assert len(resultado.rutas) == 2 and not resultado.avisos
    assert resultado.rutas[0].read_bytes() == resultado.rutas[1].read_bytes()
    assert resultado.rutas[1].parent == usb


def test_destino_no_disponible_avisa_y_deja_copia_en_pc(con_datos, admin, tmp_path, sesion):
    usb = tmp_path / "usb"
    usb.mkdir()
    con_datos.backups.cambiar_destino(admin, usb)
    usb.rmdir()  # se desconectó el disco
    estado = con_datos.backups.estado(admin)
    assert estado.destino_disponible is False
    resultado = con_datos.backups.hacer_backup(admin)
    assert resultado.exitoso and len(resultado.rutas) == 1
    assert "¿El disco está conectado?" in resultado.avisos[0]
    resultados = sorted(f.resultado for f in sesion.scalars(select(BackupLog)))
    assert resultados == ["exitoso", "fallido"]


def test_no_acepta_destino_inexistente(con_datos, admin, tmp_path):
    with pytest.raises(ErrorValidacion, match="No se encuentra"):
        con_datos.backups.cambiar_destino(admin, tmp_path / "no-existe")
    with pytest.raises(ErrorValidacion, match="no la carpeta del PC"):
        (tmp_path / "backups").mkdir()
        con_datos.backups.cambiar_destino(admin, tmp_path / "backups")
    con_datos.backups.cambiar_destino(admin, None)
    assert con_datos.backups.destino_externo() is None


# --- contraseña -----------------------------------------------------------------

def test_sin_clave_manual_avisa_y_automatica_queda_registrada(servicios, admin, sesion):
    with pytest.raises(ErrorBackupNegocio, match="Falta configurar la contraseña"):
        servicios.backups.hacer_backup(admin, TIPO_MANUAL)
    resultado = servicios.backups.hacer_backup(None, TIPO_AUTOMATICO)
    assert not resultado.exitoso and "contraseña" in resultado.error
    [fila] = sesion.scalars(select(BackupLog)).all()
    assert fila.resultado == "fallido" and fila.tipo == "automatico"


def test_clave_minimo_y_confirmacion(servicios, admin):
    with pytest.raises(ErrorValidacion, match="al menos"):
        servicios.backups.configurar_clave(admin, "corta", "corta")
    with pytest.raises(ErrorValidacion, match="no coinciden"):
        servicios.backups.configurar_clave(admin, CLAVE, CLAVE + "x")
    servicios.backups.configurar_clave(admin, CLAVE, CLAVE)
    assert servicios.backups.clave_configurada() and servicios.backups.clave_coincide(admin, CLAVE)


def test_clave_guardada_pasa_por_el_protector(tmp_path):
    class ProtectorFalso:
        protege_de_verdad = True

        def proteger(self, datos):
            return bytes(b ^ 0x5A for b in datos)

        def desproteger(self, datos):
            return bytes(b ^ 0x5A for b in datos)

    almacen = AlmacenClave(tmp_path, ProtectorFalso())
    almacen.guardar(CLAVE)
    assert CLAVE.encode() not in almacen.ruta.read_bytes()
    assert almacen.leer() == CLAVE


def test_cambiar_clave_no_afecta_copias_viejas(con_datos, admin):
    [vieja] = con_datos.backups.hacer_backup(admin).rutas
    con_datos.backups.configurar_clave(admin, "nueva-clave-99", "nueva-clave-99")
    assert con_datos.backups.verificar(admin, vieja, CLAVE).integra
    with pytest.raises(ErrorBackupNegocio):
        con_datos.backups.verificar(admin, vieja, "nueva-clave-99")


# --- permisos -------------------------------------------------------------------

def test_permisos_de_recepcion(con_datos, recepcion, admin, tmp_path):
    for accion in (
        lambda: con_datos.backups.hacer_backup(recepcion, TIPO_MANUAL),
        lambda: con_datos.backups.listar(recepcion),
        lambda: con_datos.backups.historial(recepcion),
        lambda: con_datos.backups.configurar_clave(recepcion, CLAVE, CLAVE),
        lambda: con_datos.backups.cambiar_destino(recepcion, tmp_path),
        lambda: con_datos.backups.copiar_a_otro_disco(recepcion, tmp_path),
        lambda: con_datos.backups.verificar(recepcion, tmp_path / "x.enfbak", CLAVE),
        lambda: con_datos.backups.restaurar(recepcion, tmp_path / "x.enfbak", CLAVE),
    ):
        with pytest.raises(ErrorPermiso):
            accion()
    # La copia automática al cerrar se hace aunque cierre Recepción.
    assert con_datos.backups.hacer_backup(recepcion, TIPO_AUTOMATICO).exitoso
    # Y cualquiera con sesión ve el estado (aviso al iniciar).
    assert con_datos.backups.estado(recepcion).alerta_antigua is False
    with pytest.raises(ErrorPermiso):
        con_datos.backups.estado(None)


# --- alertas y copia diaria -------------------------------------------------------

def test_alerta_si_la_ultima_copia_buena_tiene_mas_de_2_dias(con_datos, admin, reloj):
    assert con_datos.backups.estado(admin).alerta_antigua  # nunca se ha hecho
    con_datos.backups.hacer_backup(admin)
    estado = con_datos.backups.estado(admin)
    assert not estado.alerta_antigua and estado.dias_sin_copia == 0
    reloj.avanzar(days=2)
    assert not con_datos.backups.estado(admin).alerta_antigua
    reloj.avanzar(hours=1)
    estado = con_datos.backups.estado(admin)
    assert estado.alerta_antigua and estado.dias_sin_copia == 2


def test_las_copias_fallidas_no_cuentan_para_la_alerta(servicios, admin):
    servicios.backups.hacer_backup(admin, TIPO_AUTOMATICO)  # falla: sin contraseña
    assert servicios.backups.estado(admin).alerta_antigua


def test_toca_copia_diaria(con_datos, admin, reloj):
    # El reloj está a las 10:00 de Bogotá (15:00 UTC); la hora por defecto es 21.
    assert con_datos.configuracion.obtener("backup_hora") == 21
    assert not con_datos.backups.toca_copia_diaria()
    reloj.avanzar(hours=11, minutes=30)  # 21:30 de Bogotá
    assert con_datos.backups.toca_copia_diaria()
    con_datos.backups.hacer_backup(None, TIPO_AUTOMATICO)
    assert not con_datos.backups.toca_copia_diaria()
    reloj.avanzar(hours=3)  # 00:30 del día siguiente: aún no es la hora
    assert not con_datos.backups.toca_copia_diaria()


def test_copia_diaria_fallida_reintenta_cada_hora(servicios, admin, reloj):
    reloj.avanzar(hours=11, minutes=30)
    assert servicios.backups.toca_copia_diaria()
    servicios.backups.hacer_backup(None, TIPO_AUTOMATICO)  # falla: sin contraseña
    assert not servicios.backups.toca_copia_diaria()
    reloj.avanzar(minutes=61)
    assert servicios.backups.toca_copia_diaria()


def test_copia_manual_antes_de_la_hora_no_evita_la_diaria(con_datos, admin, reloj):
    con_datos.backups.hacer_backup(admin)  # 10:00 de Bogotá
    reloj.avanzar(hours=11, minutes=30)
    assert con_datos.backups.toca_copia_diaria()


# --- rotación -------------------------------------------------------------------

def _fechas(dias: int, por_dia: int = 1) -> list[datetime]:
    inicio = datetime(2026, 11, 26, 2, 0, tzinfo=timezone.utc)  # 21:00 de Bogotá del 25
    return [inicio - timedelta(days=d, minutes=10 * k) for d in range(dias)
            for k in range(por_dia)]


def test_rotacion_7_diarias_4_semanales_12_mensuales():
    fechas = _fechas(400, por_dia=2)
    conservar = rotacion.a_conservar(fechas, lambda f: f)
    elegidas = sorted((fechas[i] for i in conservar), reverse=True)
    locales = [f.astimezone(rotacion.ZONA_HORARIA) for f in elegidas]
    # Las 7 diarias: la última copia de cada uno de los 7 días más recientes.
    assert elegidas[:7] == [fechas[2 * d] for d in range(7)]
    assert len({f.date() for f in locales}) == len(locales)  # nunca 2 del mismo día
    semanas = {tuple(f.isocalendar())[:2] for f in locales}
    meses = {(f.year, f.month) for f in locales}
    assert len(meses) == 12
    assert len(semanas) >= 4
    assert len(elegidas) <= 7 + 4 + 12
    assert min(locales).date() > (datetime(2026, 11, 26) - timedelta(days=366)).date()


def test_rotacion_cuenta_dias_con_copia_no_dias_del_calendario():
    # Copias solo cada 10 días: se conservan igual las 7 más recientes.
    fechas = [datetime(2026, 11, 1, 2, tzinfo=timezone.utc) - timedelta(days=10 * i)
              for i in range(10)]
    conservar = rotacion.a_conservar(fechas, lambda f: f)
    assert set(range(7)) <= conservar


def test_rotacion_borra_archivos_viejos(con_datos, admin, reloj):
    for _ in range(20):  # una diaria del 26/11 al 15/12
        con_datos.backups.hacer_backup(None, TIPO_AUTOMATICO)
        reloj.avanzar(days=1)
    copias = con_datos.backups.listar(admin)
    dias = sorted(c.creado.astimezone(rotacion.ZONA_HORARIA).day for c in copias)
    # 7 diarias (9 a 15 de diciembre), semanales (6/12, última de la semana del 30/11,
    # y 29/11, última de la semana anterior) y la mensual de noviembre (30/11).
    assert dias == [6, 9, 10, 11, 12, 13, 14, 15, 29, 30]
    # Varias copias el mismo día: queda solo la última de ese día.
    for _ in range(3):
        con_datos.backups.hacer_backup(admin)
        reloj.avanzar(minutes=5)
    del_dia = [c for c in con_datos.backups.listar(admin)
               if c.creado.astimezone(rotacion.ZONA_HORARIA).date()
               == reloj.ahora.astimezone(rotacion.ZONA_HORARIA).date()]
    assert len(del_dia) == 1


# --- tercera copia ---------------------------------------------------------------

def test_copiar_a_otro_disco_y_recordatorio_semanal(con_datos, admin, reloj, tmp_path):
    assert con_datos.backups.estado(admin).recordatorio_externo
    with pytest.raises(ErrorValidacion, match="no hay copias"):
        con_datos.backups.copiar_a_otro_disco(admin, tmp_path)
    [ruta] = con_datos.backups.hacer_backup(admin).rutas
    disco = tmp_path / "disco_casa"
    disco.mkdir()
    copia = con_datos.backups.copiar_a_otro_disco(admin, disco)
    assert copia.read_bytes() == ruta.read_bytes()
    assert not con_datos.backups.estado(admin).recordatorio_externo
    reloj.avanzar(days=8)
    assert con_datos.backups.estado(admin).recordatorio_externo


# --- restaurar ------------------------------------------------------------------

def test_restaurar_vuelve_al_estado_de_la_copia(con_datos, admin, motor, sesion, tmp_path,
                                                 reloj):
    [ruta] = con_datos.backups.hacer_backup(admin).rutas
    reloj.avanzar(hours=1)
    nuevo_cliente(sesion, 4)
    sesion.commit()
    (tmp_path / "fotos" / "000001.png").unlink()
    (tmp_path / "fotos" / "000004.png").write_bytes(b"otra")
    assert _contar(motor, "clientes") == 4

    resumen = con_datos.backups.restaurar(admin, ruta, CLAVE)
    assert resumen.conteos["clientes"] == 3
    assert _contar(motor, "clientes") == 3
    assert sorted(p.name for p in (tmp_path / "fotos").iterdir()) == ["000001.png"]
    with motor.connect() as c:
        assert c.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0011"

    # Hubo copia "antes de restaurar" con el estado previo (4 clientes).
    [previa] = list((tmp_path / "backups" / CARPETA_SEGURIDAD).glob("*.enfbak"))
    revision = tmp_path / "revision_previa"
    revision.mkdir()
    assert abrir_y_revisar(previa, CLAVE, revision).conteos["clientes"] == 4

    # El historial de copias no se pierde y la restauración queda en la auditoría.
    sesion.expire_all()
    tipos = sorted(f.tipo for f in sesion.scalars(select(BackupLog)))
    assert tipos == ["manual", "seguridad"]
    acciones = list(sesion.scalars(select(Auditoria.accion)))
    assert "backup_restaurado" in acciones
    assert con_datos.backups.estado(admin).ultima_exitosa is not None


def test_restaurar_con_clave_incorrecta_no_toca_nada(con_datos, admin, motor, sesion):
    [ruta] = con_datos.backups.hacer_backup(admin).rutas
    nuevo_cliente(sesion, 4)
    sesion.commit()
    with pytest.raises(ErrorBackupNegocio, match="contraseña no es correcta"):
        con_datos.backups.restaurar(admin, ruta, "clave-equivocada")
    assert _contar(motor, "clientes") == 4
    assert not (con_datos.backups.carpeta_seguridad()).exists()


def test_restaurar_copia_de_version_mas_nueva_se_rechaza(con_datos, admin, motor):
    ruta_base = Path(motor.url.database)
    motor.dispose()
    with sqlite3.connect(ruta_base) as c:
        c.execute("UPDATE alembic_version SET version_num = '9999'")
    [ruta] = con_datos.backups.hacer_backup(admin).rutas
    with sqlite3.connect(ruta_base) as c:
        c.execute("UPDATE alembic_version SET version_num = '0008'")
    with pytest.raises(ErrorBackupNegocio, match="versión más nueva"):
        con_datos.backups.restaurar(admin, ruta, CLAVE)


def test_restaurar_copia_vieja_actualiza_el_esquema(con_datos, admin, motor, tmp_path):
    """Una copia hecha con la versión anterior (0006) se restaura y queda en la última (0010)."""
    vieja = tmp_path / "vieja"
    vieja.mkdir()
    base_vieja = vieja / "enforma.db"
    paquete.copiar_base(Path(motor.url.database), base_vieja)
    with sqlite3.connect(base_vieja) as c:
        c.execute("DROP INDEX ix_backups_log_fecha_hora")
        c.execute("DROP INDEX ix_pagos_consecutivo_concepto")  # como antes de la 0008
        c.execute("CREATE UNIQUE INDEX ix_pagos_consecutivo ON pagos (consecutivo)")
        c.execute("ALTER TABLE invitados DROP COLUMN visitas_anteriores")  # antes de la 0009
        c.execute("UPDATE alembic_version SET version_num = '0006'")
    contenido, resumen = paquete.crear_paquete(base_vieja, vieja)
    archivo = vieja / "vieja.enfbak"
    archivo.write_bytes(cifrado.cifrar(contenido, CLAVE, {
        "creado_utc": "2026-11-01T00:00:00+00:00", "tipo": "manual",
        "revision": resumen.revision}))
    con_datos.backups.restaurar(admin, archivo, CLAVE)
    with motor.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0011"


def test_restaurar_rechaza_usuario_desactivado(con_datos, admin, servicios):
    [ruta] = con_datos.backups.hacer_backup(admin).rutas
    otro = servicios.usuarios.crear(admin, "Otro Admin", "otro", "admin", "ClaveSegura1")
    from gimnasio.servicios.permisos import UsuarioActual

    actual = UsuarioActual(id=otro.id, usuario="otro", nombre_completo="Otro", rol="admin")
    servicios.usuarios.desactivar(admin, otro.id)
    with pytest.raises(ErrorPermiso):
        con_datos.backups.restaurar(actual, ruta, CLAVE)


# --- esquema --------------------------------------------------------------------

def test_backups_log_valida_tipo_y_resultado(sesion):
    sesion.add(BackupLog(tipo="seguridad", ruta="x", resultado="exitoso"))
    sesion.commit()
    sesion.add(BackupLog(tipo="manual", ruta="x", resultado="quizas"))
    with pytest.raises(IntegrityError):
        sesion.commit()
    sesion.rollback()
    sesion.add(BackupLog(tipo="otro", ruta="x", resultado="exitoso"))
    with pytest.raises(IntegrityError):
        sesion.commit()


def test_el_seed_de_clientes_no_esta_en_el_log(con_datos, admin, sesion):
    con_datos.backups.hacer_backup(admin)
    detalles = " ".join(f.detalle or "" for f in sesion.scalars(select(BackupLog)))
    assert "Valentina" not in detalles and "Rodríguez" not in detalles
    assert not sesion.scalars(select(Cliente).where(Cliente.nombres == "x")).first()


# --- scripts/verificar_backup.py ------------------------------------------------

def test_script_verificar_backup(con_datos, admin, tmp_path, capsys, reloj):
    from scripts import verificar_backup

    assert verificar_backup.main(["--datos", str(tmp_path)]) == 1  # aún no hay copias
    con_datos.backups.hacer_backup(admin)
    reloj.avanzar(hours=2)
    [ultima] = con_datos.backups.hacer_backup(admin).rutas
    capsys.readouterr()
    assert verificar_backup.main(["--datos", str(tmp_path)]) == 0
    salida = capsys.readouterr().out
    assert str(ultima) in salida and "Integridad: ok" in salida and "3 clientes" in salida

    datos = bytearray(ultima.read_bytes())
    datos[-5] ^= 0x01
    ultima.write_bytes(bytes(datos))
    assert verificar_backup.main(["--archivo", str(ultima), "--datos", str(tmp_path)]) == 1
    assert "ERROR" in capsys.readouterr().out
