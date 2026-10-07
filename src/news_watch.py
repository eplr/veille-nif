"""Veille quotidienne : actualités finance durable, axe nature et biodiversité.

Trois canaux :
1. Flux RSS/Atom directs des sources du registre (data/sources.yaml).
2. Requêtes Google News « site: » pour les sources sans flux valide.
3. Requêtes thématiques Google News par zone (France, Europe, Suisse, Royaume-Uni).

Seuls les articles nouveaux (absents de data/interim/news_seen.json) et récents
sont renvoyés. Chaque article porte un pays et des thèmes.

Usage :
    python src/news_watch.py                    # veille normale
    python src/news_watch.py --lookback-days 7  # première exécution, fenêtre plus large
    python src/news_watch.py --check-sources    # vérifie que toutes les sources répondent
"""
import argparse
import time

from lib import (
    INTERIM, OUTPUT, append_csv, detect_themes, fetch_feed, google_news_rss, http_get,
    is_generic_landing_title, is_land_related, is_nature_related, is_noise, load_seen, load_sources,
    normalize_title, parse_feed, save_seen, today_utc, within_lookback,
)

SEEN_FILE = INTERIM / "news_seen.json"
LOG_OUT = OUTPUT / "news_log.csv"
LOG_FIELDS = ["date_detection", "pays", "source", "titre", "themes", "date_publication", "lien", "canal"]

LOOKBACK_DAYS = 3
THROTTLE_S = 1.0
SITE_MIN_TITLE = 25  # sur le canal « site: », les titres plus courts sont presque toujours des pages de navigation

# Sources bruitées à ignorer (nom de l'éditeur tel que renvoyé par Google News, en minuscules).
SOURCE_BLOCKLIST = {"orange actualités", "vietnam.vn"}

# Mots-clés ajoutés aux requêtes « site: » des sources généralistes.
# Pour le filtre « mots_cles_large » (Carenews) : vocabulaire agricole et environnemental inclus.
SITE_KEYWORDS_LARGE = "(biodiversité OR nature OR agriculture OR paysans OR environnement OR écologie)"
SITE_KEYWORDS = {
    "fr": '(biodiversité OR nature OR TNFD OR "capital naturel")',
    "en": '(biodiversity OR "nature-related" OR TNFD OR "natural capital")',
    "de": "(Biodiversität OR Naturkapital OR TNFD)",
}

# Requêtes thématiques par zone. Syntaxe Google : espace = ET, OR en majuscules,
# guillemets pour une expression exacte.
ZONES = [
    {
        "id": "FR", "pays": "FR", "hl": "fr", "gl": "FR", "ceid": "FR:fr",
        "queries": [
            'TNFD OR "Taskforce on Nature-related Financial Disclosures"',
            'biodiversité (finance OR investissement OR banque OR assurance OR "société de gestion")',
            '("ESRS E4" OR CSRD) (biodiversité OR nature)',
            '"crédits biodiversité" OR "crédits nature" OR "compensation biodiversité"',
            '"capital naturel" (finance OR entreprise OR comptabilité)',
            '"article 29" "loi énergie-climat" biodiversité',
            '"risques liés à la nature" (banque OR assureur OR superviseur)',
        ],
    },
    {
        "id": "UE", "pays": "UE", "hl": "en", "gl": "IE", "ceid": "IE:en",
        "queries": [
            '"Nature Restoration Law" (finance OR investment OR implementation)',
            '("ESRS E4" OR EFRAG) (biodiversity OR nature)',
            '"EU taxonomy" (biodiversity OR nature)',
            'SFDR (biodiversity OR "nature-related")',
            '(ECB OR "European Central Bank") (nature OR biodiversity) risk',
            '"EU biodiversity" finance strategy',
        ],
    },
    {
        "id": "CH-fr", "pays": "CH", "hl": "fr", "gl": "CH", "ceid": "CH:fr",
        "queries": [
            'biodiversité (finance OR banque OR assurance OR investisseurs) Suisse',
            'OFEV biodiversité finance',
        ],
    },
    {
        "id": "CH-de", "pays": "CH", "hl": "de", "gl": "CH", "ceid": "CH:de",
        "queries": [
            'Biodiversität (Finanzplatz OR Banken OR Investoren OR Versicherer) Schweiz',
            '(Naturkapital OR "naturbezogene Risiken") Finanz',
            'FINMA (Biodiversität OR Naturrisiken)',
        ],
    },
    {
        "id": "UK", "pays": "UK", "hl": "en-GB", "gl": "GB", "ceid": "GB:en",
        "queries": [
            'TNFD (adoption OR disclosure) (UK OR Britain)',
            '"nature-related" (risk OR disclosure OR finance) (UK OR Britain)',
            '"biodiversity credits" OR "nature credits"',
            '("nature finance" OR "nature-positive") investors',
            '"UK Sustainability Reporting Standards" (nature OR biodiversity)',
            '"Biodiversity Net Gain" (finance OR investment)',
        ],
    },
]


