"""Contrôles de la planification GitHub, sans agent IA."""
import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestSchedule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.load(
            (ROOT / ".github/workflows/veille.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        cls.steps = {
            step["name"]: step
            for step in cls.workflow["jobs"]["veille"]["steps"]
            if "name" in step
        }

    def test_collecte_quotidienne_a_six_heures_utc(self):
        self.assertEqual(self.workflow["on"]["schedule"], [{"cron": "0 6 * * *"}])

    def test_publications_planifiees_gardent_le_mode_hebdomadaire(self):
        for name, force in (
            ("Composer et envoyer l’hebdomadaire", "INPUT_SEND_NOW"),
            ("Actualiser la veille Notion hebdomadaire", "INPUT_PUBLISH_NOW"),
        ):
            with self.subTest(step=name):
                script = self.steps[name]["run"]
                argument = 'args+=(--weekly)' if force == "INPUT_PUBLISH_NOW" else 'args="$args --weekly"'
                self.assertIn(
                    f'if [ "${force}" != "true" ] && [ "$INPUT_DRY_RUN" != "true" ]; then\n'
                    f'  {argument}',
                    script,
                )
                dry_argument = 'args+=(--dry-run)' if force == "INPUT_PUBLISH_NOW" else 'args="$args --dry-run"'
                self.assertIn(f'[ "$INPUT_DRY_RUN" = "true" ] && {dry_argument}', script)

    def test_dry_run_sans_persistance_avec_apercus(self):
        for name in (
            "Mettre à jour les versions copier-coller",
            "Actualiser les appels pour la bibliothèque",
            "Synchroniser la bibliothèque Notion",
            "Enregistrer l'état et les livrables",
        ):
            with self.subTest(step=name):
                self.assertIn("inputs.dry_run != true", self.steps[name]["if"])
        preview = self.steps["Conserver les aperçus du dry run"]
        self.assertIn("inputs.dry_run == true", preview["if"])
        self.assertEqual(preview["with"]["retention-days"], "7")
        self.assertIn("/tmp/veille.html", preview["with"]["path"])
        self.assertIn("/tmp/notion-weekly.json", preview["with"]["path"])


if __name__ == "__main__":
    unittest.main()
