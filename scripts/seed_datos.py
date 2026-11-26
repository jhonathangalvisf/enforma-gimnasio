"""Genera datos FALSOS de prueba (español de Colombia) para medir rendimiento.

Uso:
    python scripts/seed_datos.py                    # 12.000 clientes en la base configurada
    python scripts/seed_datos.py --clientes 500     # menos clientes
    python scripts/seed_datos.py --db prueba.db     # otra base (se crea si no existe)

Crea la base con las migraciones si hace falta y se niega a escribir en una base
que ya tenga clientes, para no mezclar datos de prueba con datos reales.

Ningún dato es real: los nombres, documentos y teléfonos salen de Faker.
"""

from __future__ import annotations

import argparse
import random
import secrets
import sys
import time
import unicodedata
from datetime import date, datetime, time as hora, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from argon2 import PasswordHasher  # noqa: E402
from faker import Faker  # noqa: E402
from sqlalchemy import Engine, func, insert, select  # noqa: E402

from gimnasio.config import ZONA_HORARIA, url_base_datos  # noqa: E402
from gimnasio.db.engine import crear_motor  # noqa: E402
from gimnasio.db.migraciones import actualizar_esquema  # noqa: E402
from gimnasio.modelos import (  # noqa: E402
    Alerta,
    Asistencia,
    Casillero,
    CasilleroAsignacion,
    Cliente,
    Config,
    Contacto,
    Invitado,
    InvitadoAsistencia,
    Membresia,
    Pago,
    Plan,
    Usuario,
)

CLAVE_DEMO = "Enforma2026!"  # solo para la base de prueba
DIAS_POR_VENCER = 5
DIAS_ASISTENCIA = 90  # historial de asistencias generado
LOTE = 5000

PLANES = [
    ("Mensual", 30, 120_000),
    ("Quincenal", 15, 70_000),
    ("Trimestral", 90, 320_000),
    ("Semestral", 180, 600_000),
    ("Tiquetera 10 días", 10, 50_000),
]
PESOS_PLANES = [70, 10, 12, 4, 4]


def a_utc(dia: date, h: int, m: int) -> datetime:
    """Hora local de Bogotá -> UTC (aware)."""
    return datetime.combine(dia, hora(h, m), tzinfo=ZONA_HORARIA).astimezone(timezone.utc)


