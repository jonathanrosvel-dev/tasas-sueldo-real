import argparse
import calendar
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
TASAS_JSON = ROOT / "tasas.json"
HISTORICO_DIR = ROOT / "tasas" / "historico"
PERIODOS_DIR = HISTORICO_DIR / "periodos"
UF_DIR = HISTORICO_DIR / "uf"
MANUAL_DIR = HISTORICO_DIR / "manual"
INDEX_PATH = HISTORICO_DIR / "index.json"

AFP_URL = "https://www.spensiones.cl/portal/institucional/594/w3-article-2810.html"
FUENTE_TOPES_MANUAL = "tasas/historico/manual/topes.json"
FUENTE_LABORAL_MANUAL = "tasas/historico/manual/laboral.json"
FUENTE_CESANTIA_MANUAL = "tasas/historico/manual/cesantia.json"
FUENTE_AFP_MANUAL = "tasas/historico/manual/afp_comisiones.json"

MESES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}
MESES_CORTOS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12
}
MESES_INV = {v.lower(): k for k, v in MESES.items()}

AFP_FALLBACK = [
    {"nombre": "Capital", "comision": 0.0144},
    {"nombre": "Cuprum", "comision": 0.0144},
    {"nombre": "Habitat", "comision": 0.0127},
    {"nombre": "Modelo", "comision": 0.0058},
    {"nombre": "PlanVital", "comision": 0.0116},
    {"nombre": "Provida", "comision": 0.0145},
    {"nombre": "Uno", "comision": 0.0046}
]

TRAMOS_UTM_FALLBACK = [
    {"desdeUtm": 0, "hastaUtm": 13.5, "factor": 0.0, "rebajaUtm": 0.0},
    {"desdeUtm": 13.5, "hastaUtm": 30, "factor": 0.04, "rebajaUtm": 0.54},
    {"desdeUtm": 30, "hastaUtm": 50, "factor": 0.08, "rebajaUtm": 1.74},
    {"desdeUtm": 50, "hastaUtm": 70, "factor": 0.135, "rebajaUtm": 4.49},
    {"desdeUtm": 70, "hastaUtm": 90, "factor": 0.23, "rebajaUtm": 11.14},
    {"desdeUtm": 90, "hastaUtm": 120, "factor": 0.304, "rebajaUtm": 17.8},
    {"desdeUtm": 120, "hastaUtm": 310, "factor": 0.35, "rebajaUtm": 23.32},
    {"desdeUtm": 310, "hastaUtm": None, "factor": 0.40, "rebajaUtm": 38.82}
]

UF_MIN = 30000
UF_MAX = 60000
UTM_MIN = 50000
UTM_MAX = 100000

OK_STATES = {"online", "online_sii", "online_mindicador", "ok", "validado", "manual_validado"}
INCOMPLETE_STATES = {"manual", "manual_pendiente", "respaldo"}
REQUIRED_STATES = {"manual_requerido", "faltante", "error", "invalido"}
ESSENTIAL_STATUS_KEYS = (
    "uf",
    "utm",
    "impuestoUnico",
    "afp",
    "topes",
    "imm",
    "salud",
    "cesantia",
)
ALERT_STATES = {"manual_pendiente", "respaldo", "manual_requerido", "faltante", "error", "invalido"}
UF_VALUE_RE = r"\d{1,3}(?:\.\d{3})*,\d{2}"

DEFAULT_MANUAL_FILES = {
    "laboral.json": {
        "vigencias": [
            {
                "desde": "2026-01-01",
                "hasta": None,
                "imm": 539000,
                "fechaVigencia": "2026-01-01",
                "estado": "manual_validado",
                "fuente": "manual",
                "nota": "IMM ingresado manualmente y validado para pruebas beta"
            }
        ]
    },
    "cesantia.json": {
        "vigencias": [
            {
                "desde": "2026-01-01",
                "hasta": None,
                "trabajadorIndefinido": 0.006,
                "trabajadorPlazoFijo": 0.0,
                "estado": "manual_validado",
                "fuente": "manual",
                "nota": "Tasas ingresadas manualmente y validadas para pruebas beta"
            }
        ]
    },
    "topes.json": {
        "vigencias": [
            {
                "desde": "2026-01-01",
                "hasta": None,
                "afpSaludUf": 90.0,
                "cesantiaUf": 135.2,
                "estado": "manual_validado",
                "fuente": "manual",
                "nota": "Dato ingresado manualmente y validado para pruebas beta"
            }
        ]
    },
    "afp_comisiones.json": {
        "vigencias": [
            {
                "desde": "2026-01-01",
                "hasta": None,
                "estado": "manual_validado",
                "fuente": "manual",
                "nota": "Dato ingresado manualmente y validado para pruebas beta",
                "afp": AFP_FALLBACK
            }
        ]
    }
}


