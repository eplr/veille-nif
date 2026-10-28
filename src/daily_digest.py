"""Newsletter hebdomadaire Nature in Finance, alimentée par une collecte quotidienne.

Usage :
    python src/daily_digest.py --weekly       # collecte ; envoi uniquement le lundi UTC
    python src/daily_digest.py --collect-only # collecte et archive, sans email
    python src/daily_digest.py --dry-run --html-out /tmp/veille.html
    python src/daily_digest.py --ignore-seen   # renvoi de test, sans modifier les historiques
"""
import argparse
import html
import sys
from datetime import date, timedelta
from pathlib import Path

import calls_watch
import editorial
import events_watch
import news_archive
import news_watch
import reports as report_files
from lib import PAYS_LABELS, today_utc, parse_date
from send_digest_email import send_email

TITRE = "Veille hebdomadaire Nature in Finance"
REPO_URL = "https://github.com/eplr/veille-nif"
AGENDA_URL = REPO_URL + "/blob/main/dist/pack_avec_pieces_jointes.md"
ARCHIVE_URL = REPO_URL + "/blob/main/data/output/news_archive.json"
FOOTER = (
    "Vous recevez ce message car vous faites partie de la liste de diffusion de la veille Nature in Finance. "
    "Pour ne plus le recevoir, répondez simplement « désinscription »."
)
AUCUNE_ACTU = "Aucune nouvelle actualité retenue pour cette édition."
NOTE_METHODE = (
    "Sélection automatique par mots-clés et priorité de source, sans garantie d’exhaustivité. "
    "Une source primaire ne vaut pas validation de ses affirmations. Vérifiez la source avant de la citer. "
    "L’agenda et les fiches de rapports sont validés à la main ; "
    "les événements marqués « à revérifier » comportent encore une incertitude."
)

MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


# --------------------------------------------------------------------------
# Mise en forme
# --------------------------------------------------------------------------
def fr_day(d: date) -> str:
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"


def fr_range(debut: date, fin: date) -> str:
    """« mar. 13 oct. 2026 », « 3–6 nov. 2026 » ou « 28 oct.–2 nov. 2026 » (tiret demi-cadratin)."""
    if debut == fin:
        return f"{fr_day(debut)} {debut.year}"
    if debut.month == fin.month and debut.year == fin.year:
        return f"{debut.day}–{fin.day} {MOIS[fin.month - 1]} {fin.year}"
    return f"{debut.day} {MOIS[debut.month - 1]}–{fin.day} {MOIS[fin.month - 1]} {fin.year}"


def fr_closing(d: date | None) -> str:
    return f"clôture {fr_day(d)} {d.year}" if d else "clôture non précisée"


def _esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _article_meta(item: dict) -> str:
    published = parse_date(item.get("date_publication", ""))
    parts = [item["source"], PAYS_LABELS.get(item["pays"], item["pays"]),
             published.strftime("%d/%m/%Y") if published else "date de publication non précisée"]
    if item.get("acces") == "abonnement":
        parts.append("accès sur abonnement")
    return " · ".join(parts)


def _period(today: date) -> str:
    return f"Du {(today - timedelta(days=6)).strftime('%d/%m/%Y')} au {today.strftime('%d/%m/%Y')}"


def _event_tags(e: dict, new_ids: set) -> list[str]:
    tags = []
    if e["id"] in new_ids:
        tags.append("nouveau")
    if e.get("en_cours"):
        tags.append("en cours")
    if e.get("confiance") == "moyenne":
        tags.append("à revérifier")
    return tags


