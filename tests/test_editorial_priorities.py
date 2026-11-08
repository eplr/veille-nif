"""Priorités du collectif : financer le vivant, pas promouvoir des recrutements."""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import daily_digest
import editorial
import lib
import news_watch
import notion_weekly

NOW = datetime(2026, 11, 8, 14, tzinfo=timezone.utc)


def article(index, title, **extra):
    return {
        "titre": title, "lien": f"https://example.org/{index}", "source": "Source",
        "autorite": "presse", "date_publication": "2026-11-05T14:00:00Z",
        "date_detection": "2026-11-08 14:00", "themes": [], **extra,
    }


class TestPriorities(unittest.TestCase):
    def test_emplois_stages_concours_et_navigation_exclus_meme_archives(self):
        titles = [
            "Ingénieur-e en Agroécologie et Living Labs", "Stage biodiversité et finance",
            "Chargé·e de mission biodiversité H/F", "Concours de photographie biodiversité",
            "BCG Appoints New Global Climate & Sustainability Practice Leader",
            "ESG Today: Week in Review", "finance Archives – Page 2 of 3",
            "Placements plaisir : investir dans l’art, vin, forêts",
        ]
        items = [article(i, title, autorite="primaire") for i, title in enumerate(titles)]
        self.assertEqual(notion_weekly.select_weekly(items, NOW), [])
        self.assertEqual(editorial.select_news(items, NOW.date()), [])
        self.assertFalse(lib.is_noise("Early-stage biodiversity fund raises $50 million"))
        self.assertFalse(lib.is_noise("Fonds biodiversité : nouvelle dénomination réglementaire"))
        self.assertFalse(lib.is_noise("Un concours financier pour restaurer les zones humides"))

    def test_financement_vivant_avant_actualite_institutionnelle_ou_science_generique(self):
        science = article(0, "Étude sur les écosystèmes forestiers", autorite="primaire", axe="science")
        blue = article(1, "Outrigger Impact Launches $100 Million Blue Economy Fund")
        biodiversity = article(2, "BofA, SMI, Eurazeo Launch New Biodiversity Solutions Fund")
        regulation = article(3, "CSRD : modification du calendrier", autorite="primaire")
        selected = notion_weekly.select_weekly([science, regulation, blue, biodiversity], NOW)
        self.assertEqual({i["lien"] for i in selected[:2]}, {blue["lien"], biodiversity["lien"]})
        self.assertIn(science["lien"], {item["lien"] for item in selected})
        self.assertEqual(editorial.section_for(blue), "financement")
        self.assertTrue(lib.matches_source_filter(blue["titre"], "reglementation"))
        self.assertTrue(lib.matches_source_filter(
            "Google Invests $160 Million in Water Projects Alongside AI Infrastructure", "reglementation"))
        self.assertFalse(lib.is_nature_related("Battery Storage Investment in Germany"))

    def test_pagination_esg_sans_double_collecte(self):
        source = next(s for s in lib.load_sources() if s["id"] == "esg-today")
        feed = {"title": "Outrigger Impact Launches $100 Million Blue Economy Fund",
                "link": "https://example.org/blue", "pub_date": "", "summary": ""}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(news_watch, "SEEN_FILE", pathlib.Path(directory) / "seen.json"), \
                patch.object(news_watch, "load_sources", return_value=[source]), \
                patch.object(news_watch, "fetch_feed", side_effect=[[], [feed], [], []]) as fetch, \
                patch.object(news_watch, "ZONES", []), patch.object(news_watch.time, "sleep"), \
                contextlib.redirect_stdout(io.StringIO()):
            # Un flux vide arrête proprement la pagination.
            items, _ = news_watch.collect()
            self.assertEqual(items, [])
            self.assertEqual(fetch.call_count, 1)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(news_watch, "SEEN_FILE", pathlib.Path(directory) / "seen.json"), \
                patch.object(news_watch, "load_sources", return_value=[source]), \
                patch.object(news_watch, "fetch_feed", side_effect=[[feed], [feed], []]) as fetch, \
                patch.object(news_watch, "ZONES", []), patch.object(news_watch.time, "sleep"), \
                contextlib.redirect_stdout(io.StringIO()):
            items, _ = news_watch.collect()
            self.assertEqual(len(items), 1)
            self.assertEqual(fetch.call_args_list[1].args[0], "https://www.esgtoday.com/feed/?paged=2")

    def test_reprises_du_meme_fonds_regroupees_sans_confondre_les_emetteurs(self):
        first = article(0, "BofA, SMI, Eurazeo Launch New Biodiversity Solutions Fund",
                        source="ESG Today", source_id="esg-today")
        replay = article(1, "Bank of America and sustainable markets initiative launch fund to invest in biodiversity")
        other = article(2, "Outrigger Impact Launches $100 Million Blue Economy Fund")
        self.assertTrue(editorial.same_story(first, replay))
        self.assertFalse(editorial.same_story(first, other))
        chosen = notion_weekly.select_weekly([replay, first, other], NOW)
        self.assertEqual(len(chosen), 2)
        self.assertIn(first["lien"], {item["lien"] for item in chosen})


