"""Transformation des données publiques locales ; aucune lecture de contenu privé Notion."""
import csv
import hashlib
import re
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import calls_watch
import editorial
import events_watch
import news_archive
import reports
from lib import OUTPUT, PAYS_LABELS, detect_themes, load_sources, parse_date

KEYWORDS = {
    "CSRD": r"\bCSRD\b", "SFDR": r"\bSFDR\b", "ESRS E4": r"ESRS E4",
    "IFRS/ISSB": r"\bIFRS\b|\bISSB\b", "TNFD": r"\bTNFD\b", "IPBES": r"\bIPBES\b",
    "Génie écologique": r"g[ée]nie [ée]cologique|ecological engineering",
    "Restauration": r"restauration|restoration",
    "Stratégies territoriales": r"strat[ée]gies? (de )?territ",
    "Engagements": r"engagement|commitment", "Bonnes pratiques": r"bonnes? pratiques?|best practices?",
}


def canonical_url(url):
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc or parts.username or parts.password:
        raise ValueError("URL de contenu invalide : HTTP(S) sans identifiant requis")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(query), ""))


def stable_id(kind, url=None, identifier=None):
    key = str(identifier) if identifier is not None else hashlib.sha256(canonical_url(url).encode()).hexdigest()
    return f"veille-nif:{kind}:{key}"


def rich_text(value, kind="rich_text"):
    value = str(value or "")
    if kind == "title":
        value = value.strip().strip("\u200b\ufeff").strip()
    if len(value) > 190000:
        raise ValueError("Contenu trop long pour une propriété Notion")
    return {kind: [{"type": "text", "text": {"content": value[i:i + 1900]}}
                   for i in range(0, len(value), 1900)]}


def select(value):
    return {"select": {"name": value} if value else None}


def multi_select(values):
    names = sorted({str(v).strip().replace(",", " –") for v in values if str(v).strip()})
    if len(names) > 100 or any(len(name) > 100 for name in names):
        raise ValueError("Liste de tags trop longue pour Notion")
    return {"multi_select": [{"name": name} for name in names]}


def notion_date(raw, end=None):
    if not raw:
        return {"date": None}
    parsed = parse_date(str(raw))
    if not parsed:
        return {"date": None}  # date illisible : ne pas l’inventer
    raw = str(raw)
    # Notion restitue les propriétés date à la minute, même si la source
    # fournit des secondes. Le journal local conserve la précision d’origine.
    start = parsed.date().isoformat() if len(raw) == 10 else parsed.replace(second=0, microsecond=0).isoformat()
    result = {"start": start}
    if end and str(end) != raw:
        result["end"] = date.fromisoformat(str(end)).isoformat()
    return {"date": result}


def base_record(kind, item, key, source=None):
    url = canonical_url(item["lien"])
    if not url or not item.get("titre"):
        raise ValueError("Contenu incomplet : titre et URL requis")
    themes = item.get("themes") or detect_themes(item["titre"])
    if isinstance(themes, str):
        themes = themes.split(" | ")
    return {
        "Nom": rich_text(item["titre"], "title"),
        "Identifiant sync": rich_text(key),
        "Type": select(kind), "URL": {"url": url},
        "Source": rich_text(source or item.get("source", "")),
        "Publication": notion_date(item.get("date_publication")),
        "Détection": notion_date(item.get("date_detection")),
        "Dates événement": notion_date(None), "Clôture": notion_date(None),
        "Thématiques": multi_select(themes),
        "Mots-clés": multi_select([name for name, pattern in KEYWORDS.items()
                                  if re.search(pattern, item["titre"], re.IGNORECASE)]),
        "Écosystèmes": multi_select([]),
        "Zone": select(PAYS_LABELS.get(item.get("pays"))),
        "Rubrique": select(None), "Autorité": select(None), "Accès": select(None),
        "Origine": select("Collecte automatique"), "Validation": select("À valider"),
        "Vérifié le": notion_date(None), "Lieu": rich_text(""), "Horaires": rich_text(""),
        "Contenu source": rich_text(""), "Notes": rich_text(""),
        "Dernière diffusion": notion_date(None),
    }


