"""Archive des collectes, distincte de la diffusion effective des éditions."""
import json
import os
import tempfile

from lib import INTERIM, OUTPUT

ARCHIVE_FILE = OUTPUT / "news_archive.json"
DELIVERY_FILE = INTERIM / "newsletter_delivery.json"


def read_json(path, default):
    if not path.exists():
        return default
    # Un état corrompu doit faire échouer le traitement, jamais repartir de zéro.
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, type(default)):
        raise ValueError(f"État invalide : {path}")
    return value


def write_json(path, value):
    """Remplacement atomique pour ne pas tronquer un état lors d’une interruption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, encoding="utf-8", delete=False) as stream:
            name = stream.name
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def merge(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Le premier enregistrement conserve sa date de détection, y compris en rejeu."""
    by_link = {item["lien"]: item for item in existing}
    for item in incoming:
        by_link.setdefault(item["lien"], item)
    return list(by_link.values())


def load() -> list[dict]:
    return read_json(ARCHIVE_FILE, [])


def save(items: list[dict]):
    write_json(ARCHIVE_FILE, items)


def deliveries() -> dict:
    return read_json(DELIVERY_FILE, {})


def unsent(items: list[dict], history: dict) -> list[dict]:
    sent = {link for edition in history.values() for link in edition["articles"]}
    return [item for item in items if item["lien"] not in sent]


def mark_sent(today, items: list[dict], reports: list[dict]):
    history = deliveries()
    previous = history.get(today.isoformat(), {"articles": [], "rapports": []})
    history[today.isoformat()] = {
        "articles": list(dict.fromkeys(previous["articles"] + [i["lien"] for i in items])),
        "rapports": list(dict.fromkeys(previous["rapports"] + [r["id"] for r in reports])),
    }
    write_json(DELIVERY_FILE, history)