def chile_today():
    return datetime.now(ZoneInfo("America/Santiago")).date()


def sii_uf_url(anio):
    return f"https://www.sii.cl/valores_y_fechas/uf/uf{anio}.htm"


def sii_utm_url(anio):
    return f"https://www.sii.cl/valores_y_fechas/utm/utm{anio}.htm"


def sii_impuesto_url(anio):
    return f"https://www.sii.cl/valores_y_fechas/impuesto_2da_categoria/impuesto{anio}.htm"


def ensure_dirs():
    HISTORICO_DIR.mkdir(parents=True, exist_ok=True)
    PERIODOS_DIR.mkdir(parents=True, exist_ok=True)
    UF_DIR.mkdir(parents=True, exist_ok=True)
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)


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


def ensure_manual_files():
    ensure_dirs()
    for filename, content in DEFAULT_MANUAL_FILES.items():
        path = MANUAL_DIR / filename
        if not path.exists():
            write_json(path, content)


def cargar_json_actual():
    return read_json(TASAS_JSON, {}) or {}


def normalizar(texto):
    return re.sub(r"\s+", " ", texto or "").strip()


def limpiar_decimal_chileno(texto):
    texto = texto or ""
    texto = texto.replace("$", "").replace(" ", "")
    texto = texto.replace(".", "").replace(",", ".")
    texto = re.sub(r"[^0-9.\-]", "", texto)
    if texto in ("", "-", "--"):
        return None
    return float(texto)


def limpiar_entero_chileno(texto):
    limpio = re.sub(r"[^\d]", "", texto or "")
    return int(limpio) if limpio else None


def limpiar_monto_chileno(texto):
    return limpiar_decimal_chileno(texto)


def limpiar_factor(texto):
    texto = (texto or "").replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", texto)
    return float(match.group(0)) if match else 0.0


def porcentaje_a_decimal(texto):
    texto = (texto or "").replace("%", "").replace(",", ".").strip()
    return round(float(texto) / 100, 6)


def validar_uf(uf):
    return uf is not None and UF_MIN <= float(uf) <= UF_MAX


def validar_utm(utm):
    return utm is not None and UTM_MIN <= float(utm) <= UTM_MAX


def get_html(url, timeout=30, referer=None):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        headers["Referer"] = referer
    r = requests.get(url, timeout=timeout, headers=headers)
    r.raise_for_status()
    return r.text


def parse_period(periodo):
    match = re.fullmatch(r"(\d{4})-(\d{2})", periodo)
    if not match:
        raise ValueError(f"Periodo invalido: {periodo}. Usa YYYY-MM.")
    return int(match.group(1)), int(match.group(2))


def period_key(anio, mes):
    return f"{anio:04d}-{mes:02d}"


def period_path(anio, mes):
    return PERIODOS_DIR / f"{anio:04d}" / f"{period_key(anio, mes)}.json"


def uf_path(anio):
    return UF_DIR / f"uf_diaria_{anio}.json"


def last_day(anio, mes):
    return calendar.monthrange(anio, mes)[1]


def month_iter(start_period, end_period):
    anio, mes = parse_period(start_period)
    end_anio, end_mes = parse_period(end_period)
    while (anio, mes) <= (end_anio, end_mes):
        yield anio, mes
        mes += 1
        if mes == 13:
            mes = 1
            anio += 1


def normalizar_fecha(valor, fin_periodo=False):
    if valor is None:
        return None
    if isinstance(valor, date):
        return valor
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        return date.fromisoformat(valor)
    if re.fullmatch(r"\d{4}-\d{2}", valor):
        anio, mes = parse_period(valor)
        dia = last_day(anio, mes) if fin_periodo else 1
        return date(anio, mes, dia)
    raise ValueError(f"Fecha o periodo invalido: {valor}")


def vigencias_de(data, *legacy_keys):
    if data.get("vigencias"):
        return data["vigencias"]
    for key in legacy_keys:
        if data.get(key):
            return data[key]
    return []


def estado_manual(item):
    estado = item.get("estado")
    if estado:
        return estado
    fuente = item.get("fuente", "")
    if "respaldo" in fuente:
        return "respaldo"
    return "manual_pendiente"


def resolve_vigencia(items, fecha_referencia):
    fecha_referencia = normalizar_fecha(fecha_referencia)
    candidatos = []
    for item in items:
        desde = normalizar_fecha(item.get("desde", "0000-01-01"))
        hasta = normalizar_fecha(item.get("hasta"), fin_periodo=True)
        if desde <= fecha_referencia and (hasta is None or fecha_referencia <= hasta):
            candidatos.append(item)
    if not candidatos:
        raise RuntimeError(f"No hay vigencia manual para {fecha_referencia.isoformat()}")
    return sorted(candidatos, key=lambda x: normalizar_fecha(x.get("desde", "0000-01-01")))[-1]


