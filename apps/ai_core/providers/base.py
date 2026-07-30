from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


class ModelError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class ModelCallResult(Generic[T]):
    output: T
    usage: ModelUsage = ModelUsage()


class ChatModel(Protocol):
    provider_name: str
    model_name: str

    def generate_structured(
        self,
        *,
        purpose: str,
        instructions: str,
        payload: dict[str, Any],
        response_model: type[T],
    ) -> ModelCallResult[T]: ...

