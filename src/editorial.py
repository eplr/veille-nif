"""Classement explicite et sélection courte, sans génération ni score opaque."""
from datetime import date, timedelta

from lib import REGULATION_RE, SCIENCE_RE, parse_date

SECTIONS = {
    "reglementation": "Réglementation et standards",
    "science": "Science et génie écologique",
    "financement": "Financement et marchés",
    "pratiques": "Pratiques et engagements",
}
AUTHORITY_ORDER = {"primaire": 0, "analyse": 1, "presse": 2, "communication": 3}
MAX_ARTICLES = 15
MAX_EVENTS = 5
OPPORTUNITY_TYPES = {
    "financement": "Appels à projets et financements",
    "ao_structure": "AO/RfP pour structures",
    "mission_consultant": "Missions de consultants indépendants",
}


def group_opportunities(calls: list[dict]) -> dict[str, list[dict]]:
    groups = {}
    for call in calls:
        kind = call.get("type", "financement")
        if kind not in OPPORTUNITY_TYPES:
            raise ValueError(f"Type d’opportunité invalide : {kind}")
        groups.setdefault(kind, []).append(call)
    return {label: groups[kind] for kind, label in OPPORTUNITY_TYPES.items() if kind in groups}


def section_for(item: dict) -> str:
    if item.get("axe") in SECTIONS:
        return item["axe"]
    text = f"{item['titre']} {' '.join(item.get('themes', []))}"
    if REGULATION_RE.search(text) or "Réglementation et supervision" in item.get("themes", []):
        return "reglementation"
    if SCIENCE_RE.search(item["titre"]) or "Cadre mondial et science" in item.get("themes", []):
        return "science"
    if "Instruments et marchés" in item.get("themes", []):
        return "financement"
    return "pratiques"


def priority(item: dict) -> tuple:
    dt = parse_date(item.get("date_publication", ""))
    return (
        AUTHORITY_ORDER.get(item.get("autorite"), 2),
        -(dt.timestamp() if dt else 0),
        item["titre"].casefold(),
        item["lien"],
    )


def select_news(items: list[dict], today: date, limit: int = MAX_ARTICLES, days: int = 7) -> list[dict]:
    """Réserve une place à la science ; les autres contenus restent dans l’archive.

    La date de détection définit la période éditoriale ; la collecte filtre déjà
    les dates de publication. Une date absente n’est pas inventée.
    """
    if limit < 1 or days < 1:
        raise ValueError("Le plafond et la période doivent être strictement positifs")
    start = today - timedelta(days=days - 1)
    candidates = []
    for item in items:
        detected = parse_date(item.get("date_detection", ""))
        if detected and start <= detected.date() <= today:
            candidates.append(item)
    ordered = sorted(candidates, key=priority)
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
