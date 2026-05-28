import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
TASAS_JSON = ROOT / "tasas.json"

OK_STATES = {"online", "online_sii", "online_mindicador", "ok", "validado", "manual_validado"}
ALERT_STATES = {"manual", "manual_pendiente", "respaldo", "manual_requerido", "faltante", "error", "invalido"}

GITHUB_BASE = "https://github.com/jonathanrosvel-dev/tasas-sueldo-real/blob/main"
RAW_BASE = "https://raw.githubusercontent.com/jonathanrosvel-dev/tasas-sueldo-real/main"

INDICADORES = {
    "uf": {
        "nombre": "UF",
        "explicacion": "La UF se usa para convertir topes previsionales y valores expresados en UF.",
        "link_revision": "https://www.sii.cl/valores_y_fechas/uf/uf{anio}.htm",
        "link_json": f"{GITHUB_BASE}/tasas/historico/uf/uf_diaria_{{anio}}.json",
    },
    "utm": {
        "nombre": "UTM",
        "explicacion": "La UTM se usa para calcular los tramos del Impuesto Único de Segunda Categoría.",
        "link_revision": "https://www.sii.cl/valores_y_fechas/utm/utm{anio}.htm",
        "link_json": f"{GITHUB_BASE}/tasas.json",
    },
    "impuestoUnico": {
        "nombre": "Impuesto Único",
        "explicacion": "La tabla de IUSC define los tramos y rebajas que usa la app para calcular el impuesto mensual.",
        "link_revision": "https://www.sii.cl/valores_y_fechas/impuesto_2da_categoria/impuesto{anio}.htm",
        "link_json": f"{GITHUB_BASE}/tasas.json",
    },
    "afp": {
        "nombre": "Comisiones AFP",
        "explicacion": "Las comisiones AFP se descuentan junto con la cotización obligatoria. Si no se pudo leer la fuente, la app usa respaldo local.",
        "link_revision": "https://www.spensiones.cl/portal/institucional/594/w3-article-2810.html",
        "link_json": f"{GITHUB_BASE}/tasas/historico/manual/afp_comisiones.json",
    },
    "topes": {
        "nombre": "Topes imponibles",
        "explicacion": "Los topes previsionales limitan la base usada para AFP/salud y seguro de cesantía.",
        "link_revision": "https://www.spensiones.cl/portal/institucional/594/w3-propertyvalue-9923.html",
        "link_json": f"{GITHUB_BASE}/tasas/historico/manual/topes.json",
    },
    "imm": {
        "nombre": "Ingreso Mínimo Mensual",
        "explicacion": "El IMM se usa para gratificación legal y otras referencias laborales.",
        "link_revision": "https://www.dt.gob.cl/portal/1628/w3-propertyvalue-145768.html",
        "link_json": f"{GITHUB_BASE}/tasas/historico/manual/laboral.json",
    },
    "cesantia": {
        "nombre": "Seguro de cesantía",
        "explicacion": "Estas tasas dependen del tipo de contrato y afectan el descuento del trabajador.",
        "link_revision": "https://www.dt.gob.cl/portal/1628/w3-propertyvalue-145768.html",
        "link_json": f"{GITHUB_BASE}/tasas/historico/manual/cesantia.json",
    },
    "salud": {
        "nombre": "Salud",
        "explicacion": "Cotización legal base de salud, normalmente 7%.",
        "link_revision": "https://www.dt.gob.cl/portal/1628/w3-propertyvalue-145768.html",
        "link_json": f"{GITHUB_BASE}/tasas.json",
    },
}


def read_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def format_clp(value):
    try:
        return "$" + f"{round(float(value)):,.0f}".replace(",", ".")
    except Exception:
        return str(value)


