# Exercices – Veille et IA en finance de la nature

Les corrigés s’appuient sur des faits vérifiés le 7 octobre 2026 (sources dans `support.md`). Le formateur les revérifie avant chaque séance (voir la fiche de vérification dans `programme.md`).

## Partie 1 – Exercice 1 : lire un signal (module 2, 10 minutes)

Consigne : à partir de l’email de veille du jour, choisir trois entrées et répondre, pour chacune, aux cinq questions : qui parle, quelle source, quelle date, quel statut juridique, quel effet pour mon métier.

Corrigé type, avec le webinaire de l’ISSB du 22 octobre 2026 :
- Qui parle : l’ISSB, normalisateur de la Fondation IFRS.
- Source : primaire (page ifrs.org).
- Date : webinaire le jeudi 22 octobre 2026 à 16 h (heure d’Europe centrale) ; consultation de 120 jours jusqu’au 19 février 2027.
- Statut : projet de norme (Practice Statement) en consultation, donc pas encore applicable.
- Effet : à suivre pour les entités qui appliquent IFRS S1 ; possibilité de répondre à la consultation avant le 19 février 2027.

## Partie 2 – Exercice 2 : prompt autonome (module 3, 12 minutes)

Matériel : un assistant avec recherche web.
Consigne :
1. Copier le contenu de `dist/prompt_autonome.md` dans l’assistant.
2. Ajouter à la fin : « Limite-toi à la Suisse et au Royaume-Uni. »
3. Lire la réponse et, pour trois entrées au hasard, ouvrir le lien et vérifier la date.

Critères de réussite :
- chaque entrée a un lien qui s’ouvre ;
- les dates correspondent à celles de la page ;
- les sections sans résultat disent « Rien de vérifié trouvé » au lieu d’être complétées ;
- les interprétations sont marquées « Lecture : ».

Points d’attention pour l’animateur : si l’assistant produit un événement sans lien ou avec un lien mort, le placer en exemple pour l’exercice 4.

## Partie 3 – Exercice 3 : pack avec pièces jointes (module 3, 12 minutes)

Matériel : un assistant sans recherche web, ou avec la recherche web désactivée.
Consigne :
1. Copier le contenu de `dist/pack_avec_pieces_jointes.md` dans l’assistant.
2. Poser la question : « Quels événements des 30 prochains jours concernent la supervision des risques liés à la nature ? »
3. Vérifier que la réponse ne contient aucun événement absent des pièces fournies.

Critères de réussite : l’assistant n’ajoute rien de mémoire, ou le signale par « [mémoire du modèle, non vérifié] » ; les événements marqués « à revérifier » sont signalés comme tels.

## Partie 4 – Exercice 4 : repérer les erreurs (module 4, 10 minutes)

Consigne : le texte ci-dessous est une sortie d’IA fictive. Il contient six erreurs. Les trouver, puis les corriger avec une source.

> « Synthèse de la semaine. La circulaire FINMA 2026/1 sur les risques financiers liés à la nature est entrée en vigueur le 1er janvier 2025 et couvre dès le départ tous les risques liés à la nature. La COP17 de la Convention sur la diversité biologique se tiendra à Cali en octobre 2026. Les recommandations du TNFD ont été publiées en 2021. L’ISSB a ouvert une consultation sur l’information relative à la nature qui se termine le 19 février 2026. L’article 29 de la loi énergie-climat s’applique aux acteurs de plus de 500 salariés. La Commission européenne a publié sa feuille de route sur les crédits nature en 2023. »

Corrigé :
1. FINMA 2026/1 : en vigueur par étapes à partir du 1er janvier 2026 (pas 2025) ; au départ, uniquement les risques liés au climat, l’ensemble des risques liés à la nature à partir du 1er janvier 2028. Source : https://www.finma.ch/news/2024/12/20241207-mm-rs-2026-01-naturbezogene-finanzrisiken/
2. COP17 : Erevan, Arménie, du 19 au 30 octobre 2026 (Cali a accueilli la COP16 en 2024). Source : https://www.cbd.int/conferences/2026
3. TNFD : recommandations publiées en septembre 2023. Source : https://tnfd.global
4. Consultation ISSB : se termine le 19 février 2027 (pas 2026). Source : https://www.ifrs.org/news-and-events/news/2026/10/cop17-issb-nature-related-disclosures-consultation/
5. Article 29 de la loi énergie-climat : seuil de 500 millions d’euros de bilan ou d’encours, pas de 500 salariés (le seuil de 500 salariés est celui du règlement européen SFDR au niveau de l’entité). Source : guide pédagogique de la DG Trésor, https://www.tresor.economie.gouv.fr/Articles/2021/06/08/publication-du-decret-d-application-de-l-article-29-de-la-loi-energie-climat-sur-le-reporting-extra-financier-des-acteurs-de-marche
6. Feuille de route de la Commission sur les crédits nature : publiée le 7 juillet 2025 (pas 2023). Source : COM(2025) 374 final.

Question de réflexion : lesquelles de ces erreurs un lecteur pressé aurait-il laissé passer, et pourquoi ?

## Partie 5 – Quiz de clôture (5 minutes)

Réponses attendues entre parenthèses.
1. Quelle date marque l’entrée en vigueur par étapes de la circulaire FINMA 2026/1 ? (1er janvier 2026)
2. Où se tient la COP17 de la CBD et quand ? (Erevan, 19–30 octobre 2026)
3. Citez deux des quatre piliers des recommandations du TNFD. (Gouvernance, stratégie, gestion des risques et des impacts, indicateurs et cibles)
4. Pourquoi les événements de l’agenda sont-ils validés à la main ? (Une date ou un lieu erroné diffusé à la communauté est pire qu’un événement manquant)
5. Que doit faire un assistant d’IA quand il ne trouve rien de vérifié pour une section ? (Écrire « Rien de vérifié trouvé », sans compléter de mémoire)

## Partie 6 – Exercice 5 (variante 2 h) : appliquer le prompt à son institution

Consigne : adapter le prompt de veille à un sujet propre à son entité, par exemple « quelles échéances de supervision nature s’appliquent à mon entité en 2027 ? ». Noter, pour chaque réponse, ce qui est vérifié sur une source primaire et ce qui ne l’est pas. Échanger en binômes.

## Partie 7 – Plan de routine personnelle

Remplir, à la fin de la séance :
- mon créneau de veille (par exemple 8 h 30–8 h 45) ;
- mes cinq sources prioritaires, choisies dans `data/sources.yaml` ;
- mon point hebdomadaire de vérification (un fait du support à reprendre sur sa source) ;
- la personne avec qui je partage les signaux utiles.
