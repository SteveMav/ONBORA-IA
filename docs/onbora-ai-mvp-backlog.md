# Backlog de développement — Onbora AI V1

Source principale : [`onbora-ai-mvp-architecture.md`](./onbora-ai-mvp-architecture.md)

## Verdict produit

- **Objectif :** livrer le module IA et les rapports, pas la plateforme entière.
- **Stack :** Django, SQLite et Python.
- **Résultat V1 :** une conversation produit un profil d’entreprise sourcé et exportable, des opportunités explicables et un rapport KAM.
- **Interface :** services Python/Django intégrables par le reste de l’équipe.
- **Données :** catalogue léger en JSON et scénarios synthétiques.
- **Hors périmètre :** React, PostgreSQL, pgvector, workers, cloud, multi-tenant et exploitation avancée.
- **État :** prêt à démarrer avec les hypothèses documentées.

## 1. Contrat de livraison

La V1 IA est terminée lorsqu’un développeur peut :

1. Créer une conversation de test et lui envoyer plusieurs messages.
2. Obtenir un profil d’entreprise structuré avec sources, incertitudes et informations manquantes.
3. Calculer des opportunités à partir du catalogue sans laisser le LLM choisir librement les services.
4. Générer un rapport KAM et un profil d’entreprise validés par schéma.
5. Rejouer un corpus synthétique et détecter une extraction, recommandation ou affirmation invalide.
6. Appeler le pipeline depuis un service Python/Django documenté.

### Invariants

- Une sortie IA invalide n’est jamais appliquée ni enregistrée comme résultat final.
- Un fait inféré ne remplace jamais un fait rapporté ou confirmé.
- Un service absent du catalogue ne peut pas devenir une recommandation.
- Le rapport KAM et le profil exportable utilisent les mêmes faits validés; seul le rapport KAM contient les opportunités.
- L’échec du fournisseur conserve le dernier profil valide.
- Les clés, tokens et secrets ne sont jamais stockés dans SQLite ou les logs.
- Les données réelles restent hors des fixtures et démonstrations initiales.

### Hypothèses et décisions

| ID | Décision ou hypothèse | Valeur V1 | Bloque |
|---|---|---|---|
| DEC-001 | Backend et persistance | Django + SQLite | Bootstrap |
| DEC-002 | Catalogue | 5–8 services en JSON | Matching final |
| DEC-003 | Profil d’entreprise | Description structurée de l’entreprise, sans recommandation ni prédiction | Contrats rapports |
| DEC-004 | Fournisseur | Fake par défaut, Gemini via `google-genai` pour les essais réels | Pas le cœur déterministe |
| DEC-005 | Langue | Français pour les contenus, anglais pour les identifiants techniques | Corpus final |
| DEC-006 | Intégration équipe | Services Python/Django avant une API HTTP dédiée | Intégration finale |

## 2. Roadmap

| Phase | Résultat | Tickets | Gate de sortie |
|---|---|---|---|
| P0 — Socle | Projet Django exécutable avec SQLite et tests | `FND-001`, `CNT-001`, `DAT-001` | Migrations et tests passent depuis un clone propre |
| P1 — Cœur déterministe | Catalogue et opportunités sans LLM | `CAT-001`, `REC-001` | Les scénarios métier déterministes passent |
| P2 — Qualification IA | Conversation → profil validé | `LLM-001`, `QLF-001`, `QLF-002` | Démo avec fake, provenance et conflits |
| P3 — Rapports | KAM et profil d’entreprise | `RPT-001`, `RPT-002` | JSON valides et revue métier d’exemples |
| P4 — Intégration et qualité | Interface d’équipe et gate synthétique | `INT-001`, `EVL-001`, `QA-001` | Pipeline complet reproductible |
| P5 — Modèle réel | Adaptateur réel évalué | `LLM-002` | Qualité/coût/erreurs mesurés sur le même corpus |

## 3. Epics

| Epic | Valeur livrée | Tickets |
|---|---|---|
| E1 — Fondations | Django, SQLite, contrats et migrations | `FND-001`, `CNT-001`, `DAT-001` |
| E2 — Catalogue et opportunités | Décisions métier explicables sans LLM | `CAT-001`, `REC-001` |
| E3 — Qualification IA | Profil d’entreprise sourcé et révisable | `LLM-001`, `LLM-002`, `QLF-001`, `QLF-002` |
| E4 — Rapports | KAM et profil d’entreprise descriptif | `RPT-001`, `RPT-002` |
| E5 — Intégration et validation | Services appelables et régressions détectées | `INT-001`, `EVL-001`, `QA-001` |

