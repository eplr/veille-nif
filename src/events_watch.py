"""Agenda des événements nature et finance sur une fenêtre glissante de 60 jours.

- Lit l'agenda validé à la main (data/events.yaml).
- Détecte les événements nouveaux dans la fenêtre depuis le dernier envoi
  (data/interim/events_announced.json), pour déclencher un email même sans actualité.
- Cherche des événements candidats via Google News (webinaire, conférence, appel à contributions…) et les
  écrit dans data/interim/events_candidates.csv. Ils ne sont JAMAIS ajoutés à l'agenda automatiquement :
  une date ou un lieu erroné dans un email envoyé à la communauté est pire qu'un événement manquant.

Usage :
    python src/events_watch.py                 # affiche l'agenda des 60 prochains jours
    python src/events_watch.py --candidates    # cherche aussi des candidats
    python src/events_watch.py --check-links   # vérifie que les liens de l'agenda répondent
"""
import argparse
import re
import time
from datetime import date, datetime, timedelta

import yaml

from lib import (
    DATA, INTERIM, PAYS_ORDER, append_csv, google_news_rss, http_get, is_nature_related,
    load_seen, normalize_title, save_seen, within_lookback,
)

EVENTS_FILE = DATA / "events.yaml"
ANNOUNCED_FILE = INTERIM / "events_announced.json"
CANDIDATES_FILE = INTERIM / "events_candidates.csv"
CANDIDATES_SEEN = INTERIM / "events_candidates_seen.json"
CANDIDATE_FIELDS = ["date_detection", "titre", "source", "date_publication", "lien", "requete"]

WINDOW_DAYS = 60
REQUIRED = ["id", "titre", "debut", "pays", "lien", "verifie_le", "source"]
PAYS_VALIDES = set(PAYS_ORDER)

EVENT_WORDS = re.compile(
    r"webinaire|webinar|conf[ée]rence|conference|forum|summit|sommet|atelier|workshop|colloque|congr[eè]s"
    r"|appel [àa] (contributions|communications)|call for (papers|abstracts)|save the date|rencontres?"
    r"|symposium|Tagung|Konferenz|Veranstaltung",
    re.IGNORECASE,
)

# Requêtes de détection de candidats (une par langue/zone).
CANDIDATE_QUERIES = [
    ("fr", "FR", "FR:fr", '(webinaire OR conférence OR colloque OR forum) (biodiversité OR "capital naturel" OR TNFD) finance'),
    ("en-GB", "GB", "GB:en", '(webinar OR conference OR summit OR workshop) ("nature finance" OR biodiversity OR TNFD OR "nature-related")'),
    ("en", "IE", "IE:en", '(webinar OR conference OR workshop) ("nature credits" OR "nature restoration" OR "biodiversity finance") EU'),
    ("de", "CH", "CH:de", "(Konferenz OR Tagung OR Webinar) (Biodiversität OR Naturkapital) Finanz"),
]


def _as_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v), "%Y-%m-%d").date()


def load_events() -> list[dict]:
    """Charge et valide l'agenda. Une erreur de saisie fait échouer tôt et clairement."""
    with EVENTS_FILE.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f).get("evenements") or []
    events, ids = [], set()
    for e in raw:
        missing = [k for k in REQUIRED if not e.get(k)]
        if missing:
            raise ValueError(f"Événement {e.get('id', '?')} : champ(s) manquant(s) {missing}")
        if e["id"] in ids:
            raise ValueError(f"Identifiant d'événement en double : {e['id']}")
        ids.add(e["id"])
        if e["pays"] not in PAYS_VALIDES:
            raise ValueError(f"Événement {e['id']} : pays invalide {e['pays']!r} (attendu {sorted(PAYS_VALIDES)})")
        e = dict(e)
        e["debut"] = _as_date(e["debut"])
        e["fin"] = _as_date(e["fin"]) if e.get("fin") else e["debut"]
        if e["fin"] < e["debut"]:
            raise ValueError(f"Événement {e['id']} : la fin précède le début")
        events.append(e)
    return events


def in_window(events: list[dict], today: date | None = None, days: int = WINDOW_DAYS) -> list[dict]:
    """Événements dont la période recoupe [aujourd'hui, aujourd'hui + days], triés par date de début."""
    today = today or date.today()
    limit = today + timedelta(days=days)
    kept = [e for e in events if e["fin"] >= today and e["debut"] <= limit]
    for e in kept:
        e["en_cours"] = e["debut"] < today <= e["fin"]
    return sorted(kept, key=lambda e: (e["debut"], e["id"]))


def mark_announced(events: list[dict]):
    """Enregistre ces événements comme annoncés (à appeler après un envoi réussi)."""
    announced = load_seen(ANNOUNCED_FILE)
    save_seen(ANNOUNCED_FILE, announced + [e["id"] for e in events])


def run(today: date | None = None, persist: bool = True) -> tuple[list[dict], list[dict]]:
    """Renvoie (événements de la fenêtre, événements jamais annoncés dans un envoi précédent)."""
    window = in_window(load_events(), today)
    announced = set(load_seen(ANNOUNCED_FILE))
    new = [e for e in window if e["id"] not in announced]
    if persist:
        mark_announced(new)
    print(f"[events-watch] {len(window)} événement(s) dans les {WINDOW_DAYS} prochains jours, {len(new)} nouveau(x)")
    return window, new


def find_candidates(lookback_days: int = 7, persist: bool = True) -> list[dict]:
    """Détecte des événements possibles. Résultat : fichier CSV à relire, jamais l'agenda."""
    known_titles = {normalize_title(e["titre"]) for e in load_events()}
    seen = set(load_seen(CANDIDATES_SEEN))
    found = []
    for hl, gl, ceid, query in CANDIDATE_QUERIES:
        for item in google_news_rss(f"{query} when:{lookback_days}d", hl=hl, gl=gl, ceid=ceid):
            key = item["link"] or item["title"]
            if key in seen:
                continue
            seen.add(key)
            title = item["title"]
            if not EVENT_WORDS.search(title) or not is_nature_related(title, wide=True):
                continue
            if normalize_title(title) in known_titles or not within_lookback(item["pub_date"], lookback_days):
                continue
            found.append({
                "date_detection": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "titre": title, "source": item["source"], "date_publication": item["pub_date"],
                "lien": item["link"], "requete": query,
            })
        time.sleep(1.0)
    if persist:
        save_seen(CANDIDATES_SEEN, list(seen))
        append_csv(CANDIDATES_FILE, CANDIDATE_FIELDS, found)
    print(f"[events-watch] {len(found)} candidat(s) à valider manuellement ({CANDIDATES_FILE.name})")
    return found


def check_links() -> int:
    """Vérifie que chaque lien d'événement répond. Renvoie le nombre de liens en défaut."""
    bad = 0
    for e in load_events():
        ok = http_get(e["lien"], retries=2) is not None
        bad += not ok
        print(f"{'ok   ' if ok else 'ÉCHEC'}  {e['id']:<32} {e['lien']}")
        time.sleep(0.3)
    print(f"\n{bad} lien(s) en défaut")
    return bad


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidates", action="store_true", help="chercher aussi des événements candidats")
    parser.add_argument("--check-links", action="store_true", help="vérifier les liens de l'agenda")
    args = parser.parse_args()
    if args.check_links:
        raise SystemExit(1 if check_links() else 0)
    window, _ = run(persist=False)
    for e in window:
        print(f"- {e['debut']} → {e['fin']}  [{e['pays']}] {e['titre']}")
    if args.candidates:
        for c in find_candidates(persist=False):
            print(f"? {c['titre']} ({c['source']}) {c['lien']}")
