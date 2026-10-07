# Atelier visio – Veille et IA en finance de la nature : s’informer vite, vérifier bien

Format : visioconférence interactive, 1 h 30 (variante 2 h en fin de document).
Animation : un formateur, un co-animateur pour le chat si le groupe dépasse 15 personnes.
Dernière vérification des faits : 7 octobre 2026 (voir la fiche de vérification en fin de document).

## Public

Professionnels de la finance qui rencontrent la nature et la biodiversité dans leur métier : gestion d’actifs, banque, assurance, conseil, audit, ESG, risques, conformité. Pas de prérequis technique.

## Prérequis

- Un accès à un assistant d’IA généraliste (Claude, ChatGPT ou équivalent). La version gratuite suffit pour l’atelier ; la recherche web peut en revanche être limitée.
- Avoir ouvert, avant la séance, le fichier `dist/prompt_autonome.md` du dépôt `veille-nif`, pour savoir où le trouver.
- Un document de son propre travail (note, rapport, extrait de politique) dont on peut parler sans le partager, pour la variante de 2 h.

## Objectifs pédagogiques

À la fin de la séance, chaque participant sait :
1. situer les grands textes et standards sur la nature et la finance (cadre mondial, information, supervision, instruments) et dire ce qui concerne la France, l’Europe, la Suisse et le Royaume-Uni ;
2. lire un signal de veille avec cinq questions (qui parle, quelle source, quelle date, quel statut juridique, quel effet pour mon métier) ;
3. utiliser le prompt de veille avec un assistant d’IA, avec ou sans accès au web ;
4. repérer au moins trois types d’erreurs typiques d’une sortie d’IA (date, lieu, chiffre, statut d’un texte) et les vérifier sur une source primaire ;
5. mettre en place une routine de veille de 15 minutes par jour.

## Déroulé minuté (90 minutes)

- 0 h 00 – 0 h 05 · Accueil. Tour de table par le chat : « Quel texte sur la nature vous préoccupe le plus cette semaine ? ». Présentation des objectifs.
- 0 h 05 – 0 h 25 · Module 1 – Enjeux nature et biodiversité pour la finance, et cartographie du cadre en France, en Europe, en Suisse et au Royaume-Uni (support : diapositives 2 à 8).
- 0 h 25 – 0 h 40 · Module 2 – Comment fonctionne la veille : sources, filtres, agenda, appels à projets ; lecture d’un signal avec la grille en cinq questions (diapositives 9 à 11, exercice 1).
- 0 h 40 – 1 h 10 · Module 3 – Atelier avec le prompt copier-coller : deux exercices pratiques sur l’assistant de son choix, puis comparaison des sorties (diapositives 12 à 15, exercices 2 et 3).
- 1 h 10 – 1 h 25 · Module 4 – Vérifier les sorties de l’IA et installer sa routine de veille (diapositives 16 à 18, exercice 4).
- 1 h 25 – 1 h 30 · Clôture : quiz de 5 questions, ressources, questions.

## Matériel

- Dépôt du projet : `veille-nif` (README, `dist/prompt_autonome.md`, `dist/pack_avec_pieces_jointes.md`, `data/events.yaml`).
- `formation/support.md` : plan des diapositives avec notes d’animation et sources.
- `formation/exercices.md` : exercices, corrigés et quiz.
- L’email de veille du jour, ou son aperçu HTML (`python src/daily_digest.py --dry-run --html-out veille.html`).

## Évaluation

- Formative : exercices 1 à 4, corrigés en séance.
- Quiz de 5 questions en fin de séance (exercices, partie 5). Pas de note : un score indicatif de réussite est donné aux participants pour qu’ils situent leurs acquis.
- Livrable facultatif envoyé après la séance : la liste de leurs 5 sources prioritaires et de leur créneau de veille.

## Variante de 2 heures

Ajouter 30 minutes, entre le module 3 et le module 4 :
- 20 minutes : exercice 5, appliquer le prompt à un sujet propre à son institution (par exemple « quelles échéances de supervision nature s’appliquent à mon entité ? ») et noter ce qui est vérifié ou non ;
- 10 minutes : retours croisés en binômes (salles de sous-groupes), puis mise en commun en plénière.

## Fiche de vérification du formateur (à faire la veille de la séance)

Les textes évoluent vite. Avant chaque séance, reprendre chaque point sur sa source primaire et corriger le support si besoin. Dernière vérification : 7 octobre 2026.

- COP17 de la CBD (Erevan, 19–30 octobre 2026) : si la séance a lieu après le 30 octobre, ajouter les décisions adoptées. Page : https://www.cbd.int/conferences/2026
- Normes ESRS révisées : l’acte délégué a été adopté par la Commission le 3 juillet 2026 (C(2026) 5010) ; un cabinet d’avocats indique une publication au Journal officiel le 21 septembre 2026 et une entrée en vigueur le 10 novembre 2026. Confirmer au Journal officiel de l’Union européenne et vérifier que la norme E4 figure bien dans le texte final.
- Directive Omnibus I (UE) 2026/470 : entrée en vigueur le 18 mars 2026, transposition au plus tard le 19 mars 2027. Texte : https://eur-lex.europa.eu
- ISSB : projet de norme (Practice Statement) sur l’information relative à la nature, consultation de 120 jours jusqu’au 19 février 2027. Page : https://www.ifrs.org/news-and-events/news/2026/10/cop17-issb-nature-related-disclosures-consultation/
- TNFD : LEAP 2.0 annoncé pour le 13 octobre 2026. Page : https://tnfd.global
- FINMA, circulaire 2026/1 : calendrier d’entrée en vigueur par catégorie d’établissements. Page : https://www.finma.ch/en/documentation/dossier/dossier-sustainable-finance/aufsicht-zu-naturrisiken/
- France, article 29 de la loi énergie-climat : consulter la FAQ la plus récente de la DG Trésor. Page : https://www.tresor.economie.gouv.fr
- Royaume-Uni : état de la consultation de la FCA sur les UK Sustainability Reporting Standards (approche « comply or explain » relayée par la presse en octobre 2026, à vérifier sur la page de la FCA). Page : https://www.fca.org.uk
- Union européenne, crédits nature : réunions du groupe d’experts et suites de la feuille de route. Page : https://green-forum.ec.europa.eu/green-business/nature-credits_en
