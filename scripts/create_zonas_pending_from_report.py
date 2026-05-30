import json
from pathlib import Path

from pending_utils import create_pending, github_link, stable_id

ROOT = Path(__file__).resolve().parents[1]
REPORTES_DIR = ROOT / "tasas" / "historico" / "reportes"
ZONAS_PATH = "tasas/historico/manual/zonas_extremas.json"


def read_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def latest_zonas_report():
    reports = sorted(REPORTES_DIR.glob("zonas_extremas_*.json"))
    if not reports:
        return None
    return reports[-1]


def format_clp(valor):
    try:
        return "$" + f"{int(valor):,}".replace(",", ".")
    except Exception:
        return str(valor)


def nombre_mes(mes):
    return {
        1: "enero",
        2: "febrero",
        3: "marzo",
        4: "abril",
        5: "mayo",
        6: "junio",
        7: "julio",
        8: "agosto",
        9: "septiembre",
        10: "octubre",
        11: "noviembre",
        12: "diciembre",
    }.get(mes, "mes")


def periodo_humano(item):
    desde = str(item.get("desde") or "")
    hasta = str(item.get("hasta") or "")
    partes_desde = desde.split("-")
    partes_hasta = hasta.split("-")

    if len(partes_desde) == 3 and len(partes_hasta) == 3:
        anio_desde = partes_desde[0]
        anio_hasta = partes_hasta[0]
        mes_desde = int(partes_desde[1]) if partes_desde[1].isdigit() else None
        mes_hasta = int(partes_hasta[1]) if partes_hasta[1].isdigit() else None
        if mes_desde and mes_hasta and anio_desde == anio_hasta:
            if mes_desde == mes_hasta:
                return f"{nombre_mes(mes_desde).capitalize()} {anio_desde}"
            return f"{nombre_mes(mes_desde).capitalize()} a {nombre_mes(mes_hasta)} {anio_desde}"

    return f"{item.get('desde')} a {item.get('hasta')}"


def pending_for_sueldo(item, fecha_revision):
    periodo = periodo_humano(item)
    valor = item.get("valor")
    valor_texto = format_clp(valor)
    fuente_nombre = item.get("fuente") or "SII"
    fuente_url = item.get("url")
    pending_id = stable_id("zona_sueldo_1a", item.get("desde"), item.get("hasta"), valor, fuente_url)

    return pending_id, {
        "tipo": "validar_sueldo_grado_1a",
        "titulo": f"Nuevo sueldo grado 1-A detectado: {periodo}",
        "periodo": periodo,
        "valorActual": "Dato agregado como pendiente de validación en GitHub",
        "valorDetectado": valor_texto,
        "motivo": (
            f"Detecté un nuevo valor de sueldo grado 1-A publicado por {fuente_nombre}. "
            "Este dato se usa como base para calcular el tope de la rebaja de zona extrema."
        ),
        "descripcion": (
            "Revísalo en la fuente oficial antes de validarlo.\n\n"
            f"Mes o período detectado: {periodo}\n"
            f"Valor detectado: {valor_texto}\n"
            f"Fuente informada: {fuente_nombre}\n\n"
            "✅ Si presionas Validar, el dato queda como manual_validado y la app podrá usarlo para cálculos de zona extrema.\n"
            "❌ Si presionas Rechazar, queda marcado como manual_requerido y no se debe usar como validado."
        ),
        "fuente": fuente_url or fuente_nombre,
        "targetFile": ZONAS_PATH,
        "linkGitHub": github_link(ZONAS_PATH),
        "fechaRevision": fecha_revision,
        "action": {
            "kind": "set_estado_by_match",
            "arrayPath": ["sueldoGrado1A"],
            "match": {
                "desde": item.get("desde"),
                "hasta": item.get("hasta"),
                "valor": valor,
            },
            "estadoOk": "manual_validado",
            "estadoReject": "manual_requerido",
        },
    }


def pending_for_change(change, fecha_revision):
    motivo = change.get("motivo") or "cambio_detectado"
    pending_id = stable_id("zona_norma", motivo, change.get("url"), change.get("hashNuevo"), fecha_revision)
    return pending_id, {
        "tipo": "revision_normativa_zona_extrema",
        "titulo": "Revisión normativa zona extrema DL 889 / DL 249",
        "periodo": fecha_revision,
        "valorActual": "Tabla vigente guardada en GitHub",
        "valorDetectado": motivo,
        "motivo": "El monitoreo detectó un cambio o aviso en una fuente relacionada con zona extrema.",
        "descripcion": "No se modifica ningún porcentaje automáticamente. Validar significa dejar registrado que revisaste la fuente; rechazar significa mantenerlo como pendiente.",
        "fuente": change.get("url") or change.get("fuente"),
        "targetFile": ZONAS_PATH,
        "linkGitHub": github_link(ZONAS_PATH),
        "fechaRevision": fecha_revision,
        "action": None,
    }


def main():
    report_path = latest_zonas_report()
    if not report_path:
        print("No hay reporte de zonas extremas para generar pendientes.")
        return

    report = read_json(report_path)
    fecha_revision = report.get("fechaRevision") or report_path.stem.replace("zonas_extremas_", "")
    created_count = 0

    for item in report.get("datosPendientes", {}).get("sueldosAgregadosPendientesValidacion", []) or []:
        pending_id, payload = pending_for_sueldo(item, fecha_revision)
        created, _ = create_pending(pending_id, payload)
        if created:
            created_count += 1

    for change in report.get("cambiosDetectados", []) or []:
        if change.get("motivo") in {"nuevo_sueldo_grado_1a_pendiente_validacion", "zonas_con_porcentaje_pendiente"}:
            continue
        pending_id, payload = pending_for_change(change, fecha_revision)
        created, _ = create_pending(pending_id, payload)
        if created:
            created_count += 1

    print(f"Pendientes de zona extrema creados: {created_count}")


if __name__ == "__main__":
    main()