## 4. Definition of Done globale

Chaque ticket est terminé lorsque :

- Ses critères d’acceptation sont couverts par des tests ou une preuve explicitement citée.
- Les sorties structurées utilisent des contrats versionnés.
- Les erreurs fournisseur ne laissent aucun état métier partiel.
- Les nouvelles traces ne contiennent aucun secret.
- Les fichiers de catalogue, prompts et fixtures restent lisibles et versionnés.
- Les commandes de test et de démonstration affectées sont documentées.

## 5. Backlog priorisé

### E1 — Fondations

#### FND-001 — Initialiser le projet Django

- **Objectif :** fournir un socle exécutable pour les modules IA et rapports.
- **Type / Priorité / Taille / Owner :** `chore` / P0 / S / Développeur IA.
- **Dépendances :** `DEC-001`.
- **Description :** créer le projet Django, les applications `ai_core` et `reports`, la configuration SQLite, les variables d’environnement et Pytest.
- **Critères d’acceptation :** `manage.py check`, les migrations et un test smoke passent ; aucune infrastructure externe n’est nécessaire.
- **Notes techniques :** isoler configuration locale et secrets ; choisir et verrouiller le gestionnaire de dépendances Python.
- **Tests attendus :** démarrage Django, base temporaire de test et configuration invalide.
- **Risques :** importer trop tôt une architecture de plateforme.
- **Definition of Done :** DoD globale plus commandes d’installation documentées.

#### CNT-001 — Définir les contrats IA versionnés

- **Objectif :** stabiliser les entrées et sorties du pipeline.
- **Type / Priorité / Taille / Owner :** `feature` / P0 / M / Développeur IA.
- **Dépendances :** `FND-001`.
- **Description :** définir `Fact`, `CompanyProfile`, `CompanyProfilePatch`, `RecommendationResult`, `KAMReport` et `CompanyProfileReport` avec validation stricte.
- **Critères d’acceptation :** chaque objet porte `schema_version`; les statuts et scores invalides sont refusés; les exemples de l’architecture valident.
- **Notes techniques :** privilégier Pydantic pour les contrats IA et garder les DTO indépendants de l’ORM Django.
- **Tests attendus :** exemples valides/invalides, bornes, champs inconnus et payload vide.
- **Risques :** dupliquer ou enrichir inutilement le profil avant les premiers retours.
- **Definition of Done :** DoD globale plus fixtures JSON lisibles.

#### DAT-001 — Persister les essais dans SQLite

- **Objectif :** conserver conversations, profils, opportunités, rapports et diagnostics minimaux.
- **Type / Priorité / Taille / Owner :** `feature` / P0 / M / Développeur IA.
- **Dépendances :** `CNT-001`.
- **Description :** créer `Conversation`, `Message`, `CompanyProfileSnapshot`, `RecommendationResult`, `GeneratedReport` et `AIExecution` avec migrations Django.
- **Critères d’acceptation :** une base vide migre; seuls les JSON validés deviennent des résultats finaux; les relations et suppressions ne créent pas d’orphelins.
- **Notes techniques :** utiliser `JSONField` pour les contenus structurés et des colonnes normales pour les identifiants, statuts et versions.
- **Tests attendus :** migrations, contraintes, rollback de transaction et suppression en cascade contrôlée.
- **Risques :** stocker tout dans un seul JSON opaque.
- **Definition of Done :** DoD globale plus diagramme ou dictionnaire minimal des modèles.

### E2 — Catalogue et opportunités

#### CAT-001 — Créer le catalogue initial

- **Objectif :** fournir la source autorisée des services et règles de rapprochement.
- **Type / Priorité / Taille / Owner :** `docs` / P0 / M / Métier + Développeur IA.
- **Dépendances :** `CNT-001`, `DEC-002`.
- **Description :** définir 5–8 services avec identifiant stable, description, bénéfices autorisés, besoins correspondants, prérequis, exclusions et informations manquantes.
- **Critères d’acceptation :** tous les IDs sont uniques; les références sont valides; aucun prix non approuvé n’existe; une personne métier valide le contenu.
- **Notes techniques :** fichiers JSON avec version et validation de schéma au chargement.
- **Tests attendus :** catalogue valide, entrée invalide, doublon et référence inconnue.
- **Risques :** catalogue fictif ou règles implicites non validées.
- **Definition of Done :** DoD globale plus preuve de revue métier.

