"""Contrats Notion hors réseau : migration additive, reprises et propriété des champs."""
import copy
import pathlib
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import notion_content as content
import notion_sync as notion

SOURCE_ID = "00000000-0000-0000-0000-000000000001"


def article(**overrides):
    return {
        "titre": "CSRD et biodiversité", "lien": "https://example.org/news",
        "source": "AMF", "pays": "FR", "themes": ["Reporting et standards"],
        "date_detection": "2026-10-28 07:00", "date_publication": "2026-10-27",
        **overrides,
    }


def record(**overrides):
    return content.article_record(article(**overrides), {})


class MemoryClient:
    data_source_id = SOURCE_ID

    def __init__(self, pages=()):
        self.entries = copy.deepcopy(list(pages))
        self.writes = []

    def ensure_schema(self):
        return []

    def pages(self):
        return iter(copy.deepcopy(self.entries))

    def request(self, method, path, payload):
        self.writes.append((method, path, copy.deepcopy(payload)))
        if method == "POST":
            page = {"id": str(len(self.entries) + 1), "properties": copy.deepcopy(payload["properties"])}
            self.entries.append(page)
        else:
            page = next(p for p in self.entries if path.endswith("/" + p["id"]))
            page["properties"].update(copy.deepcopy(payload["properties"]))
        return copy.deepcopy(page)


class TestContent(unittest.TestCase):
    def test_instantane_appels_ne_marque_pas_envoye_et_preserve_le_cache_en_cas_de_panne(self):
        import json
        import calls_watch
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "calls.json"
            call = {"titre": "Appel nature", "lien": "https://example.org/call",
                    "publie_le": date(2026, 10, 1), "cloture": date(2026, 11, 1)}
            with patch.object(calls_watch, "SNAPSHOT_FILE", path), patch.object(calls_watch, "commit") as commit:
                calls_watch.save_snapshot([call], {"ok": True})
                before = path.read_bytes()
                self.assertEqual(json.loads(before)[0]["cloture"], "2026-11-01")
                with self.assertRaises(ValueError):
                    calls_watch.save_snapshot([], {"ok": False})
                self.assertEqual(path.read_bytes(), before)
                commit.assert_not_called()

    def test_types_opportunites_et_rapport(self):
        for kind, expected in (("financement", "Financement"), ("ao_structure", "AO/RfP pour structures"),
                               ("mission_consultant", "Mission de consultant")):
            call = content.call_record({**article(), "type": kind, "cloture": "2026-11-01"})
            self.assertEqual(notion.property_value(call["Type"]), expected)
            self.assertEqual(notion.property_value(call["Validation"]), "À valider")
        report = content.report_record({
            **article(), "id": "version-1", "date": "2026-10-27", "verifie_le": "2026-10-28",
            "resultats": ["Résultat (p. 3)"], "methode": "Méthode", "limites": "Limites",
            "implications": "Lecture : implications",
        })
        self.assertEqual(notion.property_value(report["Validation"]), "Validé")
        self.assertIn("p. 3", notion.property_value(report["Contenu source"]))

    def test_identifiants_stables_et_sans_tracking(self):
        a = "https://EXAMPLE.org/news?id=1&utm_source=chat#section"
        b = "https://example.org/news?id=1"
        self.assertEqual(content.stable_id("article", a), content.stable_id("article", b))
        self.assertNotEqual(content.stable_id("article", b), content.stable_id("financement", b))
        for bad in ("javascript:alert(1)", "https://name:password@example.org"):
            with self.assertRaises(ValueError):
                content.canonical_url(bad)

    def test_champs_et_tags_article_sans_fausse_validation(self):
        props = content.article_record(article(), {"AMF": {"autorite": "primaire", "acces": "abonnement"}})
        self.assertEqual(notion.property_value(props["Validation"]), "À valider")
        self.assertEqual(notion.property_value(props["Autorité"]), "Primaire")
        self.assertEqual(notion.property_value(props["Accès"]), "Abonnement")
        self.assertEqual(notion.property_value(props["Rubrique"]), "Réglementation et standards")
        self.assertIn("CSRD", notion.property_value(props["Mots-clés"]))
        self.assertEqual(notion.property_value(props["Vérifié le"]), None)
        self.assertTrue(set(props) <= set(notion.SCHEMA))

    def test_evenement_a_reverifier_et_plage_de_dates(self):
        event = {
            "id": "event-1", "titre": "Rencontre", "lien": "https://example.org/event",
            "debut": date(2026, 11, 2), "fin": date(2026, 11, 3),
            "verifie_le": date(2026, 10, 7), "confiance": "moyenne",
        }
        props = content.event_record(event)
        self.assertEqual(notion.property_value(props["Validation"]), "À revérifier")
        self.assertEqual(notion.property_value(props["Dates événement"]), ("2026-11-02", "2026-11-03"))
        event["confiance"] = "haute"
        self.assertEqual(notion.property_value(content.event_record(event)["Validation"]), "Validé")
        event.pop("confiance")
        self.assertEqual(notion.property_value(content.event_record(event)["Validation"]), "À revérifier")

    def test_dates_et_limites_rich_text(self):
        self.assertEqual(notion.property_value(content.rich_text("\u200bTitre", "title")), "Titre")
        self.assertEqual(content.notion_date("inconnue"), {"date": None})
        self.assertEqual(content.notion_date(None), {"date": None})
        self.assertEqual(notion.property_value(content.notion_date("2026-10-28T07:00:47Z")),
                         notion.property_value(content.notion_date("2026-10-28T07:00:00Z")))
        value = content.rich_text("a" * 5000)
        self.assertEqual(len(value["rich_text"]), 3)
        self.assertEqual(notion.property_value(value), "a" * 5000)
        self.assertEqual(notion.property_value({"date": {"start": "2026-10-28T07:00:00.000Z"}}),
                         notion.property_value(content.notion_date("2026-10-28 07:00")))

    def test_reprise_csv_et_dedup_sans_modification_locale(self):
        import news_archive
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "news_log.csv").write_text(
                "titre,lien,source,pays,themes,date_detection,date_publication\n"
                "Actualité,https://example.org/news,AMF,FR,Reporting et standards,2026-10-28 07:00,2026-10-27\n",
                encoding="utf-8",
            )
            with patch.object(content, "OUTPUT", root), \
                    patch.object(news_archive, "load", return_value=[article()]), \
                    patch.object(news_archive, "deliveries", return_value={}), \
                    patch.object(content.events_watch, "load_events", return_value=[]), \
                    patch.object(content.reports, "load", return_value=[]), \
                    patch.object(content.calls_watch, "SNAPSHOT_FILE", root / "absent.json"):
                records = content.load_records(date(2026, 10, 28))
                self.assertEqual(len(records), 1)
                self.assertEqual(len(content.load_records(date(2026, 12, 1))), 0)
                self.assertEqual(len(content.load_records(date(2026, 12, 1), days=0)), 1)
            self.assertEqual(len(list(root.iterdir())), 1)


