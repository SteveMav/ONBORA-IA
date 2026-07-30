from __future__ import annotations

import json
import uuid

from django.core.management.base import BaseCommand

from apps.ai_core.providers import HeuristicFakeChatModel
from apps.ai_core.services import ConversationService


DEFAULT_MESSAGE = (
    "Notre entreprise École Lumière, une école de formation à Kinshasa avec 25 employés, "
    "a besoin d’une connexion internet stable et d’une sauvegarde des données."
)


class Command(BaseCommand):
    help = "Exécute le parcours Onbora IA complet avec le fake hors-ligne."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--message", default=DEFAULT_MESSAGE)

    def handle(self, *args, **options) -> None:
        service = ConversationService(model=HeuristicFakeChatModel())
        conversation = service.create_conversation(metadata={"source": "demo_command"})
        turn = service.process_conversation_turn(
            conversation.pk,
            options["message"],
            f"demo-{uuid.uuid4()}",
        )
        recommendations = service.analyze_conversation(conversation.pk)
        kam = service.generate_report(conversation.pk, "kam")
        twin = service.generate_report(conversation.pk, "business_twin")
        self.stdout.write(
            json.dumps(
                {
                    "turn": turn.model_dump(mode="json"),
                    "recommendations": recommendations.model_dump(mode="json"),
                    "kam": kam.model_dump(mode="json"),
                    "business_twin": twin.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
