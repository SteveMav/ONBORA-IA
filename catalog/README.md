# Base de connaissances Orange Business RDC et internationale

Le catalogue `versions/v1/catalog.json` contient 41 entrées vérifiées au 28 juillet 2026 :
28 offres publiques Orange Business RDC et 13 familles internationales Orange Business ou
Orange Cyberdefense. Les neuf domaines mondiaux couverts sont la sécurité, le cloud, la
collaboration, la Data/IA/IoT, l’expérience client, le conseil et l’intégration, la téléphonie
fixe et VoIP, les réseaux et la mobilité. La cybersécurité détaille aussi les services managés,
les services professionnels, l’ethical hacking et les formations Orange Cyberdefense.

Chaque fiche conserve sa catégorie, son explication, ses bénéfices autorisés, ses cibles,
ses variantes publiques, ses conditions, ses prérequis, ses limites, ses mots-clés de
recommandation, son fournisseur et sa source officielle. Les champs `portfolio_scope`,
`portfolio_level`, `rdc_availability` et `availability_note` empêchent de confondre une offre
publiée localement avec une famille internationale dont la livraison en RDC reste à confirmer.

Le statut reste `draft` car une page publique n’est pas une proposition contractuelle. Les
tarifs, volumes, couvertures, délais, SLA, engagements et disponibilités doivent être confirmés
par Orange. Une présence sur le site mondial ne prouve pas qu’une offre est commandable par une
entité en RDC. Les anomalies repérées sont conservées dans les exclusions plutôt que corrigées
par supposition, notamment deux liens Orange Money en erreur 404, une contradiction d’engagement
sur Business Mix Pro et une valeur ambiguë sur Share Voice 150u.

Le chargeur refuse les doublons, les identifiants invalides, les champs inconnus et les
fichiers de plus de 1 Mo. Une opération destinée à un environnement partagé peut appeler
`load_catalog(..., require_approved=True)`.

## Préparer un catalogue métier

Le dossier [`intake/`](intake/) contient le kit PREP-001 pour collecter ou mettre à jour les offres Orange
Business RDC ou internationales sans modifier directement le catalogue actif. Le gabarit sépare le contenu
exécutable, compatible avec `CatalogDefinition`, des preuves et de la checklist de revue
métier. Son outil de validation refuse l’export tant que le catalogue n’est pas entièrement
approuvé.