# --------------------------------------------------------------------------
# Version texte (Markdown)
# --------------------------------------------------------------------------
def compose_markdown(items, window, new_events, calls, health, today: date, reports=()) -> str:
    new_ids = {e["id"] for e in new_events}
    groups = editorial.group_news(items)
    lines = [f"# {TITRE} – {today.strftime('%d/%m/%Y')}", "", _period(today), ""]

    if items:
        lines.append(f"## Nouveautés – {len(items)} article(s)")
        for label, group in groups.items():
            lines.append(f"### {label}")
            for it in group:
                lines.append(f"- [{it['titre']}]({it['lien']}) – {_article_meta(it)} – {' · '.join(it['themes'])}")
        lines.append("")
    else:
        lines += [f"_{AUCUNE_ACTU}_", ""]
    if not any(editorial.section_for(i) == "science" for i in items):
        lines += ["_Science et génie écologique : aucun nouveau contenu retenu cette semaine._", ""]
    lines += [f"[Consulter les articles collectés]({ARCHIVE_URL})", ""]

    lines.append("## Synthèses de rapports")
    if not reports:
        lines.append("_Aucune nouvelle fiche validée cette semaine._")
    for report in reports:
        lines += [f"### [{report['titre']}]({report['lien']})",
                  f"{report['source']} · publication : {report['date']} · fiche vérifiée : {report['verifie_le']}"]
        lines += [f"- {result}" for result in report["resultats"]]
        lines += [f"**Méthode :** {report['methode']}", f"**Limites :** {report['limites']}",
                  f"**Implications pratiques :** {report['implications']}"]
    lines.append("")

    if window:
        lines.append("## Agenda – prochaines rencontres")
        for e in window[:editorial.MAX_EVENTS]:
            tags = _event_tags(e, new_ids)
            tag_txt = f" [{', '.join(tags)}]" if tags else ""
            lines.append(f"- **{fr_range(e['debut'], e['fin'])}** – [{e['titre']}]({e['lien']}) – {e['lieu']}{tag_txt}")
        lines.append("")
        lines += [f"[Agenda complet des {events_watch.WINDOW_DAYS} prochains jours]({AGENDA_URL})", ""]

    for label, group in editorial.group_opportunities(calls).items():
        lines.append(f"## {label}")
        for c in group:
            flag = "nouveau" if c["nouveau"] else "clôture proche"
            lines.append(f"- [{c['titre']}]({c['lien']}) – {c['porteur']} – {fr_closing(c['cloture'])} [{flag}]")
        lines.append("")

    if not health.get("ok", True):
        lines.append("_Source Carenews indisponible aujourd’hui : la section « Appels à projets » est incomplète._")
        lines.append("")
    lines += ["---", f"_{NOTE_METHODE}_", f"_{FOOTER}_"]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Version HTML (CSS en ligne : indispensable pour Outlook et Microsoft Graph)
# --------------------------------------------------------------------------
# Fond vert sombre. Les accents évitent le vert pour rester lisibles dessus :
# or pour les nouveautés, bleu ciel pour l'agenda, lavande pour les appels à projets.
_BG, _CARD, _HEADER, _BORDER = "#091e16", "#113227", "#0c281e", "#2a5c47"
_TEXT, _MUTED, _BRAND = "#eaf2ec", "#9bb5a5", "#a8dcbe"
_NEWS, _NEWS_BG = "#e8c069", "#362c13"
_AGENDA, _AGENDA_BG = "#84c9e6", "#14323d"
_CALLS, _CALLS_BG = "#bba8f2", "#292245"
_WARN = "#e8a05c"  # panne de source : ne doit pas se confondre avec une couleur de section
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def _badge(label: str, color: str, bg: str) -> str:
    return (f'<div style="display:inline-block;font-size:11px;font-weight:700;letter-spacing:0.6px;'
            f'text-transform:uppercase;color:{color};background:{bg};border-radius:4px;padding:3px 8px;">{_esc(label)}</div>')


def _pill(text: str, color: str) -> str:
    return (f'<span style="display:inline-block;font-size:10px;font-weight:700;color:{color};border:1px solid {color};'
            f'border-radius:3px;padding:1px 5px;margin-left:6px;text-transform:uppercase;letter-spacing:0.4px;">{_esc(text)}</span>')


def _article_row(it: dict) -> str:
    meta = _esc(_article_meta(it)) + " · " + _esc(" · ".join(it["themes"]))
    return (f'<div style="padding:10px 0;border-bottom:1px solid {_BORDER};">'
            f'<a href="{_esc(it["lien"])}" style="font-size:14px;color:{_TEXT};text-decoration:none;font-weight:600;">{_esc(it["titre"])}</a>'
            f'<div style="font-size:12px;color:{_MUTED};margin-top:3px;">{meta}</div></div>')


def _html_news(items: list[dict]) -> str:
    blocks = []
    if not items:
        blocks.append(f'<p style="color:{_MUTED};">{_esc(AUCUNE_ACTU)}</p>')
    for label, group in editorial.group_news(items).items():
        rows = "".join(_article_row(i) for i in group)
        blocks.append(f'<div style="margin-top:16px;"><div style="font-size:12px;font-weight:700;letter-spacing:0.4px;'
                      f'color:{_NEWS};">{_esc(label)}</div>{rows}</div>')
    if not any(editorial.section_for(i) == "science" for i in items):
        blocks.append(f'<p style="font-size:12px;color:{_MUTED};">'
                      'Science et génie écologique : aucun nouveau contenu retenu cette semaine.</p>')
    blocks.append(f'<p><a href="{ARCHIVE_URL}" style="font-size:12px;color:{_BRAND};">'
                  'Consulter les articles collectés</a></p>')
    return (f'<tr><td style="padding:24px 32px 8px 32px;">{_badge(f"Nouveautés – {len(items)}", _NEWS, _NEWS_BG)}'
            f'{"".join(blocks)}</td></tr>')


