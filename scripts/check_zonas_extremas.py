import hashlib
import json
import os
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
MANUAL_DIR = ROOT / "tasas" / "historico" / "manual"
REPORTES_DIR = ROOT / "tasas" / "historico" / "reportes"
ZONAS_EXTREMAS_PATH = MANUAL_DIR / "zonas_extremas.json"
HASHES_PATH = MANUAL_DIR / "zonas_extremas_hashes.json"

FUENTES_BASE = [
    {
        "nombre": "SII Pregunta frecuente DL 889",
        "url": "https://www.sii.cl/preguntas_frecuentes/declaracion_renta/001_140_1533.htm",
        "tipo": "html",
    },
    {
        "nombre": "SII valores y fechas renta 2026",
        "url": "https://www.sii.cl/valores_y_fechas/renta/2026/personas_naturales.html",
        "tipo": "html",
    },
    {
        "nombre": "SII Circular N°2 de 2026",
        "url": "https://www.sii.cl/normativa_legislacion/circulares/2026/circu2.pdf",
        "tipo": "pdf",
    },
    {
        "nombre": "SII DDJJ 1887 zonas extremas",
        "url": "https://www.sii.cl/preguntas_frecuentes/ddjj/001_135_0476.htm",
        "tipo": "html",
    },
]

KEYWORDS = {
    "DL 889": ["dl 889", "d.l. 889", "d.l. n 889", "decreto ley 889"],
    "zona extrema": ["zona extrema", "zonas extremas"],
    "sueldo grado 1-A": ["sueldo grado 1-a", "sueldo grado 1 a"],
    "asignacion de zona": ["asignacion de zona", "asignación de zona"],
    "articulo 13": ["articulo 13", "artículo 13"],
    "Provincia de Chiloe": ["provincia de chiloe", "provincia de chiloé"],
    "Provincia de Palena": ["provincia de palena"],
    "Regiones I XI XII XV": [" i, xi", "xi , xii", "xii y xv", "xv region", "xv región"],
}

MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

ANIO_MINIMO_APP = 2026


def chile_today():
    return datetime.now(ZoneInfo("America/Santiago")).date()


def fuentes_a_revisar(hoy=None):
    """Fuentes fijas + páginas SII de renta relevantes para detectar sueldo grado 1-A."""
    hoy = hoy or chile_today()
    fuentes = list(FUENTES_BASE)
    for anio_tributario in sorted({hoy.year, hoy.year + 1}):
        url = f"https://www.sii.cl/valores_y_fechas/renta/{anio_tributario}/personas_naturales.html"
        if any(f["url"] == url for f in fuentes):
            continue
        fuentes.append({
            "nombre": f"SII valores y fechas renta {anio_tributario}",
            "url": url,
            "tipo": "html",
            "opcional": True,
            "uso": "Detección automática de sueldo grado 1-A cuando SII publique nuevo año tributario",
        })
    return fuentes


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


def normalizar_texto(texto):
    texto = texto or ""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = texto.lower()
    texto = texto.replace("º", "o")
    texto = texto.replace("ª", "a")
    return re.sub(r"\s+", " ", texto).strip()