def site_query(source: dict, lookback_days: int = LOOKBACK_DAYS) -> str:
    q = f"site:{source['domaine']} when:{lookback_days}d"
    if source.get("requete_extra"):
        q += f" {source['requete_extra']}"
    if source["filtre"] == "mots_cles":
        q += " " + SITE_KEYWORDS.get(source["langue"], SITE_KEYWORDS["en"])
    elif source["filtre"] == "mots_cles_large":
        q += " " + SITE_KEYWORDS_LARGE
    return q


class Seen:
    """Ensemble ordonné des liens et titres déjà traités (persisté dans news_seen.json).

    Les titres normalisés sont préfixés par « t: » pour éviter qu'un même article
    relayé par plusieurs sources ne soit signalé deux fois.
    """

    def __init__(self, path, ignore_existing: bool = False):
        """ignore_existing : rejoue la veille (renvoi d'un email) sans oublier l'historique.

        Le filtre ne consulte alors que ce qui est vu pendant cette exécution, mais `order`
        conserve tout l'historique : save() ne fait donc rien perdre.
        """
        self.path = path
        self.order = load_seen(path)
        self.replay = ignore_existing
        self._stored = set(self.order)
        self.keys = set() if ignore_existing else set(self.order)

    def __contains__(self, key: str) -> bool:
        return key in self.keys

    def add(self, key: str):
        self.keys.add(key)
        if key not in self._stored:
            self._stored.add(key)
            self.order.append(key)

    def save(self):
        save_seen(self.path, self.order)


def _accept(item: dict, seen: Seen, lookback_days: int) -> bool:
    """Filtres communs. Les articles écartés sont marqués comme vus pour ne pas les réexaminer."""
    key = item["link"] or item["title"]
    tkey = f"t:{normalize_title(item['title'])}"
    if key in seen or tkey in seen:
        return False
    seen.add(key)
    seen.add(tkey)
    if item.get("source", "").strip().lower() in SOURCE_BLOCKLIST:
        return False
    if not within_lookback(item["pub_date"], lookback_days):
        return False
    if is_generic_landing_title(item["title"]) or is_noise(item["title"]):
        return False
    return True