def _html_agenda(window: list[dict], new_events: list[dict]) -> str:
    if not window:
        return ""
    new_ids = {e["id"] for e in new_events}
    rows = []
    for e in window[:editorial.MAX_EVENTS]:
        pills = "".join(_pill(t, _AGENDA if t == "nouveau" else _MUTED) for t in _event_tags(e, new_ids))
        horaire = f" · {_esc(e['horaire'])}" if e.get("horaire") else ""
        cout = f" · {_esc(e['cout'])}" if e.get("cout") else ""
        rows.append(
            f'<div style="padding:12px 0;border-bottom:1px solid {_BORDER};">'
            f'<div style="font-size:12px;font-weight:700;color:{_AGENDA};">{_esc(fr_range(e["debut"], e["fin"]))}{pills}</div>'
            f'<a href="{_esc(e["lien"])}" style="font-size:14px;color:{_TEXT};text-decoration:none;font-weight:600;">{_esc(e["titre"])}</a>'
            f'<div style="font-size:12px;color:{_MUTED};margin-top:3px;">{_esc(e["lieu"])} · {_esc(e["format"])}{horaire}{cout}</div>'
            f'</div>')
    return (f'<tr><td style="padding:24px 32px 8px 32px;">'
            f'{_badge("Agenda – prochaines rencontres", _AGENDA, _AGENDA_BG)}{"".join(rows)}'
            f'<p><a href="{AGENDA_URL}" style="font-size:12px;color:{_AGENDA};">'
            f'Agenda complet des {events_watch.WINDOW_DAYS} prochains jours</a></p></td></tr>')


def _html_calls(calls: list[dict]) -> str:
    sections = []
    for label, group in editorial.group_opportunities(calls).items():
        rows = []
        for c in group:
            pill = _pill("nouveau", _CALLS) if c["nouveau"] else _pill("clôture proche", _MUTED)
            rows.append(
                f'<div style="padding:10px 0;border-bottom:1px solid {_BORDER};">'
                f'<a href="{_esc(c["lien"])}" style="font-size:14px;color:{_TEXT};text-decoration:none;font-weight:600;">{_esc(c["titre"])}</a>{pill}'
                f'<div style="font-size:12px;color:{_MUTED};margin-top:3px;">{_esc(c["porteur"])} · {_esc(fr_closing(c["cloture"]))}</div></div>')
        sections.append(f'<tr><td style="padding:24px 32px 8px 32px;">{_badge(label, _CALLS, _CALLS_BG)}'
                        f'{"".join(rows)}</td></tr>')
    return "".join(sections)


def _html_reports(reports) -> str:
    rows = []
    for report in reports:
        results = "".join(f"<li>{_esc(result)}</li>" for result in report["resultats"])
        details = "".join(
            f'<p><strong>{label} :</strong> {_esc(report[field])}</p>'
            for label, field in (("Méthode", "methode"), ("Limites", "limites"),
                                 ("Implications pratiques", "implications"))
        )
        rows.append(
            f'<div style="padding:12px 0;border-bottom:1px solid {_BORDER};">'
            f'<a href="{_esc(report["lien"])}" style="color:{_TEXT};font-weight:600;">{_esc(report["titre"])}</a>'
            f'<p style="color:{_MUTED};">{_esc(report["source"])} · {_esc(report["date"])}'
            f' · fiche vérifiée : {_esc(report["verifie_le"])}</p>'
            f'<ul>{results}</ul>{details}</div>'
        )
    if not rows:
        rows.append(f'<p style="color:{_MUTED};">Aucune nouvelle fiche validée cette semaine.</p>')
    return (f'<tr><td style="padding:24px 32px 8px 32px;color:{_TEXT};font-size:13px;line-height:1.6;">'
            f'{_badge("Synthèses de rapports", _BRAND, _HEADER)}{"".join(rows)}</td></tr>')


