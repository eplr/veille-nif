"""Aperçu autonome des blocs Notion, sans dépendance tierce ni accès réseau."""
import argparse
import base64
import html
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def render(block):
    kind = block["type"]
    value = block[kind]
    if kind == "divider":
        return "<hr>"
    parts, plain = [], []
    for part in value.get("rich_text", []):
        raw = part["text"]["content"]
        plain.append(raw)
        content = html.escape(raw)
        link = part["text"].get("link")
        if link and urlsplit(link["url"]).scheme in {"https", "http"}:
            content = f'<a href="{html.escape(link["url"], quote=True)}">{content}</a>'
        parts.append(content)
    tag = {"heading_1": "h1", "heading_2": "h2", "heading_3": "h3",
           "quote": "blockquote", "toggle": "details"}.get(kind, "p")
    content = "".join(parts)
    label = "".join(plain)
    css = ""
    if kind == "quote" and "sources citées" in label:
        css = ' class="sources"'
    elif (kind == "quote" and "rencontres à l’agenda" in label) or label.startswith("Agenda –"):
        css = ' class="agenda"'
    if kind == "toggle":
        content = "<summary>" + content + "</summary>" + "".join(render(child) for child in value.get("children", []))
    return f"<{tag}{css}>{content}</{tag}>"


def build_preview(blocks, cover, stylesheet):
    image = base64.b64encode(cover).decode("ascii")
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Aperçu Nature in Finance</title><style>" + stylesheet + "</style></head><body>"
        "<aside>Aperçu HTML – le rendu natif Notion peut différer. Aucun envoi ni publication par cet outil.</aside>"
        '<header><img alt="Financer le vivant – forêt" src="data:image/png;base64,' + image + '"></header>'
        "<main>" + "".join(render(block) for block in blocks) + "</main></body></html>"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    blocks = json.loads(args.blocks.read_text(encoding="utf-8"))
    result = build_preview(blocks, (ROOT / "assets/notion-cover.png").read_bytes(),
                           (ROOT / "assets/weekly-preview.css").read_text(encoding="utf-8"))
    args.output.write_text(result, encoding="utf-8")


if __name__ == "__main__":
    main()
