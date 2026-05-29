import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
MANUAL_DIR = ROOT / "tasas" / "historico" / "manual"
REPORTES_DIR = ROOT / "tasas" / "historico" / "reportes"
HASHES_PATH = MANUAL_DIR / "manual_indicator_hashes.json"

GITHUB_BASE = "https://github.com/jonathanrosvel-dev/tasas-sueldo-real/blob/main"

SOURCES = [
    {
        "indicador": "topes_previsionales",
        "nombre_humano": "Topes imponibles AFP/salud y seguro de cesantía",
        "descripcion": "Estos topes limitan la base usada para cotizaciones previsionales. No cambian todos los días, pero pueden cambiar por resolución o actualización normativa.",
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
        "descripcion": "Las tasas del seguro de cesantía no cambian normalmente mes a mes, pero podrían cambiar por modificación legal.",
        "url": "https://www.dt.gob.cl/portal/1628/w3-propertyvalue-145768.html",
        "archivo_json": "tasas/historico/manual/cesantia.json",
        "palabras_clave": ["seguro de cesantía", "contrato indefinido", "plazo fijo", "trabajador", "empleador"],
    },
    {
        "indicador": "afp_comisiones",
        "nombre_humano": "Comisiones AFP",
        "descripcion": "Las comisiones AFP pueden cambiar. Si la lectura automática falla, la app usa respaldo y conviene revisar la fuente.",
        "url": "https://www.spensiones.cl/portal/institucional/594/w3-article-2810.html",
        "archivo_json": "tasas/historico/manual/afp_comisiones.json",
        "palabras_clave": ["capital", "cuprum", "habitat", "modelo", "planvital", "provida", "uno", "comisión"],
    },
    {
        "indicador": "zona_extrema_porcentajes",
        "nombre_humano": "Porcentajes de zona extrema DL 889 / DL 249",
        "descripcion": "Los porcentajes por comuna son estables por ley, pero si cambia la norma o una fuente oficial, hay que revisar la tabla antes de actualizarla.",
        "url": "https://www.bcn.cl/leychile/navegar?idNorma=6368",
        "archivo_json": "tasas/historico/manual/zonas_extremas.json",
        "palabras_clave": ["asignación de zona", "zona", "porcentaje", "tarapacá", "aysén", "magallanes", "chiloé", "palena"],
    },
    {
        "indicador": "zona_extrema_modificacion_1",
        "nombre_humano": "Modificaciones normativa zona extrema",
        "descripcion": "Fuente complementaria entregada para revisar posibles cambios normativos vinculados a zona extrema.",
        "url": "https://www.bcn.cl/leychile/navegar?i=1203976",
        "archivo_json": "tasas/historico/manual/zonas_extremas.json",
        "palabras_clave": ["zona", "asignación", "porcentaje", "dl 889", "dl 249"],
    },
    {
        "indicador": "zona_extrema_modificacion_2",
        "nombre_humano": "Normativa relacionada zona extrema",
        "descripcion": "Fuente complementaria entregada para revisar posibles cambios normativos vinculados a zona extrema.",
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


def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram no configurado. No se envió aviso.")
        return
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
        timeout=20,
    )
    print("Telegram response:", response.status_code, response.text)
    response.raise_for_status()


def human_message(change):
    json_link = f"{GITHUB_BASE}/{change['archivo_json']}"
    lines = [
        "👋 Jonathan, encontré algo que conviene revisar en Sueldo Real Chile.",
        "",
        f"📌 Dato: {change['nombre_humano']}",
        f"⚠️ Qué pasó: {change['mensaje']}",
        "",
        change["descripcion"],
        "",
        f"🔎 Fuente para revisar:\n{change['url']}",
        "",
        f"🛠️ Archivo que se actualizaría si confirmas el cambio:\n{json_link}",
        "",
        "No actualicé el valor automáticamente. Revísalo y, cuando tengamos el bot interactivo, podrás aprobar o rechazar desde Telegram.",
    ]
    if change.get("keywords"):
        resumen = ", ".join([f"{k}: {v}" for k, v in change["keywords"].items() if v])
        if resumen:
            lines.insert(6, f"🔤 Menciones detectadas: {resumen}")
            lines.insert(7, "")
    return "\n".join(lines)


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

    for source in SOURCES:
        key = source["indicador"] + "|" + source["url"]
        record = {
            "indicador": source["indicador"],
            "nombre": source["nombre_humano"],
            "url": source["url"],
            "estado": "ok",
        }
        try:
            html = get_content(source["url"])
            text = clean_text(html)
            new_hash = digest(text)
            counts = keyword_counts(text, source["palabras_clave"])
            old = stored.get(key)

            if old is None:
                baseline.append({
                    **source,
                    "mensaje": "dejé registrada esta fuente por primera vez para compararla en próximas revisiones.",
                    "hashNuevo": new_hash,
                    "keywords": counts,
                })
            elif old.get("hash") != new_hash:
                changes.append({
                    **source,
                    "mensaje": "la fuente oficial o de referencia cambió desde la última revisión. Podría ser un cambio real o una actualización menor de la página.",
                    "hashAnterior": old.get("hash"),
                    "hashNuevo": new_hash,
                    "keywords": counts,
                })
            else:
                old_counts = old.get("keywordCounts", {})
                for keyword, count in counts.items():
                    if count > old_counts.get(keyword, 0):
                        changes.append({
                            **source,
                            "mensaje": f"aumentaron las menciones de '{keyword}' en la fuente revisada. Conviene revisar si hubo cambio normativo o de criterio.",
                            "keyword": keyword,
                            "conteoAnterior": old_counts.get(keyword, 0),
                            "conteoNuevo": count,
                            "keywords": counts,
                        })
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
            changes.append({
                **source,
                "mensaje": f"no pude revisar esta fuente automáticamente ({exc}). Conviene abrir el link y verificar manualmente.",
                "keywords": {},
            })

        reviewed.append(record)

    hashes["fechaActualizacion"] = today
    write_json(HASHES_PATH, hashes)

    report = {
        "fechaRevision": today,
        "estado": "revision_requerida" if changes else "sin_cambios",
        "fuentesRevisadas": reviewed,
        "baselineCreados": baseline,
        "cambiosDetectados": changes,
    }
    report_path = REPORTES_DIR / f"manual_indicators_{today}.json"
    if changes:
        write_json(report_path, report)
        for change in changes:
            send_telegram(human_message(change))
        print(f"Revisión requerida. Reporte: {report_path.relative_to(ROOT)}")
    else:
        print("Monitoreo de indicadores manuales sin cambios relevantes.")
        if baseline:
            print(f"Baseline creado para {len(baseline)} fuentes; no se envía Telegram por baseline.")

    print(f"Fuentes revisadas: {len(reviewed)}")
    print(f"Cambios detectados: {len(changes)}")


if __name__ == "__main__":
    main()
