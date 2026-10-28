"""Veille hebdomadaire publique : sept jours d’actualités, sans propriétés techniques.

Le thème Notion du lecteur reste libre. Les couleurs sont les couleurs natives
de Notion, pas une reproduction CSS du PDF. Aucun email ni message WhatsApp.
"""
import argparse
import copy
import hashlib
import json
import os
import re
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID
from zoneinfo import ZoneInfo

import calls_watch
import daily_digest
import editorial
import events_watch
import news_archive
from lib import DEFAULT_THEME, is_noise, load_sources, normalize_title, parse_date, today_utc
from notion_content import canonical_url, load_articles, notion_date, rich_text, select
from notion_sync import NotionClient, NotionError, property_value

PAGE_KEY = "veille-nif:weekly-publication:current"
CONTAINER_KEY = "veille-nif:weekly-publication:management"
LEGACY_KEYS = {"veille-nif:daily-edition:current", "veille-nif:weekly-edition:current"}
PAGE_TITLE = "Veille – Nature in Finance"
# Conserver le marqueur initial pour remplacer aussi le prototype quotidien.
MARKER = "https://github.com/eplr/veille-nif#daily-v1-"
PARIS = ZoneInfo("Europe/Paris")


def select_weekly(items, now, limit=15):
    """Publications sur sept jours ; une sélection courte indépendante des envois."""
    if now.tzinfo is None:
        raise ValueError("L’instant de génération doit préciser son fuseau")
    sources = {source["nom"]: source for source in load_sources()}
    candidates = []
    for item in items:
        if is_noise(item["titre"]):
            continue
        raw = item.get("date_publication", "")
        # Une simple date calendaire ne permet pas de garantir les bornes horaires.
        if not raw or not re.search(r"\d{2}:\d{2}", str(raw)):
            continue
        published = parse_date(str(raw))
        if not published or not now - timedelta(days=7) <= published <= now:
            continue
        source = sources.get(item.get("source"), {})
        enriched = {**source, **{k: v for k, v in item.items() if v is not None}}
        themes = item.get("themes") or [DEFAULT_THEME]
        enriched["themes"] = themes.split(" | ") if isinstance(themes, str) else themes
        candidates.append(enriched)
    selected, links, titles = [], set(), set()
    for item in sorted(candidates, key=editorial.priority):
        url = canonical_url(item["lien"])
        title = re.sub(r"\bcop\s+(\d+)\b", r"cop\1", normalize_title(item["titre"]))
        duplicate = url in links or title in titles
        links.add(url)
        titles.add(title)
        if not duplicate:
            selected.append(item)
    if limit is None:
        return selected
    if limit < 1:
        raise ValueError("Le nombre d’actualités doit être strictement positif")
    science = next((item for item in selected if editorial.section_for(item) == "science"), None)
    chosen = [science] if science else []
    return chosen + [item for item in selected if item is not science][:limit - len(chosen)]


def text(value, *, color="default", bold=False, link=None):
    parts = rich_text(value)["rich_text"]
    for part in parts:
        part["annotations"] = {"color": color, "bold": bold}
        if link:
            part["text"]["link"] = {"url": canonical_url(link)}
    return parts


def block(kind, value="", color="default", bold=False, link=None):
    if kind == "divider":
        return {"object": "block", "type": kind, kind: {}}
    return {
        "object": "block", "type": kind,
        kind: {"rich_text": text(value, bold=bold, link=link), "color": color},
    }


def article_blocks(item):
    published = parse_date(item.get("date_publication", ""))
    meta = [item["source"]]
    if published:
        meta.append(published.astimezone(PARIS).strftime("%d/%m"))
    if item.get("acces") == "abonnement":
        meta.append("accès sur abonnement")
    return [
        block("paragraph", item["titre"], bold=True, link=item["lien"]),
        block("paragraph", " · ".join(meta), color="gray"),
    ]


