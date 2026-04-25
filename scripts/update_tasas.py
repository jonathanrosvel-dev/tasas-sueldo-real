import json
import re
from datetime import date

import requests
from bs4 import BeautifulSoup

SII_UTM_URL = "https://www.sii.cl/valores_y_fechas/utm/utm2026.htm"
SII_IMPUESTO_URL = "https://www.sii.cl/valores_y_fechas/impuesto_2da_categoria/impuesto2026.htm"

AFP_COMISIONES = [
    {"nombre": "Capital", "comision": 0.0144},
    {"nombre": "Cuprum", "comision": 0.0144},
    {"nombre": "Habitat", "comision": 0.0127},
    {"nombre": "Modelo", "comision": 0.0058},
    {"nombre": "PlanVital", "comision": 0.0116},
    {"nombre": "Provida", "comision": 0.0145},
    {"nombre": "Uno", "comision": 0.0049}
]

TRAMOS_UTM = [
    {"desdeUtm": 0, "hastaUtm": 13.5, "factor": 0.0, "rebajaUtm": 0.0},
    {"desdeUtm": 13.5, "hastaUtm": 30, "factor": 0.04, "rebajaUtm": 0.54},
    {"desdeUtm": 30, "hastaUtm": 50, "factor": 0.08, "rebajaUtm": 1.74},
    {"desdeUtm": 50, "hastaUtm": 70, "factor": 0.135, "rebajaUtm": 4.49},
    {"desdeUtm": 70, "hastaUtm": 90, "factor": 0.23, "rebajaUtm": 11.14},
    {"desdeUtm": 90, "hastaUtm": 120, "factor": 0.304, "rebajaUtm": 17.8},
    {"desdeUtm": 120, "hastaUtm": 310, "factor": 0.35, "rebajaUtm": 23.32},
    {"desdeUtm": 310, "hastaUtm": None, "factor": 0.40, "rebajaUtm": 38.82}
]

MESES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}


def limpiar_numero(texto):
    limpio = re.sub(r"[^\d]", "", texto)
    return int(limpio) if limpio else None


def obtener_utm_actual():
    hoy = date.today()
    mes_nombre = MESES[hoy.month]

    html = requests.get(SII_UTM_URL, timeout=20).text
    soup = BeautifulSoup(html, "html.parser")
    texto = soup.get_text(" ", strip=True)

    patron = rf"{mes_nombre}\s+\$?\s*([\d\.]+)"
    match = re.search(patron, texto, re.IGNORECASE)

    if not match:
        raise RuntimeError(f"No se pudo encontrar UTM para {mes_nombre}")

    return limpiar_numero(match.group(1))


def crear_json():
    hoy = date.today()
    utm = obtener_utm_actual()

    data = {
        "version": hoy.strftime("%Y-%m-%d"),
        "fechaActualizacion": hoy.isoformat(),
        "utm": utm,
        "afp": AFP_COMISIONES,
        "salud": {
            "fonasa": 0.07
        },
        "cesantia": {
            "trabajadorIndefinido": 0.006
        },
        "impuestoUnico": {
            "tramos": TRAMOS_UTM
        },
        "fuentes": {
            "utm": SII_UTM_URL,
            "impuestoUnico": SII_IMPUESTO_URL,
            "afp": "https://www.spensiones.cl/infoydec"
        }
    }

    with open("tasas.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("tasas.json actualizado correctamente")
    print(f"UTM: {utm}")


if __name__ == "__main__":
    crear_json()