def article_record(item, sources):
    source = sources.get(item.get("source"), {})
    metadata = {**source, **{k: v for k, v in item.items() if v is not None}}
    themes = item.get("themes") or detect_themes(item["titre"])
    if isinstance(themes, str):
        themes = themes.split(" | ")
    enriched = {**item, "themes": themes, "axe": metadata.get("axe")}
    result = base_record("Actualité", enriched, stable_id("article", item["lien"]))
    result["Rubrique"] = select(editorial.SECTIONS[editorial.section_for(enriched)])
    result["Autorité"] = select(metadata.get("autorite", "presse").capitalize())
    result["Accès"] = select("Abonnement" if metadata.get("acces") == "abonnement" else "Libre")
    return result


def event_record(event):
    result = base_record("Événement", event, stable_id("event", identifier=event["id"]),
                         source=event.get("organisateur"))
    result.update({
        "Dates événement": notion_date(event["debut"], event["fin"]),
        "Vérifié le": notion_date(event["verifie_le"]),
        "Lieu": rich_text(event.get("lieu")), "Horaires": rich_text(event.get("horaire")),
        "Origine": select("Agenda éditorial"),
        "Validation": select("Validé" if event.get("confiance") == "haute" else "À revérifier"),
        "Contenu source": rich_text("\n".join(filter(None, [
            event.get("note"), event.get("cout"), event.get("format"), event.get("source"),
        ]))),
    })
    return result


def report_record(report):
    result = base_record("Rapport", report, stable_id("report", identifier=report["id"]))
    content = "\n".join([*[f"• {item}" for item in report["resultats"]],
                         f"Méthode : {report['methode']}", f"Limites : {report['limites']}",
                         f"Implications pratiques : {report['implications']}"])
    result.update({
        "Publication": notion_date(report["date"]),
        "Vérifié le": notion_date(report["verifie_le"]),
        "Origine": select("Fiche éditoriale"), "Validation": select("Validé"),
        "Contenu source": rich_text(content),
    })
    return result


def call_record(call):
    kinds = {"financement": "Financement", "ao_structure": "AO/RfP pour structures",
             "mission_consultant": "Mission de consultant"}
    kind = call.get("type", "financement")
    if kind not in kinds:
        raise ValueError("Type d’opportunité inconnu")
    result = base_record(kinds[kind], call, stable_id(kind, call["lien"]), source=call.get("porteur"))
    result.update({
        "Publication": notion_date(call.get("publie_le")),
        "Clôture": notion_date(call.get("cloture")),
        "Contenu source": rich_text(call.get("resume")),
    })
    return result


def load_records(today, days=14):
    """Stock récent d’articles (ou tout si days=0), agenda complet, rapports et appels.

    Le CSV permet de reprendre l’historique antérieur à l’archive JSON sans
    prétendre connaître les dates d’envoi de l’ancienne veille quotidienne.
    """
    sources = {s["nom"]: s for s in load_sources()}
    log, rows = OUTPUT / "news_log.csv", []
    if log.exists():
        with log.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
    articles = news_archive.merge(news_archive.load(), rows)
    cutoff = today - timedelta(days=days - 1) if days else date.min
    records, history = {}, news_archive.deliveries()
    sent_articles, sent_reports = {}, {}
    for edition, delivered in sorted(history.items()):
        for url in delivered["articles"]:
            sent_articles[canonical_url(url)] = edition
        for rid in delivered["rapports"]:
            sent_reports[rid] = edition
    for item in articles:
        detected = parse_date(item.get("date_detection", ""))
        if days and (not detected or not cutoff <= detected.date() <= today):
            continue
        record = article_record(item, sources)
        record["Dernière diffusion"] = notion_date(sent_articles.get(canonical_url(item["lien"])))
        records.setdefault(stable_id("article", item["lien"]), record)
    for event in events_watch.load_events():
        records[stable_id("event", identifier=event["id"])] = event_record(event)
    for report in reports.load(today, days=None):
        record = report_record(report)
        record["Dernière diffusion"] = notion_date(sent_reports.get(report["id"]))
        records[stable_id("report", identifier=report["id"])] = record
    for call in news_archive.read_json(calls_watch.SNAPSHOT_FILE, []):
        record = call_record(call)
        records.setdefault(stable_id(call.get("type", "financement"), call["lien"]), record)
    return list(records.values())