#### REC-001 — Calculer les opportunités de manière déterministe

- **Objectif :** identifier les services intéressants sans déléguer la décision au LLM.
- **Type / Priorité / Taille / Owner :** `feature` / P0 / M / Développeur IA.
- **Dépendances :** `CNT-001`, `CAT-001`.
- **Description :** appliquer prérequis, exclusions, correspondances de besoins et ordre stable pour retourner `recommended`, `needs_information` ou `no_match`.
- **Critères d’acceptation :** le même profil et le même catalogue donnent le même résultat; un service exclu n’est jamais recommandé; chaque résultat possède une raison.
- **Notes techniques :** module Python pur sans Django ni fournisseur IA.
- **Tests attendus :** tables de décision, valeurs manquantes, égalités, exclusions et déterminisme.
- **Risques :** inventer une notation trop complexe pour le petit catalogue.
- **Definition of Done :** DoD globale plus 10–15 cas métier lisibles.

### E3 — Qualification IA

#### LLM-001 — Définir le port modèle et un fake déterministe

- **Objectif :** développer tout le pipeline sans dépendre d’un fournisseur réel.
- **Type / Priorité / Taille / Owner :** `feature` / P0 / S / Développeur IA.
- **Dépendances :** `CNT-001`.
- **Description :** créer un port `ChatModel`, des erreurs typées et un fake configurable en succès, timeout, erreur et sortie malformée.
- **Critères d’acceptation :** aucun cas d’usage ne dépend directement d’un SDK; tous les échecs sont reproductibles sans réseau.
- **Notes techniques :** contrat étroit centré sur la génération structurée.
- **Tests attendus :** succès, timeout, erreur, JSON invalide et usage simulé.
- **Risques :** abstraction générique disproportionnée.
- **Definition of Done :** DoD globale plus documentation du port.

#### QLF-001 — Extraire un patch de profil sourcé

- **Objectif :** convertir un message en informations structurées sans modifier directement le profil.
- **Type / Priorité / Taille / Owner :** `feature` / P0 / M / Développeur IA.
- **Dépendances :** `CNT-001`, `LLM-001`.
- **Description :** versionner le prompt d’extraction, fournir le profil courant et valider un `CompanyProfilePatch` contenant sources, statuts et confiance.
- **Critères d’acceptation :** chaque valeur possède une source ou le statut `inferred`; une sortie invalide ne produit aucun patch utilisable; le timeout est contrôlé.
- **Notes techniques :** limiter le contexte et le nombre total de tentatives par traitement.
- **Tests attendus :** extraction attendue, omission, contradiction, injection, timeout et JSON malformé.
- **Risques :** accepter une paraphrase comme preuve d’un fait absent.
- **Definition of Done :** DoD globale plus premier corpus annoté.

#### QLF-002 — Fusionner le profil et identifier les manques

- **Objectif :** maintenir une description cohérente de l’entreprise au fil de la conversation.
- **Type / Priorité / Taille / Owner :** `feature` / P0 / M / Développeur IA.
- **Dépendances :** `QLF-001`.
- **Description :** appliquer les patches, conserver les sources, signaler les contradictions et calculer les informations manquantes utiles au catalogue.
- **Critères d’acceptation :** une inférence ne remplace jamais un fait rapporté/confirmé; les contradictions restent visibles; le même patch est idempotent.
- **Notes techniques :** logique pure avec table de décision de fusion.
- **Tests attendus :** matrice des statuts, doublon, conflit, confirmation explicite et champs manquants.
- **Risques :** règles de priorité implicites.
- **Definition of Done :** DoD globale plus table de fusion documentée.

#### LLM-002 — Ajouter un adaptateur de fournisseur réel

- **Objectif :** exécuter le même pipeline avec une configuration réelle après validation avec le fake.
- **Type / Priorité / Taille / Owner :** `feature` / P1 / M / Développeur IA.
- **Dépendances :** `QA-001`, `DEC-004`.
- **Description :** implémenter le port, la sortie structurée, le timeout, l’usage/coût et les erreurs normalisées pour un seul fournisseur initial.
- **Critères d’acceptation :** le fournisseur passe les tests de contrat; aucune clé n’apparaît dans les erreurs; la configuration et les versions sont enregistrées.
- **Notes techniques :** au maximum deux appels totaux par traitement, y compris retry ou réparation.
- **Tests attendus :** contrat avec fixtures, timeout, rate limit, sortie invalide et essai réel séparé.
- **Risques :** coût, rétention fournisseur et différences entre fake et API réelle.
- **Definition of Done :** DoD globale plus résultats comparés sur le corpus synthétique.

