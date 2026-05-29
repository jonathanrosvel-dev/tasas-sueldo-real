import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from pending_utils import create_pending, github_link, stable_id

ROOT = Path(__file__).resolve().parents[1]
MANUAL_DIR = ROOT / "tasas" / "historico" / "manual"
REPORTES_DIR = ROOT / "tasas" / "historico" / "reportes"
HASHES_PATH = MANUAL_DIR / "manual_indicator_hashes.json"

SOURCES = [
    {
        "indicador": "topes_previsionales",
        "nombre_humano": "Topes imponibles AFP/salud y seguro de cesantía",
        "descripcion": "Estos topes limitan la base usada para cotizaciones previsionales. Pueden cambiar por resolución o actualización normativa.",
        "url": "https://www.spensiones.cl/portal/institucional/594/w3-propertyvalue-9923.html",
        "archivo_json": "tasas/historico/manual/topes.json",
        "palabras_clave": ["tope imponible", "afiliados", "seguro de cesantía", "uf", "cotizaciones"],
    },
    {
        "indicador": "imm",
        "nombre_humano": "Ingreso Mínimo Mensual",
        "descripcion": "El IMM afecta cálculos como la gratificación legal estimada. Cambia cuando se publica una ley o actualización oficial.",
        "url": "https://www.dt.gob.cl/portal/1628/w3-propertyvalue-145768.html",
        "archivo_json": "tasas/historico/manual/laboral.json",
        "palabras_clave": ["ingreso mínimo", "sueldo mínimo", "remuneración mínima", "trabajadores", "ley"],
    },
    {
        "indicador": "seguro_cesantia",
        "nombre_humano": "Seguro de cesantía",
        "descripcion": "Las tasas del seguro de cesantía son estables, pero podrían cambiar por modificación legal.",
        "url": "https://www.dt.gob.cl/portal/1628/w3-propertyvalue-145768.html",
        "archivo_json": "tasas/historico/manual/cesantia.json",
        "palabras_clave": ["seguro de cesantía", "contrato indefinido", "plazo fijo", "trabajador", "empleador"],
    },
    {
        "indicador": "afp_comisiones",
        "nombre_humano": "Comisiones AFP",
        "descripcion": "Las comisiones AFP pueden cambiar y conviene revisar la fuente cuando detectemos movimientos.",
        "url": "https://www.spensiones.cl/portal/institucional/594/w3-article-2810.html",
        "archivo_json": "tasas/historico/manual/afp_comisiones.json",
        "palabras_clave": ["capital", "cuprum", "habitat", "modelo", "planvital", "provida", "uno", "comisión"],
    },
    {
        "indicador": "zona_extrema_porcentajes",
        "nombre_humano": "Porcentajes de zona extrema DL 889 / DL 249",
        "descripcion": "Los porcentajes por comuna son estables por ley, pero si cambia la norma corresponde revisar la tabla.",
        "url": "https://www.bcn.cl/leychile/navegar?idNorma=6368",
        "archivo_json": "tasas/historico/manual/zonas_extremas.json",
        "palabras_clave": ["asignación de zona", "zona", "porcentaje", "tarapacá", "aysén", "magallanes", "chiloé", "palena"],
    },
    {
        "indicador": "zona_extrema_modificacion_1",
        "nombre_humano": "Modificaciones normativa zona extrema",
        "descripcion": "Fuente complementaria para revisar posibles cambios normativos vinculados a zona extrema.",
        "url": "https://www.bcn.cl/leychile/navegar?i=1203976",
        "archivo_json": "tasas/historico/manual/zonas_extremas.json",
        "palabras_clave": ["zona", "asignación", "porcentaje", "dl 889", "dl 249"],
    },
    {
        "indicador": "zona_extrema_modificacion_2",
        "nombre_humano": "Normativa relacionada zona extrema",
        "descripcion": "Fuente complementaria para revisar posibles cambios normativos vinculados a zona extrema.",
        "url": "https://www.bcn.cl/leychile/navegar?i=6390",
        "archivo_json": "tasas/historico/manual/zonas_extremas.json",
        "palabras_clave": ["zona", "asignación", "porcentaje", "dl 889", "dl 249"],
    },
]


def chile_today():
    return datetime.now(ZoneInfo("America/Santiago")).date()


def read_json(path, default=None):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def get_content(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    }
    response = requests.get(url, headers=headers, timeout=45)
    response.raise_for_status()
    return response.text


def clean_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True).lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def keyword_counts(text, keywords):
    return {kw: text.count(kw.lower()) for kw in keywords}