class TestEditionCalendar(unittest.TestCase):
    def test_pied_de_page_repo_et_signature(self):
        blocks = notion_weekly.build_blocks([], [], [], NOW)
        repo, signature = blocks[-2:]
        repo_text = repo["paragraph"]["rich_text"][0]["text"]
        self.assertEqual(repo_text["content"], "https://github.com/eplr/veille-nif")
        self.assertEqual(repo_text["link"]["url"], "https://github.com/eplr/veille-nif")
        self.assertEqual(signature["paragraph"]["rich_text"][0]["text"]["content"], "© 2026 fidestra")

    def test_dimanche_et_lundi_meme_edition_meme_semaine(self):
        expected = (date(2026, 11, 9), datetime(2026, 11, 2, tzinfo=timezone.utc),
                    datetime(2026, 11, 9, tzinfo=timezone.utc))
        self.assertEqual(editorial.edition_calendar(NOW), expected)
        self.assertEqual(editorial.edition_calendar(datetime(2026, 11, 9, 6, tzinfo=timezone.utc)), expected)
        self.assertEqual(daily_digest._period(date(2026, 11, 9)), "Actualités du 2 au 8 novembre 2026")

    def test_changement_annee_et_edition_non_lundi_refusee(self):
        edition, start, end = editorial.edition_calendar(datetime(2027, 1, 4, 6, tzinfo=timezone.utc))
        self.assertEqual(edition, date(2027, 1, 4))
        self.assertEqual(start.date(), date(2026, 12, 28))
        self.assertEqual(end.date(), edition)
        self.assertIn("28 décembre 2026 au 3 janvier 2027",
                      editorial.news_period(start.date(), date(2027, 1, 3)))
        with self.assertRaises(ValueError):
            editorial.edition_calendar(NOW, date(2026, 11, 8))

    def test_publications_lundi_suivant_exclues(self):
        monday = datetime(2026, 11, 9, 6, tzinfo=timezone.utc)
        items = [article(0, "Un fonds biodiversité", date_publication="2026-11-08T23:59:59Z"),
                 article(1, "Un autre fonds biodiversité", date_publication="2026-11-09T00:00:00Z")]
        _, start, end = editorial.edition_calendar(monday)
        self.assertEqual(editorial.select_news(items, monday.date(), publication_window=(start, end)), [items[0]])
        blocks = notion_weekly.build_blocks([], [], [], NOW)
        content = json.dumps(blocks, ensure_ascii=False)
        self.assertIn("Édition du 9 novembre 2026", content)
        self.assertIn("Actualités du 2 au 8 novembre 2026", content)


if __name__ == "__main__":
    unittest.main()
