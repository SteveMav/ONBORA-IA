# RPT-003 — Exports des rapports

La V1 exporte chaque rapport KAM et profil d’entreprise existant sous deux formes :

- JSON téléchargé, revalidé avec le contrat Pydantic correspondant avant sérialisation ;
- HTML autonome, échappé par le moteur de templates Django et optimisé pour l’impression A4.

L’export HTML peut être ouvert dans un nouvel onglet puis enregistré en PDF avec la fonction
**Imprimer > Enregistrer au format PDF** du navigateur.

## Décision concernant le PDF serveur

La génération PDF côté serveur est différée. Le format métier final (charte, pagination,
mentions légales, en-têtes, validation des sections) n’est pas encore validé et le projet ne
dispose actuellement d’aucune dépendance PDF. Ajouter un moteur maintenant augmenterait le
poids de déploiement et le périmètre de maintenance pour reproduire un document encore amené
à changer. L’HTML imprimable couvre le besoin de test sans verrouiller prématurément la mise
en page. Une génération PDF dédiée pourra être ajoutée après validation d’un modèle de rapport.

## Garanties d’accès

L’URL d’export contient la conversation, le type et l’identifiant du rapport. Le serveur exige
que ces trois valeurs correspondent au même enregistrement. Un rapport absent ou appartenant
à une autre conversation renvoie `404`; un type ou format non pris en charge renvoie `400`.
L’export ne déclenche aucun appel au modèle IA.
