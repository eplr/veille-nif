"""Classement explicite et sélection courte, sans génération ni score opaque."""
from datetime import date, datetime, time, timedelta, timezone
import re

from lib import REGULATION_RE, SCIENCE_RE, is_generic_landing_title, is_nature_related, is_noise, parse_date

SECTIONS = {
    "financement": "Financement et marchés",
    "pratiques": "Pratiques et engagements",
    "reglementation": "Réglementation et standards",
    "science": "Science et génie écologique",
}
AUTHORITY_ORDER = {"primaire": 0, "analyse": 1, "presse": 2, "communication": 3}
MAX_ARTICLES = 15
MAX_EVENTS = 5
OPPORTUNITY_TYPES = {
    "financement": "Appels à projets et financements",
    "ao_structure": "AO/RfP pour structures",
    "mission_consultant": "Missions de consultants indépendants",
}


def edition_calendar(now: datetime, edition: date | None = None):
    """Édition du lundi, semaine civile précédente en UTC, fin exclusive."""
    if now.tzinfo is None:
        raise ValueError("La date de génération doit préciser son fuseau")
    today = now.astimezone(timezone.utc).date()
    edition = edition or today + timedelta(days=(-today.weekday()) % 7)
    if edition.weekday() != 0:
        raise ValueError("La date d’édition doit être un lundi")
    end = datetime.combine(edition, time.min, timezone.utc)
    return edition, end - timedelta(days=7), end


MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin",
          "juillet", "août", "septembre", "octobre", "novembre", "décembre")