def manual_laboral(fecha_referencia):
    data = read_json(MANUAL_DIR / "laboral.json", DEFAULT_MANUAL_FILES["laboral.json"])
    item = resolve_vigencia(vigencias_de(data, "imm"), fecha_referencia)
    valor = item.get("imm", item.get("valor"))
    return (
        {"imm": valor, "fechaImm": item.get("fechaVigencia", item.get("desde"))},
        item.get("fuente", FUENTE_LABORAL_MANUAL),
        estado_manual(item)
    )


def manual_cesantia(fecha_referencia):
    data = read_json(MANUAL_DIR / "cesantia.json", DEFAULT_MANUAL_FILES["cesantia.json"])
    item = resolve_vigencia(vigencias_de(data, "cesantia"), fecha_referencia)
    return (
        {
            "trabajadorIndefinido": item["trabajadorIndefinido"],
            "trabajadorPlazoFijo": item.get("trabajadorPlazoFijo", 0.0)
        },
        item.get("fuente", FUENTE_CESANTIA_MANUAL),
        estado_manual(item)
    )


def manual_topes(fecha_referencia):
    data = read_json(MANUAL_DIR / "topes.json", DEFAULT_MANUAL_FILES["topes.json"])
    item = resolve_vigencia(vigencias_de(data, "topes"), fecha_referencia)
    return (
        {
            "afpSaludUf": item["afpSaludUf"],
            "cesantiaUf": item["cesantiaUf"]
        },
        item.get("fuente", FUENTE_TOPES_MANUAL),
        estado_manual(item)
    )


def manual_afp(fecha_referencia):
    data = read_json(MANUAL_DIR / "afp_comisiones.json", DEFAULT_MANUAL_FILES["afp_comisiones.json"])
    item = resolve_vigencia(vigencias_de(data, "afp"), fecha_referencia)
    return (
        item.get("afp", item.get("comisiones", AFP_FALLBACK)),
        item.get("fuente", FUENTE_AFP_MANUAL),
        estado_manual(item)
    )


def agregar_uf_valor(valores, anio, mes, dia, valor_texto):
    if dia < 1 or dia > last_day(anio, mes):
        return
    valor = limpiar_decimal_chileno(valor_texto)
    if validar_uf(valor):
        valores[date(anio, mes, dia).isoformat()] = round(float(valor), 2)


def extraer_pares_dia_uf_desde_texto(texto, anio, mes, valores):
    patron = rf"(?<![\d.,])(\d{{1,2}})\s+({UF_VALUE_RE})(?![\d.,])"
    for dia_texto, valor_texto in re.findall(patron, texto):
        agregar_uf_valor(valores, anio, mes, int(dia_texto), valor_texto)


def parsear_uf_tablas_por_mes(soup, anio):
    valores = {}
    for titulo in soup.find_all(["h1", "h2", "h3", "h4"]):
        mes_nombre = normalizar(titulo.get_text()).lower()
        if mes_nombre not in MESES_INV:
            continue
        mes = MESES_INV[mes_nombre]
        tabla = titulo.find_next("table")
        if not tabla:
            continue
        for fila in tabla.find_all("tr"):
            celdas = [normalizar(c.get_text(" ", strip=True)) for c in fila.find_all(["td", "th"])]
            extraer_pares_dia_uf_desde_texto(" ".join(celdas), anio, mes, valores)
    return valores


def parsear_uf_texto_por_mes(soup, anio):
    valores = {}
    mes_actual = None
    for raw_line in soup.get_text("\n").splitlines():
        line = normalizar(raw_line)
        lower = line.lower()
        if lower in MESES_INV:
            mes_actual = MESES_INV[lower]
            continue
        if lower.startswith("dia ") or lower.startswith("día "):
            mes_actual = None
            continue
        if mes_actual:
            extraer_pares_dia_uf_desde_texto(line, anio, mes_actual, valores)
    return valores


def parsear_uf_tabla_resumen(soup, anio):
    valores = {}
    for tabla in soup.find_all("table"):
        filas = tabla.find_all("tr")
        encabezado_meses = []
        for fila in filas:
            celdas = [normalizar(c.get_text(" ", strip=True)).lower() for c in fila.find_all(["td", "th"])]
            if celdas and (celdas[0] in ("dia", "día")):
                encabezado_meses = [MESES_CORTOS.get(c[:3]) for c in celdas[1:]]
                continue
            if not encabezado_meses or not celdas or not celdas[0].isdigit():
                continue
            dia = int(celdas[0])
            for idx, valor_texto in enumerate(celdas[1:]):
                if idx >= len(encabezado_meses):
                    break
                mes = encabezado_meses[idx]
                if mes:
                    agregar_uf_valor(valores, anio, mes, dia, valor_texto)
    return valores