def valor_usado(data, indicador):
    if indicador == "uf":
        return data.get("uf")
    if indicador == "utm":
        return format_clp(data.get("utm"))
    if indicador == "impuestoUnico":
        tramos = data.get("impuestoUnico", {}).get("tramos", [])
        return f"{len(tramos)} tramos cargados" if tramos else "sin tramos cargados"
    if indicador == "afp":
        afps = data.get("afp", [])
        if not afps:
            return "sin AFP cargadas"
        return ", ".join([f"{a.get('nombre')} {round(float(a.get('comision', 0)) * 100, 3)}%" for a in afps])
    if indicador == "topes":
        topes = data.get("topes", {})
        return f"AFP/Salud: {topes.get('afpSaludUf')} UF · Cesantía: {topes.get('cesantiaUf')} UF"
    if indicador == "imm":
        laboral = data.get("laboral", {})
        return format_clp(laboral.get("imm"))
    if indicador == "salud":
        salud = data.get("salud", {})
        return f"Fonasa/legal: {round(float(salud.get('fonasa', 0)) * 100, 2)}%"
    if indicador == "cesantia":
        cesantia = data.get("cesantia", {})
        return f"Indefinido trabajador: {round(float(cesantia.get('trabajadorIndefinido', 0)) * 100, 3)}% · Plazo fijo trabajador: {round(float(cesantia.get('trabajadorPlazoFijo', 0)) * 100, 3)}%"
    return str(data.get(indicador, "sin valor"))


def fuente_revisada(data, indicador, anio):
    fuente = data.get("fuentes", {}).get(indicador)
    if fuente:
        return fuente
    meta = INDICADORES.get(indicador, {})
    return meta.get("link_revision", "").format(anio=anio)


def estado_en_humano(estado):
    if estado == "respaldo":
        return "usé un respaldo porque la fuente principal no se pudo confirmar"
    if estado == "manual_pendiente":
        return "quedó pendiente de validación manual"
    if estado == "manual_requerido":
        return "necesita revisión manual antes de confiar en el cálculo"
    if estado in {"faltante", "error", "invalido"}:
        return "hay un problema que requiere revisión"
    if estado == "manual":
        return "viene de archivo manual"
    return estado


def construir_alerta(data, indicador, estado):
    periodo = data.get("periodo", {})
    anio = periodo.get("anio")
    mes_nombre = periodo.get("mesNombre") or periodo.get("mes")
    meta = INDICADORES.get(indicador, {"nombre": indicador, "explicacion": "Dato usado por la app."})
    link_revision = meta.get("link_revision", "").format(anio=anio)
    link_json = meta.get("link_json", "").format(anio=anio)
    fuente = fuente_revisada(data, indicador, anio)
    valor = valor_usado(data, indicador)

    return (
        f"👋 Jonathan, necesito que revises un dato de Sueldo Real Chile.\n\n"
        f"📌 Dato: {meta['nombre']}\n"
        f"📅 Período: {mes_nombre} {anio}\n"
        f"⚠️ Qué pasó: {estado_en_humano(estado)}.\n"
        f"🧾 Valor que quedó usando la app: {valor}\n\n"
        f"{meta['explicacion']}\n\n"
        f"🔎 Fuente revisada:\n{fuente}\n\n"
        f"✅ Para revisar y aceptar o corregir:\n{link_revision}\n\n"
        f"🛠️ Archivo donde se guarda este dato:\n{link_json}\n\n"
        f"Por ahora confirma el dato editando GitHub. Después lo dejaremos con botones de Telegram para aceptar o rechazar desde el chat."
    )


def construir_ok(data):
    periodo = data.get("periodo", {})
    anio = periodo.get("anio")
    mes_nombre = periodo.get("mesNombre") or periodo.get("mes")
    return (
        "✅ Jonathan, la actualización automática terminó bien.\n\n"
        f"📅 Período actualizado: {mes_nombre} {anio}\n"
        f"💰 UF usada: {data.get('uf')} ({data.get('ufFecha')})\n"
        f"📌 UTM usada: {format_clp(data.get('utm'))}\n\n"
        "No encontré datos críticos pendientes de revisión en esta corrida."
    )


def enviar_telegram(mensaje):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram no configurado. No se envió alerta humana.")
        return
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": mensaje, "disable_web_page_preview": True},
        timeout=20,
    )
    print("Telegram response:", response.status_code, response.text)
    response.raise_for_status()


def main():
    data = read_json(TASAS_JSON)
    estados = data.get("estadoActualizacion", {})
    alertas = []
    for indicador, estado in estados.items():
        if estado in ALERT_STATES:
            alertas.append(construir_alerta(data, indicador, estado))

    if alertas:
        for alerta in alertas:
            enviar_telegram(alerta)
    else:
        enviar_telegram(construir_ok(data))


if __name__ == "__main__":
    main()
