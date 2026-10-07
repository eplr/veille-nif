"""Veille quotidienne Nature in Finance : agrège, compose et envoie l'email.

Trois blocs :
1. Nouveautés : articles des sources du registre (par pays), puis presse et veille thématique.
2. Agenda des 60 prochains jours (data/events.yaml).
3. Appels à projets en cours relayés par Carenews (nouveaux ou qui se clôturent sous 14 jours).

Un email part chaque jour, même sans nouveauté : dans ce cas l'objet porte la mention « rien de nouveau » et
l'email le dit. L'état de déduplication n'est enregistré qu'après un envoi réussi : un échec d'envoi ne fait
perdre aucun article.

Usage :
    python src/daily_digest.py                        # exécution normale
    python src/daily_digest.py --dry-run              # compose et affiche, n'envoie ni n'enregistre rien
    python src/daily_digest.py --dry-run --html-out /tmp/veille.html   # aperçu HTML à ouvrir dans un navigateur
    python src/daily_digest.py --ignore-seen          # renvoi d'un test : inclut les articles déjà envoyés
    python src/daily_digest.py --lookback-days 7      # première exécution : fenêtre plus large
"""
import argparse
import html
import sys
from datetime import date

import calls_watch
import events_watch
import news_watch
from lib import DEFAULT_THEME, PAYS_LABELS, PAYS_ORDER, THEMES, parse_date
from send_digest_email import send_email

TITRE = "Veille Nature in Finance"
FOOTER = (
    "Vous recevez ce message car vous faites partie de la liste de diffusion de la veille Nature in Finance. "
    "Pour ne plus le recevoir, répondez simplement « désinscription »."
)
AUCUNE_ACTU = "Aucune nouvelle actualité depuis le précédent envoi."
NOTE_METHODE = (
    "Sélection automatique par mots-clés : vérifiez toujours la source avant de la citer. "
    "L’agenda est validé à la main ; les événements marqués « à revérifier » reposent sur une source secondaire."
)

MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
THEME_ORDER = list(THEMES) + [DEFAULT_THEME]


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


def _sort_news(items: list[dict]) -> list[dict]:
    """Du plus récent au plus ancien (date de publication ; date illisible en dernier)."""
    def key(i):
        dt = parse_date(i["date_publication"])
        return dt.timestamp() if dt else 0
    return sorted(items, key=key, reverse=True)


def split_news(items: list[dict]) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """(sources du registre groupées par pays, presse et veille thématique groupée par thème)."""
    registry: dict[str, list[dict]] = {}
    press: dict[str, list[dict]] = {}
    for it in _sort_news(items):
        if it["canal"] in ("rss", "site"):
            registry.setdefault(it["pays"], []).append(it)
        else:
            press.setdefault(it["themes"][0], []).append(it)
    registry = {p: registry[p] for p in PAYS_ORDER if p in registry}
    press = {t: press[t] for t in THEME_ORDER if t in press}
    return registry, press


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
def compose_markdown(items, window, new_events, calls, health, today: date) -> str:
    new_ids = {e["id"] for e in new_events}
    registry, press = split_news(items)
    lines = [f"# {TITRE} – {today.strftime('%d/%m/%Y')}", ""]

    if items:
        lines.append(f"## Nouveautés – {len(items)} article(s)")
        for pays, group in registry.items():
            lines.append(f"### {PAYS_LABELS[pays]}")
            for it in group:
                lines.append(f"- [{it['titre']}]({it['lien']}) ({it['source']}) – {' · '.join(it['themes'])}")
        if press:
            lines.append("### Presse et veille thématique")
            for theme, group in press.items():
                lines.append(f"**{theme}**")
                for it in group:
                    lines.append(f"- [{it['titre']}]({it['lien']}) ({it['source']})")
        lines.append("")
    else:
        lines += [f"_{AUCUNE_ACTU}_", ""]

    if window:
        lines.append(f"## Agenda des {events_watch.WINDOW_DAYS} prochains jours")
        for e in window:
            tags = _event_tags(e, new_ids)
            tag_txt = f" [{', '.join(tags)}]" if tags else ""
            lines.append(f"- **{fr_range(e['debut'], e['fin'])}** – [{e['titre']}]({e['lien']}) – {e['lieu']}{tag_txt}")
        lines.append("")

    if calls:
        lines.append("## Appels à projets en cours")
        for c in calls:
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