def obtener_uf_diaria_sii(anio):
    html = get_html(sii_uf_url(anio), timeout=45, referer="https://www.sii.cl/valores_y_fechas/")
    soup = BeautifulSoup(html, "html.parser")
    valores = {}
    for extractor in (parsear_uf_tablas_por_mes, parsear_uf_texto_por_mes, parsear_uf_tabla_resumen):
        try:
            valores.update(extractor(soup, anio))
        except Exception as e:
            print(f"Extractor UF {extractor.__name__} fallo: {e}")
    if not valores:
        raise RuntimeError(f"No se encontraron valores UF para {anio} en SII")
    return dict(sorted(valores.items()))


def obtener_uf_mindicador():
    response = requests.get("https://mindicador.cl/api/uf", timeout=30)
    response.raise_for_status()
    valor = response.json()["serie"][0]["valor"]
    if validar_uf(valor):
        return float(valor)
    raise RuntimeError(f"UF invalida desde mindicador.cl: {valor}")


def cargar_o_actualizar_uf_anual(anio, hasta=None):
    hasta = hasta or chile_today()
    hoy = chile_today()
    existente = read_json(uf_path(anio), {"anio": anio, "fuente": "SII", "valores": {}}) or {}
    valores = dict(existente.get("valores", {}))
    estado = "online_sii"

    try:
        valores_sii = obtener_uf_diaria_sii(anio)
        agregados = 0
        for fecha, valor in valores_sii.items():
            fecha_dt = date.fromisoformat(fecha)
            if fecha_dt <= hasta:
                valores[fecha] = valor
                agregados += 1
        if agregados == 0:
            raise RuntimeError(f"SII no entrego valores hasta {hasta.isoformat()}")
    except Exception as e:
        print(f"No se pudo actualizar UF diaria desde SII: {e}")
        estado = "respaldo" if valores else "manual_requerido"
        if anio == hoy.year and hoy <= hasta and hoy.isoformat() not in valores:
            try:
                valores[hoy.isoformat()] = round(obtener_uf_mindicador(), 2)
                estado = "respaldo"
            except Exception as fallback_error:
                print(f"No se pudo agregar UF actual como respaldo parcial: {fallback_error}")
                estado = "respaldo" if valores else "manual_requerido"

    data = {
        "anio": anio,
        "fuente": "SII",
        "fechaActualizacion": chile_today().isoformat(),
        "valores": dict(sorted(valores.items()))
    }
    write_json(uf_path(anio), data)
    return data, estado


def obtener_utm_actual(anio, mes):
    html = get_html(sii_utm_url(anio), timeout=30, referer="https://www.sii.cl/valores_y_fechas/")
    soup = BeautifulSoup(html, "html.parser")
    texto = soup.get_text(" ", strip=True)
    patron = rf"{MESES[mes]}\s+\$?\s*([\d\.]+)"
    match = re.search(patron, texto, re.IGNORECASE)
    if not match:
        raise RuntimeError(f"No se pudo encontrar UTM para {MESES[mes]} {anio}")
    return limpiar_entero_chileno(match.group(1))


def obtener_utm_blindada(anio, mes, actual):
    try:
        utm = obtener_utm_actual(anio, mes)
        if validar_utm(utm):
            return utm, "online", sii_utm_url(anio)
    except Exception as e:
        print(f"UTM SII fallo: {e}")

    utm_respaldo = actual.get("utm")
    if validar_utm(utm_respaldo):
        return utm_respaldo, "respaldo", "respaldo_local"
    raise RuntimeError("No hay UTM valida disponible")


def buscar_tabla_impuesto_mes(soup, mes_nombre, anio):
    titulo_buscado = f"{mes_nombre} {anio}".lower()
    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        texto = normalizar(tag.get_text()).lower()
        if titulo_buscado in texto:
            tabla = tag.find_next("table")
            if tabla:
                return tabla
    if titulo_buscado not in soup.get_text(" ", strip=True).lower():
        raise RuntimeError(f"No se encontro el titulo {mes_nombre} {anio}")
    tabla = soup.find("table")
    if not tabla:
        raise RuntimeError("No se encontro tabla de impuesto")
    return tabla