def hash_texto(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()


def get_content(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
        "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
        "Referer": "https://www.sii.cl/",
    }
    response = requests.get(url, headers=headers, timeout=45)
    response.raise_for_status()
    return response.content, response.headers.get("content-type", "")


def extraer_texto_html(content):
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def extraer_texto_fuente(content, content_type, tipo):
    if tipo == "pdf" or "pdf" in content_type.lower():
        return content.decode("latin-1", errors="ignore")
    return extraer_texto_html(content)


def contar_keywords(texto_normalizado):
    counts = {}
    for etiqueta, patrones in KEYWORDS.items():
        total = 0
        for patron in patrones:
            total += texto_normalizado.count(normalizar_texto(patron))
        counts[etiqueta] = total
    return counts


def monto_a_int(valor):
    limpio = re.sub(r"[^0-9]", "", valor or "")
    return int(limpio) if limpio else None


def ultimo_dia_mes(anio, mes):
    if mes == 12:
        return 31
    siguiente = date(anio, mes + 1, 1)
    return (siguiente.toordinal() - date(anio, mes, 1).toordinal())


def extraer_anio_tributario_desde_url(url):
    match = re.search(r"/renta/(\d{4})/personas_naturales\.html", url or "")
    return int(match.group(1)) if match else None


def extraer_anio_tabla_sueldo(texto_norm, fuente):
    patrones = [
        r"meses\s+ano\s+(\d{4})",
        r"meses\s+del\s+ano\s+(\d{4})",
        r"ano\s+(\d{4})\s+sueldo\s+grado",
    ]
    for patron in patrones:
        match = re.search(patron, texto_norm)
        if match:
            return int(match.group(1))

    anio_tributario = extraer_anio_tributario_desde_url(fuente.get("url"))
    if anio_tributario:
        return anio_tributario - 1
    return None


def extraer_seccion_sueldo_grado(texto_norm):
    start = texto_norm.find("sueldo grado")
    if start < 0:
        return ""
    seccion = texto_norm[start:start + 5000]
    cortes = [
        "porcentajes que los compradores",
        "porcentajes que los mineros",
        "tabla de calculo",
    ]
    for corte in cortes:
        idx = seccion.find(corte, 600)
        if idx > 0:
            seccion = seccion[:idx]
    return seccion


def extraer_sueldo_grado_1a(texto, fuente):
    texto_norm = normalizar_texto(texto)
    if "sueldo grado 1-a" not in texto_norm and "sueldo grado 1 a" not in texto_norm:
        return []

    anio = extraer_anio_tabla_sueldo(texto_norm, fuente)
    if anio is None:
        return []

    seccion = extraer_seccion_sueldo_grado(texto_norm)
    if not seccion:
        return []

    candidatos = []
    for mes_nombre, mes_numero in MESES.items():
        patron = rf"\b{mes_nombre}\b\s+(?:\$\s*)?([0-9]{{1,3}}(?:\.[0-9]{{3}})+|[0-9]{{5,}})"
        match = re.search(patron, seccion)
        if not match:
            continue
        valor = monto_a_int(match.group(1))
        if not valor or valor <= 0:
            continue
        candidatos.append({
            "desde": f"{anio}-{mes_numero:02d}-01",
            "hasta": f"{anio}-{mes_numero:02d}-{ultimo_dia_mes(anio, mes_numero):02d}",
            "valor": valor,
            "fuente": fuente["nombre"],
            "url": fuente["url"],
            "anioTabla": anio,
            "anioTributario": extraer_anio_tributario_desde_url(fuente.get("url")),
            "confianza": "alta" if anio >= ANIO_MINIMO_APP else "historico_no_usado_app",
        })

    return candidatos


def sueldo_existente(zonas_data, candidato):
    for item in zonas_data.get("sueldoGrado1A", []):
        if item.get("desde") == candidato["desde"] and item.get("hasta") == candidato["hasta"]:
            return True
        if item.get("valor") == candidato["valor"] and item.get("desde") == candidato["desde"]:
            return True
    return False


def agregar_sueldos_pendientes(zonas_data, candidatos):
    agregados = []
    sueldo_grado = zonas_data.setdefault("sueldoGrado1A", [])
    for candidato in candidatos:
        if candidato.get("confianza") != "alta":
            continue
        if sueldo_existente(zonas_data, candidato):
            continue
        nuevo = {
            "desde": candidato["desde"],
            "hasta": candidato["hasta"],
            "valor": candidato["valor"],
            "estado": "manual_pendiente",
            "fuente": candidato["fuente"],
            "url": candidato["url"],
            "nota": "Detectado automáticamente por monitoreo DL 889 desde SII. Requiere validación humana antes de marcar manual_validado.",
        }
        sueldo_grado.append(nuevo)
        agregados.append(nuevo)
    if agregados:
        sueldo_grado.sort(key=lambda item: (item.get("desde", ""), item.get("valor", 0)))
    return agregados


def pendientes_zonas(zonas_data):
    pendientes = []
    for zona in zonas_data.get("zonas", []):
        if zona.get("porcentaje") is None:
            pendientes.append({
                "nombre": zona.get("nombre"),
                "estado": zona.get("estado"),
                "motivo": "porcentaje_null",
            })
    return pendientes


def enviar_telegram(mensaje):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram no configurado. No se envió alerta.")
        return
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": mensaje},
            timeout=20,
        )
        print("Telegram response:", response.status_code, response.text)
        response.raise_for_status()
    except Exception as exc:
        print(f"No se pudo enviar alerta Telegram: {exc}")


def mensaje_alerta(reporte):
    cambios = reporte.get("cambiosDetectados", [])
    primer_cambio = cambios[0] if cambios else {}
    fuente = primer_cambio.get("fuente") or "varias fuentes"
    motivo = primer_cambio.get("motivo") or "hay datos pendientes de validación"
    return (
        "⚠️ Sueldo Real Chile - revisar zona extrema DL 889\n"
        f"Fuente modificada: {fuente}\n"
        f"Estado: {reporte['estado']}\n"
        f"Motivo: {motivo}\n"
        "Acción sugerida: revisar zonas_extremas.json antes de validar nuevos datos"
    )


