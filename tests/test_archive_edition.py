"""Instantanés des éditions : intégrité, reprises et séparation des aperçus."""
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import archive_edition


class TestArchiveEdition(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = pathlib.Path(self.temporary.name)
        self.root = self.base / "editions"
        self.notion = self.base / "notion.json"
        self.email = self.base / "newsletter.html"
        self.notion.write_text('[{"type":"paragraph"}]', encoding="utf-8")
        self.email.write_text("<html>Édition</html>", encoding="utf-8")
        self.monday = datetime(2026, 11, 9, 6, tzinfo=timezone.utc)

    def archive(self, now=None, attempt="1", notion="success", email="success"):
        return archive_edition.archive(
            self.root, now or self.monday, date(2026, 11, 9), "123", attempt,
            self.notion, self.email, notion, email,
        )

    def test_copie_integrale_et_empreintes(self):
        destination = self.archive()
        self.assertEqual(destination, self.root / "2026-11-09/123-1")
        self.assertEqual((destination / "newsletter.html").read_bytes(), self.email.read_bytes())
        metadata = json.loads((destination / "metadata.json").read_text())
        self.assertFalse(metadata["preview"])
        self.assertEqual(metadata["files_sha256"]["notion.json"],
                         hashlib.sha256(self.notion.read_bytes()).hexdigest())

    def test_apercu_dimanche_separe_et_echec_non_presente_comme_envoi(self):
        destination = self.archive(datetime(2026, 11, 8, 15, tzinfo=timezone.utc),
                                   notion="success", email="skipped")
        self.assertIn("previews", destination.parts)
        metadata = json.loads((destination / "metadata.json").read_text())
        self.assertTrue(metadata["preview"])
        self.assertEqual(metadata["email_outcome"], "skipped")
        failed = self.archive(attempt="2", notion="failure", email="failure")
        self.assertEqual(json.loads((failed / "metadata.json").read_text())["email_outcome"], "failure")

    def test_aucun_ecrasement_et_nouvelle_tentative_distincte(self):
        first = self.archive()
        with self.assertRaises(ValueError):
            self.archive()
        second = self.archive(attempt="2")
        self.assertTrue(first.exists())
        self.assertNotEqual(first, second)

    def test_aucune_copie_partielle_si_ecriture_echoue(self):
        with patch.object(archive_edition, "write_json", side_effect=OSError("Panne simulée")):
            with self.assertRaises(OSError):
                self.archive()
        self.assertEqual(list(self.root.rglob("metadata.json")), [])
        self.assertFalse((self.root / "2026-11-09/123-1").exists())
        self.assertEqual(list(self.root.rglob(".archive-*")), [])

    def test_fichiers_absents_ou_json_invalide(self):
        self.notion.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.archive()
        self.assertFalse(self.root.exists())
        self.notion.unlink()
        self.email.unlink()
        self.assertIsNone(self.archive())
        self.assertFalse(self.root.exists())

    def test_workflow_archive_avant_persistance_hors_dry_run(self):
        workflow = yaml.load((ROOT / ".github/workflows/veille.yml").read_text(), Loader=yaml.BaseLoader)
        steps = workflow["jobs"]["veille"]["steps"]
        archive = next(s for s in steps if "src/archive_edition.py" in s.get("run", ""))
        persist = next(s for s in steps if "git add" in s.get("run", ""))
        self.assertIn("inputs.dry_run != true", archive["if"])
        self.assertIn("always()", archive["if"])
        self.assertLess(steps.index(archive), steps.index(persist))
        self.assertIn("data/editions", persist["run"])
