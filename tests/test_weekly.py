"""Régressions de la migration quotidienne → collecte quotidienne / édition hebdomadaire."""
import contextlib
import io
import pathlib
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import daily_digest
import editorial
import export_prompt_pack
import lib
import news_archive
import news_watch
import reports


TODAY = date(2026, 11, 2)  # lundi


def article(number=0, **overrides):
    return {
        "titre": f"Actualité biodiversité numéro {number}",
        "lien": f"https://example.org/{number}",
        "source": "Source",
        "pays": "FR",
        "canal": "rss",
        "themes": ["Autres signaux"],
        "date_detection": "2026-11-02 07:00",
        "date_publication": "2026-11-01T10:00:00Z",
        "autorite": "presse",
        **overrides,
    }


def report(**overrides):
    return {
        "id": "rapport-v1", "titre": "Rapport de test", "lien": "https://example.org/report",
        "source": "Éditeur", "date": "2026-10-30", "verifie_le": "2026-11-01",
        "valide": True, "resultats": ["Résultat (p. 12)"],
        "methode": "Méthode (p. 5)", "limites": "Limites (p. 20)",
        "implications": "Lecture : implications", **overrides,
    }


class TestEditorial(unittest.TestCase):
    def test_types_opportunites_distincts(self):
        calls = [{"titre": kind, "type": kind} for kind in editorial.OPPORTUNITY_TYPES]
        groups = editorial.group_opportunities(calls)
        self.assertEqual(len(groups), 3)
        for call in calls:
            self.assertEqual(groups[editorial.OPPORTUNITY_TYPES[call["type"]]], [call])
        with self.assertRaises(ValueError):
            editorial.group_opportunities([{"type": "inconnu"}])

    def test_sources_ajoutees_et_profils(self):
        sources = {s["id"]: s for s in lib.load_sources()}
        for source_id in ("vert", "boursorama", "aef-info", "esg-today", "ifrs-issb", "inrae", "mnhn", "cnrs"):
            self.assertIn(source_id, sources)
        self.assertEqual(sources["ipbes"]["axe"], "science")
        self.assertEqual(sources["inrae"]["autorite"], "primaire")
        self.assertEqual(sources["aef-info"]["acces"], "abonnement")
        self.assertEqual(sources["esg-today"]["pays"], "INT")
        for source_id in ("amf", "efrag", "esma"):
            self.assertEqual(sources[source_id]["filtre"], "reglementation")

    def test_collecte_prefere_la_source_primaire_et_garde_metadonnees(self):
        sources = [
            {"id": kind, "nom": kind, "autorite": kind, "rss": f"https://example.org/{kind}",
             "pays": "FR", "filtre": "science", "axe": "science", "acces": "libre"}
            for kind in ("presse", "primaire")
        ]
        feed = [{"title": "Étude de génie écologique des zones humides",
                 "link": "https://example.org/science", "pub_date": "", "summary": ""}]
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(news_watch, "SEEN_FILE", pathlib.Path(directory) / "seen.json"), \
                patch.object(news_watch, "load_sources", return_value=sources), \
                patch.object(news_watch, "fetch_feed", return_value=feed), \
                patch.object(news_watch, "ZONES", []), patch.object(news_watch.time, "sleep"):
            items, _ = news_watch.collect()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source_id"], "primaire")
        self.assertEqual(items[0]["axe"], "science")
        self.assertEqual(items[0]["autorite"], "primaire")

    def test_science_et_reglementation_sans_mot_finance(self):
        self.assertTrue(lib.matches_source_filter("Génie écologique et zones humides", "science"))
        self.assertTrue(lib.matches_source_filter("CSRD : nouvelles règles", "reglementation"))
        self.assertFalse(lib.matches_source_filter("Résultats trimestriels de la banque", "reglementation"))
        self.assertFalse(lib.matches_source_filter("Nouveau processeur quantique", "science"))
        self.assertIn("Science et génie écologique", lib.detect_themes("Génie écologique"))
        self.assertIn("CSRD", news_watch.site_query({"domaine": "example.org", "filtre": "reglementation"}))
        self.assertIn("écologie", news_watch.site_query({"domaine": "example.org", "filtre": "science"}))

    def test_rubriques(self):
        for title, expected in (("CSRD et SFDR", "reglementation"),
                                ("Restauration écologique", "science"),
                                ("Un nouvel engagement", "pratiques")):
            self.assertEqual(editorial.section_for(article(titre=title)), expected)
        self.assertEqual(editorial.section_for(article(themes=["Instruments et marchés"])), "financement")
        self.assertEqual(editorial.section_for(article(titre="Rapport CSRD", axe="science")), "science")

    def test_plafond_et_place_reservee_science(self):
        items = [article(i, autorite="primaire") for i in range(20)]
        science = article(100, axe="science")
        items.append(science)
        selected = editorial.select_news(items, TODAY)
        self.assertEqual(len(selected), 15)
        self.assertIn(science, selected)
        self.assertEqual(len(items), 21)
        self.assertEqual(editorial.select_news(items, TODAY, limit=1), [science])

    def test_priorite_source_puis_recence_et_bornes(self):
        press = article(1)
        primary = article(2, autorite="primaire", date_publication="2026-10-29T10:00:00Z")
        old = article(3, date_detection="2026-10-26 07:00")
        future = article(4, date_detection="2026-11-03 07:00")
        boundary = article(5, date_detection="2026-10-27 07:00")
        undated = article(6, date_detection="")
        selected = editorial.select_news([press, primary, old, future, boundary, undated], TODAY)
        self.assertEqual(selected[0], primary)
        self.assertEqual({i["lien"] for i in selected}, {press["lien"], primary["lien"], boundary["lien"]})
        for value in (0, -1):
            with self.assertRaises(ValueError):
                editorial.select_news([], TODAY, limit=value)