def sin_tildes(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def hora_gimnasio(rnd: random.Random) -> tuple[int, int]:
    """Horas típicas: picos en la mañana y en la tarde."""
    h = rnd.choice([5, 6, 6, 7, 8, 9, 10, 12, 16, 17, 18, 18, 19, 19, 20])
    return h, rnd.randint(0, 59)


def insertar(motor: Engine, modelo, filas: list[dict]) -> None:
    """Inserción masiva. Todas las filas deben tener las mismas claves."""
    claves = set().union(*filas) if filas else set()
    for fila in filas:
        for clave in claves:
            fila.setdefault(clave, None)
    with motor.begin() as cx:
        for i in range(0, len(filas), LOTE):
            cx.execute(insert(modelo), filas[i : i + LOTE])


def generar(motor: Engine, n_clientes: int, semilla: int) -> dict[str, int]:
    rnd = random.Random(semilla)
    fk = Faker("es_CO")
    fk.seed_instance(semilla)
    hoy = datetime.now(ZONA_HORARIA).date()
    ahora = datetime.now(timezone.utc)

    # --- Usuarios ---------------------------------------------------------
    hash_demo = PasswordHasher().hash(CLAVE_DEMO)
    usuarios = [
        dict(id=1, nombre_completo="Administrador", usuario="admin", rol="admin"),
        dict(id=2, nombre_completo="Recepción Mañana", usuario="recepcion1", rol="recepcion"),
        dict(id=3, nombre_completo="Recepción Tarde", usuario="recepcion2", rol="recepcion"),
    ]
    for u in usuarios:
        u.update(hash_clave=hash_demo, activo=True, intentos_fallidos=0, creado_en=ahora)
    insertar(motor, Usuario, usuarios)
    ids_recepcion = [1, 2, 3]

    insertar(motor, Config, [
        dict(clave="dias_por_vencer", valor=str(DIAS_POR_VENCER)),
        dict(clave="minutos_inactividad", valor="15"),
        dict(clave="intentos_login_max", valor="5"),
        dict(clave="asistencia_duplicada", valor="confirmar"),
        dict(clave="gimnasio_nombre", valor="Gimnasio Enforma (DATOS DE PRUEBA)"),
    ])

    # --- Planes -----------------------------------------------------------
    insertar(motor, Plan, [
        dict(id=i + 1, nombre=n, duracion_dias=d, precio=p, activo=True)
        for i, (n, d, p) in enumerate(PLANES)
    ])

    # --- Clientes y contactos --------------------------------------------
    clientes, contactos = [], []
    documentos: set[str] = set()
    info_clientes = []  # (id, sexo, fecha_registro, estado)
    for i in range(1, n_clientes + 1):
        sexo = rnd.choices(["M", "F", "O"], [49, 49, 2])[0]
        nombres = fk.first_name_male() if sexo == "M" else fk.first_name_female()
        if rnd.random() < 0.3:
            nombres += " " + (fk.first_name_male() if sexo == "M" else fk.first_name_female())
        apellidos = f"{fk.last_name()} {fk.last_name()}"
        while True:
            doc = str(rnd.randint(1_000_000, 1_299_999_999))
            if doc not in documentos:
                documentos.add(doc)
                break
        registro = hoy - timedelta(days=rnd.randint(0, 3 * 365))
        estado = "inactivo" if rnd.random() < 0.06 else "activo"
        creado = a_utc(registro, *hora_gimnasio(rnd))
        clientes.append(dict(
            id=i,
            codigo=f"{i:06d}",
            qr_token=secrets.token_urlsafe(16),
            tipo_documento=rnd.choices(["CC", "TI", "CE", "PAS"], [85, 8, 5, 2])[0],
            documento=doc,
            nombres=nombres,
            apellidos=apellidos,
            sexo=sexo,
            fecha_nacimiento=fk.date_of_birth(minimum_age=14, maximum_age=75),
            direccion=fk.street_address(),
            estado=estado,
            notas=None,
            autoriza_datos_en=creado,
            creado_en=creado,
            actualizado_en=creado,
            creado_por=rnd.choice(ids_recepcion),
        ))
        contactos.append(dict(cliente_id=i, tipo="telefono", valor=f"3{rnd.randint(0, 2)}{rnd.randint(0, 9)}{rnd.randint(1_000_000, 9_999_999)}", principal=True))
        if rnd.random() < 0.2:
            contactos.append(dict(cliente_id=i, tipo="telefono", valor=f"60{rnd.randint(1, 8)}{rnd.randint(1_000_000, 9_999_999)}", principal=False))
        if rnd.random() < 0.7:
            usuario_correo = sin_tildes(f"{nombres.split()[0]}.{apellidos.split()[0]}{rnd.randint(1, 999)}").lower()
            contactos.append(dict(cliente_id=i, tipo="email", valor=f"{usuario_correo}@example.com", principal=True))
        if rnd.random() < 0.5:
            contactos.append(dict(cliente_id=i, tipo="emergencia", valor=f"3{rnd.randint(0, 2)}{rnd.randint(0, 9)}{rnd.randint(1_000_000, 9_999_999)}", nombre_contacto=fk.name(), principal=False))
        info_clientes.append((i, sexo, registro, estado))
    insertar(motor, Cliente, clientes)
    insertar(motor, Contacto, contactos)

    # --- Membresías y pagos -----------------------------------------------
    membresias, pagos = [], []
    periodos: dict[int, list[tuple[date, date]]] = {}  # cliente -> [(inicio, fin)] no anuladas
    id_memb = 0
    consecutivo = 0
    for cid, _sexo, registro, estado in info_clientes:
        perfil = rnd.random()
        if perfil < 0.08:
            continue  # sin membresía
        inicio = max(registro, hoy - timedelta(days=400))
        # Clientes que dejaron de venir: su cadena termina antes de hoy.
        limite = hoy if perfil > 0.35 else hoy - timedelta(days=rnd.randint(10, 300))
        if estado == "inactivo":
            limite = min(limite, hoy - timedelta(days=rnd.randint(30, 200)))
        plan_fav = rnd.choices(range(len(PLANES)), PESOS_PLANES)[0]
        while inicio <= limite:
            p = plan_fav if rnd.random() < 0.85 else rnd.choices(range(len(PLANES)), PESOS_PLANES)[0]
            nombre, dur, precio = PLANES[p]
            fin = inicio + timedelta(days=dur - 1)  # RN-03
            id_memb += 1
            descuento = rnd.random() < 0.05
            precio_pactado = int(precio * 0.9) if descuento else precio
            anulada = rnd.random() < 0.005
            creado = a_utc(inicio, *hora_gimnasio(rnd))
            membresias.append(dict(
                id=id_memb, cliente_id=cid, plan_id=p + 1, fecha_inicio=inicio, fecha_fin=fin,
                precio_pactado=precio_pactado, estado="anulada" if anulada else "activa",
                motivo_descuento="Descuento por referido" if descuento else None,
                creado_por=1 if descuento else rnd.choice(ids_recepcion), creado_en=creado,
            ))
            # Pago total o parcial (10 % queda con saldo pendiente).
            montos = [precio_pactado]
            if rnd.random() < 0.10:
                abono = (precio_pactado // 2) // 1000 * 1000
                montos = [abono] if rnd.random() < 0.5 else [abono, precio_pactado - abono]
            for k, monto in enumerate(montos):
                consecutivo += 1
                metodo = rnd.choices(["efectivo", "tarjeta", "transferencia"], [55, 20, 25])[0]
                fecha_pago = min(creado + timedelta(days=7 * k), ahora)
                pagos.append(dict(
                    consecutivo=consecutivo, cliente_id=cid, membresia_id=id_memb,
                    concepto="membresia", monto=monto, metodo=metodo,
                    referencia=None if metodo == "efectivo" else f"{metodo[:3].upper()}-{rnd.randint(100000, 999999)}",
                    fecha_hora=fecha_pago, usuario_id=rnd.choice(ids_recepcion),
                    anulado=anulada, motivo_anulacion="Membresía registrada por error" if anulada else None,
                    anulado_por=1 if anulada else None, anulado_en=fecha_pago if anulada else None,
                ))
            if not anulada:
                periodos.setdefault(cid, []).append((inicio, fin))
            # Algunos renuevan con unos días de atraso.
            inicio = fin + timedelta(days=1 if rnd.random() < 0.7 else rnd.randint(2, 20))
    insertar(motor, Membresia, membresias)

    # --- Casilleros ---------------------------------------------------------
    casilleros = []
    for n in range(1, 241):
        zona = "hombres" if n <= 100 else "mujeres" if n <= 200 else "mixto"
        estado = "mantenimiento" if n % 47 == 0 else "disponible"
        casilleros.append(dict(id=n, numero=f"{n:03d}", zona=zona, estado=estado))

    asignaciones = []
    con_casillero: dict[int, tuple[str, date]] = {}  # cliente -> (numero, desde)
    libres = {"M": [c for c in casilleros if c["zona"] in ("hombres", "mixto") and c["estado"] == "disponible"],
              "F": [c for c in casilleros if c["zona"] in ("mujeres", "mixto") and c["estado"] == "disponible"]}
    for lista in libres.values():
        rnd.shuffle(lista)
    candidatos = [c for c in info_clientes if c[3] == "activo" and c[0] in periodos]
    rnd.shuffle(candidatos)
    for cid, sexo, registro, _estado in candidatos:
        lista = libres["M" if sexo == "M" else "F"]
        # Sacar el primero que siga disponible (los mixtos están en ambas listas).
        while lista and lista[0]["estado"] != "disponible":
            lista.pop(0)
        if not lista:
            continue
        cas = lista.pop(0)
        # Historial: a veces el casillero tuvo antes otro dueño ya liberado.
        desde = max(registro, hoy - timedelta(days=rnd.randint(5, 300)))
        cas["estado"] = "ocupado"
        asignaciones.append(dict(
            casillero_id=cas["id"], cliente_id=cid, fecha_asignacion=a_utc(desde, 9, 0),
            asignado_por=rnd.choice(ids_recepcion),
        ))
        con_casillero[cid] = (cas["numero"], desde)
    # Asignaciones antiguas ya liberadas (historial), de clientes sin casillero actual.
    sin_casillero = [c[0] for c in info_clientes if c[0] not in con_casillero]
    for cid in rnd.sample(sin_casillero, min(len(sin_casillero), 150)):
        cas = rnd.choice(casilleros)
        fin = hoy - timedelta(days=rnd.randint(320, 700))
        ini = fin - timedelta(days=rnd.randint(30, 200))
        asignaciones.append(dict(
            casillero_id=cas["id"], cliente_id=cid,
            fecha_asignacion=a_utc(ini, 9, 0), fecha_liberacion=a_utc(fin, 18, 0),
            asignado_por=rnd.choice(ids_recepcion), liberado_por=rnd.choice(ids_recepcion),
            motivo_liberacion=rnd.choice(["Membresía vencida", "Solicitud del cliente", "Cambio de casillero"]),
        ))
    insertar(motor, Casillero, casilleros)
    insertar(motor, CasilleroAsignacion, asignaciones)
    insertar(motor, Pago, pagos)

    # --- Asistencias ------------------------------------------------------
    asistencias = []
    estado_cliente = {c[0]: c[3] for c in info_clientes}
    for cid, lista in periodos.items():
        frecuencia = rnd.uniform(0.15, 0.7)
        cas = con_casillero.get(cid)
        for inicio, fin in lista:
            d0 = max(inicio, hoy - timedelta(days=DIAS_ASISTENCIA))
            d1 = min(fin, hoy)
            dia = d0
            while dia <= d1:
                if dia.weekday() != 6 and rnd.random() < frecuencia:  # domingo cerrado
                    h, m = hora_gimnasio(rnd)
                    if dia == hoy and h > datetime.now(ZONA_HORARIA).hour:
                        dia += timedelta(days=1)
                        continue
                    resultado = "por_vencer" if (fin - dia).days < DIAS_POR_VENCER else "permitido"
                    asistencias.append(dict(
                        cliente_id=cid, fecha_hora=a_utc(dia, h, m), fecha=dia, resultado=resultado,
                        casillero_numero=cas[0] if cas and dia >= cas[1] else None,
                        usuario_id=rnd.choice(ids_recepcion), eliminada=False,
                    ))
                dia += timedelta(days=1)
        # Unos pocos intentos de ingreso vencido o autorizado por el admin.
        if lista and rnd.random() < 0.05 and lista[-1][1] < hoy - timedelta(days=1):
            dia = min(lista[-1][1] + timedelta(days=rnd.randint(1, 10)), hoy)
            inactivo = estado_cliente[cid] == "inactivo"
            asistencias.append(dict(
                cliente_id=cid, fecha_hora=a_utc(dia, 7, 30), fecha=dia,
                resultado="autorizado" if rnd.random() < 0.3 else ("inactivo" if inactivo else "vencido"),
                usuario_id=1, eliminada=False,
            ))
    # Algunas asistencias eliminadas lógicamente, con motivo.
    for a in rnd.sample(asistencias, min(len(asistencias), 60)):
        a.update(eliminada=True, motivo_eliminacion="Registro duplicado por error",
                 eliminada_por=1, eliminada_en=a["fecha_hora"] + timedelta(minutes=5))
    asistencias.sort(key=lambda a: a["fecha_hora"])
    insertar(motor, Asistencia, asistencias)

    # --- Invitados --------------------------------------------------------
    invitados, visitas = [], []
    ids_activos = [c[0] for c in info_clientes if c[3] == "activo"]
    n_invitados = max(10, n_clientes // 15)
    for j in range(1, n_invitados + 1):
        while True:
            doc = str(rnd.randint(1_000_000, 1_299_999_999))
            if doc not in documentos:
                documentos.add(doc)
                break
        primera = hoy - timedelta(days=rnd.randint(0, 365))
        invitados.append(dict(
            id=j, nombre=fk.name(), documento=doc,
            telefono=f"3{rnd.randint(0, 2)}{rnd.randint(0, 9)}{rnd.randint(1_000_000, 9_999_999)}",
            creado_en=a_utc(primera, 10, 0), creado_por=rnd.choice(ids_recepcion),
        ))
        anfitrion = rnd.choice(ids_activos) if rnd.random() < 0.8 else None
        for _ in range(rnd.choices([1, 2, 3, 5, 8], [50, 20, 15, 10, 5])[0]):
            dia = primera + timedelta(days=rnd.randint(0, (hoy - primera).days))
            visitas.append(dict(
                invitado_id=j, fecha_hora=a_utc(dia, *hora_gimnasio(rnd)), fecha=dia,
                cliente_anfitrion_id=anfitrion, usuario_id=rnd.choice(ids_recepcion), eliminada=False,
            ))
    insertar(motor, Invitado, invitados)
    insertar(motor, InvitadoAsistencia, visitas)

    # --- Alertas manuales -------------------------------------------------
    textos = [("Falta copia del documento", "advertencia"), ("Pendiente firmar autorización", "info"),
              ("Revisar certificado médico", "critica"), ("Tiene saldo pendiente", "advertencia")]
    alertas = []
    for cid in rnd.sample(ids_activos, min(len(ids_activos), max(5, n_clientes // 40))):
        msg, nivel = rnd.choice(textos)
        alertas.append(dict(cliente_id=cid, mensaje=msg, nivel=nivel, activa=True,
                            fecha_inicio=hoy - timedelta(days=rnd.randint(0, 60)),
                            creada_por=rnd.choice(ids_recepcion), creada_en=ahora))
    insertar(motor, Alerta, alertas)

    return {
        "usuarios": len(usuarios), "clientes": len(clientes), "contactos": len(contactos),
        "planes": len(PLANES), "membresias": len(membresias), "pagos": len(pagos),
        "casilleros": len(casilleros), "casillero_asignaciones": len(asignaciones),
        "asistencias": len(asistencias), "invitados": len(invitados),
        "invitado_asistencias": len(visitas), "alertas": len(alertas),
    }


def main(argumentos: list[str] | None = None) -> dict[str, int]:
    parser = argparse.ArgumentParser(description="Carga datos falsos de prueba.")
    parser.add_argument("--clientes", type=int, default=12_000)
    parser.add_argument("--db", help="Ruta de un archivo .db (por defecto, la base configurada)")
    parser.add_argument("--semilla", type=int, default=2026)
    args = parser.parse_args(argumentos)

    url = f"sqlite:///{Path(args.db).resolve().as_posix()}" if args.db else url_base_datos()
    inicio = time.perf_counter()
    actualizar_esquema(url)
    motor = crear_motor(url)
    with motor.connect() as cx:
        if cx.execute(select(func.count()).select_from(Cliente)).scalar_one():
            motor.dispose()
            raise SystemExit("La base ya tiene clientes. Usa --db con un archivo nuevo para los datos de prueba.")
    conteos = generar(motor, args.clientes, args.semilla)
    motor.dispose()
    segundos = time.perf_counter() - inicio
    print(f"Datos de prueba cargados en {segundos:.1f} s ({url})")
    for tabla, n in conteos.items():
        print(f"  {tabla:<24}{n:>10,}".replace(",", "."))
    print(f"Usuarios: admin, recepcion1, recepcion2. Clave de prueba: {CLAVE_DEMO}")
    return conteos


if __name__ == "__main__":
    main()
