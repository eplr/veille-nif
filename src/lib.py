"""Fonctions communes de la veille Nature in Finance.

HTTP avec relances, lecture de flux RSS/Atom, requêtes Google News RSS,
gestion des dates, filtres par mots-clés et fichiers d'état (déduplication).
"""
import html
import json
import pathlib
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
INTERIM = DATA / "interim"
OUTPUT = DATA / "output"
DIST = ROOT / "dist"

USER_AGENT = "veille-nif/0.1 (+https://github.com/eplr/veille-nif)"
RETRY_STATUSES = {429, 500, 502, 503, 504}

PAYS_LABELS = {
    "FR": "France",
    "UE": "Europe",
    "CH": "Suisse",
    "UK": "Royaume-Uni",
    "INT": "International",
}
PAYS_ORDER = ["FR", "UE", "CH", "UK", "INT"]


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def http_get(url: str, timeout: int = 25, retries: int = 3, backoff: float = 3.0, **kwargs) -> requests.Response | None:
    """GET avec relances sur les statuts transitoires. Renvoie None en cas d'échec."""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    headers.update(kwargs.pop("headers", {}))
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            print(f"[http] {url} : {exc.__class__.__name__}")
            if attempt == retries:
                return None
            time.sleep(backoff * attempt)
            continue
        if resp.status_code in RETRY_STATUSES and attempt < retries:
            time.sleep(backoff * attempt)
            continue
        if resp.status_code >= 400:
            print(f"[http] {url} : HTTP {resp.status_code}")
            return None
        return resp
    return None


