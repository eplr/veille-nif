"""Tests hors réseau : lecture des flux, filtres, agenda, appels à projets, email, prompts.

Lancer : python -m unittest discover -s tests -v
"""
import pathlib
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import calls_watch  # noqa: E402
import daily_digest  # noqa: E402
import events_watch  # noqa: E402
import export_prompt_pack  # noqa: E402
import lib  # noqa: E402
import news_watch  # noqa: E402

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Premier article</title><link>https://exemple.org/a</link><pubDate>Tue, 06 Oct 2026 07:00:00 GMT</pubDate>
<description>&lt;p&gt;Texte &lt;b&gt;riche&lt;/b&gt;&lt;/p&gt;</description></item>
<item><title></title><link>https://exemple.org/vide</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Entree Atom</title><link rel="alternate" href="https://exemple.org/atom"/>
<updated>2026-10-05T10:00:00Z</updated><summary>Resume</summary></entry></feed>"""

CAREWS_HTML = """
<div class="job-thumbnail"><h3 class="job-thumbnail__title"><a href="/fonds/appels-a-projet/biodiversite">Appel biodiversité  -  Fonds Vert</a></h3>
<div class="job-thumbnail__text">Soutien aux haies et aux zones humides.</div>
<div class="job-thumbnail__company">Par <a href="/fonds">Fonds Vert</a></div>
<div class="job-thumbnail__date-start">Publié le :  01.10.2026</div>
<div class="job-thumbnail__date-end">Date de clôture :  15.11.2026</div></div>
<div class="job-thumbnail"><h3 class="job-thumbnail__title"><a href="/x/appels-a-projet/numerique">Appel numérique inclusif</a></h3>
<div class="job-thumbnail__text">Accompagner la fracture numérique.</div>
<div class="job-thumbnail__company">Par <a href="/x">Fondation X</a></div>
<div class="job-thumbnail__date-start">Publié le :  01.10.2026</div>
<div class="job-thumbnail__date-end">Date de clôture :  20.11.2026</div></div>
<div class="job-thumbnail"><h3 class="job-thumbnail__title"><a href="/y/appels-a-projet/ancien">Ancien appel forêt</a></h3>
<div class="job-thumbnail__text">Forêt.</div>
<div class="job-thumbnail__company">Par <a href="/y">Y</a></div>
<div class="job-thumbnail__date-start">Publié le :  01.01.2025</div>
<div class="job-thumbnail__date-end">Date de clôture :  01.03.2025</div></div>
"""


class TestFeeds(unittest.TestCase):
    def test_rss_ignore_items_sans_titre_et_nettoie_le_html(self):
        items = lib.parse_feed(RSS)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Premier article")
        self.assertEqual(items[0]["summary"], "Texte riche")

    def test_atom(self):
        items = lib.parse_feed(ATOM)
        self.assertEqual(items[0]["link"], "https://exemple.org/atom")
        self.assertEqual(items[0]["pub_date"], "2026-10-05T10:00:00Z")

    def test_flux_invalide(self):
        self.assertEqual(lib.parse_feed(b"pas du xml"), [])

    def test_dates(self):
        self.assertIsNotNone(lib.parse_date("Tue, 06 Oct 2026 07:00:00 GMT"))
        self.assertIsNotNone(lib.parse_date("2026-10-05T10:00:00Z"))
        self.assertIsNone(lib.parse_date("n'importe quoi"))
        self.assertTrue(lib.within_lookback("", 3))  # date absente : on conserve


class TestFilters(unittest.TestCase):
    def test_nature_positive(self):
        for t in ["Crédits biodiversité : un marché en construction", "TNFD adoption grows",
                  "Risques climat et nature : des exigences renforcées", "Biodiversität im Finanzsektor"]:
            self.assertTrue(lib.is_nature_related(t), t)

    def test_nature_negative(self):
        for t in ["Taux d'usure mensuel", "ECB's Rehn on inflation", "Résultats trimestriels de la banque"]:
            self.assertFalse(lib.is_nature_related(t), t)

    def test_filtre_large_pour_carenews(self):
        titre = "Solidaires avec nos paysans : le Fonds de dotation Biocoop mobilisé"
        self.assertFalse(lib.is_nature_related(titre))
        self.assertTrue(lib.is_land_related(titre))

    def test_bruit_administratif(self):
        self.assertTrue(lib.is_noise("DÉCISION N° 2026 – DGA – 2091"))
        self.assertFalse(lib.is_noise("Le TNFD publie LEAP 2.0"))

    def test_themes(self):
        self.assertIn("Reporting et standards", lib.detect_themes("TNFD publishes new disclosure guidance"))
        self.assertEqual(lib.detect_themes("Texte sans rapport"), [lib.DEFAULT_THEME])

    def test_etat_conserve_l_ordre_et_dedoublonne(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "seen.json"
            lib.save_seen(p, ["a", "b", "a", "c"])
            self.assertEqual(lib.load_seen(p), ["a", "b", "c"])
            lib.save_seen(p, ["1", "2", "3", "4"], keep=2)
            self.assertEqual(lib.load_seen(p), ["3", "4"])

    def test_registre_valide(self):
        for s in lib.load_sources():
            self.assertIn(s["pays"], lib.PAYS_LABELS, s["id"])
            self.assertIn(s["filtre"], {"aucun", "mots_cles", "mots_cles_large"}, s["id"])
            self.assertTrue(s.get("rss") or s.get("domaine"), f"{s['id']} : ni flux ni domaine")


class TestNewsDedup(unittest.TestCase):
    def test_un_meme_titre_relaye_deux_fois_n_est_signale_qu_une_fois(self):
        with tempfile.TemporaryDirectory() as d:
            seen = news_watch.Seen(pathlib.Path(d) / "seen.json")
            a = {"title": "Un titre assez long pour passer", "link": "https://a/1", "pub_date": "", "source": "A"}
            b = {"title": "Un titre assez long pour passer", "link": "https://b/2", "pub_date": "", "source": "B"}
            self.assertTrue(news_watch._accept(a, seen, 3))
            self.assertFalse(news_watch._accept(b, seen, 3))


class TestEvents(unittest.TestCase):
    def test_agenda_reel_valide(self):
        events = events_watch.load_events()
        self.assertGreater(len(events), 5)
        for e in events:
            self.assertTrue(str(e["lien"]).startswith("https://"), e["id"])

    def test_fenetre(self):
        evs = [
            {"id": "passe", "debut": date(2026, 9, 1), "fin": date(2026, 9, 2)},
            {"id": "en-cours", "debut": date(2026, 10, 6), "fin": date(2026, 10, 8)},
            {"id": "proche", "debut": date(2026, 11, 1), "fin": date(2026, 11, 1)},
            {"id": "limite", "debut": date(2026, 12, 6), "fin": date(2026, 12, 6)},
            {"id": "trop-loin", "debut": date(2026, 12, 7), "fin": date(2026, 12, 7)},
        ]
        got = events_watch.in_window(evs, today=date(2026, 10, 7), days=60)
        self.assertEqual([e["id"] for e in got], ["en-cours", "proche", "limite"])
        self.assertTrue(got[0]["en_cours"])
        self.assertFalse(got[1]["en_cours"])

    def test_validation_refuse_pays_inconnu(self):
        yaml_text = (
            "evenements:\n  - {id: x, titre: T, debut: 2026-10-10, pays: ZZ, lien: 'https://x', "
            "verifie_le: 2026-10-07, source: s}\n"
        )
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "events.yaml"
            p.write_text(yaml_text, encoding="utf-8")
            old = events_watch.EVENTS_FILE
            events_watch.EVENTS_FILE = p
            try:
                with self.assertRaises(ValueError):
                    events_watch.load_events()
            finally:
                events_watch.EVENTS_FILE = old


class TestCalls(unittest.TestCase):
    def test_lecture_de_la_liste(self):
        calls = calls_watch.parse_listing(CAREWS_HTML)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0]["cloture"], date(2026, 11, 15))
        self.assertEqual(calls[0]["porteur"], "Fonds Vert")
        self.assertTrue(calls[0]["lien"].startswith("https://www.carenews.com/"))

    def test_selection_ouverts_et_pertinents(self):
        calls = calls_watch.parse_listing(CAREWS_HTML)
        got = calls_watch.select_open(calls, today=date(2026, 10, 7))
        self.assertEqual([c["titre"][:12] for c in got], ["Appel biodiv"])

    def test_page_vide_signale_une_panne(self):
        self.assertEqual(calls_watch.parse_listing("<html><body>rien</body></html>"), [])


class TestDigest(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 10, 7)
        self.items = [
            {"date_detection": "x", "pays": "FR", "source": "AMF", "titre": "Titre <script>alert(1)</script>",
             "themes": ["Réglementation et supervision"], "date_publication": "Tue, 06 Oct 2026 07:00:00 GMT",
             "lien": "https://exemple.org/?a=1&b=2", "canal": "rss"},
            {"date_detection": "x", "pays": "UK", "source": "BusinessGreen", "titre": "Un article de presse",
             "themes": ["Instruments et marchés"], "date_publication": "", "lien": "https://exemple.org/p",
             "canal": "zone"},
        ]
        self.window = events_watch.in_window(events_watch.load_events(), self.today)
        self.new = self.window[:1]

    def test_dates_francaises(self):
        self.assertEqual(daily_digest.fr_range(date(2026, 11, 3), date(2026, 11, 6)), "3–6 nov. 2026")
        self.assertEqual(daily_digest.fr_range(date(2026, 10, 28), date(2026, 11, 2)), "28 oct.–2 nov. 2026")
        self.assertEqual(daily_digest.fr_range(date(2026, 10, 13), date(2026, 10, 13)), "mar. 13 oct. 2026")

    def test_html_echappe_les_titres(self):
        html = daily_digest.compose_html(self.items, self.window, self.new, [], {"ok": True}, self.today)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("a=1&amp;b=2", html)

    def test_sections_et_alerte_source(self):
        md = daily_digest.compose_markdown(self.items, self.window, self.new, [], {"ok": False}, self.today)
        for needle in ["## Nouveautés", "### France", "Presse et veille thématique", "## Agenda", "Carenews indisponible"]:
            self.assertIn(needle, md)
        self.assertNotIn("## Appels à projets", md)  # section absente quand il n'y a rien

    def test_pas_d_adresse_email_dans_le_depot(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        for path in list((root / "src").glob("*.py")) + list((root / "data").glob("*.yaml")):
            text = path.read_text(encoding="utf-8")
            for token in text.replace("<", " ").replace(">", " ").split():
                if "@" in token and "." in token.split("@")[-1] and "example" not in token and "noreply" not in token:
                    # tolère les adresses de documentation (ex. user@host) mais pas de vraie boîte
                    self.assertNotRegex(token, r"^[\w.+-]+@[\w-]+\.(com|fr|org|net|ch)$", f"{path.name}: {token}")


class TestPromptPack(unittest.TestCase):
    def test_garde_fous_presents(self):
        sources = lib.load_sources()
        p = export_prompt_pack.build_autonomous(date(2026, 10, 7), sources)
        for needle in ["Ne jamais inventer", "Rien de vérifié trouvé", "Points à vérifier", "TNFD", "2026-10-07"]:
            self.assertIn(needle, p)
        self.assertNotIn("grade", p)  # règle de style propre à fidestra, absente du prompt communautaire

    def test_pack_avec_pieces(self):
        today = date(2026, 10, 7)
        window = events_watch.in_window(events_watch.load_events(), today)
        pack = export_prompt_pack.build_pack(today, lib.load_sources(), window, [], [])
        self.assertIn("N’utilise QUE les éléments fournis", pack)
        self.assertIn("COP17", pack)
        self.assertIn("## C. Appels à projets ouverts", pack)


if __name__ == "__main__":
    unittest.main()