class TestSynchronization(unittest.TestCase):
    def test_deux_passages_sans_doublon_ni_mise_a_jour_inutile(self):
        client = MemoryClient()
        self.assertEqual(notion.sync(client, [record()])["created"], 1)
        self.assertEqual(notion.sync(client, [record()])["unchanged"], 1)
        self.assertEqual(len(client.entries), 1)
        self.assertEqual(len(client.writes), 1)

    def test_mise_a_jour_preserve_validation_notes_et_ecosystemes(self):
        client = MemoryClient()
        notion.sync(client, [record()])
        current = client.entries[0]["properties"]
        current["Validation"] = content.select("Rejeté")
        current["Notes"] = content.rich_text("Annotation communautaire")
        current["Écosystèmes"] = content.multi_select(["Zones humides"])
        current["Vérifié le"] = content.notion_date("2026-10-28")
        notion.sync(client, [record(titre="CSRD : mise à jour")])
        updated = client.writes[-1][2]["properties"]
        self.assertEqual(notion.property_value(updated["Nom"]), "CSRD : mise à jour")
        self.assertFalse(notion.EDITORIAL_FIELDS & updated.keys())
        self.assertEqual(notion.property_value(current["Validation"]), "Rejeté")
        self.assertEqual(notion.property_value(current["Notes"]), "Annotation communautaire")

    def test_apercu_necrit_rien(self):
        client = MemoryClient()
        self.assertEqual(notion.sync(client, [record()], dry_run=True)["created"], 1)
        self.assertEqual(client.writes, [])
        self.assertEqual(client.entries, [])

    def test_entrees_manuelles_et_archivees_non_remplacees(self):
        manual = {"id": "manual", "properties": {"URL": {"url": "https://example.org/news"}}}
        client = MemoryClient([manual])
        self.assertEqual(notion.sync(client, [record()])["skipped_manual"], 1)
        client = MemoryClient([{"id": "archived", "archived": True, "properties": record()}])
        self.assertEqual(notion.sync(client, [record()])["skipped_archived"], 1)
        self.assertEqual(client.writes, [])

    def test_doublons_distants_font_echouer_avant_ecriture(self):
        client = MemoryClient([{"id": str(i), "properties": record()} for i in range(2)])
        with self.assertRaises(notion.NotionError):
            notion.sync(client, [record()])
        self.assertEqual(client.writes, [])


