"""Prueba de humo del ejecutable: `Enforma.exe --prueba-humo --reporte salida.txt`.

La usa el workflow de Windows sobre el .exe ya empaquetado (y sirve en cualquier PC)
para comprobar que dentro del ejecutable está todo lo que el programa necesita:
migraciones, servicios, PDF (reportlab), Excel (openpyxl), argon2, cifrado de copias,
zona horaria, ayuda, DPAPI e interfaz Qt.

Trabaja en una carpeta temporal con datos inventados: **nunca toca la base del
gimnasio**. Devuelve 0 si todo pasó y 1 si algo falló.
"""

from __future__ import annotations

import os
import tempfile
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from gimnasio import __version__

CLAVE_USUARIO = "Prueba-Humo-2026"
CLAVE_COPIAS = "copias-Prueba-Humo-2026"


def ejecutar(reporte: Path | None = None) -> int:
    resultados: list[str] = []
    fallas = 0

    def paso(nombre: str, funcion: Callable[[], str | None]) -> None:
        nonlocal fallas
        inicio = time.perf_counter()
        try:
            detalle = funcion() or ""
            resultados.append(f"[OK   ] {nombre} ({time.perf_counter() - inicio:.2f} s) {detalle}")
        except Exception as e:
            fallas += 1
            resultados.append(f"[FALLA] {nombre}: {type(e).__name__}: {e}")
            resultados.append(traceback.format_exc())

    with tempfile.TemporaryDirectory(prefix="enforma_humo_") as temporal:
        carpeta = Path(temporal)
        url = f"sqlite:///{(carpeta / 'enforma.db').as_posix()}"
        estado: dict = {}

        def migrar():
            from gimnasio.db.migraciones import actualizar_esquema
            actualizar_esquema(url)
            from gimnasio.servicios.backups import revisiones_conocidas
            return f"esquema {revisiones_conocidas()[-1]}"

        def servicios():
            from gimnasio.db.engine import crear_fabrica_sesiones, crear_motor
            from gimnasio.servicios.contenedor import crear_servicios
            estado["motor"] = crear_motor(url)
            s = crear_servicios(crear_fabrica_sesiones(estado["motor"]), carpeta_datos=carpeta)
            estado["s"] = s
            estado["admin"] = s.usuarios.crear_primer_administrador(
                "Administrador de prueba", "admin", CLAVE_USUARIO)
            s.sesion.iniciar_sesion("admin", CLAVE_USUARIO)  # argon2
            return "usuario creado e inicio de sesión con argon2"

        def cliente_y_pago():
            from gimnasio.servicios.clientes import DatosCliente
            from gimnasio.servicios.pagos import DatosPago
            s, admin = estado["s"], estado["admin"]
            plan = s.planes.crear(admin, "Mensual prueba", 30, 100_000)
            ficha = s.clientes.registrar(admin, DatosCliente(
                tipo_documento="CC", documento="99999999", nombres="Cliente", apellidos="De Prueba",
                sexo="M", telefonos=["3000000000"]))
            membresia = s.pagos.registrar_membresia(
                admin, ficha.id, plan.id, pago=DatosPago(monto=100_000))
            estado["pago_id"] = membresia.pago.id
            estado["codigo"] = ficha.codigo
            return f"cliente {ficha.codigo}, saldo {membresia.saldo}"

        def ingreso():
            r = estado["s"].asistencia.registrar_ingreso(estado["admin"], estado["codigo"])
            return f"ingreso {r.estado}"

        def recibo_pdf():
            ruta = estado["s"].pagos.generar_recibo(estado["admin"], estado["pago_id"])
            assert ruta.stat().st_size > 1000
            return ruta.name

        def reportes():
            s, admin = estado["s"], estado["admin"]
            xlsx = s.reportes.exportar(admin, "clientes_morosos", None, carpeta / "r.xlsx", "xlsx")
            pdf = s.reportes.exportar(admin, "clientes_morosos", None, carpeta / "r.pdf", "pdf")
            assert xlsx.stat().st_size > 1000 and pdf.stat().st_size > 1000
            return "Excel y PDF"

        def copia():
            s, admin = estado["s"], estado["admin"]
            s.backups.configurar_clave(admin, CLAVE_COPIAS, CLAVE_COPIAS)
            resultado = s.backups.hacer_backup(admin, "manual")
            assert resultado.exitoso, resultado.error
            resumen = s.backups.verificar(admin, resultado.rutas[0], CLAVE_COPIAS)
            assert resumen.integridad == "ok"
            protegida = s.backups.estado(admin)
            return f"creada y verificada (integridad {resumen.integridad})" + (
                "" if os.name != "nt" else f", clave con DPAPI: {protegida.clave_protegida}")

        def ayuda():
            from gimnasio.servicios.ayuda import TEMAS
            s, admin = estado["s"], estado["admin"]
            textos = [s.ayuda.contenido(admin, t.clave) for t in TEMAS]
            assert all(len(t) > 100 for t in textos)
            return f"{len(textos)} temas"

        def interfaz():
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from PySide6.QtWidgets import QApplication
            from gimnasio.ui.ventana_principal import VentanaPrincipal
            app = QApplication.instance() or QApplication([])
            ventana = VentanaPrincipal(estado["s"], estado["admin"])
            ventana.show()
            app.processEvents()
            ventana.close()
            return f"ventana principal ({app.platformName()})"

        def diagnostico():
            from gimnasio import diagnostico as d
            revisiones = [d.revisar_archivos_programa(), d.revisar_zona_horaria(), d.revisar_dpapi(),
                          d.revisar_clave_guardada(carpeta)]
            malas = [r for r in revisiones if r.estado == d.FALLA]
            assert not malas, "; ".join(f"{r.nombre}: {r.detalle}" for r in malas)
            return "; ".join(f"{r.nombre}: {r.estado}" for r in revisiones)

        for nombre, funcion in (
            ("Migraciones", migrar), ("Servicios y usuarios", servicios),
            ("Cliente, membresía y pago", cliente_y_pago), ("Ingreso en Recepción", ingreso),
            ("Recibo PDF", recibo_pdf), ("Reportes Excel y PDF", reportes),
            ("Copia de seguridad cifrada", copia), ("Ayuda", ayuda),
            ("Interfaz Qt", interfaz), ("Diagnóstico y DPAPI", diagnostico),
        ):
            if "s" not in estado and nombre not in ("Migraciones", "Servicios y usuarios",
                                                     "Diagnóstico y DPAPI"):
                resultados.append(f"[-----] {nombre}: no se probó (falló un paso anterior)")
                continue
            paso(nombre, funcion)
        if "motor" in estado:
            estado["motor"].dispose()

    texto = "\n".join([f"Prueba de humo de Enforma {__version__}", *resultados,
                       "RESULTADO: " + ("OK" if not fallas else f"{fallas} FALLAS")])
    if reporte:
        Path(reporte).write_text(texto + "\n", encoding="utf-8")
    else:
        print(texto)
    return 0 if not fallas else 1
