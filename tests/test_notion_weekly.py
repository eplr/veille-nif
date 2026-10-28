"""Veille hebdomadaire : page de lecture, migration des propriétés et présentation."""
import contextlib
import copy
import io
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import daily_digest
import news_archive
import news_watch
import notion_weekly as daily
from notion_content import rich_text
from notion_sync import NotionError, property_value

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
SOURCE_ID = str(UUID(int=1))


def article(index=0, **overrides):
    return {
        "titre": f"Actualité biodiversité {index}", "lien": f"https://example.org/{index}",
        "date_publication": "2026-10-28T09:00:00Z", "date_detection": "2026-10-28 10:00",
        "source": "Source", "pays": "FR", "themes": ["Science et génie écologique"],
        "canal": "rss", "autorite": "presse", **overrides,
    }


class BlockClient:
    data_source_id = SOURCE_ID

    def __init__(self):
        self.entries, self.nodes, self.contents, self.writes = [], {}, {}, []
        self.append_count, self.fail_on_append = 0, None

    def pages(self):
        return iter(copy.deepcopy(self.entries))

    def add_subpage(self, page):
        title = page["properties"].get("Nom", page["properties"].get("title"))
        self.nodes[page["id"]] = {"id": page["id"], "type": "child_page",
                                 "child_page": {"title": property_value(title)}}
        self.contents.setdefault(page["parent"]["page_id"], []).append(page["id"])

    def request(self, method, path, payload=None):
        clean, query = urlsplit(path).path, parse_qs(urlsplit(path).query)
        if method == "GET" and clean.startswith("/pages/"):
            return copy.deepcopy(next(p for p in self.entries if clean.endswith(p["id"])))
        if method == "GET" and clean.endswith("/children"):
            parent = clean.split("/")[2]
            children = [self.nodes[key] for key in self.contents.get(parent, [])
                        if not self.nodes[key].get("in_trash")]
            offset = int(query.get("start_cursor", [0])[0])
            chunk = children[offset:offset + 100]
            more = offset + len(chunk) < len(children)
            return {"results": copy.deepcopy(chunk), "has_more": more,
                    "next_cursor": str(offset + len(chunk)) if more else None}
        self.writes.append((method, clean, copy.deepcopy(payload)))
        if method == "POST" and clean == "/pages":
            page = {"id": str(UUID(int=1000 + len(self.entries))), **copy.deepcopy(payload)}
            self.entries.append(page)
            if "page_id" in page["parent"]:
                self.add_subpage(page)
            return copy.deepcopy(page)
        if method == "POST" and clean.endswith("/move"):
            key = clean.split("/")[2]
            page = next(p for p in self.entries if p["id"] == key)
            title = page["properties"].get("Nom", page["properties"].get("title"))
            page["parent"] = copy.deepcopy(payload["parent"])
            page["properties"] = {"title": copy.deepcopy(title)}
            self.add_subpage(page)
            return copy.deepcopy(page)
        if method == "PATCH" and clean.endswith("/children"):
            self.append_count += 1
            if self.append_count == self.fail_on_append:
                raise NotionError("Échec d’ajout simulé")
            parent = clean.split("/")[2]
            results = []
            for value in payload["children"]:
                key = f"node-{len(self.nodes)}"
                self.nodes[key] = {"id": key, **copy.deepcopy(value)}
                self.contents.setdefault(parent, []).append(key)
                results.append(self.nodes[key])
            return {"results": copy.deepcopy(results)}
        if method == "PATCH" and clean.startswith("/pages/"):
            page = next(p for p in self.entries if clean.endswith(p["id"]))
            page["properties"].update(copy.deepcopy(payload.get("properties", {})))
            if "cover" in payload:
                page["cover"] = copy.deepcopy(payload["cover"])
            if page["id"] in self.nodes and self.nodes[page["id"]].get("type") == "child_page":
                self.nodes[page["id"]]["child_page"]["title"] = property_value(page["properties"]["title"])
            return copy.deepcopy(page)
        if method == "PATCH" and clean.startswith("/blocks/"):
            key = clean.split("/")[2]
            self.nodes[key].update(copy.deepcopy(payload))
            return copy.deepcopy(self.nodes[key])
        raise AssertionError((method, path))