def compose_html(items, window, new_events, calls, health, today: date, reports=()) -> str:
    warn = ""
    if not health.get("ok", True):
        warn = (f'<tr><td style="padding:16px 32px 0 32px;font-size:12px;color:{_WARN};">'
                'Source Carenews indisponible aujourd’hui : la section « Appels à projets » est incomplète.</td></tr>')
    body = _html_news(items) + _html_reports(reports) + _html_agenda(window, new_events) + _html_calls(calls) + warn
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
</head>
<body style="margin:0;padding:0;background-color:{_BG};font-family:{_FONT};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{_BG};padding:24px 12px;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background-color:{_CARD};border-radius:10px;border:1px solid {_BORDER};overflow:hidden;">
        <tr><td style="background-color:{_HEADER};padding:24px 32px;border-bottom:1px solid {_BORDER};">
          <div style="font-size:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:{_BRAND};">Nature in Finance</div>
          <div style="font-size:20px;font-weight:600;color:{_TEXT};margin-top:6px;">L’hebdo – {today.strftime('%d/%m/%Y')}</div>
          <div style="font-size:12px;color:{_MUTED};margin-top:8px;">{_period(today)}</div>
        </td></tr>
        {body}
        <tr><td style="padding:20px 32px;background-color:{_HEADER};border-top:1px solid {_BORDER};">
          <div style="font-size:12px;color:{_MUTED};line-height:1.6;">{_esc(NOTE_METHODE)}</div>
          <div style="font-size:12px;color:{_MUTED};line-height:1.6;margin-top:8px;">{_esc(FOOTER)}</div>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="composer et afficher, sans envoyer ni enregistrer")
    parser.add_argument("--ignore-seen", action="store_true",
                        help="rejouer les articles connus pour un test, sans modifier les historiques")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--collect-only", action="store_true", help="archiver la collecte sans envoyer")
    mode.add_argument("--weekly", action="store_true", help="collecter chaque jour ; envoyer le lundi UTC seulement")
    parser.add_argument("--max-articles", type=int, default=editorial.MAX_ARTICLES)
    parser.add_argument("--lookback-days", type=int, default=news_watch.LOOKBACK_DAYS)
    parser.add_argument("--html-out", help="écrire l'aperçu HTML dans ce fichier")
    parser.add_argument("--collection-file", help="réutiliser une collecte JSON préparée, sans refaire les requêtes")
    args = parser.parse_args()

    if args.lookback_days < 1 or args.max_articles < 1:
        parser.error("lookback-days et max-articles doivent être strictement positifs")
    today = today_utc().date()
    if args.collection_file:
        path = Path(args.collection_file)
        if not path.is_file():
            parser.error("fichier de collecte introuvable")
        incoming, seen = news_archive.read_json(path, []), None
    else:
        incoming, seen = news_watch.collect(args.lookback_days, ignore_seen=args.ignore_seen)
    archive = news_archive.merge(news_archive.load(), incoming)
    if not args.dry_run and not args.ignore_seen and not args.collection_file:
        news_watch.commit(incoming, seen)
    if args.collect_only or (args.weekly and today.weekday() != 0 and not args.dry_run):
        print(f"[weekly-digest] collecte seule : {len(incoming)} article(s), aucun email")
        return 0

    history = news_archive.deliveries()
    if args.weekly and today.isoformat() in history and not args.ignore_seen and not args.dry_run:
        print("[weekly-digest] édition déjà envoyée aujourd’hui, aucun nouvel envoi")
        return 0
    # Un rejeu utilise les dates de détection courantes sans réécrire l’archive.
    candidates = news_archive.merge(incoming, archive) if args.ignore_seen else news_archive.unsent(archive, history)
    items = editorial.select_news(candidates, today, args.max_articles)
    sent_reports = {rid for edition in history.values() for rid in edition["rapports"]}
    reports = [r for r in report_files.load(today) if args.ignore_seen or r["id"] not in sent_reports][:2]
    window, new_events = events_watch.run(today, persist=False)
    calls, health = calls_watch.run(today=today, persist=False)

    has_content = bool(items or reports or new_events or calls)
    body_md = compose_markdown(items, window, new_events, calls, health, today, reports)
    body_html = compose_html(items, window, new_events, calls, health, today, reports)

    if args.html_out:
        with open(args.html_out, "w", encoding="utf-8") as f:
            f.write(body_html)
        print(f"[daily-digest] aperçu HTML écrit dans {args.html_out}")

    if args.dry_run:
        print(body_md)
        return 0

    subject = f"{TITRE} – {today.strftime('%d/%m/%Y')}" + ("" if has_content else " (rien de nouveau)")
    send_email(subject=subject, body_markdown=body_md, body_html=body_html)
    print("[daily-digest] email envoyé")

    # La collecte est déjà archivée ; seule la diffusion est acquittée après succès.
    if not args.ignore_seen:
        news_archive.mark_sent(today, items, reports)
        visible_ids = {e["id"] for e in window[:editorial.MAX_EVENTS]}
        events_watch.mark_announced([e for e in new_events if e["id"] in visible_ids])
        if health.get("ok"):
            calls_watch.commit(calls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
