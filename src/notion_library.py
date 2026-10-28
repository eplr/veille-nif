"""Configurer la navigation de la bibliothèque sans toucher aux fiches ni aux droits."""
import argparse
import os
from urllib.parse import urlencode

from notion_content import canonical_url, rich_text
from notion_sync import NotionClient, NotionError

DEFAULT_LIBRARY_URL = "https://seen-whitefish-f22.notion.site/3fa773b59fa48007b568dd6a1ef36a08"
PUBLIC_TYPES = ["Actualité", "Rapport", "Événement", "Financement",
                "AO/RfP pour structures", "Mission de consultant"]


def view_specs(schema):
    definitions = [
        ("Toutes les ressources", "list", PUBLIC_TYPES, ["Nom", "Type", "Publication", "Thématiques"], "Publication", "descending"),
        ("Actualités", "list", ["Actualité"], ["Nom", "Publication", "Source", "Thématiques"], "Publication", "descending"),
        ("Rapports", "list", ["Rapport"], ["Nom", "Publication", "Source", "Thématiques"], "Publication", "descending"),
        ("Agenda", "list", ["Événement"], ["Nom", "Dates événement", "Lieu"], "Dates événement", "ascending"),
        ("Opportunités", "table", ["Financement", "AO/RfP pour structures", "Mission de consultant"],
         ["Nom", "Type", "Source", "Clôture"], "Clôture", "ascending"),
    ]
    result = []
    for name, kind, types, visible, date_property, direction in definitions:
        required = set(visible) | {"Type", "Validation", "Thématiques", "Zone", date_property}
        if missing := required - schema.keys():
            raise NotionError("Propriétés absentes pour les vues : " + ", ".join(sorted(missing)))
        ordered = visible + [field for field in schema if field not in visible]
        properties = [{"property_id": schema[field]["id"], "visible": field in visible} for field in ordered]
        if kind == "table":
            for field, prop in zip(ordered, properties):
                if prop["visible"]:
                    prop.update({"width": 340 if field == "Nom" else 150, "wrap": True})
        result.append({
            "name": name,
            "type": kind,
            "filter": {"and": [
                {"property": "Type", "select": {"equals": types}},
                {"property": "Validation", "select": {"does_not_equal": "Rejeté"}},
            ]},
            "sorts": [{"property": date_property, "direction": direction}],
            "quick_filters": {schema[field]["id"]: {} for field in ("Type", "Thématiques", "Zone", "Validation", date_property)},
            "configuration": {"type": kind, "properties": properties, **({"wrap_cells": True} if kind == "table" else {})},
        })
    return result


def list_views(client, database_id):
    cursor, seen = None, set()
    while True:
        query = {"database_id": database_id, "page_size": 100}
        if cursor:
            query["start_cursor"] = cursor
        result = client.request("GET", "/views?" + urlencode(query))
        for reference in result.get("results", []):
            yield client.request("GET", f"/views/{reference['id']}")
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
        if not cursor or cursor in seen:
            raise NotionError("Pagination des vues invalide")
        seen.add(cursor)


def configure(client, apply=False):
    source = client.request("GET", f"/data_sources/{client.data_source_id}")
    database_id = source["parent"]["database_id"]
    specs = view_specs(source["properties"])
    existing = list(list_views(client, database_id))
    by_name = {}
    for view in existing:
        if view.get("data_source_id") == client.data_source_id:
            by_name.setdefault(view["name"], []).append(view)
    for spec in specs:
        matches = by_name.get(spec["name"], [])
        if len(matches) > 1:
            raise NotionError(f"Vues homonymes : {spec['name']} ; aucune suppression automatique")
        if matches and matches[0]["type"] != spec["type"]:
            raise NotionError(f"Disposition différente pour {spec['name']} ; conserver ou renommer la vue avant reprise")
    configured = []
    for index, spec in enumerate(specs):
        matches = by_name.get(spec["name"], [])
        if not apply:
            configured.append({"name": spec["name"], "action": "update" if matches else "create"})
            continue
        if matches:
            payload = {key: value for key, value in spec.items() if key != "type"}
            view = client.request("PATCH", f"/views/{matches[0]['id']}", payload)
        else:
            payload = {"database_id": database_id, "data_source_id": client.data_source_id, **spec}
            if index == 0:
                payload["position"] = {"type": "start"}
            view = client.request("POST", "/views", payload)
        configured.append({"name": spec["name"], "id": view["id"]})
    if apply:
        client.request("PATCH", f"/databases/{database_id}", {
            "title": rich_text("Bibliothèque – Nature in Finance", "title")["title"],
            "description": rich_text(
                "Choisissez une vue, puis filtrez par type, thématique, zone ou date. "
                "La loupe permet de rechercher un titre. Ouvrez une fiche pour accéder au lien source "
                "et aux tags détaillés. Ressources collectées automatiquement, non exhaustives : "
                "vérifiez les sources avant de les citer."
            )["rich_text"],
        })
        # L’ancienne vue complète reste disponible, sans destruction de réglages.
        for view in existing:
            if view.get("name") == "Untitled" and view.get("data_source_id") == client.data_source_id:
                client.request("PATCH", f"/views/{view['id']}", {"name": "Exploration détaillée"})
    return configured


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="appliquer les cinq vues ; sinon aperçu en lecture seule")
    args = parser.parse_args()
    try:
        client = NotionClient(os.environ.get("NOTION_TOKEN", "").strip(), os.environ.get("NOTION_DATA_SOURCE_ID"))
        views = configure(client, apply=args.apply)
        for view in views:
            print("[notion-library]", view)
        if args.apply:
            print("[notion-library] lien de navigation :", canonical_url(DEFAULT_LIBRARY_URL) + "?" +
                  urlencode({"v": views[0]["id"].replace("-", "")}))
        return 0
    except (NotionError, ValueError) as error:
        print("[notion-library]", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