class TestArchive(unittest.TestCase):
    def test_merge_stable_et_diffusion_separee(self):
        first = article()
        replay = article(date_detection="2026-11-03 07:00")
        self.assertEqual(news_archive.merge([first], [replay]), [first])
        self.assertEqual(news_archive.unsent([first], {}), [first])
        self.assertEqual(news_archive.unsent([first], {"2026-11-02": {"articles": [first["lien"]]}}), [])

    def test_ecriture_atomique_et_etat_corrompu(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "archive.json"
            news_archive.write_json(path, [article()])
            self.assertEqual(news_archive.read_json(path, []), [article()])
            self.assertEqual(list(path.parent.iterdir()), [path])
            path.write_text("{cassé", encoding="utf-8")
            with self.assertRaises(ValueError):
                news_archive.read_json(path, [])
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                news_archive.read_json(path, [])


class TestWeeklyExecution(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = pathlib.Path(self.temp.name)
        for module, name, filename in (
            (news_archive, "ARCHIVE_FILE", "archive.json"),
            (news_archive, "DELIVERY_FILE", "delivery.json"),
            (news_watch, "SEEN_FILE", "seen.json"),
            (news_watch, "LOG_OUT", "log.csv"),
        ):
            patcher = patch.object(module, name, root / filename)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.incoming = [article(i) for i in range(20)]
        self.seen = news_watch.Seen(news_watch.SEEN_FILE)
        for item in self.incoming:
            self.seen.add(item["lien"])
        patcher = patch.object(daily_digest, "today_utc",
                               return_value=datetime(2026, 11, 2, 7, tzinfo=timezone.utc))
        self.clock = patcher.start()
        self.addCleanup(patcher.stop)
        for target, name, value in (
            (news_watch, "collect", (self.incoming, self.seen)),
            (daily_digest.events_watch, "run", ([], [])),
            (daily_digest.calls_watch, "run", ([], {"ok": True})),
            (daily_digest.report_files, "load", []),
        ):
            patcher = patch.object(target, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target, name in (
            (daily_digest, "send_email"),
            (daily_digest.events_watch, "mark_announced"),
            (daily_digest.calls_watch, "commit"),
        ):
            patcher = patch.object(target, name)
            mocked = patcher.start()
            setattr(self, name, mocked)
            self.addCleanup(patcher.stop)

    def run_main(self, *args):
        with patch.object(sys, "argv", ["daily_digest.py", *args]), contextlib.redirect_stdout(io.StringIO()):
            return daily_digest.main()

    def test_collecte_seule_n_acquitte_pas_la_diffusion(self):
        self.assertEqual(self.run_main("--collect-only"), 0)
        self.send_email.assert_not_called()
        self.assertEqual(len(news_archive.load()), 20)
        self.assertEqual(news_archive.deliveries(), {})

    def test_apercu_hebdomadaire_possible_mercredi_sans_etat(self):
        self.clock.return_value = datetime(2026, 11, 4, 7, tzinfo=timezone.utc)
        preview = pathlib.Path(self.temp.name) / "preview.html"
        self.run_main("--weekly", "--dry-run", "--html-out", str(preview))
        self.send_email.assert_not_called()
        self.assertIn("L’hebdo", preview.read_text(encoding="utf-8"))
        self.assertEqual(list(preview.parent.iterdir()), [preview])
        self.assertEqual(news_archive.deliveries(), {})

    def test_mercredi_collecte_sans_envoi(self):
        self.clock.return_value = datetime(2026, 11, 4, 7, tzinfo=timezone.utc)
        self.run_main("--weekly")
        self.send_email.assert_not_called()
        self.assertEqual(len(news_archive.load()), 20)

    def test_lundi_envoi_plafonne_archive_complete_et_pas_de_double_envoi(self):
        self.run_main("--weekly")
        self.assertEqual(len(news_archive.load()), 20)
        self.assertEqual(len(news_archive.deliveries()["2026-11-02"]["articles"]), 15)
        self.assertEqual(len(news_archive.unsent(news_archive.load(), news_archive.deliveries())), 5)
        self.run_main("--weekly")
        self.send_email.assert_called_once()

    def test_echec_email_conserve_collecte_sans_marquer_envoye(self):
        self.send_email.side_effect = RuntimeError("Échec simulé")
        with self.assertRaises(RuntimeError):
            self.run_main("--weekly")
        self.assertEqual(len(news_archive.load()), 20)
        self.assertEqual(news_archive.deliveries(), {})
        self.mark_announced.assert_not_called()
        self.commit.assert_not_called()
        # La reprise utilise le stock archivé même si la collecte ne renvoie plus rien.
        self.send_email.side_effect = None
        with patch.object(news_watch, "collect", return_value=([], self.seen)):
            self.run_main("--weekly")
        self.assertEqual(len(news_archive.deliveries()["2026-11-02"]["articles"]), 15)

    def test_dry_run_et_rejeu_ne_modifient_aucun_etat(self):
        self.run_main("--dry-run")
        self.send_email.assert_not_called()
        self.assertEqual(list(pathlib.Path(self.temp.name).iterdir()), [])
        self.run_main("--ignore-seen")
        self.send_email.assert_called_once()
        self.assertEqual(list(pathlib.Path(self.temp.name).iterdir()), [])

    def test_seuls_evenements_visibles_sont_acquittes(self):
        events = [
            {"id": str(i), "titre": f"Événement {i}", "debut": TODAY, "fin": TODAY,
             "lien": f"https://example.org/event/{i}", "lieu": "En ligne", "format": "webinaire"}
            for i in range(8)
        ]
        with patch.object(daily_digest.events_watch, "run", return_value=(events, events)):
            self.run_main("--weekly")
        self.mark_announced.assert_called_once_with(events[:5])
        body = self.send_email.call_args.kwargs["body_html"]
        self.assertIn("Événement 4", body)
        self.assertNotIn("Événement 5", body)


class TestReports(unittest.TestCase):
    def test_fiches_incluses_dans_le_pack_hors_ligne(self):
        pack = export_prompt_pack.build_pack(TODAY, [], [], None, [], [report()])
        self.assertIn("parties A à E", pack)
        self.assertIn("## E. Fiches de rapports validées", pack)
        self.assertIn("Résultat (p. 12)", pack)

    def load_report(self, entry):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "reports.yaml"
            path.write_text(yaml.safe_dump({"rapports": [entry]}), encoding="utf-8")
            with patch.object(reports, "REPORTS_FILE", path):
                return reports.load(TODAY)

    def test_validation_et_fenetre(self):
        self.assertEqual(len(self.load_report(report())), 1)
        self.assertEqual(self.load_report(report(valide=False)), [])
        self.assertEqual(self.load_report(report(verifie_le="2026-10-20", date="2026-10-19")), [])
        self.assertEqual(self.load_report(report(verifie_le="2026-11-03")), [])
        for overrides in ({"methode": ""}, {"lien": "javascript:alert(1)"}, {"resultats": "du texte"},
                          {"date": "2026-11-02", "verifie_le": "2026-11-01"}):
            with self.assertRaises(ValueError):
                self.load_report(report(**overrides))

    def test_rendu_fiche_sans_generation_et_echappement(self):
        fixture = report(titre="<script>test</script>", resultats=["Résultat <b> (p. 12)"])
        html = daily_digest.compose_html([], [], [], [], {"ok": True}, TODAY, [fixture])
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        for text in ("Méthode", "Limites", "Implications pratiques", "p. 12"):
            self.assertIn(text, html)


if __name__ == "__main__":
    unittest.main()
