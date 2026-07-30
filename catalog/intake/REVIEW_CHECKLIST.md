# Checklist de revue métier

Cette checklist doit être complétée **offre par offre** dans `service_reviews` avant de
passer le catalogue au statut `approved`.

## Identité et contenu de l’offre

- Le nom est celui utilisé officiellement par Orange Business RDC, Orange Business Global
  ou Orange Cyberdefense.
- Le fournisseur, la portée géographique, le niveau de portefeuille et la disponibilité RDC
  sont explicitement renseignés et cohérents.
- La description ne promet que ce qui est confirmé par une source officielle.
- Les bénéfices autorisés sont formulés comme des bénéfices possibles, sans garantie
  commerciale, technique ou financière non documentée.
- Les variantes correspondent à des variantes réellement commercialisées.

## Adéquation client

- Les clients cibles et critères d’éligibilité ont été vérifiés par le métier.
- Les prérequis sont complets et actionnables.
- Les exclusions et cas non couverts sont explicites.
- Les mots-clés de matching décrivent des besoins clients, pas uniquement le nom du
  produit.
- Les champs de profil nécessaires au matching sont justifiés.

## Couverture et tarification

- La couverture est marquée `national`, `international`, `limited` ou `case_by_case` sur preuve.
- Une couverture limitée contient les zones confirmées; une couverture au cas par cas
  précise qu’une vérification commerciale ou technique est nécessaire.
- Aucun prix, intervalle, remise ou périodicité n’est saisi sans source officielle datée.
- Si le prix n’est pas public, utiliser `not_public`; si un devis est requis, utiliser
  `quote_required`. Ne pas transformer une absence de prix en estimation.

## Provenance et approbation

- Chaque affirmation importante est rattachée à au moins une source dans `provenance`.
- Au moins une source primaire officielle est marquée `verified` et possède un titre,
  un éditeur, une URL HTTPS et une date de consultation.
- La date de vérification du service correspond à une vérification réelle.
- Le relecteur métier renseigne son nom, sa date de revue et le statut `approved`.
- Les dix éléments de `review_checklist` sont vrais.

L’outil automatisé contrôle la structure et la complétude. Il ne peut pas déterminer si
une source est authentique, si une offre est encore commercialisée ni si les affirmations
sont exactes : ces points restent sous la responsabilité du relecteur métier.