def obtener_tramos_impuesto_actual(anio, mes, utm):
    html = get_html(sii_impuesto_url(anio), timeout=30, referer="https://www.sii.cl/valores_y_fechas/")
    soup = BeautifulSoup(html, "html.parser")
    tabla = buscar_tabla_impuesto_mes(soup, MESES[mes], anio)
    filas = tabla.find_all("tr")
    tramos = []
    dentro_mensual = False

    for fila in filas:
        celdas = [normalizar(c.get_text(" ", strip=True)) for c in fila.find_all(["td", "th"])]
        if not celdas:
            continue
        fila_txt = " ".join(celdas).upper()
        if "MENSUAL" in fila_txt:
            dentro_mensual = True
        if dentro_mensual and "QUINCENAL" in fila_txt:
            break
        if not dentro_mensual:
            continue

        valores_monto = [c for c in celdas if "$" in c or "MÁS" in c.upper() or "MAS" in c.upper() or "--" in c]
        if len(valores_monto) < 2:
            continue

        factor = 0.0
        for c in celdas:
            if re.fullmatch(r"\d+(?:,\d+)?", c):
                factor = limpiar_factor(c)
                break

        desde_texto = valores_monto[0]
        hasta_texto = valores_monto[1]
        desde_pesos = limpiar_monto_chileno(desde_texto) or 0.0
        hasta_pesos = None if "MÁS" in hasta_texto.upper() or "MAS" in hasta_texto.upper() else limpiar_monto_chileno(hasta_texto)

        rebaja_pesos = 0.0
        for c in celdas:
            if "$" in c and c not in (desde_texto, hasta_texto):
                posible = limpiar_monto_chileno(c)
                if posible is not None:
                    rebaja_pesos = posible
                    break

        tramos.append({
            "desdeUtm": round(desde_pesos / utm, 6),
            "hastaUtm": None if hasta_pesos is None else round(hasta_pesos / utm, 6),
            "factor": factor,
            "rebajaUtm": round(rebaja_pesos / utm, 6)
        })

    if len(tramos) == 7:
        tramos.insert(0, {"desdeUtm": 0, "hastaUtm": 13.5, "factor": 0.0, "rebajaUtm": 0.0})
    if len(tramos) < 7:
        raise RuntimeError(f"Se extrajeron muy pocos tramos ({len(tramos)})")

    tramos = tramos[:8]
    tramos[0] = {"desdeUtm": 0, "hastaUtm": 13.5, "factor": 0.0, "rebajaUtm": 0.0}
    tramos[-1]["hastaUtm"] = None
    return tramos


def obtener_afp_actuales(afp_respaldo):
    try:
        html = None
        for intento in range(3):
            try:
                html = get_html(AFP_URL, timeout=60, referer="https://www.spensiones.cl/")
                break
            except Exception as e:
                print(f"Intento AFP {intento + 1} fallo: {e}")
        if html is None:
            raise RuntimeError("No se pudo conectar con la fuente AFP despues de 3 intentos")

        soup = BeautifulSoup(html, "html.parser")
        texto = normalizar(soup.get_text(" ", strip=True))
        aliases = {
            "Capital": ["Capital"],
            "Cuprum": ["Cuprum"],
            "Habitat": ["Habitat", "Hábitat"],
            "Modelo": ["Modelo"],
            "PlanVital": ["PlanVital", "Planvital", "Plan Vital"],
            "Provida": ["Provida", "ProVida", "Pro Vida"],
            "Uno": ["Uno", "UNO"]
        }
        resultado = []
        for nombre_final, nombres_posibles in aliases.items():
            encontrado = None
            for nombre_web in nombres_posibles:
                patrones = [
                    rf"AFP\s+{re.escape(nombre_web)}\s*[:\-]?\s*(\d{{1,2}}[,.]\d{{1,3}})\s*%",
                    rf"{re.escape(nombre_web)}\s*[:\-]?\s*(\d{{1,2}}[,.]\d{{1,3}})\s*%",
                    rf"{re.escape(nombre_web)}.*?(\d{{1,2}}[,.]\d{{1,3}})\s*%"
                ]
                for patron in patrones:
                    match = re.search(patron, texto, re.IGNORECASE)
                    if match:
                        encontrado = porcentaje_a_decimal(match.group(1))
                        break
                if encontrado is not None:
                    break
            if encontrado is None:
                raise RuntimeError(f"No se encontro comision AFP {nombre_final}")
            if encontrado < 0 or encontrado > 0.03:
                raise RuntimeError(f"Comision AFP fuera de rango para {nombre_final}: {encontrado}")
            resultado.append({"nombre": nombre_final, "comision": encontrado})

        if len(resultado) != 7:
            raise RuntimeError(f"Se esperaban 7 AFP, se encontraron {len(resultado)}")
        return resultado, "online", AFP_URL
    except Exception as e:
        print(f"No se pudieron actualizar AFP automaticamente: {e}")
        return afp_respaldo or AFP_FALLBACK, "respaldo", "respaldo_local"