def build_pending_from_change(change, today):
    pending_id = stable_id("manual", change["indicador"], change["url"], change.get("hashNuevo"), today)
    keywords = change.get("keywords") or {}
    keyword_text = ", ".join([f"{k}: {v}" for k, v in keywords.items() if v]) or None
    description = change["descripcion"]
    if keyword_text:
        description += f"\n\nMenciones relevantes detectadas: {keyword_text}"
    return pending_id, {
        "tipo": "revision_indicador_manual",
        "titulo": change["nombre_humano"],
        "periodo": today,
        "valorActual": "Dato vigente guardado en GitHub",
        "valorDetectado": "Cambio detectado en fuente revisada",
        "motivo": change.get("mensaje", "Detecté una fuente que requiere revisión."),
        "descripcion": description,
        "fuente": change["url"],
        "targetFile": change["archivo_json"],
        "linkGitHub": github_link(change["archivo_json"]),
        "action": None,
    }


def main():
    today = chile_today().isoformat()
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    REPORTES_DIR.mkdir(parents=True, exist_ok=True)

    hashes = read_json(HASHES_PATH, {
        "descripcion": "Hashes de monitoreo para indicadores manuales o semiautomáticos",
        "fechaCreacion": today,
        "fechaActualizacion": None,
        "fuentes": {},
    }) or {}
    stored = hashes.setdefault("fuentes", {})

    changes = []
    baseline = []
    reviewed = []
    pendientes_creados = []

    for source in SOURCES:
        key = source["indicador"] + "|" + source["url"]
        record = {"indicador": source["indicador"], "nombre": source["nombre_humano"], "url": source["url"], "estado": "ok"}
        try:
            html = get_content(source["url"])
            text = clean_text(html)
            new_hash = digest(text)
            counts = keyword_counts(text, source["palabras_clave"])
            old = stored.get(key)

            if old is None:
                baseline.append({**source, "mensaje": "baseline_creado", "hashNuevo": new_hash, "keywords": counts})
            elif old.get("hash") != new_hash:
                changes.append({**source, "mensaje": "La fuente cambió desde la última revisión.", "hashAnterior": old.get("hash"), "hashNuevo": new_hash, "keywords": counts})
            else:
                old_counts = old.get("keywordCounts", {})
                for keyword, count in counts.items():
                    if count > old_counts.get(keyword, 0):
                        changes.append({**source, "mensaje": f"Aumentaron las menciones de '{keyword}'.", "keyword": keyword, "conteoAnterior": old_counts.get(keyword, 0), "conteoNuevo": count, "keywords": counts, "hashNuevo": new_hash})
                        break

            stored[key] = {
                "indicador": source["indicador"],
                "nombre": source["nombre_humano"],
                "url": source["url"],
                "hash": new_hash,
                "fechaRevision": today,
                "keywordCounts": counts,
                "archivo_json": source["archivo_json"],
            }
            record.update({"hash": new_hash, "keywordCounts": counts})
        except Exception as exc:
            record.update({"estado": "error", "error": str(exc)})
            changes.append({**source, "mensaje": f"No pude revisar esta fuente: {exc}", "keywords": {}, "hashNuevo": f"error-{today}"})
        reviewed.append(record)

    hashes["fechaActualizacion"] = today
    write_json(HASHES_PATH, hashes)

    for change in changes:
        pending_id, payload = build_pending_from_change(change, today)
        created, pending_path = create_pending(pending_id, payload)
        if created:
            pendientes_creados.append(str(pending_path.relative_to(ROOT)))

    report = {
        "fechaRevision": today,
        "estado": "revision_requerida" if changes else "sin_cambios",
        "fuentesRevisadas": reviewed,
        "baselineCreados": baseline,
        "cambiosDetectados": changes,
        "pendientesCreados": pendientes_creados,
    }
    if changes:
        report_path = REPORTES_DIR / f"manual_indicators_{today}.json"
        write_json(report_path, report)
        print(f"Revisión requerida. Reporte: {report_path.relative_to(ROOT)}")
        print(f"Pendientes creados: {len(pendientes_creados)}")
    else:
        print("Monitoreo de indicadores manuales sin cambios relevantes.")
        if baseline:
            print(f"Baseline creado para {len(baseline)} fuentes; no se envía Telegram por baseline.")
    print(f"Fuentes revisadas: {len(reviewed)}")
    print(f"Cambios detectados: {len(changes)}")


if __name__ == "__main__":
    main()