def build_blocks(items, events, calls, now, calls_available=True, total_articles=None):
    local, start = now.astimezone(PARIS), (now - timedelta(days=7)).astimezone(PARIS)
    blocks = [
        block("paragraph", "L’HEBDO · NATURE IN FINANCE", color="green", bold=True),
        block("heading_1", "L’essentiel de la semaine"),
        block("paragraph", f"Édition du {local.strftime('%d/%m/%Y')} · "
              f"du {start.strftime('%d/%m')} au {local.strftime('%d/%m/%Y')}",
              color="gray"),
        {"object": "block", "type": "column_list", "column_list": {"children": [
            {"object": "block", "type": "column", "column": {"children": [
                block("quote", f"{number}\n{label}", color=color, bold=True),
            ]}}
            for number, label, color in (
                (len(items), "actualités sélectionnées", "green_background"),
                (len({item["source"] for item in items}), "sources citées", "yellow_background"),
                (len(events), "rencontres à l’agenda", "blue_background"),
            )
        ]}},
    ]
    if total_articles is not None and total_articles > len(items):
        blocks.append(block("paragraph", f"{len(items)} articles retenus parmi {total_articles} publications "
                            "datées repérées cette semaine. Les autres ressources restent dans la bibliothèque.",
                            color="gray"))
    if not items:
        blocks.append(block("paragraph", "Aucune nouvelle actualité retenue pour cette édition."))
    else:
        blocks.append(block("heading_2", "À retenir cette semaine", color="green"))
        for item in items[:3]:
            entry = block("numbered_list_item", item["titre"], bold=True, link=item["lien"])
            entry["numbered_list_item"]["children"] = [block("paragraph", item["source"], color="gray")]
            blocks.append(entry)
        blocks.append(block("divider"))
    colors = {"Réglementation et standards": "yellow_background", "Science et génie écologique": "green_background",
              "Financement et marchés": "purple_background", "Pratiques et engagements": "gray_background"}
    for label, group in editorial.group_news(items).items():
        blocks.append(block("heading_2", label, color=colors[label]))
        for item in group:
            blocks.extend(article_blocks(item))
        blocks.append(block("divider"))
    blocks.append(block("heading_2", "Agenda – 60 prochains jours", color="blue_background"))
    for event in events:
        flags = []
        if event.get("en_cours"):
            flags.append("en cours")
        if event.get("confiance") != "haute":
            flags.append("à revérifier")
        label = daily_digest.fr_range(event["debut"], event["fin"])
        if flags:
            label += " · " + " · ".join(flags)
        meta = [event.get(key) for key in ("lieu", "format", "horaire", "cout") if event.get(key)]
        blocks += [
            block("paragraph", label, color="blue", bold=True),
            block("paragraph", event["titre"], bold=True, link=event["lien"]),
            block("paragraph", " · ".join(meta), color="gray"),
            block("divider"),
        ]
    if not events:
        blocks.append(block("paragraph", "Aucun événement vérifié dans cette fenêtre."))
    for label, group in editorial.group_opportunities(calls).items():
        blocks.append(block("heading_2", label, color="purple_background"))
        for call in group:
            closing = parse_date(str(call.get("cloture") or ""))
            deadline = f"clôture le {closing.strftime('%d/%m/%Y')}" if closing else "clôture non précisée"
            blocks += [
                block("paragraph", call["titre"], bold=True, link=call["lien"]),
                block("paragraph", f"{call.get('porteur', '')} · {deadline}", color="gray"),
                block("divider"),
            ]
    if not calls_available:
        blocks.append(block("paragraph", "Source Carenews indisponible ou non collectée : "
                            "les opportunités peuvent être incomplètes ou provenir du dernier instantané.", color="orange"))
    blocks.append({"object": "block", "type": "toggle", "toggle": {
        "rich_text": text("Sources et méthode", color="gray"),
        "children": [block("paragraph", "Sélection automatique, non exhaustive : vérifiez la source avant de la citer. "
                           f"Publications du {start.strftime('%d/%m à %H:%M %Z')} au "
                           f"{local.strftime('%d/%m à %H:%M %Z')}. "
                           "Les dates absentes ou inexploitables sont exclues. L’agenda est validé à la main ; "
                           "les mentions « à revérifier » signalent une incertitude.", color="gray")],
    }})
    return blocks