def main():
    hoy = chile_today().isoformat()
    REPORTES_DIR.mkdir(parents=True, exist_ok=True)
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)

    zonas_data = read_json(ZONAS_EXTREMAS_PATH, {}) or {}
    hashes_data = read_json(HASHES_PATH, {
        "descripcion": "Hashes de monitoreo de fuentes oficiales para rebaja zona extrema DL 889",
        "fechaCreacion": hoy,
        "fechaActualizacion": None,
        "fuentes": [],
    }) or {}

    hashes_por_url = {item.get("url"): item for item in hashes_data.get("fuentes", [])}
    fuentes_revisadas = []
    cambios = []
    baseline_creados = []
    candidatos_sueldo = []

    for fuente in fuentes_a_revisar():
        registro = {
            "nombre": fuente["nombre"],
            "url": fuente["url"],
            "estado": "ok",
        }
        try:
            content, content_type = get_content(fuente["url"])
            texto = extraer_texto_fuente(content, content_type, fuente["tipo"])
            texto_norm = normalizar_texto(texto)
            contenido_hash = hash_bytes(content) if fuente["tipo"] == "pdf" else hash_texto(texto_norm)
            keyword_counts = contar_keywords(texto_norm)
            candidatos = extraer_sueldo_grado_1a(texto, fuente)
            candidatos_sueldo.extend(candidatos)

            anterior = hashes_por_url.get(fuente["url"])
            if anterior is None:
                baseline_creados.append({
                    "fuente": fuente["nombre"],
                    "url": fuente["url"],
                    "motivo": "baseline_creado",
                    "detalle": "Primera revisión registrada para esta fuente.",
                })
            elif anterior.get("ultimoHash") != contenido_hash:
                cambios.append({
                    "fuente": fuente["nombre"],
                    "url": fuente["url"],
                    "motivo": "cambio_hash",
                    "hashAnterior": anterior.get("ultimoHash"),
                    "hashNuevo": contenido_hash,
                })

            if anterior:
                prev_counts = anterior.get("keywordCounts", {})
                for etiqueta, count in keyword_counts.items():
                    if count > prev_counts.get(etiqueta, 0):
                        cambios.append({
                            "fuente": fuente["nombre"],
                            "url": fuente["url"],
                            "motivo": "nueva_mencion_keyword",
                            "keyword": etiqueta,
                            "conteoAnterior": prev_counts.get(etiqueta, 0),
                            "conteoNuevo": count,
                        })

            registro.update({
                "hash": contenido_hash,
                "keywordCounts": keyword_counts,
                "sueldoGrado1ADetectado": candidatos,
            })
            hashes_por_url[fuente["url"]] = {
                "nombre": fuente["nombre"],
                "url": fuente["url"],
                "ultimoHash": contenido_hash,
                "fechaRevision": hoy,
                "keywordCounts": keyword_counts,
            }
        except Exception as exc:
            registro.update({"estado": "error", "error": str(exc)})
            if not fuente.get("opcional"):
                cambios.append({
                    "fuente": fuente["nombre"],
                    "url": fuente["url"],
                    "motivo": "fuente_no_disponible",
                    "error": str(exc),
                })

        fuentes_revisadas.append(registro)

    nuevos_sueldos = agregar_sueldos_pendientes(zonas_data, candidatos_sueldo)
    for item in nuevos_sueldos:
        cambios.append({
            "fuente": item.get("fuente"),
            "url": item.get("url"),
            "motivo": "nuevo_sueldo_grado_1a_pendiente_validacion",
            "valor": item.get("valor"),
            "desde": item.get("desde"),
            "hasta": item.get("hasta"),
        })

    pendientes = pendientes_zonas(zonas_data)
    pendientes_count = len(pendientes)
    pendientes_prev_count = hashes_data.get("zonasConPorcentajeNullCount")
    if pendientes and pendientes_prev_count != pendientes_count:
        cambios.append({
            "fuente": "zonas_extremas.json",
            "motivo": "zonas_con_porcentaje_pendiente",
            "cantidad": pendientes_count,
            "cantidadAnterior": pendientes_prev_count,
            "zonas": pendientes,
        })

    hashes_data["fechaActualizacion"] = hoy
    hashes_data["fuentes"] = [hashes_por_url[url] for url in sorted(hashes_por_url) if url]
    hashes_data["zonasConPorcentajeNullCount"] = pendientes_count
    write_json(HASHES_PATH, hashes_data)

    if nuevos_sueldos:
        write_json(ZONAS_EXTREMAS_PATH, zonas_data)

    estado = "revision_requerida" if cambios else "sin_cambios"
    reporte = {
        "fechaRevision": hoy,
        "estado": estado,
        "fuentesRevisadas": fuentes_revisadas,
        "baselineCreados": baseline_creados,
        "cambiosDetectados": cambios,
        "sueldosGrado1ADetectados": candidatos_sueldo,
        "datosPendientes": {
            "zonasConPorcentajeNull": pendientes,
            "sueldosAgregadosPendientesValidacion": nuevos_sueldos,
        },
        "accionSugerida": "Revisar manualmente antes de actualizar zonas_extremas.json",
    }

    if estado != "sin_cambios":
        reporte_path = REPORTES_DIR / f"zonas_extremas_{hoy}.json"
        write_json(reporte_path, reporte)
        enviar_telegram(mensaje_alerta(reporte))
        print(f"Revisión requerida. Reporte: {reporte_path.relative_to(ROOT)}")
    else:
        print("Monitoreo DL 889 sin cambios relevantes.")
        if baseline_creados:
            print(f"Baseline creado/actualizado para {len(baseline_creados)} fuentes; no se envía alerta por baseline.")

    print(f"Fuentes revisadas: {len(fuentes_revisadas)}")
    print(f"Cambios detectados: {len(cambios)}")
    print(f"Zonas con porcentaje pendiente: {pendientes_count}")


if __name__ == "__main__":
    main()