### E4 — Rapports

#### RPT-001 — Générer le rapport KAM

- **Objectif :** produire une synthèse commerciale révisable.
- **Type / Priorité / Taille / Owner :** `feature` / P0 / M / Développeur IA.
- **Dépendances :** `QLF-002`, `REC-001`, `LLM-001`.
- **Description :** générer les sections résumé, faits rapportés/confirmés, inférences, besoins, opportunités, points à vérifier et prochaines actions.
- **Critères d’acceptation :** chaque affirmation provient du profil/catalogue ou reste explicitement une inférence; les conflits ne deviennent pas des faits; le JSON respecte son schéma.
- **Notes techniques :** conserver le JSON comme source et produire le texte/HTML depuis ce JSON.
- **Tests attendus :** profil complet, incomplet, contradictoire, `no_match` et fournisseur en erreur.
- **Risques :** formulation élégante masquant l’incertitude.
- **Definition of Done :** DoD globale plus revue d’au moins trois exemples.

#### RPT-002 — Générer le profil d’entreprise descriptif

- **Objectif :** décrire l’entreprise à partir des faits collectés et confirmés.
- **Type / Priorité / Taille / Owner :** `feature` / P0 / M / Développeur IA.
- **Dépendances :** `QLF-002`, `LLM-001`.
- **Description :** produire `description`, `company_summary`, `needs`, `constraints`, `missing_information` et `sources`.
- **Critères d’acceptation :** aucune offre, recommandation ou prochaine action n’apparaît dans le profil; les données absentes restent visibles; chaque fait conserve son statut et ses sources.
- **Notes techniques :** le rapport KAM porte seul les opportunités et les actions commerciales.
- **Tests attendus :** snapshots JSON, données partielles, contradictions et idempotence.
- **Risques :** réintroduire progressivement des recommandations dans un artefact uniquement descriptif.
- **Definition of Done :** DoD globale plus revue métier d’au moins trois exemples.

### E5 — Intégration et validation

#### INT-001 — Exposer les services Django à l’équipe

- **Objectif :** rendre le module intégrable sans imposer une plateforme supplémentaire.
- **Type / Priorité / Taille / Owner :** `feature` / P0 / M / Développeur IA + intégrateur.
- **Dépendances :** `DAT-001`, `QLF-002`, `RPT-001`, `RPT-002`.
- **Description :** fournir `process_conversation_turn` et `generate_report` avec DTO stables, erreurs typées et transactions courtes.
- **Critères d’acceptation :** un appelant n’utilise pas directement l’ORM ni le SDK; un retry avec la même clé ne duplique pas le message ou le rapport; les erreurs sont documentées.
- **Notes techniques :** l’API HTTP éventuelle doit seulement envelopper ces services.
- **Tests attendus :** intégration Django, doublon, échec fournisseur et rollback.
- **Risques :** coupler les DTO aux vues de la plateforme.
- **Definition of Done :** DoD globale plus exemple d’appel consommable par l’équipe.

#### EVL-001 — Construire le corpus synthétique et les évaluateurs

- **Objectif :** mesurer les régressions de l’extraction aux rapports.
- **Type / Priorité / Taille / Owner :** `test` / P0 / M / Développeur IA + relecteur métier.
- **Dépendances :** `QLF-002`, `REC-001`, `RPT-001`, `RPT-002`.
- **Description :** créer 15–20 conversations synthétiques annotées et mesurer validité, faits attendus, services autorisés/interdits, provenance et sections de rapport.
- **Critères d’acceptation :** chaque cas fixe versions, entrée, attentes et justification; les erreurs critiques sont reportées séparément des moyennes.
- **Notes techniques :** Pytest et fichiers versionnés suffisent; aucune UI d’évaluation n’est requise.
- **Tests attendus :** cas attendu, cas incomplet, contradiction, service interdit et réponse malformée.
- **Risques :** corpus trop simple ou écrit uniquement par l’auteur du pipeline.
- **Definition of Done :** DoD globale plus revue de la couverture métier.

#### QA-001 — Créer le gate V1 IA

