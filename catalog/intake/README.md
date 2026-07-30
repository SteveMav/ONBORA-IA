# Kit de collecte — Orange Business RDC et international

Ce dossier sert à collecter, tracer et faire approuver les offres avant leur import dans
le catalogue utilisé par l’application. Il ne contient aucune offre réelle préremplie et
ne modifie pas `catalog/versions/v1/catalog.json`.

## Fichiers

- `template.json` : gabarit à copier et à compléter.
- `validate_intake.py` : validation structurelle, contrôle d’approbation et export sûr.
- `REVIEW_CHECKLIST.md` : règles de revue humaine avant approbation.

Le bloc `catalog` du gabarit respecte directement `CatalogDefinition` et chaque élément
de `catalog.services` respecte `ServiceDefinition`. Les informations de gouvernance qui
ne font pas partie du contrat d’exécution sont conservées dans `service_reviews`.

## Procédure de collecte

1. Copier `template.json` vers un fichier de travail, sans éditer le gabarit original.
2. Remplacer l’offre factice et dupliquer `catalog.services[]` et
   `service_reviews[]` pour chaque offre. Les `service_id` doivent correspondre exactement.
3. Conserver `catalog.status` et les validations au statut `draft` pendant la recherche.
4. Renseigner les sources et les dates de consultation. Une page officielle Orange doit
   être préférée; une source secondaire officielle doit être signalée avec
   `source_status: official_secondary`.
5. Décrire l’éligibilité, les prérequis, les exclusions et la couverture sans les déduire
   du seul nom commercial.
6. Renseigner le fournisseur, la portée et le niveau de portefeuille. Une famille mondiale
   utilise `portfolio_scope: international`, `portfolio_level: global_solution_family`,
   `rdc_availability: to_confirm` et une note de disponibilité explicite.
7. Pour les prix, utiliser `not_public` ou `quote_required` si aucun prix public vérifié
   n’existe. `published` exige les termes du prix, la devise et une source datée.
8. Faire compléter la checklist par un responsable métier. Lui seul passe chaque
   validation et le catalogue à `approved`.

Validation pendant la collecte :

```powershell
python catalog/intake/validate_intake.py catalog/intake/orange-business-rdc.intake.json
```

Contrôle bloquant avant import :

```powershell
python catalog/intake/validate_intake.py catalog/intake/orange-business-rdc.intake.json --require-approved
```

## Import vers le catalogue applicatif

Ne jamais écraser directement le catalogue actif. Exporter d’abord vers un nouveau
dossier de version :

```powershell
python catalog/intake/validate_intake.py catalog/intake/orange-business-rdc.intake.json `
  --export catalog/versions/orange-rdc-2026-07/catalog.json
```

L’export exige automatiquement une approbation complète, refuse d’écraser un fichier
existant et relit le résultat avec `load_catalog(..., require_approved=True)`. Après revue
du diff et exécution des tests, l’équipe peut changer `ONBORA_CATALOG_PATH` pour pointer
vers cette nouvelle version. Le catalogue public enrichi de V1 reste disponible pour le
retour arrière tant que la version approuvée n’a pas été activée.

## Limites du contrôle automatisé

Le validateur vérifie la forme, la cohérence des identifiants, la présence des sources,
les dates, la couverture, la discipline tarifaire, l’approbation et la checklist. Il ne
vérifie pas le contenu des pages web et ne remplace pas la validation d’Orange RDC,
d’Orange Business ou d’Orange Cyberdefense.
