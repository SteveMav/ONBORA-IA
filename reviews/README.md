# Revue métier du catalogue et des rapports

Les fichiers `*.pending.json` de ce dossier sont des dossiers de décision, pas des
preuves d’approbation. Ils utilisent exclusivement le catalogue public et des scénarios
synthétiques. Ne pas remplacer `pending` ou `needs_review` par `approved` sans revue
effective par une personne autorisée.

## Catalogue

Le paquet courant contient une fiche de revue pour chacune des 41 offres ou familles :

```powershell
python catalog/intake/validate_intake.py `
  reviews/catalog/orange-business-rdc-global-2026-07-28.pending.json
```

Le relecteur métier doit vérifier les sources, la disponibilité, l’éligibilité, les
prérequis, les exclusions, la couverture, les prix et les termes de matching. Il renseigne
ensuite son nom, la date, les dix éléments de checklist et la décision de chaque offre.

Le contrôle final est bloquant :

```powershell
python catalog/intake/validate_intake.py `
  reviews/catalog/orange-business-rdc-global-2026-07-28.pending.json `
  --require-approved
```

Après succès seulement, exporter vers une nouvelle version avec `--export`. Ne pas écraser
le catalogue draft ni changer `ONBORA_CATALOG_PATH` avant revue du diff et des tests.

## Rapports KAM et Business Twin

Le paquet courant contient cinq scénarios synthétiques, chacun décliné en rapport KAM et
Business Twin. Pour chaque rapport, le KAM ou responsable métier vérifie les six critères,
renseigne son identité, la date, ses notes et la décision.

```powershell
python manage.py validate_report_review `
  reviews/reports/kam-twin-v1.pending.json

python manage.py validate_report_review `
  reviews/reports/kam-twin-v1.pending.json `
  --require-approved
```

Une décision rejetée reste une preuve utile : corriger le générateur ou le contrat, créer un
nouveau paquet versionné, puis refaire la revue. Ne pas modifier rétroactivement le paquet
qui a reçu la décision.

## Régénération sans écrasement

```powershell
python manage.py prepare_catalog_review `
  --output reviews/catalog/catalog-review-v2.pending.json

python manage.py prepare_report_review `
  --scenario-count 5 `
  --output reviews/reports/kam-twin-v2.pending.json
```

Les commandes refusent volontairement d’écraser un dossier existant.