- **Objectif :** empêcher une livraison avec des objets invalides ou des recommandations inventées.
- **Type / Priorité / Taille / Owner :** `test` / P0 / S / Développeur IA.
- **Dépendances :** `INT-001`, `EVL-001`.
- **Description :** regrouper contrats, matching, provenance, échecs fournisseur et parcours complet dans une commande CI locale.
- **Critères d’acceptation :** 100 % des objets persistés sont valides; zéro service inconnu; aucun fait inféré n’est confirmé; le parcours complet avec fake passe.
- **Notes techniques :** garder les appels réels hors du gate obligatoire pour éviter le coût et le flakiness.
- **Tests attendus :** suite complète avec fake et preuve qu’une règle volontairement cassée échoue.
- **Risques :** métrique moyenne cachant un échec critique.
- **Definition of Done :** DoD globale plus commande unique documentée.

## 6. Dépendances et ordre recommandé

```text
FND-001
  → CNT-001
    → DAT-001
    → CAT-001 → REC-001
    → LLM-001 → QLF-001 → QLF-002
      → RPT-001 / RPT-002
        → INT-001
        → EVL-001
          → QA-001
            → LLM-002
```

Travail parallélisable :

- `DAT-001`, `CAT-001` et `LLM-001` peuvent avancer après stabilisation de `CNT-001`.
- `REC-001` peut être développé sur des profils fixtures pendant `QLF-001/002`.
- `RPT-001` et `RPT-002` peuvent être développés en parallèle.
- L’équipe métier peut préparer le catalogue et annoter le corpus pendant le développement du socle.

## 7. Plan de tests lié aux tickets

| Test | Couverture | Tickets | Gate |
|---|---|---|---|
| TEST-CONTRACTS | Schémas valides/invalides | `CNT-001` | Dès P0 |
| TEST-DATA | Migrations, relations, rollback | `DAT-001` | Dès P0 |
| TEST-CATALOG | Format, IDs et références | `CAT-001` | Bloquant matching |
| TEST-MATCHING | Recommandé/interdit/manquant/no_match | `REC-001` | Bloquant |
| TEST-PROVIDER | Timeout, erreur, JSON malformé | `LLM-001`, `LLM-002` | Fake obligatoire |
| TEST-PROFILE | Extraction, fusion, sources et conflits | `QLF-001`, `QLF-002` | Bloquant |
| TEST-REPORTS | KAM/profil, incertitude et séparation des recommandations | `RPT-001`, `RPT-002` | Bloquant |
| TEST-INTEGRATION | Service Django, retry et rollback | `INT-001` | Bloquant livraison |
| TEST-EVALS | Corpus synthétique complet | `EVL-001`, `QA-001` | Gate V1 |

## 8. Questions ouvertes non bloquantes pour le bootstrap

| ID | Question | Valeur provisoire | Bloque |
|---|---|---|---|
| OQ-001 | Quel fournisseur et quel modèle utiliser ? | Gemini, modèle configurable ; `gemini-3.5-flash-lite` par défaut | Résolu |
| OQ-002 | Quels sont les 5–8 services réels ? | Fixtures temporaires clairement marquées | Validation de `CAT-001` |
| OQ-003 | Qui valide les rapports ? | Un KAM ou responsable métier | Gate final rapports |
| OQ-004 | L’équipe appelle-t-elle Python ou HTTP ? | Service Python/Django | Enveloppe d’intégration seulement |
| OQ-005 | Quelles sections du profil sont réellement utiles ? | Description, identité, besoins, contraintes, manques et sources | Stabilisation après première revue |

## 9. Handoff for Development

### Première vague

1. `FND-001` — projet Django, SQLite et Pytest.
2. `CNT-001` — contrats et fixtures JSON.
3. En parallèle : `DAT-001`, `CAT-001` et `LLM-001`.
4. `REC-001` puis `QLF-001/002` pour obtenir la première tranche complète.
5. `RPT-001/002`, `INT-001`, puis `EVL-001/QA-001`.
6. `LLM-002` seulement après que le pipeline fake et le gate synthétique fonctionnent.

### Premier objectif démontrable

Avec une conversation synthétique et le fake :

- créer un profil sourcé ;
- signaler les informations manquantes ;
- retourner des opportunités du catalogue ;
- générer les deux rapports JSON ;
- tout persister dans SQLite ;
- faire passer une commande de tests reproductible.

### Risques à surveiller

- Commencer les prompts avant de stabiliser les contrats.
- Inventer le catalogue à la place du métier.
- Confondre formulation du rapport et décision de recommandation.
- Ajouter prématurément PostgreSQL, RAG, frontend séparé ou infrastructure.
- Tester uniquement les cas heureux ou avec des données trop propres.