def technical_key(page):
    return property_value(page.get("properties", {}).get("Identifiant sync", {}))


def check_active(page):
    if any(page.get(flag) for flag in ("archived", "is_archived", "in_trash")):
        raise NotionError("Page de publication archivée ; aucune recréation automatique")


def copy_properties(properties):
    """Copier les valeurs éditoriales avant tout déplacement hors de la base."""
    result = {}
    readonly = {"created_time", "created_by", "last_edited_time", "last_edited_by",
                "formula", "rollup", "unique_id", "button"}
    for name, prop in properties.items():
        kind = prop.get("type") or next(iter(prop), None)
        value = prop.get(kind)
        if kind in readonly:
            continue
        if kind in {"title", "rich_text"}:
            result[name] = {kind: [
                {key: copy.deepcopy(part[key]) for key in ("type", "text", "mention", "equation", "annotations") if key in part}
                for part in (value or [])
            ]}
        elif kind == "select":
            result[name] = {kind: {"name": value["name"]} if value else None}
        elif kind == "multi_select":
            result[name] = {kind: [{"name": part["name"]} for part in (value or [])]}
        elif kind in {"url", "date", "number", "checkbox", "email", "phone_number"}:
            result[name] = {kind: copy.deepcopy(value)}
        elif value:
            raise NotionError(f"Propriété {name} non prise en charge : déplacement annulé pour éviter une perte")
    return result


def get_page(client, page_id=None, create=True):
    entries = list(client.pages())
    managers = [page for page in entries if technical_key(page) == CONTAINER_KEY]
    if len(managers) > 1:
        raise NotionError("Plusieurs fiches de gestion de publication")
    manager = managers[0] if managers else None
    if manager:
        check_active(manager)
        if manager.get("parent", {}).get("data_source_id") != client.data_source_id:
            raise NotionError("Fiche de gestion étrangère à la bibliothèque")
    page = None
    if page_id:
        try:
            page = client.request("GET", f"/pages/{str(UUID(page_id))}")
        except ValueError:
            raise NotionError("NOTION_WEEKLY_PAGE_ID doit être un UUID") from None
    else:
        legacy = [p for p in entries if technical_key(p) in LEGACY_KEYS | {PAGE_KEY}]
        if len(legacy) > 1:
            raise NotionError("Plusieurs pages de veille portent le même identifiant technique")
        if legacy:
            page = legacy[0]
        elif manager:
            subpages = [b for b in children(client, manager["id"]) if b.get("type") == "child_page"]
            candidates = [b for b in subpages if b["child_page"].get("title") == PAGE_TITLE]
            if len(candidates) > 1:
                raise NotionError("Plusieurs pages de lecture sous la fiche de gestion")
            if candidates:
                page = client.request("GET", f"/pages/{candidates[0]['id']}")
            elif subpages:
                raise NotionError("La sous-page a été renommée : configurer NOTION_WEEKLY_PAGE_ID")
    legacy_properties = None
    if page:
        check_active(page)
        if page.get("parent", {}).get("data_source_id"):
            if page["parent"]["data_source_id"] != client.data_source_id or technical_key(page) not in LEGACY_KEYS | {PAGE_KEY}:
                raise NotionError("La page cible n’est pas une publication gérée par le programme")
            legacy_properties = copy_properties(page["properties"])
        elif not manager or page.get("parent", {}).get("page_id") != manager["id"]:
            raise NotionError("La page publique n’appartient pas à la fiche de gestion attendue")
    if not create:
        return page
    if not manager:
        properties = dict(legacy_properties or {})
        properties.update({
            "Nom": rich_text("Gestion de la veille hebdomadaire", "title"),
            "Identifiant sync": rich_text(CONTAINER_KEY), "Type": select("Édition hebdomadaire"),
        })
        manager = client.request("POST", "/pages", {
            "parent": {"data_source_id": client.data_source_id}, "properties": properties,
        })
    if legacy_properties:
        # Une sauvegarde d’un essai précédent ne doit pas écraser des annotations.
        for name, value in legacy_properties.items():
            if name not in {"Nom", "Identifiant sync", "Type"}:
                actual = manager["properties"].get(name, {})
                if property_value(actual) != property_value(value):
                    raise NotionError(f"Sauvegarde différente pour {name} : déplacement interrompu")
        page = client.request("POST", f"/pages/{page['id']}/move", {
            "parent": {"type": "page_id", "page_id": manager["id"]},
        })
        page = client.request("PATCH", f"/pages/{page['id']}", {
            "properties": {"title": rich_text(PAGE_TITLE, "title")},
        })
    elif not page:
        page = client.request("POST", "/pages", {
            "parent": {"page_id": manager["id"]},
            "properties": {"title": rich_text(PAGE_TITLE, "title")},
        })
    if page.get("parent", {}).get("page_id") != manager["id"]:
        raise NotionError("Le déplacement n’a pas produit une page de lecture autonome")
    if any(prop.get("type", next(iter(prop), None)) != "title" for prop in page["properties"].values()):
        raise NotionError("Des propriétés techniques restent présentes sur la page de lecture")
    page["_management_id"] = manager["id"]
    return page


