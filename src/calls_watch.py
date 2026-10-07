"""Appels à projets relayés par Carenews, filtrés sur la nature et la biodiversité.

Carenews n'a pas de flux RSS. La page https://www.carenews.com/appels_a_projets liste les appels avec leur
date de clôture ; son robots.txt n'exclut que /search/. La liste couvre toutes les causes : on la parcourt sur
quelques pages (pause entre requêtes, user-agent identifié) puis on filtre par mots-clés.

Sortie : appels ouverts qui parlent de nature, avec deux indicateurs :
- `nouveau` : jamais vu dans un envoi précédent (data/interim/calls_seen.json)
- `urgent`  : clôture dans les 14 jours

Si la page ne renvoie aucun appel (changement de structure, panne), `health["ok"]` est faux : le digest
l'indique au lieu de passer sous silence une source muette.

Usage :
    python src/calls_watch.py            # affiche les appels ouverts retenus
    python src/calls_watch.py --pages 3  # limite le nombre de pages parcourues
"""
import argparse
import re
import time
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup

from lib import INTERIM, OUTPUT, append_csv, http_get, is_land_related, load_seen, save_seen

BASE = "https://www.carenews.com"
LIST_URL = BASE + "/appels_a_projets/{page}/?page=0"
SEEN_FILE = INTERIM / "calls_seen.json"
LOG_OUT = OUTPUT / "calls_log.csv"
LOG_FIELDS = ["date_detection", "titre", "porteur", "publie_le", "cloture", "lien"]

MAX_PAGES = 10          # 20 appels par page : les 200 plus récents
THROTTLE_S = 1.0
URGENT_DAYS = 14

_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def _parse_date(text: str) -> date | None:
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def parse_listing(html: str) -> list[dict]:
    """Extrait les appels d'une page de liste. Fonction pure, testée sans réseau."""
    soup = BeautifulSoup(html, "html.parser")
    calls = []
    for card in soup.select(".job-thumbnail"):
        link = card.select_one(".job-thumbnail__title a")
        if not link or not link.get("href"):
            continue
        company = card.select_one(".job-thumbnail__company a")
        text = card.select_one(".job-thumbnail__text")
        start = card.select_one(".job-thumbnail__date-start")
        end = card.select_one(".job-thumbnail__date-end")
        calls.append({
            "titre": re.sub(r"\s+", " ", link.get_text(" ", strip=True)),
            "porteur": company.get_text(strip=True) if company else "",
            "resume": re.sub(r"\s+", " ", text.get_text(" ", strip=True)) if text else "",
            "publie_le": _parse_date(start.get_text() if start else ""),
            "cloture": _parse_date(end.get_text() if end else ""),
            "lien": BASE + link["href"] if link["href"].startswith("/") else link["href"],
        })
    return calls


def is_relevant(call: dict) -> bool:
    # Les appels de fonds et fondations parlent souvent d'agriculture ou d'environnement sans dire « biodiversité ».
    return is_land_related(f"{call['titre']} {call['porteur']} {call['resume']}")


def select_open(calls: list[dict], today: date | None = None) -> list[dict]:
    """Appels pertinents encore ouverts (clôture absente = ouvert), triés par date de clôture."""
    today = today or date.today()
    kept = [c for c in calls if is_relevant(c) and (c["cloture"] is None or c["cloture"] >= today)]
    return sorted(kept, key=lambda c: (c["cloture"] or date.max, c["titre"]))


def collect(max_pages: int = MAX_PAGES, today: date | None = None) -> tuple[list[dict], dict]:
    """Parcourt les pages et renvoie (appels ouverts pertinents, état de santé de la source)."""
    all_calls, pages_ok = [], 0
    for page in range(1, max_pages + 1):
        resp = http_get(LIST_URL.format(page=page), retries=2)
        if resp is not None:
            found = parse_listing(resp.text)
            if found:
                pages_ok += 1
                all_calls.extend(found)
        time.sleep(THROTTLE_S)
    # Dédoublonnage par lien (une page peut chevaucher la suivante si de nouveaux appels arrivent)
    unique = list({c["lien"]: c for c in all_calls}.values())
    health = {"ok": pages_ok > 0, "pages_ok": pages_ok, "pages_demandees": max_pages, "appels_lus": len(unique)}
    if not health["ok"]:
        print("[calls-watch] ATTENTION : aucun appel lu, la structure de la page a peut-être changé")
    return select_open(unique, today), health


def commit(flagged: list[dict]):
    """Enregistre les appels nouveaux comme vus et les ajoute au journal (après un envoi réussi)."""
    new = [c for c in flagged if c["nouveau"]]
    save_seen(SEEN_FILE, load_seen(SEEN_FILE) + [c["lien"] for c in new])
    append_csv(LOG_OUT, LOG_FIELDS, [
        {"date_detection": datetime.now().strftime("%Y-%m-%d %H:%M"), "titre": c["titre"], "porteur": c["porteur"],
         "publie_le": c["publie_le"], "cloture": c["cloture"], "lien": c["lien"]}
        for c in new
    ])


def run(max_pages: int = MAX_PAGES, today: date | None = None, persist: bool = True) -> tuple[list[dict], dict]:
    """Renvoie (appels à signaler aujourd'hui, santé). Un appel est signalé s'il est nouveau ou urgent."""
    today = today or date.today()
    calls, health = collect(max_pages, today)
    seen = set(load_seen(SEEN_FILE))
    flagged = []
    for c in calls:
        c["nouveau"] = c["lien"] not in seen
        c["urgent"] = c["cloture"] is not None and c["cloture"] <= today + timedelta(days=URGENT_DAYS)
        if c["nouveau"] or c["urgent"]:
            flagged.append(c)
    if persist and health["ok"]:
        commit(flagged)
    print(f"[calls-watch] {len(calls)} appel(s) ouvert(s) sur la nature, {len(flagged)} à signaler")
    return flagged, health


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pages", type=int, default=MAX_PAGES)
    args = parser.parse_args()
    open_calls, health = collect(args.pages)
    print(health)
    for c in open_calls:
        end = c["cloture"].isoformat() if c["cloture"] else "non précisée"
        print(f"- clôture {end} | {c['porteur']} | {c['titre']}\n    {c['lien']}")
