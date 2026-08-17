# ONBORA IA

Module Django/SQLite consacré à la qualification IA et à la génération de rapports,
avec une petite interface web locale pour les essais. Il ne contient volontairement ni
frontend séparé, ni PostgreSQL, ni worker, ni plateforme multi-tenant.

Ce dépôt est l'espace de travail partagé de l'équipe IA d'ONBORA. Il isole le moteur de
qualification, les règles de recommandation, les évaluations et les rapports du reste de la
plateforme afin que deux développeurs puissent faire évoluer l'IA sans coupler leur rythme à
celui du produit principal.

## Situation actuelle

**État au 30 juillet 2026 : V1 fonctionnelle, validation métier et durcissement avant
production encore nécessaires.**

| Domaine | État | Prochaine étape |
|---|---|---|
| Conversation et extraction Gemini | Fonctionnel | Corriger les confusions résiduelles entre activité, besoin et contrainte |
| Profil d'entreprise sourcé | Fonctionnel | Faire relire les champs et règles de confirmation par le métier |
| Matching des offres | Fonctionnel sur catalogue `draft` | Faire approuver les offres et règles par Orange / le responsable métier |
| Rapport KAM et profil d’entreprise | Fonctionnels en JSON et HTML | Organiser une revue avec leurs utilisateurs cibles |
| Évaluations hors ligne | Gate reproductible | Enrichir les scénarios à chaque régression détectée |
| Évaluation Gemini réelle | 5 scénarios sur 8 entièrement conformes au dernier run | Atteindre le seuil de qualité convenu avant données réelles |
| Interface de démonstration | Fonctionnelle en local | Conserver ce workbench léger jusqu'à l'intégration produit |
| Production | Non prête | Décider auth, multi-tenant, stockage, observabilité et politique de données |

Le détail ticket par ticket et les preuves de vérification sont dans
[`docs/onbora-ai-v1-implementation-status.md`](docs/onbora-ai-v1-implementation-status.md).

## Trajectoire de la partie IA

1. **Fiabiliser la qualification** — analyser les trois cas Gemini encore non conformes,
   améliorer prompt et règles de fusion, puis figer un seuil de qualité mesurable.
2. **Valider le métier** — approuver le catalogue, les règles de matching et un échantillon
   représentatif de rapports KAM et de profils d’entreprise.
3. **Préparer l'intégration** — stabiliser les DTO du `ConversationService`, préciser le
   contrat d'appel avec l'équipe plateforme et ajouter une API HTTP seulement si nécessaire.
4. **Durcir avant production** — authentification, isolation des organisations, PostgreSQL,
   journalisation sûre, supervision, sauvegardes et politique de rétention.
5. **Améliorer en continu** — convertir chaque incident ou correction humaine en scénario
   d'évaluation versionné avant de modifier le prompt ou le modèle.

Les choix structurants et le backlog complet sont documentés dans
[`docs/onbora-ai-mvp-architecture.md`](docs/onbora-ai-mvp-architecture.md) et
[`docs/onbora-ai-mvp-backlog.md`](docs/onbora-ai-mvp-backlog.md).

## Fonctionnalités

- conversation Gemini multi-tour avec une réponse assistant et une extraction structurée à chaque message ;
- signal explicite du modèle quand les informations sont suffisantes, sans lancer l’analyse automatiquement ;
- conservation des sources, statuts, contradictions et informations manquantes ;
- matching déterministe avec 28 offres publiques Orange Business RDC et 13 familles
  internationales Orange Business / Orange Cyberdefense ;
- explication client des offres retenues, de leurs bénéfices et des prérequis à vérifier ;
- génération d’un rapport KAM et d’un profil d’entreprise strictement descriptif ;
- export autonome des rapports en HTML imprimable et en JSON validé ;
- idempotence des messages et rapports ;
- workbench web Django pour tester le parcours sans construire la plateforme complète ;
- fake hors-ligne clairement signalé, adaptateur Gemini réel et traces techniques minimisées ;
- corpus synthétique et gate Pytest reproductible.

Le catalogue fourni est en statut `draft` : ses fiches proviennent des pages publiques
officielles Orange Business RDC, Orange Business Global et Orange Cyberdefense vérifiées
jusqu’au 28 juillet 2026. Les familles mondiales sont signalées comme internationales et leur
disponibilité en RDC reste explicitement à confirmer. Les prix, la couverture, la livraison et
les conditions contractuelles doivent être validés par Orange et par le responsable métier
avant un usage commercial.

## Installation

Prérequis : Python 3.12.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python manage.py migrate
```

Le projet charge automatiquement `.env` au démarrage sans remplacer les variables déjà
définies par le processus. Renseigner `GEMINI_API_KEY` dans ce fichier pour le chat réel.

## Travailler à deux

Le dépôt suit un flux simple basé sur des branches courtes et des pull requests :

```powershell
git checkout main
git pull
git checkout -b feature/description-courte
# développement et tests
git push -u origin feature/description-courte
```

- `main` doit rester exécutable et passer les vérifications hors ligne ;
- une branche par sujet, avec les préfixes `feature/`, `fix/`, `eval/` ou `docs/` ;
- toute modification d'un prompt, du catalogue ou d'une règle de matching doit inclure un
  cas d'évaluation ou un test qui explique le comportement attendu ;
- ne jamais committer `.env`, une clé API, `db.sqlite3`, des données client ou les sorties de
  test locales ;
- demander une revue de l'autre développeur avant fusion pour les contrats, migrations,
  prompts et règles métier ;
- noter les validations humaines du catalogue et des rapports dans `reviews/`.

### Répartition de travail suggérée

| Axe | Responsable principal | Revue croisée |
|---|---|---|
| Fournisseur LLM, prompts, extraction, évaluations réelles | Développeur IA A | Développeur IA B |
| Domaine déterministe, matching, rapports, intégration Django | Développeur IA B | Développeur IA A |
| Contrats, catalogue, sécurité des données et gates qualité | Partagé | Obligatoire |

Cette répartition est une base de coordination, pas une séparation rigide de propriété.

## Vérification et démonstration

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest
python manage.py run_ai_eval
python manage.py demo_ai_v1
```

