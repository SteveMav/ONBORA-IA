from __future__ import annotations

import os

from .base import ChatModel
from .fake import HeuristicFakeChatModel
from .gemini_adapter import GeminiChatModel


def build_chat_model() -> ChatModel:
    provider = os.getenv("ONBORA_AI_PROVIDER")
    if not provider:
        provider = "gemini" if os.getenv("GEMINI_API_KEY") else "fake"
    provider = provider.casefold()
    if provider == "fake":
        return HeuristicFakeChatModel()
    if provider == "gemini":
        return GeminiChatModel(
            model_name=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        )
    raise ValueError(f"unsupported ONBORA_AI_PROVIDER: {provider}")