def calcular_estado_periodo(current, estado_actualizacion):
    if current:
        return "vigente"
    estados = [estado_actualizacion.get(k) for k in ESSENTIAL_STATUS_KEYS]
    if any(not estado or estado in REQUIRED_STATES for estado in estados):
        return "manual_requerido"
    if any(estado in INCOMPLETE_STATES for estado in estados):
        return "incompleto"
    if all(estado in OK_STATES for estado in estados):
        return "cerrado"
    return "incompleto"


def build_snapshot(anio, mes, current=False, uf_values=None, fecha_calculo=None):
    ensure_manual_files()
    actual = cargar_json_actual()
    periodo = period_key(anio, mes)
    hoy = chile_today()
    cierre = date(anio, mes, last_day(anio, mes))
    fecha_referencia = fecha_calculo or (hoy if current else cierre)
    if fecha_referencia > hoy:
        fecha_referencia = hoy

    if uf_values is None:
        uf_data, estado_uf_file = cargar_o_actualizar_uf_anual(anio, hasta=fecha_referencia)
        uf_values = uf_data.get("valores", {})
    else:
        estado_uf_file = "online_sii"

    uf = uf_values.get(fecha_referencia.isoformat())
    estado_uf = estado_uf_file
    fuente_uf = sii_uf_url(anio) if uf and estado_uf_file == "online_sii" else "respaldo_local"

    if not uf:
        if current:
            try:
                uf = obtener_uf_mindicador()
                estado_uf = "online_mindicador"
                fuente_uf = "https://mindicador.cl/api/uf"
            except Exception as e:
                print(f"UF mindicador fallo: {e}")
        if not uf:
            uf = actual.get("uf")
            estado_uf = "respaldo" if validar_uf(uf) else "manual_requerido"
            fuente_uf = "respaldo_local"

    topes, fuente_topes, estado_topes = manual_topes(fecha_referencia)
    laboral, fuente_laboral, estado_laboral = manual_laboral(fecha_referencia)
    cesantia, fuente_cesantia, estado_cesantia = manual_cesantia(fecha_referencia)

    utm, estado_utm, fuente_utm = obtener_utm_blindada(anio, mes, actual)

    try:
        tramos = obtener_tramos_impuesto_actual(anio, mes, utm)
        estado_impuesto = "online"
        fuente_impuesto = sii_impuesto_url(anio)
    except Exception as e:
        print(f"No se pudo actualizar impuesto unico desde SII: {e}")
        tramos = actual.get("impuestoUnico", {}).get("tramos", TRAMOS_UTM_FALLBACK)
        estado_impuesto = "respaldo"
        fuente_impuesto = sii_impuesto_url(anio)

    if current:
        afp_respaldo = actual.get("afp", AFP_FALLBACK)
        afp, estado_afp, fuente_afp = obtener_afp_actuales(afp_respaldo)
    else:
        afp, fuente_afp, estado_afp = manual_afp(fecha_referencia)

    estado_actualizacion = {
        "utm": estado_utm,
        "uf": estado_uf,
        "impuestoUnico": estado_impuesto,
        "afp": estado_afp,
        "topes": estado_topes,
        "imm": estado_laboral,
        "salud": "ok",
        "cesantia": estado_cesantia
    }
    estado_periodo = calcular_estado_periodo(current, estado_actualizacion)

    return {
        "version": periodo if not current else hoy.isoformat(),
        "fechaActualizacion": hoy.isoformat() if current else fecha_referencia.isoformat(),
        "periodo": {"anio": anio, "mes": mes, "mesNombre": MESES[mes]},
        "utm": utm,
        "uf": round(float(uf), 2) if uf is not None else None,
        "ufFecha": fecha_referencia.isoformat(),
        "ufPolitica": "valor_dia_actual" if current else "fecha_referencia",
        "topes": topes,
        "laboral": laboral,
        "afp": afp,
        "salud": {"fonasa": 0.07},
        "cesantia": cesantia,
        "impuestoUnico": {"tramos": tramos},
        "estadoPeriodo": estado_periodo,
        "estadoActualizacion": estado_actualizacion,
        "fuentes": {
            "utm": fuente_utm,
            "uf": fuente_uf,
            "impuestoUnico": fuente_impuesto,
            "afp": fuente_afp if fuente_afp.startswith("http") else FUENTE_AFP_MANUAL,
            "topes": fuente_topes if fuente_topes.startswith("http") else FUENTE_TOPES_MANUAL,
            "imm": fuente_laboral if fuente_laboral.startswith("http") else FUENTE_LABORAL_MANUAL,
            "salud": "cotizacion_legal_7_por_ciento",
            "cesantia": fuente_cesantia if fuente_cesantia.startswith("http") else FUENTE_CESANTIA_MANUAL
        }
    }


