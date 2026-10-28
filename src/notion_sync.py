"""Synchronise la bibliothèque publique locale vers Notion, sans importer les contributions privées.

Le jeton et l’identifiant de source de données proviennent exclusivement de
NOTION_TOKEN et NOTION_DATA_SOURCE_ID. Aucun secret n’est accepté en argument.
"""
import argparse
import os
import time
from datetime import datetime, timezone
from uuid import UUID

import requests

from lib import PAYS_LABELS, today_utc
from editorial import SECTIONS

API_VERSION = "2026-03-11"
API_ROOT = "https://api.notion.com/v1"
VALIDATION = ["À valider", "À revérifier", "Validé", "Rejeté"]
CONTENT_TYPES = ["Actualité", "Rapport", "Événement", "Financement",
                 "AO/RfP pour structures", "Mission de consultant", "Édition hebdomadaire"]


def definition(kind, options=()):
    body = {"options": [{"name": name} for name in options]} if options else {}
    return {"type": kind, kind: body}


SCHEMA = {
    "Nom": definition("title"),
    "Identifiant sync": definition("rich_text"),
    "Type": definition("select", CONTENT_TYPES),
    "URL": definition("url"),
    "Source": definition("rich_text"),
    "Publication": definition("date"),
    "Détection": definition("date"),
    "Dates événement": definition("date"),
    "Clôture": definition("date"),
    "Thématiques": definition("multi_select"),
    "Mots-clés": definition("multi_select"),
    "Écosystèmes": definition("multi_select"),
    "Zone": definition("select", PAYS_LABELS.values()),
    "Rubrique": definition("select", SECTIONS.values()),
    "Autorité": definition("select", ["Primaire", "Analyse", "Presse", "Communication"]),
    "Accès": definition("select", ["Libre", "Abonnement"]),
    "Origine": definition("select", ["Collecte automatique", "Agenda éditorial", "Fiche éditoriale", "Communauté"]),
    "Validation": definition("select", VALIDATION),
    "Vérifié le": definition("date"),
    "Lieu": definition("rich_text"),
    "Horaires": definition("rich_text"),
    "Contenu source": definition("rich_text"),
    "Notes": definition("rich_text"),
    "Dernière diffusion": definition("date"),
    "Dernière synchronisation": definition("date"),
}
# Ces champs appartiennent aux membres après la création. Les corps de pages
# ne sont jamais remplacés : les annotations et contributions restent intactes.
EDITORIAL_FIELDS = {"Validation", "Vérifié le", "Notes", "Écosystèmes"}


class NotionError(RuntimeError):
    pass


class NotionClient:
    def __init__(self, token, data_source_id, session=None):
        if not token or any(character.isspace() for character in token):
            raise NotionError("NOTION_TOKEN absent ou mal formé")
        try:
            self.data_source_id = str(UUID(data_source_id))
        except (ValueError, TypeError, AttributeError):
            raise NotionError("NOTION_DATA_SOURCE_ID doit être un UUID") from None
        self.session = session or requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}", "Notion-Version": API_VERSION,
            "Content-Type": "application/json",
        })

    def request(self, method, path, payload=None, files=None):
        safe_to_retry = method == "GET" or path.endswith("/query")
        for attempt in range(5):
            time.sleep(0.35)  # sous le budget habituel de trois requêtes par seconde
            try:
                options = {"json": payload} if files is None else {
                    "files": files, "headers": {"Content-Type": None},
                }
                response = self.session.request(
                    method, API_ROOT + path, timeout=30, allow_redirects=False, **options,
                )
            except requests.RequestException:
                if safe_to_retry and attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                # Ne pas exposer les en-têtes ni répéter une création ambiguë.
                raise NotionError("Erreur réseau Notion ; relancer pour réconcilier les entrées") from None
            try:
                body = response.json()
            except ValueError:
                body = {}
            if response.status_code == 200:
                return body
            retryable = response.status_code in {429, 529} or (
                safe_to_retry and response.status_code in {500, 502, 503, 504}
            )
            if body.get("additional_data", {}).get("rate_limit_reason") == "public_api_request_blocked":
                retryable = False
            if retryable and attempt < 4:
                try:
                    delay = max(0, float(response.headers.get("Retry-After", 2 ** attempt)))
                except (TypeError, ValueError):
                    delay = 2 ** attempt
                if delay > 120:
                    raise NotionError("Quota Notion indisponible plus de deux minutes ; réessayer plus tard")
                time.sleep(delay)
                continue
            # Aucun corps de réponse ni contenu de page dans les journaux.
            raise NotionError(f"Notion HTTP {response.status_code} ; vérifier accès, schéma ou quota")
        raise NotionError("Nombre maximal de tentatives Notion atteint")

    def schema(self):
        return self.request("GET", f"/data_sources/{self.data_source_id}")["properties"]

    def ensure_schema(self, apply=False):
        existing = self.schema()
        missing = {}
        for name, spec in SCHEMA.items():
            if name not in existing:
                missing[name] = spec
            elif existing[name]["type"] != spec["type"]:
                raise NotionError(f"Type incompatible pour la propriété {name} ; aucune migration effectuée")
        if apply and missing:
            self.request("PATCH", f"/data_sources/{self.data_source_id}", {"properties": missing})
        return list(missing)

    def pages(self):
        """Parcourir aussi les entrées archivées pour ne pas les recréer."""
        for archived in (False, True):
            cursor, cursors = None, set()
            while True:
                payload = {"page_size": 100, "is_archived": archived}
                if cursor:
                    payload["start_cursor"] = cursor
                body = self.request("POST", f"/data_sources/{self.data_source_id}/query", payload)
                if body.get("request_status", {}).get("type") == "incomplete":
                    raise NotionError("Lecture Notion incomplète ; synchronisation arrêtée sans création")
                yield from body.get("results", [])
                if not body.get("has_more"):
                    break
                cursor = body.get("next_cursor")
                if not cursor or cursor in cursors:
                    raise NotionError("Pagination Notion invalide")
                cursors.add(cursor)