class TestClient(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.session.headers = {}
        self.client = notion.NotionClient("test-token", SOURCE_ID, session=self.session)
        self.sleep = patch.object(notion.time, "sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def response(self, status=200, body=None, headers=None):
        response = Mock()
        response.status_code, response.headers = status, headers or {}
        response.json.return_value = body or {}
        return response

    def test_migration_ajoute_uniquement_les_proprietes_absentes(self):
        self.session.request.side_effect = [
            self.response(body={"properties": {"Nom": {"type": "title"}, "Personnel": {"type": "rich_text"}}}),
            self.response(),
        ]
        missing = self.client.ensure_schema(apply=True)
        properties = self.session.request.call_args.kwargs["json"]["properties"]
        self.assertEqual(set(properties), set(notion.SCHEMA) - {"Nom"})
        self.assertNotIn("Personnel", properties)
        self.assertEqual(set(missing), set(properties))

    def test_type_incompatible_aucune_migration_partielle(self):
        self.session.request.return_value = self.response(body={
            "properties": {"Nom": {"type": "title"}, "URL": {"type": "rich_text"}},
        })
        with self.assertRaises(notion.NotionError):
            self.client.ensure_schema(apply=True)
        self.assertEqual(self.session.request.call_count, 1)

    def test_pagination_et_archivees(self):
        self.session.request.side_effect = [
            self.response(body={"results": [{"id": "a"}], "has_more": True, "next_cursor": "cursor"}),
            self.response(body={"results": [{"id": "b"}], "has_more": False}),
            self.response(body={"results": [{"id": "c", "is_archived": True}], "has_more": False}),
        ]
        self.assertEqual([p["id"] for p in self.client.pages()], ["a", "b", "c"])
        calls = self.session.request.call_args_list
        self.assertEqual(calls[1].kwargs["json"]["start_cursor"], "cursor")
        self.assertTrue(calls[2].kwargs["json"]["is_archived"])

    def test_429_respecte_retry_after(self):
        self.session.request.side_effect = [
            self.response(429, headers={"Retry-After": "7"}), self.response(body={"ok": True}),
        ]
        self.assertEqual(self.client.request("GET", "/users/me"), {"ok": True})
        notion.time.sleep.assert_any_call(7)

    def test_creation_ambigue_non_repetee_et_secret_non_affiche(self):
        self.session.request.side_effect = requests.Timeout("test-token")
        with self.assertRaises(notion.NotionError) as error:
            self.client.request("POST", "/pages", {})
        self.assertNotIn("test-token", str(error.exception))
        self.assertEqual(self.session.request.call_count, 1)

    def test_503_sur_creation_non_repetee(self):
        self.session.request.return_value = self.response(503)
        with self.assertRaises(notion.NotionError):
            self.client.request("POST", "/pages", {})
        self.assertEqual(self.session.request.call_count, 1)

    def test_lecture_incomplete_refusee(self):
        self.session.request.return_value = self.response(body={
            "request_status": {"type": "incomplete"}, "results": [], "has_more": False,
        })
        with self.assertRaises(notion.NotionError):
            list(self.client.pages())


if __name__ == "__main__":
    unittest.main()
