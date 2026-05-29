import json
from pathlib import Path

from pending_utils import create_pending, github_link, stable_id

ROOT = Path(__file__).resolve().parents[1]
TASAS_JSON = ROOT / "tasas.json"

ALERT_STATES = {"manual", "manual_pendiente", "respaldo", "manual_requerido", "faltante", "error", "invalido"}

INDICADORES = {
    "uf": {
        "titulo": "UF",
        "descripcion": "La UF se usa para convertir topes y valores expresados en UF. Si quedó en respaldo, conviene revisar la fuente antes de confiar en el dato.",
        "fuente": "https://www.sii.cl/valores_y_fechas/uf/uf{anio}.htm",
        "targetFile": "tasas/historico/uf/uf_diaria_{anio}.json",
    },
    "utm": {
        "titulo": "UTM",
        "descripcion": "La UTM se usa para calcular tramos y rebajas del Impuesto Único de Segunda Categoría.",
        "fuente": "https://www.sii.cl/valores_y_fechas/utm/utm{anio}.htm",
        "targetFile": "tasas.json",
    },
    "impuestoUnico": {
        "titulo": "Impuesto Único de Segunda Categoría",
        "descripcion": "La tabla de IUSC define los tramos mensuales usados para calcular el impuesto del trabajador.",
        "fuente": "https://www.sii.cl/valores_y_fechas/impuesto_2da_categoria/impuesto{anio}.htm",
        "targetFile": "tasas.json",
    },
    "afp": {
        "titulo": "Comisiones AFP",
        "descripcion": "Las comisiones AFP afectan el descuento previsional. Si la fuente falló, la app usa respaldo local.",
        "fuente": "https://www.spensiones.cl/portal/institucional/594/w3-article-2810.html",
        "targetFile": "tasas/historico/manual/afp_comisiones.json",
    },
    "topes": {
        "titulo": "Topes imponibles AFP/salud y cesantía",
        "descripcion": "Los topes previsionales limitan la base de cálculo de cotizaciones. Si están manuales, conviene revisarlos contra fuente oficial.",
        "fuente": "https://www.spensiones.cl/portal/institucional/594/w3-propertyvalue-9923.html",
        "targetFile": "tasas/historico/manual/topes.json",
    },
    "imm": {
        "titulo": "Ingreso Mínimo Mensual",
        "descripcion": "El IMM afecta referencias laborales como la gratificación legal estimada.",
        "fuente": "https://www.dt.gob.cl/portal/1628/w3-propertyvalue-145768.html",
        "targetFile": "tasas/historico/manual/laboral.json",
    },
    "cesantia": {
        "titulo": "Seguro de cesantía",
        "descripcion": "Las tasas de seguro de cesantía dependen del tipo de contrato. Normalmente son estables, pero pueden cambiar por ley.",
        "fuente": "https://www.dt.gob.cl/portal/1628/w3-propertyvalue-145768.html",
        "targetFile": "tasas/historico/manual/cesantia.json",
    },
    "salud": {
        "titulo": "Cotización legal de salud",
        "descripcion": "Cotización legal base de salud usada por la app.",
        "fuente": "https://www.dt.gob.cl/portal/1628/w3-propertyvalue-145768.html",
        "targetFile": "tasas.json",
    },
}


def read_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def valor_usado(data, indicador):
    if indicador == "uf":
        return data.get("uf")
    if indicador == "utm":
        return data.get("utm")
    if indicador == "impuestoUnico":
        return f"{len(data.get('impuestoUnico', {}).get('tramos', []))} tramos cargados"
    if indicador == "afp":
        return f"{len(data.get('afp', []))} AFP cargadas"
    if indicador == "topes":
        return data.get("topes")
    if indicador == "imm":
        return data.get("laboral")
    if indicador == "salud":
        return data.get("salud")
    if indicador == "cesantia":
        return data.get("cesantia")
    return data.get(indicador)


def main():
    data = read_json(TASAS_JSON)
    periodo_data = data.get("periodo", {})
    anio = periodo_data.get("anio")
    mes = periodo_data.get("mes")
    periodo = f"{anio}-{int(mes):02d}" if anio and mes else data.get("version", "actual")
    estados = data.get("estadoActualizacion", {})
    fuentes = data.get("fuentes", {})
    created_count = 0

    for indicador, estado in estados.items():
        if estado not in ALERT_STATES:
            continue
        meta = INDICADORES.get(indicador, {"titulo": indicador, "descripcion": "Dato usado por la app.", "targetFile": "tasas.json", "fuente": "sin_fuente"})
        fuente = fuentes.get(indicador) or meta.get("fuente", "sin_fuente").format(anio=anio)
        target_file = meta.get("targetFile", "tasas.json").format(anio=anio)
        pending_id = stable_id("tasas", periodo, indicador, estado, str(valor_usado(data, indicador)))
        payload = {
            "tipo": "revision_tasas_actuales",
            "titulo": meta["titulo"],
            "periodo": periodo,
            "valorActual": valor_usado(data, indicador),
            "valorDetectado": f"estado: {estado}",
            "motivo": f"Después de actualizar tasas, este indicador quedó en estado '{estado}'. Requiere revisión antes de considerarlo completamente validado.",
            "descripcion": meta["descripcion"],
            "fuente": fuente,
            "targetFile": target_file,
            "linkGitHub": github_link(target_file),
            "action": None,
        }
        created, _path = create_pending(pending_id, payload)
        if created:
            created_count += 1

    print(f"Pendientes de tasas creados: {created_count}")


if __name__ == "__main__":
    main()