class TestWeeklySelection(unittest.TestCase):
    def test_bornes_exactes_et_dates_inexploitables(self):
        values = [
            article(0, date_publication=(NOW - timedelta(days=7)).isoformat()),
            article(1, date_publication=NOW.isoformat()),
            article(2, date_publication=(NOW - timedelta(days=7, microseconds=1)).isoformat()),
            article(3, date_publication=(NOW + timedelta(microseconds=1)).isoformat()),
            article(4, date_publication=""),
            article(5, date_publication="2026-10-28"),
            article(6, date_publication="date incorrecte 12:00"),
        ]
        result = daily.select_weekly(values, NOW)
        self.assertEqual({i["lien"] for i in result}, {values[0]["lien"], values[1]["lien"]})

    def test_fuseaux_et_changement_heure(self):
        now = datetime(2026, 10, 25, 8, tzinfo=timezone.utc)
        values = [article(0, date_publication="2026-10-18T10:00:00+02:00"),
                  article(1, date_publication="2026-10-18T09:59:59+02:00")]
        self.assertEqual(len(daily.select_weekly(values, now)), 1)
        with self.assertRaises(ValueError):
            daily.select_weekly([], datetime(2026, 10, 28, 12))

    def test_selection_courte_sans_filtre_deja_envoye(self):
        with patch.object(news_archive, "deliveries", side_effect=AssertionError("Historique non pertinent")):
            values = [article(i) for i in range(40)]
            self.assertEqual(len(daily.select_weekly(values, NOW)), 15)
            self.assertEqual(len(daily.select_weekly(values, NOW, limit=None)), 40)

    def test_annonces_de_postdoctorat_exclues(self):
        result = daily.select_weekly([article(titre="Post-doctorant(e) en mise à l’échelle écologique (H/F)")], NOW)
        self.assertEqual(result, [])

    def test_deduplication_et_priorite_source(self):
        values = [article(0), article(1, titre=article()["titre"], autorite="primaire"),
                  article(2, lien=article()["lien"] + "?utm_source=chat")]
        result = daily.select_weekly(values, NOW)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["autorite"], "primaire")
        values = [article(3, titre="COP-17 biodiversité : nouvelles décisions"),
                  article(4, titre="COP17 biodiversité : nouvelles décisions")]
        self.assertEqual(len(daily.select_weekly(values, NOW)), 1)

    def test_rendu_proche_pdf_et_agenda_complet(self):
        events = [{"id": str(i), "titre": f"Événement {i}", "debut": date(2026, 11, 1),
                   "fin": date(2026, 11, 2), "lieu": "En ligne", "format": "visio",
                   "horaire": "10:00 CET", "cout": "Gratuit", "confiance": "moyenne",
                   "lien": f"https://example.org/event/{i}"} for i in range(8)]
        items = [article(), article(1, canal="zone", themes=["Thème complémentaire"], acces="abonnement")]
        blocks = daily.build_blocks(items, events, [], NOW, calls_available=False)
        content = json.dumps(blocks, ensure_ascii=False)
        for expected in ("L’essentiel de la semaine", "Science et génie écologique",
                         "accès sur abonnement", "Événement 7", "à revérifier", "Carenews"):
            self.assertIn(expected, content)
        self.assertNotIn("désinscription", content)
        self.assertIn("yellow_background", content)
        self.assertIn("blue_background", content)
        self.assertNotIn("epl@", content)
        self.assertNotIn("Thème complémentaire", content)
        self.assertNotIn("Identifiant sync", content)
        self.assertIn("column_list", content)

    def test_apercu_sans_jeton_ni_ecriture_notion(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "blocks.json"
            with patch.object(sys, "argv", ["notion_weekly.py", "--dry-run", "--json-out", str(target)]), \
                    patch.object(daily, "today_utc", return_value=NOW), \
                    patch.object(daily, "load_articles", return_value=[article()]), \
                    patch.object(daily.events_watch, "load_events", return_value=[]), \
                    patch.object(daily, "NotionClient") as client, \
                    patch.object(daily_digest, "send_email") as email, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(daily.main(), 0)
                client.assert_not_called()
                email.assert_not_called()
            self.assertIsInstance(json.loads(target.read_text()), list)


class TestWeeklyPublication(unittest.TestCase):
    def test_migration_conserve_id_notes_et_blocs_hors_base(self):
        client = BlockClient()
        legacy = client.request("POST", "/pages", {
            "parent": {"data_source_id": SOURCE_ID},
            "properties": {
                "Nom": rich_text("Veille du jour", "title"),
                "Identifiant sync": rich_text("veille-nif:daily-edition:current"),
                "Notes": rich_text("Annotation à préserver"),
                "URL": {"url": "https://example.org/source-originale"},
            },
        })
        client.request("PATCH", f"/blocks/{legacy['id']}/children",
                       {"children": [daily.block("paragraph", "Texte manuel conservé")]})
        page = daily.get_page(client, legacy["id"])
        self.assertEqual(page["id"], legacy["id"])
        self.assertEqual(set(page["properties"]), {"title"})
        manager = next(p for p in client.entries if p["id"] == page["_management_id"])
        self.assertEqual(property_value(manager["properties"]["Notes"]), "Annotation à préserver")
        self.assertEqual(property_value(manager["properties"]["URL"]), "https://example.org/source-originale")
        self.assertEqual(len(list(daily.children(client, page["id"]))), 1)
        again = daily.get_page(client)
        self.assertEqual(again["id"], legacy["id"])
        self.assertEqual(len(client.entries), 2)

    def test_migration_refuse_un_champ_non_copiable_avant_deplacement(self):
        client = BlockClient()
        legacy = client.request("POST", "/pages", {
            "parent": {"data_source_id": SOURCE_ID},
            "properties": {
                "Nom": rich_text("Veille du jour", "title"),
                "Identifiant sync": rich_text("veille-nif:daily-edition:current"),
                "Lien privé": {"type": "relation", "relation": [{"id": SOURCE_ID}]},
            },
        })
        before = len(client.writes)
        with self.assertRaises(NotionError):
            daily.get_page(client, legacy["id"])
        self.assertEqual(len(client.writes), before)
        self.assertEqual(legacy["parent"]["data_source_id"], SOURCE_ID)

    def test_couverture_televersee_une_fois_sans_ecraser_un_choix_manuel(self):
        client = Mock()
        client.request.side_effect = [{"id": SOURCE_ID}, {"status": "uploaded"}, {}]
        daily.ensure_cover(client, {"id": SOURCE_ID})
        self.assertEqual(client.request.call_count, 3)
        sent = client.request.call_args_list[1]
        self.assertIn("files", sent.kwargs)
        self.assertEqual(sent.kwargs["files"]["file"][2], "image/png")
        client.reset_mock()
        daily.ensure_cover(client, {"id": SOURCE_ID, "cover": {"type": "external"}})
        client.request.assert_not_called()

    def setUp(self):
        self.client = BlockClient()
        self.page = daily.get_page(self.client)
        self.blocks = daily.build_blocks([article()], [], [], NOW)

    def roots(self):
        return list(daily.children(self.client, self.page["id"]))

    def test_page_unique_et_republication_identique_sans_ecriture(self):
        first = daily.publish(self.client, self.page, self.blocks, NOW)
        page = daily.get_page(self.client)
        writes = len(self.client.writes)
        second = daily.publish(self.client, page, self.blocks, NOW)
        self.assertEqual(page["id"], self.page["id"])
        self.assertEqual(len(self.client.entries), 2)
        self.assertEqual(set(page["properties"]), {"title"})
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(len(self.client.writes), writes)

    def test_notes_manuelles_preservees_et_ancienne_zone_archivee(self):
        self.client.request("PATCH", f"/blocks/{self.page['id']}/children",
                            {"children": [daily.block("paragraph", "Note manuelle")]})
        daily.publish(self.client, self.page, self.blocks, NOW)
        updated = daily.build_blocks([article(2)], [], [], NOW)
        daily.publish(self.client, self.page, updated, NOW)
        roots = self.roots()
        self.assertEqual(len(roots), 2)
        self.assertEqual(len([r for r in roots if daily.managed_state(r)]), 1)
        self.assertTrue(any(property_value({"rich_text": r["paragraph"]["rich_text"]}) == "Note manuelle" for r in roots))

    def test_echec_partiel_conserve_derniere_edition_complete_et_reprise(self):
        daily.publish(self.client, self.page, self.blocks, NOW)
        old = next(r for r in self.roots() if daily.managed_state(r)[0] == "active")
        many = [daily.block("paragraph", f"Bloc {i}") for i in range(205)]
        self.client.fail_on_append = self.client.append_count + 3
        with self.assertRaises(NotionError):
            daily.publish(self.client, self.page, many, NOW)
        self.assertFalse(self.client.nodes[old["id"]].get("in_trash", False))
        self.assertTrue(any(daily.managed_state(r)[0] == "draft" for r in self.roots()))
        self.client.fail_on_append = None
        daily.publish(self.client, self.page, many, NOW)
        self.assertEqual(len(self.roots()), 1)
        self.assertEqual(daily.managed_state(self.roots()[0])[0], "active")
        self.assertEqual(len(list(daily.children(self.client, self.roots()[0]["id"]))), 205)
        self.assertTrue(all(len(payload["children"]) <= 100 for _, _, payload in self.client.writes if "children" in payload))

    def test_page_archivee_ou_cible_etrangere_refusee(self):
        self.client.entries[0]["in_trash"] = True
        with self.assertRaises(NotionError):
            daily.get_page(self.client)
        self.client.entries[0]["in_trash"] = False
        self.client.entries[0]["properties"]["Identifiant sync"] = rich_text("autre")
        with self.assertRaises(NotionError):
            daily.get_page(self.client, self.page["id"])
        self.assertEqual(len(self.client.entries), 2)

    def test_doublons_de_page_refuses(self):
        other = copy.deepcopy(self.client.entries[0])
        other["id"] = str(UUID(int=2000))
        self.client.entries.append(other)
        with self.assertRaises(NotionError):
            daily.get_page(self.client)


class TestPreparedCollection(unittest.TestCase):
    def test_pas_de_publication_en_semaine_hors_apercu(self):
        with patch.object(sys, "argv", ["notion_weekly.py", "--weekly"]), \
                patch.object(daily, "today_utc", return_value=NOW), \
                patch.object(daily, "load_articles") as articles, \
                patch.object(daily, "NotionClient") as client, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(daily.main(), 0)
            articles.assert_not_called()
            client.assert_not_called()
    def test_collecte_illisible_ne_remplace_pas_le_fichier_prepare(self):
        def unreadable(*args, health, **kwargs):
            health["entries_read"] = 0
            return [], None
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "collection.json"
            path.write_text('["précédent"]', encoding="utf-8")
            with patch.object(sys, "argv", ["news_watch.py", "--dry-run", "--require-source-data", "--json-out", str(path)]), \
                    patch.object(news_watch, "collect", side_effect=unreadable), \
                    patch.object(news_watch, "commit") as commit:
                with self.assertRaises(SystemExit):
                    news_watch.main()
                commit.assert_not_called()
            self.assertEqual(json.loads(path.read_text()), ["précédent"])

    def test_sources_lisibles_sans_nouvelle_actualite_autorisent_edition_vide(self):
        def readable(*args, health, **kwargs):
            health["entries_read"] = 10
            return [], None
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "collection.json"
            with patch.object(sys, "argv", ["news_watch.py", "--dry-run", "--require-source-data", "--json-out", str(path)]), \
                    patch.object(news_watch, "collect", side_effect=readable), \
                    patch.object(news_watch, "commit") as commit:
                self.assertEqual(news_watch.main(), 0)
                commit.assert_not_called()
            self.assertEqual(json.loads(path.read_text()), [])

    def test_email_reutilise_collecte_sans_refaire_requetes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "collection.json"
            path.write_text(json.dumps([article()]), encoding="utf-8")
            with patch.object(sys, "argv", ["daily_digest.py", "--collection-file", str(path), "--dry-run"]), \
                    patch.object(daily_digest, "today_utc", return_value=NOW), \
                    patch.object(news_watch, "collect") as collect, \
                    patch.object(news_watch, "commit") as commit, \
                    patch.object(daily_digest.calls_watch, "run", return_value=([], {"ok": True})), \
                    patch.object(daily_digest, "send_email") as email, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(daily_digest.main(), 0)
                collect.assert_not_called()
                commit.assert_not_called()
                email.assert_not_called()

    def test_workflow_separe_collecte_page_et_email_hebdomadaire(self):
        path = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/veille.yml"
        data = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        steps = data["jobs"]["veille"]["steps"]
        collect = next(step for step in steps if step.get("id") == "collect")
        publisher = next(step for step in steps if "src/notion_weekly.py" in step.get("run", ""))
        email = next(step for step in steps if "src/daily_digest.py" in step.get("run", ""))
        self.assertIn("--require-source-data", collect["run"])
        self.assertIn("steps.collect.outcome == 'success'", publisher["if"])
        self.assertIn("always()", publisher["if"])
        self.assertIn("--dry-run", publisher["run"])
        self.assertIn("--weekly", publisher["run"])
        self.assertIn("INPUT_PUBLISH_NOW", publisher["env"])
        self.assertIn("--weekly", email["run"])
        self.assertIn("--collection-file", email["run"])
        self.assertIn("inputs.publish_now != true", email["if"])
        self.assertIn("inputs.send_now == true", email["if"])


if __name__ == "__main__":
    unittest.main()