def collect(lookback_days: int = LOOKBACK_DAYS, ignore_seen: bool = False) -> tuple[list[dict], "Seen"]:
    """Interroge toutes les sources. Renvoie (articles nouveaux, état de déduplication non enregistré).

    Rien n'est écrit sur disque : l'appelant enregistre avec commit() une fois l'email envoyé, pour qu'un
    échec d'envoi ne fasse pas perdre d'articles.

    ignore_seen : renvoie aussi les articles déjà envoyés (renvoi d'un email de test).
    """
    seen = Seen(SEEN_FILE, ignore_existing=ignore_seen)
    new_items: list[dict] = []
    now_str = today_utc().strftime("%Y-%m-%d %H:%M")

    def keep(item: dict, pays: str, source_name: str, canal: str):
        text = f"{item['title']} {item.get('summary', '')}"
        new_items.append({
            "date_detection": now_str,
            "pays": pays,
            "source": source_name,
            "titre": item["title"],
            "themes": detect_themes(text),
            "date_publication": item["pub_date"],
            "lien": item["link"],
            "canal": canal,
        })

    sources = load_sources()

    # 1 et 2. Sources du registre
    for src in sources:
        if src.get("rss"):
            items = fetch_feed(src["rss"])
            canal = "rss"
        elif src.get("domaine"):
            items = _site_news(src, lookback_days)
            canal = "site"
        else:
            continue
        for item in items:
            if not _accept(item, seen, lookback_days):
                continue
            # Les requêtes « site: » remontent aussi des pages dont le menu contient les mots-clés
            # (taux de change, échéances…) : on revérifie donc le titre, et on écarte les titres très courts.
            text = f"{item['title']} {item.get('summary', '')}"
            if src["filtre"] == "mots_cles" and not is_nature_related(text):
                continue
            if src["filtre"] == "mots_cles_large" and not is_land_related(text):
                continue
            if canal == "site" and len(item["title"]) < SITE_MIN_TITLE:
                continue
            keep(item, src["pays"], src["nom"], canal)
        time.sleep(THROTTLE_S if canal != "rss" else 0.3)

    # 3. Requêtes thématiques par zone
    for zone in ZONES:
        for query in zone["queries"]:
            for item in google_news_rss(f"{query} when:{lookback_days}d", hl=zone["hl"], gl=zone["gl"], ceid=zone["ceid"]):
                # Google News traite mal les opérateurs booléens : on revérifie le titre.
                if _accept(item, seen, lookback_days) and is_nature_related(item["title"], wide=True):
                    keep(item, zone["pays"], item["source"] or "Google News", "zone")
            time.sleep(THROTTLE_S)

    print(f"[news-watch] {len(new_items)} nouvel(le)s article(s)")
    return new_items, seen


def commit(new_items: list[dict], seen: "Seen"):
    """Enregistre l'état de déduplication et le journal CSV.

    En mode rejeu, le journal n'est pas alimenté : ces articles y figurent déjà, et le pack
    dist/ en reprendrait des doublons.
    """
    seen.save()
    if seen.replay:
        return
    append_csv(LOG_OUT, LOG_FIELDS, [{**i, "themes": " | ".join(i["themes"])} for i in new_items])


def run(lookback_days: int = LOOKBACK_DAYS, persist: bool = True) -> list[dict]:
    """Collecte puis, si persist, enregistre immédiatement (usage en ligne de commande)."""
    new_items, seen = collect(lookback_days)
    if persist:
        commit(new_items, seen)
    return new_items


def _site_news(src: dict, lookback_days: int = LOOKBACK_DAYS) -> list[dict]:
    zone_by_pays = {"FR": ("fr", "FR", "FR:fr"), "CH": ("fr", "CH", "CH:fr"), "UK": ("en-GB", "GB", "GB:en")}
    hl, gl, ceid = zone_by_pays.get(src["pays"], ("en", "IE", "IE:en"))
    items = google_news_rss(site_query(src, lookback_days), hl=hl, gl=gl, ceid=ceid)
    for it in items:
        it["source"] = it["source"] or src["nom"]
    return items


def check_sources() -> int:
    """Vérifie les pages d'accueil et les flux. Renvoie le nombre de sources en défaut."""
    problems = 0
    for src in load_sources():
        resp = http_get(src["url"], retries=2)
        home = "ok" if resp is not None else "ÉCHEC"
        feed = "-"
        if src.get("rss"):
            r = http_get(src["rss"], retries=2)
            n = len(parse_feed(r.content)) if r is not None else 0
            feed = f"{n} article(s)" if n else "ÉCHEC"
        if home != "ok" or feed == "ÉCHEC":
            problems += 1
        print(f"{src['id']:<24} accueil={home:<6} flux={feed}")
        time.sleep(0.3)
    print(f"\n{problems} source(s) en défaut sur {len(load_sources())}")
    return problems


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lookback-days", type=int, default=LOOKBACK_DAYS)
    parser.add_argument("--check-sources", action="store_true")
    args = parser.parse_args()
    if args.check_sources:
        raise SystemExit(1 if check_sources() else 0)
    for it in run(args.lookback_days):
        print(f"- [{it['pays']}] {it['source']} : {it['titre']}")
