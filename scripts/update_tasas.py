import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

AFP_URL = "https://www.spensiones.cl/portal/institucional/594/w3-article-2810.html"

MESES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}

AFP_NOMBRES = ["Capital", "Cuprum", "Habitat", "Modelo", "Planvital", "Provida", "Uno"]

AFP_FALLBACK = [
    {"nombre": "Capital", "comision": 0.0144},
    {"nombre": "Cuprum", "comision": 0.0144},
    {"nombre": "Habitat", "comision": 0.0127},
    {"nombre": "Modelo", "comision": 0.0058},
    {"nombre": "PlanVital", "comision": 0.0116},
    {"nombre": "Provida", "comision": 0.0145},
    {"nombre": "Uno", "comision": 0.0049}
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

TOPES_FALLBACK = {
    "afpSaludUf": 90,
    "cesantiaUf": 135.2
}

UF_MIN = 30000
UF_MAX = 60000

def sii_uf_url(anio):
    return f"https://www.sii.cl/valores_y_fechas/uf/uf{anio}.htm"


def limpiar_decimal_chileno(texto):
    texto = texto or ""
    texto = texto.replace("$", "").replace(" ", "")
    texto = texto.replace(".", "").replace(",", ".")
    texto = re.sub(r"[^0-9.\-]", "", texto)

    if texto in ("", "-", "--"):
        return None

    return float(texto)


def validar_uf(uf):
    if uf is None:
        return False

    return UF_MIN <= float(uf) <= UF_MAX


def obtener_uf_sii(anio, mes, dia):
    url = sii_uf_url(anio)
    html = get_html(url, timeout=30)
    soup = BeautifulSoup(html, "html.parser")

    for fila in soup.find_all("tr"):
        celdas = [c.get_text(" ", strip=True) for c in fila.find_all(["td", "th"])]

        if not celdas:
            continue

        for i in range(0, len(celdas) - 1, 2):
            dia_texto = normalizar(celdas[i]).strip()

            if dia_texto == str(dia):
                valor = limpiar_decimal_chileno(celdas[i + 1])

                if validar_uf(valor):
                    return valor

    raise RuntimeError(f"No se pudo encontrar UF válida en SII para {dia}-{mes}-{anio}")


def obtener_uf_mindicador():
    url = "https://mindicador.cl/api/uf"
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    data = response.json()
    valor = data["serie"][0]["valor"]

    if validar_uf(valor):
        return float(valor)

    raise RuntimeError(f"UF inválida desde mindicador.cl: {valor}")


def obtener_uf_blindada(anio, mes, dia, actual):
    try:
        uf = obtener_uf_sii(anio, mes, dia)
        return uf, "online_sii", sii_uf_url(anio)

    except Exception as e:
        print(f"No se pudo actualizar UF desde SII: {e}")

    try:
        uf = obtener_uf_mindicador()
        return uf, "online_mindicador", "https://mindicador.cl/api/uf"

    except Exception as e:
        print(f"No se pudo actualizar UF desde mindicador.cl: {e}")

    uf_respaldo = actual.get("uf")

    if validar_uf(uf_respaldo):
        return float(uf_respaldo), "respaldo", "respaldo_local"

    raise RuntimeError("No hay UF válida disponible ni online ni en respaldo local")

UTM_MIN = 50000
UTM_MAX = 100000

def validar_utm(utm):
    return utm is not None and UTM_MIN <= utm <= UTM_MAX


def obtener_utm_blindada(anio, mes, actual):
    try:
        utm = obtener_utm_actual(anio, mes)
        if validar_utm(utm):
            return utm, "online", sii_utm_url(anio)
    except Exception as e:
        print(f"UTM SII falló: {e}")

    utm_respaldo = actual.get("utm")

    if validar_utm(utm_respaldo):
        return utm_respaldo, "respaldo", "respaldo_local"

    raise RuntimeError("No hay UTM válida disponible")
    
def sii_utm_url(anio):
    return f"https://www.sii.cl/valores_y_fechas/utm/utm{anio}.htm"


def sii_impuesto_url(anio):
    return f"https://www.sii.cl/valores_y_fechas/impuesto_2da_categoria/impuesto{anio}.htm"


def cargar_json_actual():
    try:
        with open("tasas.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def normalizar(texto):
    return re.sub(r"\s+", " ", texto or "").strip()


def limpiar_entero_chileno(texto):
    limpio = re.sub(r"[^\d]", "", texto or "")
    return int(limpio) if limpio else None


def limpiar_monto_chileno(texto):
    texto = texto or ""
    texto = texto.replace("$", "").replace(" ", "").replace(".", "").replace(",", ".")
    texto = re.sub(r"[^0-9.\-]", "", texto)
    if texto in ("", "-", "--"):
        return None
    return float(texto)


def limpiar_factor(texto):
    texto = texto or ""
    texto = texto.replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", texto)
    return float(match.group(0)) if match else 0.0


def porcentaje_a_decimal(texto):
    texto = texto.replace("%", "").replace(",", ".").strip()
    return round(float(texto) / 100, 6)


def get_html(url, timeout=30):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SueldoRealChileBot/1.0)"
    }
    r = requests.get(url, timeout=timeout, headers=headers)
    r.raise_for_status()
    return r.text


