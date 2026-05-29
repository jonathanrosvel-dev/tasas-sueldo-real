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


def pending_for_sueldo(item, fecha_revision):
    periodo = f"{item.get('desde')} a {item.get('hasta')}"
    pending_id = stable_id("zona_sueldo_1a", item.get("desde"), item.get("hasta"), item.get("valor"), item.get("url"))
    return pending_id, {
        "tipo": "validar_sueldo_grado_1a",
        "titulo": "Sueldo grado 1-A para rebaja de zona extrema",
        "periodo": periodo,
        "valorActual": "Nuevo dato agregado como manual_pendiente",
        "valorDetectado": item.get("valor"),
        "motivo": "El monitoreo detectó un nuevo sueldo grado 1-A desde una fuente SII. Debe revisarse antes de marcarlo como validado.",
        "descripcion": "Este valor se usa como base del tope para la rebaja de zona extrema DL 889. Validar solo si el dato coincide con la fuente oficial indicada.",
        "fuente": item.get("url") or item.get("fuente"),
        "targetFile": ZONAS_PATH,
        "linkGitHub": github_link(ZONAS_PATH),
        "fechaRevision": fecha_revision,
        "action": {
            "kind": "set_estado_by_match",
            "arrayPath": ["sueldoGrado1A"],
            "match": {
                "desde": item.get("desde"),
                "hasta": item.get("hasta"),
                "valor": item.get("valor"),
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
