"""Copies durables des éditions, distinctes de l’archive des articles et des envois."""
import argparse
import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path

import editorial
from lib import DATA, today_utc
from news_archive import write_json


def archive(root, now, edition, run_id, attempt, notion_json, email_html, notion_outcome, email_outcome):
    editorial.edition_calendar(now, edition)  # valide le lundi de diffusion
    if not run_id.isdecimal() or not attempt.isdecimal():
        raise ValueError("Identifiant et tentative GitHub doivent être numériques")
    preview = edition > now.date()
    destination = root / edition.isoformat()
    if preview:
        destination /= "previews"
    destination /= f"{run_id}-{attempt}"
    files = {}
    for name, source in (("notion.json", notion_json), ("newsletter.html", email_html)):
        if source.is_file():
            content = source.read_bytes()
            if name.endswith(".json"):
                if not isinstance(json.loads(content), list):
                    raise ValueError("Les blocs Notion doivent être une liste")
            files[name] = content
    if not files:
        return None
    if destination.exists():
        raise ValueError("Cet instantané existe déjà ; aucun écrasement autorisé")
    metadata = {
        "edition": edition.isoformat(),
        "captured_at": now.isoformat(),
        "preview": preview,
        "notion_outcome": notion_outcome,
        "email_outcome": email_outcome,
        "source_commit": os.environ.get("GITHUB_SHA"),
        "run_url": f"https://github.com/eplr/veille-nif/actions/runs/{run_id}/attempts/{attempt}",
        "files_sha256": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".archive-") as temporary:
        staging = Path(temporary)
        for name, content in files.items():
            (staging / name).write_bytes(content)
        write_json(staging / "metadata.json", metadata)
        staging.rename(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition-date", type=date.fromisoformat)
    parser.add_argument("--notion-json", type=Path, default=Path("/tmp/notion-weekly.json"))
    parser.add_argument("--email-html", type=Path, default=Path("/tmp/veille.html"))
    args = parser.parse_args()
    now = today_utc()
    edition, _, _ = editorial.edition_calendar(now, args.edition_date)
    result = archive(
        DATA / "editions", now, edition,
        os.environ.get("GITHUB_RUN_ID", ""), os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        args.notion_json, args.email_html,
        os.environ.get("NOTION_OUTCOME", "unknown"), os.environ.get("EMAIL_OUTCOME", "unknown"),
    )
    print(f"[archive-edition] {result}" if result else "[archive-edition] aucun nouvel instantané à conserver")


if __name__ == "__main__":
    main()