def children(client, parent_id):
    cursor, seen = None, set()
    while True:
        query = {"page_size": 100}
        if cursor:
            query["start_cursor"] = cursor
        result = client.request("GET", f"/blocks/{parent_id}/children?{urlencode(query)}")
        yield from result.get("results", [])
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
        if not cursor or cursor in seen:
            raise NotionError("Pagination des blocs Notion invalide")
        seen.add(cursor)


def managed_state(root):
    if root.get("type") != "paragraph":
        return None
    for part in root["paragraph"].get("rich_text", []):
        url = (part.get("text", {}).get("link") or {}).get("url") or part.get("href", "")
        match = re.fullmatch(re.escape(MARKER) + r"(draft|active)-([0-9a-f]{64})", url or "")
        if match:
            return match.groups()
    return None


def root_block(state, digest):
    title = "Nature in Finance" + (" – édition en préparation" if state == "draft" else "")
    # Le lien identifie seulement ce sous-arbre ; les autres blocs restent manuels.
    parts = text(title, bold=True)
    parts[0]["text"]["link"] = {"url": f"{MARKER}{state}-{digest}"}
    return {"object": "block", "type": "paragraph", "paragraph": {
        "rich_text": parts, "color": "green_background" if state == "active" else "gray_background",
    }}


def publish(client, page, blocks, now):
    digest = hashlib.sha256(json.dumps(blocks, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    owned = [root for root in children(client, page["id"]) if managed_state(root)]
    current = next((root for root in owned if managed_state(root) == ("active", digest)), None)
    changed = current is None
    if changed:
        result = client.request("PATCH", f"/blocks/{page['id']}/children", {
            "children": [root_block("draft", digest)],
        })
        if len(result.get("results", [])) != 1:
            raise NotionError("Création du bloc de préparation incertaine ; édition précédente conservée")
        current = result["results"][0]
        for offset in range(0, len(blocks), 100):
            chunk = blocks[offset:offset + 100]
            result = client.request("PATCH", f"/blocks/{current['id']}/children", {"children": chunk})
            if len(result.get("results", [])) != len(chunk):
                raise NotionError("Ajout de blocs incomplet ; édition précédente conservée")
        client.request("PATCH", f"/blocks/{current['id']}", {
            "paragraph": root_block("active", digest)["paragraph"],
        })
        client.request("PATCH", f"/pages/{page['_management_id']}", {"properties": {
            "Publication": notion_date(now.isoformat()),
            "Dernière synchronisation": notion_date(now.isoformat()),
        }})
    # Ne toucher à l’ancienne édition qu’une fois la nouvelle entièrement prête.
    for root in owned:
        if root["id"] != current["id"]:
            client.request("PATCH", f"/blocks/{root['id']}", {"in_trash": True})
    return {"page_id": page["id"], "changed": changed, "blocks": len(blocks)}


def ensure_cover(client, page):
    """Joindre une couverture originale une seule fois, sans écraser un choix manuel."""
    if page.get("cover"):
        return
    path = Path(__file__).resolve().parents[1] / "assets" / "notion-cover.png"
    content = path.read_bytes()
    if not content.startswith(b"\x89PNG\r\n\x1a\n") or len(content) > 20 * 1024 * 1024:
        raise NotionError("Couverture PNG invalide ou trop volumineuse")
    upload = client.request("POST", "/file_uploads", {
        "mode": "single_part", "filename": path.name, "content_type": "image/png",
    })
    upload_id = str(UUID(upload["id"]))
    sent = client.request("POST", f"/file_uploads/{upload_id}/send",
                          files={"file": (path.name, content, "image/png")})
    if sent.get("status") != "uploaded":
        raise NotionError("Le transfert de la couverture n’est pas confirmé")
    client.request("PATCH", f"/pages/{page['id']}", {
        "cover": {"type": "file_upload", "file_upload": {"id": upload_id}},
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="composer sans accès ni écriture Notion")
    parser.add_argument("--collection-file", help="collecte JSON préparée à ajouter à l’archive")
    parser.add_argument("--json-out", help="aperçu JSON des blocs, hors des historiques")
    parser.add_argument("--calls-unavailable", action="store_true", help="signaler l’échec de collecte Carenews")
    parser.add_argument("--weekly", action="store_true", help="publier uniquement le lundi (sauf aperçu)")
    parser.add_argument("--max-articles", type=int, default=editorial.MAX_ARTICLES)
    args = parser.parse_args()
    try:
        now = today_utc()
        if args.max_articles < 1:
            raise ValueError("max-articles doit être strictement positif")
        if args.weekly and now.astimezone(PARIS).weekday() != 0 and not args.dry_run:
            print("[notion-weekly] collecte conservée ; prochaine publication le lundi")
            return 0
        articles = load_articles()
        if args.collection_file:
            path = Path(args.collection_file)
            if not path.is_file():
                raise ValueError("Fichier de collecte introuvable")
            articles = news_archive.merge(articles, news_archive.read_json(path, []))
        all_items = select_weekly(articles, now, limit=None)
        items = select_weekly(articles, now, limit=args.max_articles)
        today = now.astimezone(PARIS).date()
        events = events_watch.in_window(events_watch.load_events(), today)
        calls = news_archive.read_json(calls_watch.SNAPSHOT_FILE, [])
        calls = [c for c in calls if not c.get("cloture") or str(c["cloture"])[:10] >= today.isoformat()]
        blocks = build_blocks(items, events, calls, now,
                              calls_available=calls_watch.SNAPSHOT_FILE.exists() and not args.calls_unavailable,
                              total_articles=len(all_items))
        if args.json_out:
            news_archive.write_json(Path(args.json_out), blocks)
        print(f"[notion-weekly] {len(items)} actualité(s) retenues sur {len(all_items)} sur sept jours, "
              f"{len(events)} événement(s), {len(blocks)} blocs")
        if args.dry_run:
            print("[notion-weekly] aperçu uniquement ; aucune écriture Notion ni aucun email")
            return 0
        client = NotionClient(os.environ.get("NOTION_TOKEN"), os.environ.get("NOTION_DATA_SOURCE_ID"))
        if client.ensure_schema():
            raise NotionError("Schéma incomplet : initialiser la bibliothèque avant publication")
        page = get_page(client, os.environ.get("NOTION_WEEKLY_PAGE_ID") or os.environ.get("NOTION_DAILY_PAGE_ID"))
        ensure_cover(client, page)
        result = publish(client, page, blocks, now)
        page = client.request("GET", f"/pages/{page['id']}")
        print(f"[notion-weekly] {result}")
        print("[notion-weekly] lien Notion fixe :", page.get("url"))
        if page.get("public_url"):
            print("[notion-weekly] lien public à partager :", page["public_url"])
        else:
            print("[notion-weekly] publication publique non confirmée : ouvrir la page et choisir Partager > Publier")
        return 0
    except (NotionError, ValueError) as error:
        print(f"[notion-weekly] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
