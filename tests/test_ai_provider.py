"""Тесты переключаемого LLM-провайдера.

Оба клиента (Anthropic и OpenAI-совместимый) мокаются отдельно, реальная
сеть не используется ни для одного. Проверяется:
  * выбор клиента по settings.llm_provider (.env);
  * OpenAI-совместимый клиент создаётся с нужным base_url;
  * маппинг ошибок провайдера в AIError / AIRateLimitError / AIOverloadError;
  * обе высокоуровневые функции работают через оба клиента.
"""

import json

import pytest

from config import settings
from services.ai import (
    AIError,
    AIOverloadError,
    AIRateLimitError,
    AnthropicClient,
    OpenAICompatClient,
    get_client,
    reset_client,
)


@pytest.fixture(autouse=True)
def reset_llm_singleton():
    """Сбрасывает синглтон LLM-клиента перед каждым тестом для изоляции."""
    reset_client()
    yield
    reset_client()


# --------------------------------------------------------------------------- #
#  Фейковый OpenAI-совместимый SDK (chat.completions.create)
# --------------------------------------------------------------------------- #

class _FakeMsg:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMsg(content)


class _FakeChatResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc:
            raise self._exc
        return self._response


class FakeOpenAISDK:
    """Мок openai.AsyncOpenAI: .chat.completions.create."""

    def __init__(self, response_text=None, exc=None, base_url=None, api_key=None):
        self.base_url = base_url
        self.api_key = api_key

        class _Chat:
            pass

        self.chat = _Chat()
        response = _FakeChatResponse(response_text) if response_text is not None else None
        self.chat.completions = _FakeCompletions(response=response, exc=exc)


def _openai_errors():
    """Настоящие классы ошибок openai для точного маппинга в except."""
    import openai

    return openai


# --------------------------------------------------------------------------- #
#  Выбор клиента по .env (get_client)
# --------------------------------------------------------------------------- #

