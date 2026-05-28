import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZONAS_EXTREMAS_PATH = ROOT / "tasas" / "historico" / "manual" / "zonas_extremas.json"
HASHES_PATH = ROOT / "tasas" / "historico" / "manual" / "zonas_extremas_hashes.json"

VALID_STATES = {"manual_validado", "manual_pendiente", "manual_requerido"}


def read_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_hashes(path=HASHES_PATH):
    errores = []
    advertencias = []

    if not path.exists():
        advertencias.append(f"{path.relative_to(ROOT)} aun no existe; se generara en el primer monitoreo")
        return errores, advertencias

    data = read_json(path)
    fuentes = data.get("fuentes", [])

    if not isinstance(fuentes, list):
        errores.append("zonas_extremas_hashes.json debe tener fuentes como lista")
        return errores, advertencias

    if not fuentes:
        advertencias.append("zonas_extremas_hashes.json existe, pero aun no tiene fuentes monitoreadas")

    for fuente in fuentes:
        if not fuente.get("url"):
            errores.append(f"hash sin url: {fuente}")
        if not fuente.get("ultimoHash"):
            errores.append(f"hash sin ultimoHash: {fuente}")
        if not fuente.get("fechaRevision"):
            errores.append(f"hash sin fechaRevision: {fuente}")

    return errores, advertencias


def validate_zonas_extremas(path=ZONAS_EXTREMAS_PATH):
    errores = []
    advertencias = []

    if not path.exists():
        return [f"No existe {path.relative_to(ROOT)}"], advertencias

    data = read_json(path)

    if data.get("estado") not in VALID_STATES:
        errores.append("estado raiz debe ser manual_validado, manual_pendiente o manual_requerido")

    if not data.get("fuentes"):
        errores.append("fuentes no puede estar vacio")

    sueldo_grado = data.get("sueldoGrado1A", [])
    if not sueldo_grado:
        advertencias.append("sueldoGrado1A no tiene valores cargados")

    for item in sueldo_grado:
        valor = item.get("valor")
        estado = item.get("estado")
        if not isinstance(valor, (int, float)) or valor <= 0:
            errores.append(f"sueldoGrado1A invalido: {item}")
        if estado not in VALID_STATES:
            errores.append(f"estado invalido en sueldoGrado1A: {item}")
        if estado == "manual_validado" and not item.get("url"):
            advertencias.append(f"sueldoGrado1A validado sin URL fuente: {item}")
        if estado in {"manual_pendiente", "manual_requerido"}:
            advertencias.append(f"sueldoGrado1A pendiente de validacion: {item.get('desde')} {item.get('valor')}")

    zonas = data.get("zonas", [])
    if not zonas:
        advertencias.append("zonas no tiene registros cargados")

    for zona in zonas:
        estado = zona.get("estado")
        porcentaje = zona.get("porcentaje")
        nombre = zona.get("nombre", "sin_nombre")

        if estado not in VALID_STATES:
            errores.append(f"estado invalido en zona {nombre}: {estado}")

        if porcentaje is None and estado != "manual_pendiente":
            errores.append(f"zona {nombre} tiene porcentaje null pero no esta manual_pendiente")

        if porcentaje is None:
            advertencias.append(f"zona pendiente de porcentaje validado: {nombre}")

        if porcentaje is not None:
            if not isinstance(porcentaje, (int, float)) or porcentaje < 0:
                errores.append(f"porcentaje invalido en zona {nombre}: {porcentaje}")
            if estado != "manual_validado":
                errores.append(f"zona {nombre} tiene porcentaje pero no esta manual_validado")

    return errores, advertencias


def main():
    errores, advertencias = validate_zonas_extremas()
    errores_hashes, advertencias_hashes = validate_hashes()
    errores.extend(errores_hashes)
    advertencias.extend(advertencias_hashes)

    print("Validacion zonas extremas DL 889")
    if advertencias:
        print("Advertencias:")
        for advertencia in advertencias:
            print(f"- {advertencia}")

    if errores:
        print("Errores:")
        for error in errores:
            print(f"- {error}")
        raise SystemExit(1)

    print("zonas_extremas.json validado correctamente")


if __name__ == "__main__":
    main()
