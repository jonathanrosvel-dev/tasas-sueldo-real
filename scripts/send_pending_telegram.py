import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
PENDIENTES_DIR = ROOT / "tasas" / "historico" / "pendientes"
GITHUB_BASE = "https://github.com/jonathanrosvel-dev/tasas-sueldo-real/blob/main"


def chile_now():
    return datetime.now(ZoneInfo("America/Santiago")).isoformat()


def read_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def github_file_link(path):
    if not path:
        return None
    text = str(path)
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return f"{GITHUB_BASE}/{text.lstrip('/')}"


def telegram_send_message(text, pending_id):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram no configurado. No se envió pendiente.")
        return None

    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "✅ Validar", "callback_data": f"sr:ok:{pending_id}"},
                    {"text": "❌ Rechazar", "callback_data": f"sr:no:{pending_id}"},
                ]
            ]
        },
    }
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json=payload,
        timeout=20,
    )
    print("Telegram response:", response.status_code, response.text)
    response.raise_for_status()
    return response.json()


def build_message(pending):
    lines = [
        "👋 Jonathan, necesito tu revisión en Sueldo Real Chile.",
        "",
        f"📌 Dato: {pending.get('titulo', pending.get('id'))}",
    ]
    if pending.get("periodo"):
        lines.append(f"📅 Período: {pending['periodo']}")
    if pending.get("valorDetectado") is not None:
        lines.append(f"🧾 Valor detectado: {pending['valorDetectado']}")
    if pending.get("valorActual") is not None:
        lines.append(f"📍 Valor actual en GitHub: {pending['valorActual']}")
    if pending.get("motivo"):
        lines.extend(["", f"⚠️ Motivo: {pending['motivo']}"])
    if pending.get("descripcion"):
        lines.extend(["", pending["descripcion"]])
    if pending.get("fuente"):
        lines.extend(["", f"🔎 Fuente para revisar:\n{pending['fuente']}"])

    target_link = pending.get("linkGitHub") or github_file_link(pending.get("targetFile"))
    if target_link:
        lines.extend(["", f"🛠️ Archivo que debes revisar en GitHub:\n{target_link}"])

    lines.extend([
        "",
        "Elige una opción:",
        "✅ Validar: marca este pendiente como revisado/aprobado.",
        "❌ Rechazar: lo deja como pendiente/requiere revisión.",
    ])
    return "\n".join(lines)


def main():
    if not PENDIENTES_DIR.exists():
        print("No existe carpeta de pendientes.")
        return

    enviados = 0
    for path in sorted(PENDIENTES_DIR.glob("*.json")):
        pending = read_json(path)
        if pending.get("estado") != "pendiente":
            continue
        if pending.get("telegram", {}).get("enviado"):
            continue
        pending_id = pending.get("id") or path.stem
        result = telegram_send_message(build_message(pending), pending_id)
        pending["telegram"] = {
            "enviado": True,
            "fechaEnvio": chile_now(),
            "messageId": result.get("result", {}).get("message_id") if result else None,
        }
        write_json(path, pending)
        enviados += 1

    print(f"Pendientes enviados por Telegram: {enviados}")


if __name__ == "__main__":
    main()