def _article_row(it: dict, show_themes: bool) -> str:
    meta = _esc(it["source"])
    if show_themes:
        meta += " · " + _esc(" · ".join(it["themes"]))
    return (f'<div style="padding:10px 0;border-bottom:1px solid {_BORDER};">'
            f'<a href="{_esc(it["lien"])}" style="font-size:14px;color:{_TEXT};text-decoration:none;font-weight:600;">{_esc(it["titre"])}</a>'
            f'<div style="font-size:12px;color:{_MUTED};margin-top:3px;">{meta}</div></div>')


def _html_news(items: list[dict]) -> str:
    if not items:
        return (f'<tr><td style="padding:24px 32px 0 32px;font-size:14px;color:{_MUTED};">'
                f'{_esc(AUCUNE_ACTU)}</td></tr>')
    registry, press = split_news(items)
    blocks = []
    for pays, group in registry.items():
        rows = "".join(_article_row(i, True) for i in group)
        blocks.append(f'<div style="margin-top:16px;"><div style="font-size:12px;font-weight:700;letter-spacing:0.4px;'
                      f'text-transform:uppercase;color:{_NEWS};">{_esc(PAYS_LABELS[pays])}</div>{rows}</div>')
    if press:
        rows = ""
        for theme, group in press.items():
            rows += (f'<div style="font-size:11px;font-weight:700;color:{_MUTED};text-transform:uppercase;'
                     f'letter-spacing:0.4px;margin-top:12px;">{_esc(theme)}</div>')
            rows += "".join(_article_row(i, False) for i in group)
        blocks.append(f'<div style="margin-top:20px;"><div style="font-size:12px;font-weight:700;letter-spacing:0.4px;'
                      f'text-transform:uppercase;color:{_NEWS};">Presse et veille thématique</div>{rows}</div>')
    return (f'<tr><td style="padding:24px 32px 8px 32px;">{_badge(f"Nouveautés – {len(items)}", _NEWS, _NEWS_BG)}'
            f'{"".join(blocks)}</td></tr>')


def _html_agenda(window: list[dict], new_events: list[dict]) -> str:
    if not window:
        return ""
    new_ids = {e["id"] for e in new_events}
    rows = []
    for e in window:
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
            f'{_badge(f"Agenda – {events_watch.WINDOW_DAYS} prochains jours", _AGENDA, _AGENDA_BG)}{"".join(rows)}</td></tr>')


def _html_calls(calls: list[dict]) -> str:
    if not calls:
        return ""
    rows = []
    for c in calls:
        pill = _pill("nouveau", _CALLS) if c["nouveau"] else _pill("clôture proche", _MUTED)
        rows.append(
            f'<div style="padding:10px 0;border-bottom:1px solid {_BORDER};">'
            f'<a href="{_esc(c["lien"])}" style="font-size:14px;color:{_TEXT};text-decoration:none;font-weight:600;">{_esc(c["titre"])}</a>{pill}'
            f'<div style="font-size:12px;color:{_MUTED};margin-top:3px;">{_esc(c["porteur"])} · {_esc(fr_closing(c["cloture"]))}</div></div>')
    return (f'<tr><td style="padding:24px 32px 8px 32px;">{_badge("Appels à projets en cours", _CALLS, _CALLS_BG)}'
            f'{"".join(rows)}</td></tr>')


def compose_html(items, window, new_events, calls, health, today: date) -> str:
    warn = ""
    if not health.get("ok", True):
        warn = (f'<tr><td style="padding:16px 32px 0 32px;font-size:12px;color:{_WARN};">'
                'Source Carenews indisponible aujourd’hui : la section « Appels à projets » est incomplète.</td></tr>')
    body = _html_news(items) + _html_agenda(window, new_events) + _html_calls(calls) + warn
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
          <div style="font-size:20px;font-weight:600;color:{_TEXT};margin-top:6px;">Veille du {today.strftime('%d/%m/%Y')}</div>
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
                        help="inclure les articles déjà envoyés (renvoi d'un email de test) ; l'historique est conservé")
    parser.add_argument("--lookback-days", type=int, default=news_watch.LOOKBACK_DAYS)
    parser.add_argument("--html-out", help="écrire l'aperçu HTML dans ce fichier")
    args = parser.parse_args()

    today = date.today()
    items, seen = news_watch.collect(args.lookback_days, ignore_seen=args.ignore_seen)
    window, new_events = events_watch.run(today, persist=False)
    calls, health = calls_watch.run(persist=False)

    has_content = bool(items or new_events or calls)
    body_md = compose_markdown(items, window, new_events, calls, health, today)
    body_html = compose_html(items, window, new_events, calls, health, today)

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

    # État enregistré seulement ici : une exception d'envoi ci-dessus l'aurait laissé intact.
    news_watch.commit(items, seen)
    events_watch.mark_announced(new_events)
    if health.get("ok"):
        calls_watch.commit(calls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
