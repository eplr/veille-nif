"""Reprise manuelle depuis une date UTC, sans modifier la cadence récurrente."""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import news_watch
import notion_weekly


NOW = datetime(2026, 11, 8, 14, tzinfo=timezone.utc)
START = datetime(2026, 11, 2, tzinfo=timezone.utc)


def article(index, published):
    return {
        "titre": f"Actualité biodiversité {index}", "lien": f"https://example.org/{index}",
        "date_publication": published, "source": "Source", "pays": "FR",
        "themes": ["Science et génie écologique"], "autorite": "presse",
    }


class TestStartDate(unittest.TestCase):
    def test_selection_et_periode_affichee_depuis_le_deux_novembre(self):
        items = [
            article(0, "2026-11-01T23:59:59Z"),
            article(1, "2026-11-02T00:00:00Z"),
            article(2, NOW.isoformat()),
            article(3, "2026-11-08T14:00:01Z"),
            article(4, ""),
            article(5, "2026-11-02"),
        ]
        selected = notion_weekly.select_weekly(items, NOW, start=START)
        self.assertEqual({item["lien"] for item in selected}, {items[1]["lien"], items[2]["lien"]})
        content = json.dumps(notion_weekly.build_blocks(selected, [], [], NOW, start=START), ensure_ascii=False)
        self.assertIn("Édition du 9 novembre 2026", content)
        self.assertIn("Actualités du 2 au 8 novembre 2026", content)
        self.assertIn("02/11/2026 à 00:00 UTC", content)
        self.assertIn(items[0], notion_weekly.select_weekly(items, NOW))

    def test_collecte_elargie_et_bornee_sans_persistance_en_apercu(self):
        items = [article(0, "2026-11-01T23:59:59Z"), article(1, "2026-11-02T00:00:00Z"),
                 article(2, ""), article(3, "2026-11-09T00:00:00Z")]
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "collection.json"
            with patch.object(news_watch, "today_utc", return_value=NOW), \
                    patch.object(news_watch, "collect", return_value=(items, Mock())) as collect, \
                    patch.object(news_watch, "commit") as commit, \
                    patch.object(sys, "argv", ["news_watch.py", "--start-date", "2026-11-02",
                                              "--dry-run", "--json-out", str(target)]), \
                    contextlib.redirect_stdout(io.StringIO()):
                news_watch.main()
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), [items[1]])
            self.assertEqual(collect.call_args.args[0], 7)
            commit.assert_not_called()

    def test_dates_invalides_ou_futures_refusees_avant_collecte(self):
        for value in ("2026-11-09", "date-invalide"):
            with self.subTest(value=value), \
                    patch.object(news_watch, "today_utc", return_value=NOW), \
                    patch.object(news_watch, "collect") as collect, \
                    patch.object(sys, "argv", ["news_watch.py", "--start-date", value]), \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    news_watch.main()
                collect.assert_not_called()

    def test_borne_invalide_notion_refusee(self):
        for start in (datetime(2026, 11, 2), datetime(2026, 11, 9, tzinfo=timezone.utc)):
            with self.subTest(start=start), self.assertRaises(ValueError):
                notion_weekly.select_weekly([], NOW, start=start)


if __name__ == "__main__":
    unittest.main()
