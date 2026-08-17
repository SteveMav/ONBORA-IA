# État d’implémentation — Onbora AI V1

Date de vérification : 17 août 2026.

| Ticket | État technique | Preuve principale |
|---|---|---|
| `FND-001` | Implémenté | `manage.py check`, configuration Django/SQLite et Pytest |
| `CNT-001` | Implémenté | Contrats Pydantic, JSON Schemas et exemples valides/invalides |
| `DAT-001` | Implémenté | Migrations Django et tests de persistance/rollback |
| `CAT-001` | Catalogue public intégré ; approbation métier en attente | Chargeur strict et catalogue `draft` de 28 offres RDC + 13 familles internationales Orange Business / Orange Cyberdefense, avec portée et disponibilité RDC explicites |
| `REC-001` | Implémenté | Matching déterministe et cas `recommended`/`needs_information`/`no_match` |
| `LLM-001` | Implémenté | Port, fake configurable et fake heuristique hors-ligne |
| `QLF-001` | Implémenté | Extraction structurée, prompt versionné et trace minimisée |
| `QLF-002` | Implémenté | Fusion, provenance, confirmation, conflits et informations manquantes |
| `LLM-002` | Implémenté et vérifié sur l’API réelle avec données fictives | Gemini multi-tour, réponse + patch structurés, historique borné, timeout et deux tentatives maximum |
| `RPT-001` | Implémenté ; revue KAM externe en attente | Rapport KAM validé et persistance idempotente |
| `RPT-002` | Implémenté ; revue métier externe en attente | Profil d’entreprise descriptif validé, sans recommandations, et persistance idempotente |
| `RPT-003` | Implémenté pour HTML/JSON ; PDF serveur différé | Exports autonomes, contrôle d’appartenance, en-têtes de sécurité et HTML imprimable en PDF |
| `INT-001` | Implémenté | `ConversationService` et DTO indépendants de l’ORM |
| `EVL-001` | Implémenté | 32 scénarios synthétiques, dont cloud et cyber internationales, et évaluateurs déterministes |
| `EVL-002` | Implémenté | 15 conversations multi-tours, corrections, conflits, cas sans correspondance et injections |
| `PREP-001` | Implémenté ; validation Orange/métier requise | Gabarit de collecte, validateur, checklist et publication réservée aux catalogues approuvés |
| `UI-001` | Implémenté | Chat guidé, signal de complétude LLM, analyse explicite, réponse client avec offres Orange, bénéfices et prérequis, fiche confirmable, rapports verrouillés, responsive et CSRF |
| `QA-001` | Implémenté | 104 tests Pytest et commande `run_ai_eval` |
| `GOV-001` | Workflow implémenté ; décisions humaines en attente | 41 fiches de revue catalogue, 5 paires KAM/profil, validateurs bloquants et identité/date obligatoires |
| `EVL-003` | Implémenté et exécuté sur Gemini réel | Corpus Gemini fondé sur le texte, métriques champs/services/latence/tokens, garde réseau explicite et nettoyage des conversations synthétiques |

## Vérifications exécutées

```text
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest
python manage.py run_ai_eval
python manage.py demo_ai_v1
```

Résultats : vérification Django réussie, aucune migration manquante, 104 tests et 32 scénarios
synthétiques réussis, parcours complet vérifié dans le navigateur sans erreur
console et qualification Gemini réelle réussie avec des données fictives jusqu’au lancement
explicite de l’analyse.

Le gate Gemini end-to-end du 29 juillet reste rouge : 5 cas sur 8 entièrement conformes,
91,1 % des champs exacts, aucune erreur fournisseur et aucune offre interdite. Les écarts
restants concernent surtout la confusion entre activité, besoin et contrainte dans certains
tours. Le rapport détaillé est écrit dans `output/evals/gemini-full-final-2026-07-29.json`.

## Validations externes restantes

- Faire valider les 28 offres RDC et les 13 familles internationales, leurs variantes, règles de matching et conditions par le responsable métier et les équipes Orange concernées avant de passer le catalogue à `approved`.
- Faire relire plusieurs rapports KAM et profils d’entreprise par leur utilisateur cible.
- Valider la politique de données du fournisseur avant toute utilisation de données client réelles.

Les décisions doivent être enregistrées dans `reviews/`. Les dossiers livrés restent
volontairement `pending`; aucun outil ne déduit une approbation métier à partir des tests.
