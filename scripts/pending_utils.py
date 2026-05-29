import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PENDIENTES_DIR = ROOT / "tasas" / "historico" / "pendientes"
GITHUB_BASE = "https://github.com/jonathanrosvel-dev/tasas-sueldo-real/blob/main"


def chile_now():
    return datetime.now(ZoneInfo("America/Santiago")).isoformat()


def stable_id(prefix, *parts):
    raw = "|".join(str(part) for part in parts if part is not None)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    safe_prefix = re.sub(r"[^a-zA-Z0-9_-]+", "_", prefix).strip("_")[:40]
    return f"{safe_prefix}_{digest}"


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def read_json(path, default=None):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def github_link(path):
    return f"{GITHUB_BASE}/{path}"


def create_pending(pending_id, payload, overwrite=False):
    PENDIENTES_DIR.mkdir(parents=True, exist_ok=True)
    path = PENDIENTES_DIR / f"{pending_id}.json"
    existing = read_json(path)
    if existing and existing.get("estado") == "pendiente" and not overwrite:
        return False, path
    if existing and existing.get("estado") in {"aprobado", "rechazado"} and not overwrite:
        return False, path

    data = {
        "id": pending_id,
        "estado": "pendiente",
        "fechaCreacion": chile_now(),
        **payload,
    }
    write_json(path, data)
    return True, path