def update_index():
    periodos = []
    for path in sorted(PERIODOS_DIR.glob("*/*.json")):
        data = read_json(path, {}) or {}
        periodo = path.stem
        estado = data.get("estadoPeriodo") or "manual_requerido"
        periodos.append({
            "periodo": periodo,
            "estado": estado,
            "path": str(path.relative_to(ROOT)).replace("\\", "/")
        })

    desde = periodos[0]["periodo"] if periodos else None
    hasta = periodos[-1]["periodo"] if periodos else None
    index = {
        "desde": desde,
        "hasta": hasta,
        "fechaActualizacion": chile_today().isoformat(),
        "periodos": periodos
    }
    write_json(INDEX_PATH, index)
    return index


def enviar_alerta_telegram(mensaje):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram no configurado. No se envio alerta.")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        response = requests.post(url, data={"chat_id": chat_id, "text": mensaje}, timeout=20)
        print("Telegram response:", response.status_code, response.text)
        response.raise_for_status()
    except Exception as e:
        print(f"No se pudo enviar alerta por Telegram: {e}")


def valor_usado(data, indicador):
    if indicador == "uf":
        return data.get("uf")
    if indicador == "utm":
        return data.get("utm")
    if indicador == "impuestoUnico":
        return "tabla de tramos" if data.get("impuestoUnico", {}).get("tramos") else "sin tramos"
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
    return data.get(indicador, "sin valor")


def alerta_requerida(_indicador, estado):
    return estado in ALERT_STATES


def alertas_snapshot(data):
    alertas = []
    periodo = period_key(data["periodo"]["anio"], data["periodo"]["mes"])
    for indicador, estado in data.get("estadoActualizacion", {}).items():
        if alerta_requerida(indicador, estado):
            fuente = data.get("fuentes", {}).get(indicador, "sin_fuente")
            alertas.append(
                "⚠️ Sueldo Real Chile - dato historico requiere revision\n"
                f"Periodo: {periodo}\n"
                f"Indicador: {indicador}\n"
                f"Estado: {estado}\n"
                f"Valor usado: {valor_usado(data, indicador)}\n"
                f"Fuente revisada: {fuente}\n"
                "Accion sugerida: revisar y completar manualmente"
            )
    return alertas


def update_current():
    hoy = chile_today()
    data = build_snapshot(hoy.year, hoy.month, current=True)
    write_json(TASAS_JSON, data)
    write_json(period_path(hoy.year, hoy.month), data)
    cargar_o_actualizar_uf_anual(hoy.year, hasta=hoy)
    index = update_index()

    alertas = alertas_snapshot(data)
    if alertas:
        enviar_alerta_telegram("\n\n".join(alertas))
    else:
        enviar_alerta_telegram(
            "✅ Sueldo Real Chile\n"
            "Actualizacion completada correctamente.\n"
            "Todas las fuentes requeridas quedaron en estado usable.\n\n"
            f"Fecha: {hoy.isoformat()}\n"
            f"UF: {data['uf']} ({data['estadoActualizacion']['uf']})\n"
            f"UTM: {data['utm']} ({data['estadoActualizacion']['utm']})\n"
            f"Periodos historicos: {len(index.get('periodos', []))}"
        )

    print("tasas.json actualizado correctamente")
    print(f"Periodo: {MESES[hoy.month]} {hoy.year}")
    print(f"UF: {data['uf']} ({data['estadoActualizacion']['uf']})")
    print(f"UTM: {data['utm']} ({data['estadoActualizacion']['utm']})")
    print(f"Estado periodo vigente: {data['estadoPeriodo']}")
    print(f"Historicos indexados: {len(index.get('periodos', []))}")


def update_uf_daily():
    hoy = chile_today()
    uf_data, estado = cargar_o_actualizar_uf_anual(hoy.year, hasta=hoy)
    print(f"UF diaria {hoy.year}: {len(uf_data.get('valores', {}))} dias cargados ({estado})")


def rebuild_history(from_period, to_period=None, force=False):
    ensure_manual_files()
    hoy = chile_today()
    to_period = to_period or period_key(hoy.year, hoy.month)
    uf_cache = {}

    for anio, _mes in month_iter(from_period, to_period):
        if anio not in uf_cache:
            hasta = hoy if anio == hoy.year else date(anio, 12, 31)
            uf_cache[anio] = cargar_o_actualizar_uf_anual(anio, hasta=hasta)[0].get("valores", {})

    creados = []
    omitidos = []
    for anio, mes in month_iter(from_period, to_period):
        path = period_path(anio, mes)
        existing = read_json(path, None)
        if existing and existing.get("estadoPeriodo") == "cerrado" and not force:
            omitidos.append(period_key(anio, mes))
            continue

        current = (anio, mes) == (hoy.year, hoy.month)
        fecha_ref = hoy if current else date(anio, mes, last_day(anio, mes))
        data = build_snapshot(anio, mes, current=current, uf_values=uf_cache.get(anio, {}), fecha_calculo=fecha_ref)
        write_json(path, data)
        creados.append(period_key(anio, mes))

    index = update_index()
    print(f"Historicos creados/actualizados: {', '.join(creados) if creados else 'ninguno'}")
    print(f"Historicos omitidos: {', '.join(omitidos) if omitidos else 'ninguno'}")
    print(f"Periodos disponibles: {len(index.get('periodos', []))}")