# --------------------------------------------------------------------------
# Registre des sources
# --------------------------------------------------------------------------
def load_sources() -> list[dict]:
    with (DATA / "sources.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)["sources"]


# --------------------------------------------------------------------------
# Flux RSS / Atom
# --------------------------------------------------------------------------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(elem: ET.Element, *names: str) -> str:
    for child in elem:
        if _local(child.tag) in names and (child.text or "").strip():
            return child.text.strip()
    return ""


def strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def parse_feed(content: bytes) -> list[dict]:
    """Lit un flux RSS 2.0 ou Atom. Renvoie une liste de dicts title/link/pub_date/summary."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    items = []
    for node in root.iter():
        kind = _local(node.tag)
        if kind not in ("item", "entry"):
            continue
        title = strip_html(_child_text(node, "title"))
        link = _child_text(node, "link")
        if not link:  # Atom : <link href="..."/>
            for child in node:
                if _local(child.tag) == "link" and child.get("href"):
                    if child.get("rel") in (None, "alternate"):
                        link = child.get("href")
                        break
        pub = _child_text(node, "pubDate", "published", "updated", "date")
        summary = strip_html(_child_text(node, "description", "summary", "encoded", "content"))
        if title and link:
            items.append({"title": title, "link": link, "pub_date": pub, "summary": summary[:600]})
    return items


def fetch_feed(url: str) -> list[dict]:
    resp = http_get(url)
    if resp is None:
        return []
    return parse_feed(resp.content)


def google_news_rss(query: str, hl: str = "fr", gl: str = "FR", ceid: str = "FR:fr") -> list[dict]:
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": hl, "gl": gl, "ceid": ceid}
    )
    resp = http_get(url)
    if resp is None:
        return []
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        print(f"[google-news] flux illisible pour : {query}")
        return []
    items = []
    for item in root.iter("item"):
        title = strip_html(_child_text(item, "title"))
        link = _child_text(item, "link")
        source = _child_text(item, "source")
        # Google News ajoute « - Source » en fin de titre : on le retire.
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].rstrip()
        items.append({
            "title": title,
            "link": link,
            "pub_date": _child_text(item, "pubDate"),
            "source": source,
            "summary": "",
        })
    return items


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------
def parse_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def within_lookback(pub_date: str, lookback_days: int) -> bool:
    """Vrai si l'article est récent. Une date illisible ou absente est conservée."""
    dt = parse_date(pub_date)
    if dt is None:
        return True
    return dt >= datetime.now(timezone.utc) - timedelta(days=lookback_days)


def today_utc() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Filtres et étiquettes
# --------------------------------------------------------------------------
NATURE_RE = re.compile(
    r"biodiversit|biodiversity|\bnature[- ](related|positive|loss|risk|finance|based|restoration|capital)"
    r"|capital naturel|natural capital|[ée]cosyst[eè]m|ecosystem|d[ée]forestation|deforestation"
    r"|\bTNFD\b|\bSBTN\b|ESRS E4|kunming|restauration de la nature|nature restoration"
    r"|cr[ée]dits? (biodiversit[ée]|nature)|(biodiversity|nature) credits?|Biodiversit[äa]t|Naturkapital"
    r"|naturbezogen|risques? (li[ée]s? )?(à|a) la nature|forest|for[êe]t|oc[ée]an|pollinis|pollinat"
    r"|planetary boundaries|limites plan[ée]taires|\bIPBES\b|diversit[ée] biologique|wildlife|faune"
    r"|\bspecies\b|esp[èe]ces menac"
    r"|climat(ique)?s? et (la )?nature|nature et (du )?climat|climate and nature|nature and climate",
    re.IGNORECASE,
)

# Plus large que NATURE_RE : utilisé sur les requêtes thématiques, déjà ciblées sur la nature,
# où un titre comme « Chiffrer la nature pour enfin la prendre en compte ? » doit passer.
NATURE_WIDE_RE = re.compile(r"\bnature\b|risques? naturels?|\bnaturkapital|\bnaturrisiken", re.IGNORECASE)

# Vocabulaire agricole et environnemental, pour les sources de fonds et fondations (Carenews) dont les
# titres parlent de paysans, d'alimentation ou d'environnement sans citer la biodiversité.
FARM_ENV_RE = re.compile(
    r"environnement|[ée]cologi|agro-?[ée]cologi|zones? humides?|littoral|\bmer\b|vivant"
    r"|agricultur|paysan|alimentation durable|haies?\b|sols? vivants?|pesticid|oiseaux|esp[èe]ces|pollinis",
    re.IGNORECASE,
)

# Pages administratives et offres d'emploi, sans intérêt pour la veille.
NOISE_RE = re.compile(
    r"^d[ée]cision n°|ABSCH-|\bGCF n°|\bCIDDAE|offre d.emploi|recrutement|adjoint-e|charg[ée]-e"
    r"|g[ée]omaticien|^agenda de ",
    re.IGNORECASE,
)

THEMES = {
    "Reporting et standards": r"\bTNFD\b|ESRS|\bISSB\b|\bCSRD\b|reporting|disclosure|divulgation|\bSBTN\b|science.based",
    "Réglementation et supervision": r"SFDR|taxonomi|taxonomy|nature restoration (law|regulation)|r[èe]glement|regulation|directive|article 29|\bloi\b|supervis|superviseur|\bAMF\b|\bFCA\b|FINMA|\bESMA\b|\bEBA\b|\bBCE\b|\bECB\b",
    "Risques et dépendances": r"risque|risk|d[ée]pendanc|dependenc|stress.test|physical risk",
    "Instruments et marchés": r"cr[ée]dits? (biodiversit[ée]|nature)|(biodiversity|nature) credits?|obligation|\bbonds?\b|\bfonds?\b|\bfunds?\b|blended|financement|financing|investissement|investment|investor",
    "Cadre mondial et science": r"kunming|montr[ée]al|\bGBF\b|\bCOP ?(1[6-9]|[2-9]\d)\b|\bIPBES\b|\bCBD\b|diversit[ée] biologique|biodiversity framework|planetary boundaries|limites plan[ée]taires",
    "Solutions fondées sur la nature": r"nature.based solution|solutions? fond[ée]es? sur la nature|restoration|restauration|reforest|reboisement|agro[ée]cologi|regenerative|net gain",
}
THEME_RES = {name: re.compile(rx, re.IGNORECASE) for name, rx in THEMES.items()}
DEFAULT_THEME = "Autres signaux"


def is_nature_related(text: str, wide: bool = False) -> bool:
    text = text or ""
    return bool(NATURE_RE.search(text) or (wide and NATURE_WIDE_RE.search(text)))


def is_land_related(text: str) -> bool:
    """Nature au sens large : biodiversité, nature, mais aussi agriculture et environnement."""
    text = text or ""
    return bool(NATURE_RE.search(text) or NATURE_WIDE_RE.search(text) or FARM_ENV_RE.search(text))


def is_noise(title: str) -> bool:
    return bool(NOISE_RE.search(title or ""))


def detect_themes(text: str) -> list[str]:
    found = [name for name, rx in THEME_RES.items() if rx.search(text or "")]
    return found or [DEFAULT_THEME]


def normalize_title(title: str) -> str:
    t = re.sub(r"[^\w\s]", " ", (title or "").lower())
    return re.sub(r"\s+", " ", t).strip()


GENERIC_TITLES = {"accueil", "home", "homepage", "actualités", "news", "newsroom"}


def is_generic_landing_title(title: str) -> bool:
    return normalize_title(title) in GENERIC_TITLES or len((title or "").strip()) < 12


# --------------------------------------------------------------------------
# Fichiers d'état
# --------------------------------------------------------------------------
def load_seen(path: pathlib.Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return list(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return []


def save_seen(path: pathlib.Path, seen: list[str], keep: int = 8000):
    """Enregistre en conservant l'ordre d'insertion et en gardant les `keep` plus récents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    unique = list(dict.fromkeys(seen))[-keep:]
    path.write_text(json.dumps(unique, ensure_ascii=False, indent=0), encoding="utf-8")


def append_csv(path: pathlib.Path, fieldnames: list[str], rows: list[dict]):
    import csv

    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if is_new:
            w.writeheader()
        w.writerows(rows)