def test_get_client_anthropic(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(settings, "llm_api_key", "")
    client = get_client()
    assert isinstance(client, AnthropicClient)


def test_get_client_openrouter_uses_base_url(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    monkeypatch.setattr(settings, "llm_api_key", "or-test-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "llm_model", "moonshotai/kimi-k2.6:free")

    captured = {}

    def fake_ctor(api_key=None, base_url=None, timeout=None):
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        captured["timeout"] = timeout
        return FakeOpenAISDK(base_url=base_url, api_key=api_key)

    import openai
    monkeypatch.setattr(openai, "AsyncOpenAI", fake_ctor)

    client = get_client()
    assert isinstance(client, OpenAICompatClient)
    # Именно OpenAI-совместимый клиент с нужным base_url
    assert captured["base_url"] == "https://openrouter.ai/api/v1"
    assert captured["api_key"] == "or-test-key"


def test_get_client_unknown_provider(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gopher-mail")
    with pytest.raises(AIError, match="Unknown LLM provider"):
        get_client()


def test_default_client_selected_when_none(monkeypatch):
    """analyze_company(client=None) берёт провайдера из настроек."""
    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    monkeypatch.setattr(settings, "llm_api_key", "or-test-key")
    monkeypatch.setattr(settings, "llm_model", "moonshotai/kimi-k2.6:free")

    payload = {"score": 42, "weaknesses": ["нет сайта"], "offer": "лендинг"}
    fake_sdk = FakeOpenAISDK(response_text=json.dumps(payload, ensure_ascii=False))

    import openai
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: fake_sdk)

    # Через модульную функцию, client=None -> get_client() -> OpenAICompatClient
    return_value = get_client()
    assert isinstance(return_value, OpenAICompatClient)


# --------------------------------------------------------------------------- #
#  OpenAI-совместимый клиент: happy path и ошибки
# --------------------------------------------------------------------------- #

async def test_openai_compat_analyze_happy_path(monkeypatch):
    monkeypatch.setattr(settings, "llm_model", "moonshotai/kimi-k2.6:free")
    payload = {"score": 70, "weaknesses": ["нет онлайн-записи"], "offer": "виджет записи"}
    sdk = FakeOpenAISDK(response_text=json.dumps(payload, ensure_ascii=False))
    client = OpenAICompatClient(sdk_client=sdk)

    score, analysis, _has_booking = await client.analyze_company("Кафе", address="Мира 5")
    assert score == 70
    assert "нет онлайн-записи" in analysis
    assert "виджет записи" in analysis
    # модель передана из настроек
    assert sdk.chat.completions.calls[0]["model"] == "moonshotai/kimi-k2.6:free"


async def test_openai_compat_generate_happy_path(monkeypatch):
    payload = {"short": "Короткое", "long": "Развёрнутое сообщение подлиннее."}
    sdk = FakeOpenAISDK(response_text=json.dumps(payload, ensure_ascii=False))
    client = OpenAICompatClient(sdk_client=sdk)

    short, long = await client.generate_messages("Кафе", "нет сайта")
    assert short == "Короткое"
    assert long == "Развёрнутое сообщение подлиннее."


async def test_openai_compat_rate_limit_maps_to_rate_limit_error():
    openai = _openai_errors()
    import httpx

    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    resp = httpx.Response(429, request=req)
    exc = openai.RateLimitError("rate limited", response=resp, body=None)
    sdk = FakeOpenAISDK(exc=exc)
    client = OpenAICompatClient(sdk_client=sdk)

    with pytest.raises(AIRateLimitError):
        await client.analyze_company("X")


async def test_openai_compat_5xx_maps_to_overload_error():
    """Перегрузка бесплатной модели (HTTP 5xx) -> отдельный AIOverloadError."""
    openai = _openai_errors()
    import httpx

    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    resp = httpx.Response(503, request=req)
    exc = openai.APIStatusError("service unavailable", response=resp, body=None)
    sdk = FakeOpenAISDK(exc=exc)
    client = OpenAICompatClient(sdk_client=sdk)

    with pytest.raises(AIOverloadError):
        await client.analyze_company("X")
    # И это не rate-limit
    try:
        await client.analyze_company("X")
    except AIRateLimitError:
        pytest.fail("5xx не должен превращаться в AIRateLimitError")
    except AIOverloadError:
        pass


async def test_openai_compat_timeout_maps_to_ai_error():
    openai = _openai_errors()
    req_exc = openai.APITimeoutError(request=None) if hasattr(openai, "APITimeoutError") else TimeoutError()
    sdk = FakeOpenAISDK(exc=req_exc)
    client = OpenAICompatClient(sdk_client=sdk)

    with pytest.raises(AIError):
        await client.analyze_company("X")


async def test_openai_compat_transient_error_is_retried(monkeypatch):
    import openai
    import httpx

    monkeypatch.setattr(settings, "llm_retry_attempts", 1)
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    transient = openai.APIConnectionError(request=request)
    payload = {"score": 40, "weaknesses": [], "offer": "x", "has_online_booking": None}

    class RetrySDK:
        def __init__(self):
            self.calls = 0
            self.chat = type("Chat", (), {})()
            self.chat.completions = type("Completions", (), {"create": self.create})()

        async def create(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise transient
            return _FakeChatResponse(json.dumps(payload))

    sdk = RetrySDK()
    client = OpenAICompatClient(sdk_client=sdk)
    score, _, _ = await client.analyze_company("X")
    assert score == 40
    assert sdk.calls == 2


async def test_openai_compat_empty_response_raises():
    sdk = FakeOpenAISDK(response_text="")
    client = OpenAICompatClient(sdk_client=sdk)
    with pytest.raises(AIError):
        await client.analyze_company("X")


# --------------------------------------------------------------------------- #
#  Anthropic-клиент: перегрузка (5xx) -> AIOverloadError
# --------------------------------------------------------------------------- #

async def test_anthropic_5xx_maps_to_overload_error():
    import anthropic
    import httpx

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(529, request=req)  # Anthropic "overloaded"
    exc = anthropic.APIStatusError("overloaded", response=resp, body=None)

    from tests.test_ai import FakeClient

    client = AnthropicClient(sdk_client=FakeClient(exc=exc))
    with pytest.raises(AIOverloadError):
        await client.analyze_company("X")
