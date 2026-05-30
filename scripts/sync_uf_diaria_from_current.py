import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASAS_JSON = ROOT / "tasas.json"
UF_DIR = ROOT / "tasas" / "historico" / "uf"
UF_MIN = 30000
UF_MAX = 60000


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


def valid_uf(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    return UF_MIN <= value <= UF_MAX


def main():
    tasas = read_json(TASAS_JSON, {}) or {}
    uf = tasas.get("uf")
    uf_fecha = tasas.get("ufFecha") or tasas.get("fechaActualizacion")
    estado_uf = (tasas.get("estadoActualizacion") or {}).get("uf")

    if not uf_fecha or len(uf_fecha) < 10 or not valid_uf(uf):
        raise SystemExit("tasas.json no contiene UF vigente valida para sincronizar")

    anio = int(uf_fecha[:4])
    path = UF_DIR / f"uf_diaria_{anio}.json"
    data = read_json(path, {"anio": anio, "fuente": "SII", "valores": {}}) or {}
    valores = data.setdefault("valores", {})
    valores[uf_fecha] = round(float(uf), 2)
    data["anio"] = anio
    data.setdefault("fuente", "SII")
    data["fechaActualizacion"] = uf_fecha

    if estado_uf and estado_uf != "online_sii":
        fuentes_por_fecha = data.setdefault("fuentesPorFecha", {})
        fuentes_por_fecha[uf_fecha] = estado_uf
    elif "fuentesPorFecha" in data:
        data["fuentesPorFecha"].pop(uf_fecha, None)
        if not data["fuentesPorFecha"]:
            data.pop("fuentesPorFecha", None)

    data["valores"] = dict(sorted(valores.items()))
    write_json(path, data)
    print(f"UF diaria sincronizada: {uf_fecha} = {round(float(uf), 2)} en {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