L’évaluation déterministe ci-dessus ne contacte aucun fournisseur. L’évaluation end-to-end
Gemini utilise un corpus synthétique séparé, exige une confirmation explicite du réseau et
écrit un rapport JSON avec exactitude des champs, services attendus/interdits, erreurs,
latences et tokens :

```powershell
python manage.py run_gemini_eval --confirm-network
```

Elle n’est pas exécutée par Pytest afin que les tests reproductibles restent hors ligne.

La commande de démonstration utilise explicitement le fake et écrit une conversation, un
profil, des recommandations et deux rapports dans `db.sqlite3`.

## Interface web de test

```powershell
python manage.py runserver
```

Ouvrir ensuite `http://127.0.0.1:8000/`, puis cliquer sur **Démarrer la conversation**.
Avec Gemini configuré, chaque message produit une réponse conversationnelle et, tant que
nécessaire, une seule question suivante. Le modèle comprend d’abord le besoin, repère les
offres plausibles et ne demande ensuite que les critères utiles à ces offres.

Quand le besoin correspond à une offre plausible et que ses critères requis sont présents,
le service marque la qualification comme prête. Une demande de paiement ne déclenche donc
pas une question d’effectif, tandis qu’un besoin internet peut nécessiter le site et le
dimensionnement. Le bouton **Lancer l’analyse** devient
alors disponible. L’analyse n’est jamais lancée par le simple envoi d’un message. Après ce
clic seulement, le chatbot présente les offres Orange adaptées au problème décrit et
explique ce qu’elles peuvent apporter. La fiche entreprise affiche également les offres,
leurs bénéfices et les vérifications nécessaires. La personne corrige et confirme ensuite
la fiche avant de générer le profil d’entreprise et le rapport KAM. Le profil décrit
uniquement l’entreprise ; les offres et prochaines actions restent dans le rapport KAM.

Le workbench est destiné aux essais locaux : il ne fournit ni authentification ni isolation
multi-tenant.

## Intégration Django

```python
from apps.ai_core.providers import build_chat_model
from apps.ai_core.services import ConversationService

service = ConversationService(model=build_chat_model())
conversation = service.create_conversation()

turn = service.process_conversation_turn(
    conversation.id,
    "Notre entreprise fictive a besoin d'une connexion internet stable.",
    "client-generated-idempotency-key",
)
print(turn.assistant_message)
if turn.ready_for_analysis:
    recommendations = service.analyze_conversation(conversation.id)

# Après relecture humaine des informations extraites :
service.confirm_company_profile(
    conversation.id,
    name="Entreprise fictive",
    sector="services",
    size=25,
    activities=["conseil"],
    locations=["Kinshasa"],
    needs=["connexion internet stable"],
    constraints=[],
)
kam = service.generate_report(conversation.id, "kam")
company_profile = service.generate_report(conversation.id, "company_profile")
```

Les vues Django ou une future API HTTP doivent envelopper ces services plutôt que manipuler
directement l’ORM ou le SDK du fournisseur.

## Configuration Gemini

```powershell
# Équivalent dans .env :
# ONBORA_AI_PROVIDER=gemini
# GEMINI_API_KEY=...
# GEMINI_MODEL=gemini-3.5-flash-lite
python manage.py runserver
```

Pour une démonstration entièrement hors ligne, définir `ONBORA_AI_PROVIDER=fake`. La barre
supérieure et un avertissement dans le chat indiquent alors explicitement qu’aucun LLM n’est
utilisé.

L’adaptateur `google-genai` utilise une sortie JSON structurée comprenant la réponse du chat
et le patch de profil, ensuite validée par Pydantic. Il transmet les 12 derniers messages
bornés pour assurer la continuité de la conversation. Il applique un
timeout de 20 secondes. Le SDK est limité à une tentative par appel ; le service autorise au
maximum deux tentatives idempotentes par message. Les tests obligatoires n’appellent jamais
le réseau. Ne pas utiliser de données client réelles avant validation de la politique
fournisseur et des accès.

## Contrats et données

- `contracts/` : JSON Schemas exportés et exemples valides/invalides ;
- `catalog/versions/v1/catalog.json` : base sourcée Orange Business RDC et internationale ;
- `catalog/intake/` : kit de collecte, contrôle métier et publication d’un catalogue approuvé ;
- `prompts/extraction/v1.md` : prompt d’extraction versionné ;
- `evals/cases.json` : corpus synthétique de 32 scénarios, dont 15 multi-tours ;
- `evals/gemini-cases.json` : 8 scénarios annotés dont chaque vérité terrain est présente
  dans le texte réellement envoyé à Gemini ;
- `reviews/` : paquets traçables de revue du catalogue et de cinq paires de rapports ;
- `docs/` : architecture et backlog.

Pour régénérer les JSON Schemas :

```powershell
python manage.py export_ai_schemas
```

## Limites assumées

- SQLite convient aux essais et à une faible concurrence d’écriture.
- Le fake heuristique sert uniquement à la démonstration ; il ne mesure pas la qualité d’un
  vrai modèle.
- Les règles de matching, les tarifs et les conditions restent à approuver par le métier.
- Le profil d’entreprise reste descriptif ; il ne contient ni recommandation, ni simulation,
  ni prédiction.