def obtener_utm_actual(anio, mes):
    url = sii_utm_url(anio)
    mes_nombre = MESES[mes]

    html = get_html(url, timeout=30)
    soup = BeautifulSoup(html, "html.parser")
    texto = soup.get_text(" ", strip=True)

    patron = rf"{mes_nombre}\s+\$?\s*([\d\.]+)"
    match = re.search(patron, texto, re.IGNORECASE)

    if not match:
        raise RuntimeError(f"No se pudo encontrar UTM para {mes_nombre} {anio}")

    return limpiar_entero_chileno(match.group(1))


def buscar_tabla_impuesto_mes(soup, mes_nombre, anio):
    titulo_buscado = f"{mes_nombre} {anio}".lower()

    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        texto = normalizar(tag.get_text()).lower()
        if titulo_buscado in texto:
            tabla = tag.find_next("table")
            if tabla:
                return tabla

    texto_completo = soup.get_text(" ", strip=True).lower()
    if titulo_buscado not in texto_completo:
        raise RuntimeError(f"No se encontró el título {mes_nombre} {anio}")

    tabla = soup.find("table")
    if not tabla:
        raise RuntimeError("No se encontró tabla de impuesto")

    return tabla


def obtener_tramos_impuesto_actual(anio, mes, utm):
    url = sii_impuesto_url(anio)
    mes_nombre = MESES[mes]

    html = get_html(url, timeout=30)
    soup = BeautifulSoup(html, "html.parser")
    tabla = buscar_tabla_impuesto_mes(soup, mes_nombre, anio)

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

        valores_monto = [c for c in celdas if "$" in c or "MÁS" in c.upper() or "--" in c]
        factores = [c for c in celdas if re.fullmatch(r"\d+(?:,\d+)?", c)]

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
        hasta_pesos = None if "MÁS" in hasta_texto.upper() else limpiar_monto_chileno(hasta_texto)

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

        
    # --- POST PROCESO DE TRAMOS ---
    
    # Si faltó el tramo exento
    if len(tramos) == 7:
        print("Solo se encontraron 7 tramos. Se agregará tramo exento automáticamente.")
    
        tramo_exento = {
            "desdeUtm": 0,
            "hastaUtm": 13.5,
            "factor": 0.0,
            "rebajaUtm": 0.0
        }
    
        tramos.insert(0, tramo_exento)
    
    # Validación mínima
    if len(tramos) < 7:
        raise RuntimeError(
            f"Error grave: se extrajeron muy pocos tramos ({len(tramos)})"
        )
    
    # Normalizar siempre a 8 tramos
    tramos = tramos[:8]
    
    # Forzar primer tramo correcto (exento)
    tramos[0] = {
        "desdeUtm": 0,
        "hastaUtm": 13.5,
        "factor": 0.0,
        "rebajaUtm": 0.0
    }
    
    # Forzar último tramo abierto
    tramos[-1]["hastaUtm"] = None
    
    return tramos