def property_value(prop):
    """Normalise les réponses Notion avant comparaison, sans annotations."""
    kind = prop.get("type") or next(iter(prop), None)
    value = prop.get(kind)
    if kind in {"title", "rich_text"}:
        return "".join(part.get("plain_text", part.get("text", {}).get("content", "")) for part in (value or []))
    if kind == "select":
        return value.get("name") if value else None
    if kind == "multi_select":
        return sorted(part["name"] for part in (value or []))
    if kind == "date":
        def normalize(raw):
            if raw and "T" in raw:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
            return raw
        return (normalize(value["start"]), normalize(value.get("end"))) if value else None
    return value


def sync(client, records, dry_run=False, progress=False):
    from notion_content import canonical_url

    missing = client.ensure_schema()
    if missing:
        raise NotionError("Propriétés manquantes : lancer d’abord --init-schema")
    # Le parcours entier et la vérification d’unicité précèdent toute écriture.
    by_key, unmanaged_urls = {}, set()
    for page in client.pages():
        properties = page.get("properties", {})
        key = property_value(properties.get("Identifiant sync", {"rich_text": []}))
        if key:
            if key in by_key and by_key[key]["id"] != page["id"]:
                raise NotionError("Identifiants sync en double dans Notion ; corriger avant reprise")
            by_key[key] = page
        else:
            url = property_value(properties.get("URL", {"url": None}))
            if url:
                unmanaged_urls.add(canonical_url(url))
    stats = {"created": 0, "updated": 0, "unchanged": 0, "skipped_manual": 0, "skipped_archived": 0}
    timestamp = today_utc().isoformat()
    for index, record in enumerate(records, 1):
        key = property_value(record["Identifiant sync"])
        existing = by_key.get(key)
        if existing and any(existing.get(flag) for flag in ("archived", "is_archived", "in_trash")):
            stats["skipped_archived"] += 1
            continue
        if not existing and canonical_url(property_value(record["URL"])) in unmanaged_urls:
            stats["skipped_manual"] += 1
            continue
        if existing:
            properties = {
                name: value for name, value in record.items()
                if name not in EDITORIAL_FIELDS
                and property_value(existing["properties"].get(name, {})) != property_value(value)
            }
            if not properties:
                stats["unchanged"] += 1
                continue
            action = "updated"
        else:
            properties, action = dict(record), "created"
        properties["Dernière synchronisation"] = {"date": {"start": timestamp}}
        if not dry_run:
            if existing:
                client.request("PATCH", f"/pages/{existing['id']}", {"properties": properties})
            else:
                page = client.request("POST", "/pages", {
                    "parent": {"data_source_id": client.data_source_id}, "properties": properties,
                })
                by_key[key] = page
        stats[action] += 1
        if progress and index % 25 == 0:
            print(f"[notion-sync] {index}/{len(records)} contenus traités : {stats}", flush=True)
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--init-schema", action="store_true", help="ajouter uniquement les propriétés manquantes")
    mode.add_argument("--check-schema", action="store_true", help="contrôler le schéma sans modifier")
    parser.add_argument("--dry-run", action="store_true", help="prévisualiser sans aucune écriture Notion")
    parser.add_argument("--days", type=int, default=14, help="historique d’articles en jours ; 0 = tout")
    parser.add_argument("--limit", type=int, help="limiter le nombre de contenus pour un essai")
    args = parser.parse_args()
    if args.days < 0 or (args.limit is not None and args.limit < 1):
        parser.error("days doit être positif ou nul, limit strictement positif")
    try:
        client = NotionClient(os.environ.get("NOTION_TOKEN"), os.environ.get("NOTION_DATA_SOURCE_ID"))
        if args.init_schema or args.check_schema:
            missing = client.ensure_schema(apply=args.init_schema and not args.dry_run)
            print(f"[notion-sync] propriétés absentes : {len(missing)}"
                  + (" ; " + ", ".join(missing) if missing else ""))
            return 1 if args.check_schema and missing else 0
        from notion_content import load_records

        records = load_records(today_utc().date(), days=args.days)
        if args.limit:
            records = records[:args.limit]
        result = sync(client, records, dry_run=args.dry_run, progress=True)
        print(f"[notion-sync] {'aperçu' if args.dry_run else 'synchronisation'} : {result}")
        return 0
    except (NotionError, ValueError) as error:
        print(f"[notion-sync] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
