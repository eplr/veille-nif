"""Génère les versions « copier-coller » de la veille pour Claude, ChatGPT ou tout autre assistant.

Deux livrables dans dist/, produits à partir du registre de sources, de l'agenda et du journal des actualités,
pour qu'ils restent synchronisés avec l'outil automatique :

- dist/prompt_autonome.md : à coller dans un assistant qui sait chercher sur le web. Il décrit le rôle, le
  périmètre, les sources prioritaires, les règles de rigueur et le format de sortie.
- dist/pack_avec_pieces_jointes.md : pour un assistant sans accès au web. Même consigne, plus les sources,
  l'agenda des 60 prochains jours, les appels à projets ouverts et les actualités récentes détectées.

Usage :
    python src/export_prompt_pack.py               # génère les deux fichiers
    python src/export_prompt_pack.py --no-network  # n'interroge pas Carenews (appels à projets omis)
"""
import argparse
import csv
from datetime import date, datetime, timedelta

import calls_watch
import events_watch
from lib import DIST, OUTPUT, PAYS_LABELS, PAYS_ORDER, load_sources

NEWS_DAYS = 7          # fenêtre de recherche demandée à l'assistant
LOG_DAYS = 14          # actualités du journal incluses dans le pack avec pièces jointes
LOG_MAX = 60

CATEGORIES = {
    "institution": "Institutions et régulateurs",
    "standard": "Standards et initiatives",
    "think_tank": "Associations de place et think tanks",
    "recherche": "Recherche",
    "presse": "Presse spécialisée",
}

CONSIGNE = """\
# Rôle
Tu es analyste de veille en finance durable, axe nature et biodiversité, pour la communauté Nature in Finance \
(professionnels de la finance : gestion d’actifs, banque, assurance, conseil, audit). Tu rédiges en français, \
de façon factuelle et concise, sans jargon inutile.

# Périmètre
- Zones : France, Europe (Union européenne et institutions européennes), Suisse, Royaume-Uni. Les références \
internationales (TNFD, ISSB, CBD, IPBES, NGFS…) sont incluses quand elles touchent ces zones.
- Thèmes : information et reporting sur la nature (TNFD, ESRS E4, ISSB), réglementation et supervision \
(SFDR, taxonomie, loi de restauration de la nature, circulaires de supervision), risques et dépendances à la \
nature, instruments et marchés (crédits biodiversité et nature, obligations, fonds), cadre mondial \
(Kunming–Montréal, COP17), solutions fondées sur la nature.
- Date de référence : {date_ref}. Si ce n’est pas la date du jour, utilise la date du jour.

# Ce que tu dois produire
1. **Actualités** des {news_days} derniers jours, regroupées par zone (France, Europe, Suisse, Royaume-Uni, \
International).
2. **Agenda** des 60 prochains jours : conférences, webinaires, consultations ouvertes, échéances \
réglementaires, appels à contributions.
3. **Appels à projets et financements** ouverts (fonds, fondations, programmes publics) relayés notamment par \
Carenews, avec date de clôture.
4. **Points à vérifier** : tout ce dont tu n’es pas sûr.

# Règles de rigueur (obligatoires)
- Cite uniquement des éléments que tu peux relier à une source consultable. Chaque entrée porte un lien vers \
la page d’origine, de préférence la source primaire (régulateur, organisateur, éditeur) plutôt qu’un relais.
- Ne jamais inventer un événement, une date, un lieu, un montant ou une citation. Pour un événement, vérifie \
l’année, la date et le lieu sur la page de l’organisateur. En cas de doute, classe l’entrée dans « Points à \
vérifier » au lieu de la présenter comme acquise.
- Si tu ne trouves rien de vérifié pour une section, écris « Rien de vérifié trouvé » : une section vide \
vaut mieux qu’une section complétée de mémoire.
- Sépare les faits (ce que dit la source) de ton interprétation. Marque l’interprétation par « Lecture : ».
- Ce que tu sais de mémoire sans source n’entre pas dans la veille. Si tu l’utilises pour contextualiser, \
marque-le « [mémoire du modèle, non vérifié] ».
- Pas de chiffre sans source. Pas de superlatif.

# Format de sortie
Markdown, dans cet ordre :
- **Synthèse** : 5 lignes au maximum, les signaux à retenir.
- **Actualités** : par zone, 10 entrées au maximum par zone, au format \
`- [Titre](lien) – Source – date de publication – une phrase factuelle. Lecture : …` (la lecture est facultative).
- **Agenda** : ordre chronologique, au format `- date – [Titre](lien) – lieu ou « en ligne » – une phrase – \
coût si connu`.
- **Appels à projets** : par date de clôture croissante, au format `- [Titre](lien) – porteur – clôture – \
public visé`.
- **Points à vérifier** : liste de ce qui reste incertain et de ce qu’il faudrait confirmer.

Style : tirets demi-cadratins (–), apostrophes courbes (’), pas de majuscules superflues.
"""

SOURCES_INTRO = """\
# Sources prioritaires
Commence par ces sources. Tu peux en consulter d’autres si elles sont plus directes ou plus fiables, mais \
signale-le.
"""

