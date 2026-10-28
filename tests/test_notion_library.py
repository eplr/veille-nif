"""Navigation : vues ciblées, champs techniques masqués et liens publics durables."""
import copy
import pathlib
import sys
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import notion_library as library
import notion_weekly as weekly
from notion_sync import NotionError, SCHEMA
from test_notion_weekly import NOW, article


def schema():
    return {name: {"id": f"field-{index}", "type": value["type"]}
            for index, (name, value) in enumerate(SCHEMA.items())}


class ViewClient:
    data_source_id = "source"

    def __init__(self, views=()):
        self.views, self.writes = copy.deepcopy(list(views)), []

    def request(self, method, path, payload=None):
        if method == "GET" and path.startswith("/data_sources/"):
            return {"parent": {"database_id": "database"}, "properties": schema()}
        if method == "GET" and path.startswith("/views?"):
            return {"results": [{"id": v["id"]} for v in self.views], "has_more": False}
        if method == "GET" and path.startswith("/views/"):
            return copy.deepcopy(next(v for v in self.views if path.endswith(v["id"])))
        self.writes.append((method, path, copy.deepcopy(payload)))
        if method == "PATCH" and path.startswith("/databases/"):
            return {"id": "database", **payload}
        if method == "POST" and path == "/views":
            view = {"id": f"view-{len(self.views)}", **copy.deepcopy(payload)}
            self.views.append(view)
            return copy.deepcopy(view)
        if method == "PATCH" and path.startswith("/views/"):
            view = next(v for v in self.views if path.endswith(v["id"]))
            view.update(copy.deepcopy(payload))
            return copy.deepcopy(view)
        raise AssertionError((method, path))


class TestLibrary(unittest.TestCase):
    def test_cinq_vues_et_champs_techniques_masques(self):
        fields = schema()
        specs = library.view_specs(fields)
        self.assertEqual(len(specs), 5)
        self.assertEqual(specs[0]["name"], "Toutes les ressources")
        for spec in specs:
            properties = {p["property_id"]: p for p in spec["configuration"]["properties"]}
            for name in ("Identifiant sync", "Notes", "Dernière synchronisation"):
                self.assertFalse(properties[fields[name]["id"]]["visible"])
            allowed = spec["filter"]["and"][0]["select"]["equals"]
            self.assertNotIn("Édition hebdomadaire", allowed)
            self.assertEqual(spec["filter"]["and"][1]["select"]["does_not_equal"], "Rejeté")

    def test_apercu_lecture_seule(self):
        client = ViewClient()
        self.assertEqual(len(library.configure(client)), 5)
        self.assertEqual(client.writes, [])

    def test_reprise_sans_nouvelles_vues_ni_suppression(self):
        client = ViewClient([{"id": "original", "name": "Untitled", "type": "table", "data_source_id": "source"}])
        first = library.configure(client, apply=True)
        second = library.configure(client, apply=True)
        self.assertEqual(first, second)
        self.assertEqual(len(client.views), 6)
        self.assertEqual(client.views[0]["name"], "Exploration détaillée")
        self.assertFalse(any(method == "DELETE" or "/pages" in path for method, path, _ in client.writes))

    def test_schema_absent_refuse(self):
        with self.assertRaises(NotionError):
            library.view_specs({})

    def test_liens_en_haut_et_en_bas_de_la_veille(self):
        url = library.DEFAULT_LIBRARY_URL + "?v=vue-publique"
        blocks = weekly.build_blocks([article()], [], [], NOW, library_url=url)
        links = [(index, part["text"]["content"]) for index, block in enumerate(blocks)
                 for part in block.get(block["type"], {}).get("rich_text", [])
                 if (part.get("text", {}).get("link") or {}).get("url") == url]
        self.assertEqual(len(links), 2)
        self.assertIn("bibliothèque complète", links[0][1])
        self.assertLess(links[0][0], len(blocks) // 2)
        self.assertGreater(links[1][0], len(blocks) // 2)