def french_date(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def news_period(start: date, end: date) -> str:
    if (start.month, start.year) == (end.month, end.year):
        return f"Actualités du {start.day} au {french_date(end)}"
    return f"Actualités du {french_date(start)} au {french_date(end)}"


FINANCE_RE = re.compile(
    r"financ|invest|fund|fonds|subvention|grant|blended|paiements? pour services"
    r"|payment.*ecosystem|cr[ée]dits? (?:nature|biodiversit)|(?:nature|biodiversity) credits?"
    r"|obligations?|bonds?|capital|assurance|insurance",
    re.IGNORECASE,
)
CAPITAL_ACTION_RE = re.compile(
    r"\blaunch|\braises?\b|\binvests?\b|\bsecures?\b|\bapproves?\b|\bcommits?\b"
    r"|\bannounc|\blanc[ée]?|\b[ée]met\b|\bl[eè]ve\b|\ballou|\baccorde"
    r"|premi[eè]re cl[oô]ture|first clos",
    re.IGNORECASE,
)
ACTION_RE = re.compile(
    r"restauration|restoration|regenerati|projets?|projects?|partenariat|partnership"
    r"|d[ée]ploie|mise en œuvre|implement|terrain|conserv|solutions?",
    re.IGNORECASE,
)


def eligible(item: dict) -> bool:
    """Même garde pour la collecte récente et les contenus déjà archivés."""
    return not is_noise(item["titre"]) and not is_generic_landing_title(item["titre"])


def story_tokens(item: dict) -> set[str]:
    """Rapprochement lexical prudent des titres ; l’archive complète est conservée."""
    title = item["titre"].casefold()
    for expression, alias in (
        (r"\bbank of america\b", "bofa"),
        (r"\bsustainable markets initiative\b", "smi"),
    ):
        title = re.sub(expression, alias, title)
    generic = {
        "the", "and", "for", "with", "new", "to", "in", "of", "a", "an", "by", "on",
        "le", "la", "les", "des", "de", "du", "un", "une", "et", "pour", "dans", "en",
        "lancent", "lance", "launch", "launches", "launching",
        "fund", "funds", "fonds", "million", "millions", "billion", "milliards",
        "nature", "biodiversity", "biodiversité", "invest", "investment", "investir",
        "financing", "finance", "financement", "solutions", "initiative", "managed",
        "gestion", "sous", "faveur", "blue", "economy",
    }
    return {word for word in re.findall(r"[a-zà-ÿ]+", title) if len(word) > 2 and word not in generic}


def same_story(first: dict, second: dict) -> bool:
    if action_priority(first) > 1 or action_priority(second) > 1:
        return False
    left, right = story_tokens(first), story_tokens(second)
    shared = left & right
    return len(shared) >= 2 and len(shared) / max(1, min(len(left), len(right))) >= 0.65


def action_priority(item: dict) -> int:
    """Repère lexical transparent, pas une preuve d’impact ni un avis d’investissement."""
    title = item["titre"]
    nature = is_nature_related(title, wide=True)
    if nature and FINANCE_RE.search(title):
        return 0 if CAPITAL_ACTION_RE.search(title) else 1
    if nature and ACTION_RE.search(title):
        return 2
    if nature and REGULATION_RE.search(title):
        return 3
    return 4 if nature else 5


def group_opportunities(calls: list[dict]) -> dict[str, list[dict]]:
    groups = {}
    for call in calls:
        kind = call.get("type", "financement")
        if kind not in OPPORTUNITY_TYPES:
            raise ValueError(f"Type d’opportunité invalide : {kind}")
        groups.setdefault(kind, []).append(call)
    return {label: groups[kind] for kind, label in OPPORTUNITY_TYPES.items() if kind in groups}


def section_for(item: dict) -> str:
    if is_nature_related(item["titre"], wide=True) and FINANCE_RE.search(item["titre"]):
        return "financement"
    if item.get("axe") in SECTIONS:
        return item["axe"]
    text = f"{item['titre']} {' '.join(item.get('themes', []))}"
    if REGULATION_RE.search(text) or "Réglementation et supervision" in item.get("themes", []):
        return "reglementation"
    if (SCIENCE_RE.search(item["titre"])
            or {"Cadre mondial et science", "Science et génie écologique"} & set(item.get("themes", []))):
        return "science"
    if "Instruments et marchés" in item.get("themes", []):
        return "financement"
    return "pratiques"


def priority(item: dict) -> tuple:
    dt = parse_date(item.get("date_publication", ""))
    return (
        action_priority(item),
        AUTHORITY_ORDER.get(item.get("autorite"), 2),
        0 if item.get("source_id") else 1,
        -(dt.timestamp() if dt else 0),
        item["titre"].casefold(),
        item["lien"],
    )


def select_news(items: list[dict], today: date, limit: int = MAX_ARTICLES, days: int = 7,
                publication_window=None) -> list[dict]:
    """Réserve une place à la science ; les autres contenus restent dans l’archive.

    La date de détection définit la période éditoriale ; la collecte filtre déjà
    les dates de publication. Une date absente n’est pas inventée.
    """
    if limit < 1 or days < 1:
        raise ValueError("Le plafond et la période doivent être strictement positifs")
    start = today - timedelta(days=days - 1)
    candidates = []
    for item in items:
        if not eligible(item):
            continue
        if publication_window is not None:
            published = parse_date(item.get("date_publication", ""))
            if published and publication_window[0] <= published < publication_window[1]:
                candidates.append(item)
            continue
        detected = parse_date(item.get("date_detection", ""))
        if detected and start <= detected.date() <= today:
            candidates.append(item)
    ordered = []
    for item in sorted(candidates, key=priority):
        if not any(same_story(item, previous) for previous in ordered):
            ordered.append(item)
    science = next((i for i in ordered if section_for(i) == "science"), None)
    selected = [science] if science else []
    selected += [i for i in ordered if i is not science][:limit - len(selected)]
    return sorted(selected, key=lambda i: (list(SECTIONS).index(section_for(i)), priority(i)))


def group_news(items: list[dict]) -> dict[str, list[dict]]:
    return {
        label: sorted([i for i in items if section_for(i) == key], key=priority)
        for key, label in SECTIONS.items()
        if any(section_for(i) == key for i in items)
    }
