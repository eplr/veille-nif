"""Fiches de rapports lues et validées humainement, sans API d’IA."""
from datetime import date, timedelta
from urllib.parse import urlparse

import yaml

from lib import DATA

REPORTS_FILE = DATA / "reports.yaml"


def load(today: date, days: int | None = 7) -> list[dict]:
    with REPORTS_FILE.open(encoding="utf-8") as stream:
        raw = yaml.safe_load(stream).get("rapports") or []
    selected, ids = [], set()
    for report in raw:
        if report.get("valide") is not True:
            continue
        required = ("id", "titre", "lien", "source", "date", "verifie_le",
                    "resultats", "methode", "limites", "implications")
        if any(not report.get(field) for field in required):
            raise ValueError("Fiche de rapport validée incomplète")
        if report["id"] in ids:
            raise ValueError(f"Rapport en double : {report['id']}")
        ids.add(report["id"])
        parsed = urlparse(report["lien"])
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"Rapport {report['id']} : URL HTTPS requise")
        if not isinstance(report["resultats"], list) or not 1 <= len(report["resultats"]) <= 5:
            raise ValueError(f"Rapport {report['id']} : fournir 1 à 5 résultats sourcés")
        published = date.fromisoformat(str(report["date"]))
        checked = date.fromisoformat(str(report["verifie_le"]))
        if published > checked:
            raise ValueError(f"Rapport {report['id']} : publication postérieure à la vérification")
        if checked <= today and (days is None or checked >= today - timedelta(days=days - 1)):
            selected.append(report)
    return sorted(selected, key=lambda r: (str(r["verifie_le"]), r["id"]), reverse=True)
