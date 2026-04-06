"""Tests for OllamaClient — orchestrator LLM wrapper."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ralph.llm.ollama_client import OllamaClient, OllamaError, Message, Role


class TestMessage:
    def test_user_message(self):
        m = Message(role=Role.USER, content="Hello")
        assert m.role == Role.USER
        assert m.content == "Hello"

    def test_assistant_message(self):
        m = Message(role=Role.ASSISTANT, content="Hi")
        assert m.role == Role.ASSISTANT

    def test_system_message(self):
        m = Message(role=Role.SYSTEM, content="You are an orchestrator.")
        assert m.role == Role.SYSTEM

    def test_to_dict(self):
        m = Message(role=Role.USER, content="Hello")
        d = m.to_dict()
        assert d == {"role": "user", "content": "Hello"}


class TestOllamaClient:
    @pytest.fixture
    def client(self):
        return OllamaClient(
            model="gemma4:27b",
            endpoint="http://localhost:11434",
            max_tokens=2048,
        )

    @pytest.fixture
    def mock_response(self):
        response = MagicMock()
        response.message.content = '{"tasks": ["Write tests", "Implement feature"]}'
        return response

    async def test_chat_returns_text(self, client, mock_response):
        with patch("ralph.llm.ollama_client.ollama.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_cls.return_value = mock_instance
            mock_instance.chat.return_value = mock_response

            messages = [Message(role=Role.USER, content="Plan a feature")]
            result = await client.chat(messages)

        assert result == '{"tasks": ["Write tests", "Implement feature"]}'

    async def test_chat_passes_correct_model(self, client, mock_response):
        with patch("ralph.llm.ollama_client.ollama.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_cls.return_value = mock_instance
            mock_instance.chat.return_value = mock_response

            messages = [Message(role=Role.USER, content="Hello")]
            await client.chat(messages)

            call_kwargs = mock_instance.chat.call_args.kwargs
            assert call_kwargs["model"] == "gemma4:27b"

    async def test_chat_passes_messages_as_dicts(self, client, mock_response):
        with patch("ralph.llm.ollama_client.ollama.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_cls.return_value = mock_instance
            mock_instance.chat.return_value = mock_response

            messages = [
                Message(role=Role.SYSTEM, content="You orchestrate."),
                Message(role=Role.USER, content="Plan this."),
            ]
            await client.chat(messages)

            call_kwargs = mock_instance.chat.call_args.kwargs
            assert call_kwargs["messages"] == [
                {"role": "system", "content": "You orchestrate."},
                {"role": "user", "content": "Plan this."},
            ]

    async def test_chat_raises_ollama_error_on_exception(self, client):
        with patch("ralph.llm.ollama_client.ollama.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_cls.return_value = mock_instance
            mock_instance.chat.side_effect = Exception("Connection refused")

            messages = [Message(role=Role.USER, content="Hello")]
            with pytest.raises(OllamaError, match="Connection refused"):
                await client.chat(messages)

    async def test_chat_with_options_passes_num_predict(self, client, mock_response):
        with patch("ralph.llm.ollama_client.ollama.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_cls.return_value = mock_instance
            mock_instance.chat.return_value = mock_response

            messages = [Message(role=Role.USER, content="Hello")]
            await client.chat(messages)

            call_kwargs = mock_instance.chat.call_args.kwargs
            assert call_kwargs["options"]["num_predict"] == 2048

    async def test_endpoint_passed_to_async_client(self, client, mock_response):
        with patch("ralph.llm.ollama_client.ollama.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_cls.return_value = mock_instance
            mock_instance.chat.return_value = mock_response

            messages = [Message(role=Role.USER, content="Hello")]
            await client.chat(messages)

            mock_cls.assert_called_once_with(host="http://localhost:11434")