def validate_snapshot(data):
    errores = []
    required = [
        "version", "fechaActualizacion", "periodo", "utm", "uf", "topes",
        "laboral", "afp", "salud", "cesantia", "impuestoUnico",
        "estadoActualizacion", "fuentes"
    ]
    for field in required:
        if field not in data:
            errores.append(f"Falta campo {field}")

    uf = data.get("uf")
    utm = data.get("utm")
    if not validar_uf(uf):
        errores.append(f"UF fuera de rango: {uf}")
    if not validar_utm(utm):
        errores.append(f"UTM fuera de rango: {utm}")
    if data.get("salud", {}).get("fonasa") != 0.07:
        errores.append("Fonasa debe ser 0.07")
    laboral = data.get("laboral", {})
    if laboral.get("imm", 0) <= 0:
        errores.append("IMM debe ser mayor que 0")
    afps = data.get("afp", [])
    if not afps:
        errores.append("AFP no puede estar vacio")
    for afp in afps:
        comision = afp.get("comision")
        if comision is None or comision < 0 or comision > 0.03:
            errores.append(f"Comision AFP fuera de rango: {afp}")
    tramos = data.get("impuestoUnico", {}).get("tramos", [])
    if not tramos:
        errores.append("Tramos de impuesto no pueden estar vacios")
    return errores


def validate_history():
    errores_totales = []
    resumen = {"cerrado": [], "vigente": [], "incompleto": [], "manual_requerido": []}
    otros = []

    for path in sorted(PERIODOS_DIR.glob("*/*.json")):
        data = read_json(path, {}) or {}
        periodo = path.stem
        estado = data.get("estadoPeriodo") or "manual_requerido"
        if estado in resumen:
            resumen[estado].append(periodo)
        else:
            otros.append((periodo, estado))

        errores = validate_snapshot(data)
        if errores:
            errores_totales.append((path, errores))

    print("Resumen de validacion historica:")
    for estado in ("cerrado", "vigente", "incompleto", "manual_requerido"):
        periodos = resumen[estado]
        print(f"- {estado}: {len(periodos)} ({', '.join(periodos) if periodos else 'ninguno'})")
    if otros:
        print("- estados no reconocidos:")
        for periodo, estado in otros:
            print(f"  * {periodo}: {estado}")

    incompletos = resumen["incompleto"] + resumen["manual_requerido"]
    if incompletos:
        print("Periodos que requieren revision antes de cerrarse:")
        for periodo in incompletos:
            path = period_path(*parse_period(periodo))
            data = read_json(path, {}) or {}
            estados = data.get("estadoActualizacion", {})
            pendientes = [f"{k}={v}" for k, v in estados.items() if v not in OK_STATES]
            print(f"- {periodo}: {', '.join(pendientes) if pendientes else 'sin detalle'}")

    if errores_totales:
        print("Errores de validacion historica:")
        for path, errores in errores_totales:
            print(f"- {path.relative_to(ROOT)}")
            for error in errores:
                print(f"  * {error}")
        raise SystemExit(1)

    print("Historicos validados correctamente en estructura y rangos basicos")
    print(f"Archivos mensuales: {len(list(PERIODOS_DIR.glob('*/*.json')))}")


def main():
    parser = argparse.ArgumentParser(description="Actualiza tasas vigentes e historicas de Sueldo Real Chile")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("update-current")
    subparsers.add_parser("update-uf-daily")
    rebuild = subparsers.add_parser("rebuild-history")
    rebuild.add_argument("--from", dest="from_period", default="2026-01")
    rebuild.add_argument("--to", dest="to_period", default=None)
    rebuild.add_argument("--force", action="store_true")
    subparsers.add_parser("validate-history")

    args = parser.parse_args()
    command = args.command or "update-current"

    if command == "update-current":
        update_current()
    elif command == "update-uf-daily":
        update_uf_daily()
    elif command == "rebuild-history":
        rebuild_history(args.from_period, args.to_period, args.force)
    elif command == "validate-history":
        validate_history()
    else:
        parser.error(f"Comando no soportado: {command}")


if __name__ == "__main__":
    main()