def obtener_afp_actuales(afp_respaldo):
    try:
        html = None

        for intento in range(3):
            try:
                html = get_html(AFP_URL, timeout=60)
                break
            except Exception as e:
                print(f"Intento AFP {intento + 1} falló: {e}")

        if html is None:
            raise RuntimeError("No se pudo conectar con la fuente AFP")

        soup = BeautifulSoup(html, "html.parser")
        texto = soup.get_text(" ", strip=True)

        resultado = []

        for nombre in AFP_NOMBRES:
            # 🔥 regex más robusto
            patron = rf"AFP\s+{nombre}[:\s]+(\d{{1,2}}[,.]\d{{1,3}})\s*%"
            match = re.search(patron, texto, re.IGNORECASE)

            if not match:
                raise RuntimeError(f"No se encontró comisión AFP {nombre}")

            resultado.append({
                "nombre": nombre,
                "comision": porcentaje_a_decimal(match.group(1))
            })

        return resultado, "online"

    except Exception as e:
        print(f"No se pudieron actualizar AFP automáticamente: {e}")
        print("Se usarán AFP guardadas o fallback.")
        return afp_respaldo or AFP_FALLBACK, "respaldo"


def crear_json():
    hoy = datetime.now(ZoneInfo("America/Santiago")).date()
    anio = hoy.year
    mes = hoy.month

    actual = cargar_json_actual()
    afp_respaldo = actual.get("afp", AFP_FALLBACK)

    estado_utm = "online"
    estado_impuesto = "online"
    estado_uf = "online"

    uf, estado_uf, uf_url = obtener_uf_blindada(anio, mes, hoy.day, actual)
    
    topes = actual.get("topes", TOPES_FALLBACK)

    utm, estado_utm, utm_url = obtener_utm_blindada(anio, mes, actual)

    try:
        tramos = obtener_tramos_impuesto_actual(anio, mes, utm)
        impuesto_url = sii_impuesto_url(anio)
    except Exception as e:
        print(f"No se pudo actualizar tabla de impuesto desde SII: {e}")
        tramos = actual.get("impuestoUnico", {}).get("tramos", TRAMOS_UTM_FALLBACK)
        impuesto_url = sii_impuesto_url(anio)
        estado_impuesto = "respaldo"

    afp, estado_afp = obtener_afp_actuales(afp_respaldo)

    data = {
        "version": hoy.strftime("%Y-%m-%d"),
        "fechaActualizacion": hoy.isoformat(),
        "periodo": {
            "anio": anio,
            "mes": mes,
            "mesNombre": MESES[mes]
        },
        "utm": utm,
        "uf": uf,
        "topes": topes,
        "afp": afp,
        "salud": {
            "fonasa": 0.07
        },
        "cesantia": {
            "trabajadorIndefinido": 0.006
        },
        "impuestoUnico": {
            "tramos": tramos
        },
        "estadoActualizacion": {
            "utm": estado_utm,
            "uf": estado_uf,
            "impuestoUnico": estado_impuesto,
            "afp": estado_afp
        },
        "fuentes": {
            "utm": utm_url,
            "uf": uf_url,
            "impuestoUnico": impuesto_url,
            "afp": AFP_URL
        }
    }

    with open("tasas.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("tasas.json actualizado correctamente")
    print(f"Periodo: {MESES[mes]} {anio}")
    print(f"UTM: {utm} ({estado_utm})")
    print(f"UF: {uf} ({estado_uf})")
    print(f"Topes: {topes}")
    print(f"Impuesto único: {estado_impuesto}")
    print(f"AFP: {estado_afp}")
    print(f"AFP data: {afp}")
    


if __name__ == "__main__":
    crear_json()