PIECES_INTRO = """\
# Mode sans accès au web
Tu n’as pas accès au web. N’utilise QUE les éléments fournis dans les parties A à D ci-dessous. Ne complète \
pas avec tes connaissances : si une information manque, écris « non fourni » ou place-la dans « Points à \
vérifier ». Les liens à citer sont ceux de ces pièces.
"""


def _news_from_log(today: date) -> list[dict]:
    path = OUTPUT / "news_log.csv"
    if not path.exists():
        return []
    cutoff = datetime.combine(today - timedelta(days=LOG_DAYS), datetime.min.time())
    rows = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                if datetime.strptime(r["date_detection"], "%Y-%m-%d %H:%M") >= cutoff:
                    rows.append(r)
            except (KeyError, ValueError):
                continue
    return rows[-LOG_MAX:]


def render_sources_compact(sources: list[dict]) -> str:
    """Liste condensée : une ligne par catégorie, pour le prompt autonome."""
    lines = []
    for key, label in CATEGORIES.items():
        group = [s for s in sources if s["categorie"] == key]
        if group:
            lines.append(f"- **{label}** : " + " ; ".join(f"{s['nom']} ({s['pays']}, {s['url']})" for s in group))
    return "\n".join(lines)


def render_sources_full(sources: list[dict]) -> str:
    lines = []
    for pays in PAYS_ORDER:
        group = [s for s in sources if s["pays"] == pays]
        if not group:
            continue
        lines.append(f"### {PAYS_LABELS[pays]}")
        lines += [f"- {s['nom']} – {CATEGORIES.get(s['categorie'], s['categorie'])} – {s['url']}" for s in group]
    return "\n".join(lines)


def render_agenda(events: list[dict]) -> str:
    if not events:
        return "Aucun événement dans la fenêtre."
    lines = []
    for e in events:
        fin = f" au {e['fin'].isoformat()}" if e["fin"] != e["debut"] else ""
        extras = [e.get("horaire"), e.get("cout"), e.get("note")]
        fiable = " [à revérifier : source secondaire ou détail déduit]" if e.get("confiance") == "moyenne" else ""
        lines.append(
            f"- {e['debut'].isoformat()}{fin} – {e['titre']} – {e['lieu']} ({e['format']}) – organisé par "
            f"{e['organisateur']} – {e['lien']}"
            + ("".join(f" – {x}" for x in extras if x)) + fiable
        )
    return "\n".join(lines)


def render_calls(calls: list[dict] | None) -> str:
    if calls is None:
        return "Non inclus (génération hors ligne)."
    if not calls:
        return "Aucun appel à projets ouvert sur la nature détecté dans les appels les plus récents de Carenews."
    lines = []
    for c in calls:
        cloture = c["cloture"].isoformat() if c["cloture"] else "clôture non précisée"
        lines.append(f"- {c['titre']} – {c['porteur']} – clôture {cloture} – {c['lien']}")
    return "\n".join(lines)


def render_news(rows: list[dict]) -> str:
    if not rows:
        return "Aucune actualité enregistrée par la veille automatique sur la période."
    lines = []
    for r in rows:
        lines.append(f"- [{r['pays']}] {r['titre']} – {r['source']} – {r['date_publication'][:16]} – {r['lien']}")
    return "\n".join(lines)


def build_autonomous(today: date, sources: list[dict]) -> str:
    return (
        CONSIGNE.format(date_ref=today.isoformat(), news_days=NEWS_DAYS)
        + "\n" + SOURCES_INTRO + render_sources_compact(sources) + "\n"
    )


def build_pack(today: date, sources: list[dict], window: list[dict], calls: list[dict] | None, news: list[dict]) -> str:
    return (
        CONSIGNE.format(date_ref=today.isoformat(), news_days=NEWS_DAYS)
        + "\n" + PIECES_INTRO
        + "\n# Pièces fournies\n"
        + f"\n## A. Sources de référence\n{render_sources_full(sources)}\n"
        + f"\n## B. Agenda des {events_watch.WINDOW_DAYS} prochains jours (validé à la main le "
        + f"{max((e['verifie_le'] for e in window), default=today)})\n{render_agenda(window)}\n"
        + f"\n## C. Appels à projets ouverts (Carenews)\n{render_calls(calls)}\n"
        + f"\n## D. Actualités détectées par la veille automatique ({LOG_DAYS} derniers jours)\n{render_news(news)}\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-network", action="store_true", help="ne pas interroger Carenews")
    args = parser.parse_args()

    today = date.today()
    sources = load_sources()
    window = events_watch.in_window(events_watch.load_events(), today)
    calls = None if args.no_network else calls_watch.collect(today=today)[0]
    news = _news_from_log(today)

    DIST.mkdir(parents=True, exist_ok=True)
    (DIST / "prompt_autonome.md").write_text(build_autonomous(today, sources), encoding="utf-8")
    (DIST / "pack_avec_pieces_jointes.md").write_text(build_pack(today, sources, window, calls, news), encoding="utf-8")
    print(f"[export-prompt-pack] dist/prompt_autonome.md et dist/pack_avec_pieces_jointes.md générés "
          f"({len(window)} événement(s), {len(news)} actualité(s))")


if __name__ == "__main__":
    main()
