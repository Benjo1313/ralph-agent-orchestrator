"""Async Ollama client for the Ralph orchestrator."""
from enum import StrEnum

import ollama


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message:
    def __init__(self, role: Role, content: str) -> None:
        self.role = role
        self.content = content

    def to_dict(self) -> dict:
        return {"role": str(self.role), "content": self.content}


class OllamaError(Exception):
    pass


class OllamaClient:
    def __init__(self, model: str, endpoint: str, max_tokens: int = 2048) -> None:
        self.model = model
        self.endpoint = endpoint
        self.max_tokens = max_tokens

    async def chat(self, messages: list[Message], max_tokens: int | None = None) -> str:
        client = ollama.AsyncClient(host=self.endpoint)
        try:
            response = await client.chat(
                model=self.model,
                messages=[m.to_dict() for m in messages],
                options={"num_predict": max_tokens or self.max_tokens},
            )
        except Exception as e:
            raise OllamaError(str(e)) from e
        return response.message.content
