"""Тесты AI-сервиса (анализ). Anthropic API мокается — без реальной сети."""

import json

import anthropic
import httpx
import pytest

from services.ai import AIError, AIRateLimitError, _extract_json, analyze_company


class FakeBlock:
    def __init__(self, text):
        self.text = text


class FakeResponse:
    def __init__(self, text):
        self.content = [FakeBlock(text)]


class FakeMessages:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    async def create(self, **kwargs):
        if self._exc:
            raise self._exc
        return self._response


class FakeClient:
    def __init__(self, response_text=None, exc=None):
        response = FakeResponse(response_text) if response_text is not None else None
        self.messages = FakeMessages(response=response, exc=exc)


def _rate_limit_error():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(429, request=req)
    return anthropic.RateLimitError("rate limited", response=resp, body=None)


def _api_error(status=500):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(status, request=req)
    return anthropic.APIStatusError("server error", response=resp, body=None)


# ---------- _extract_json ----------

def test_extract_json_plain():
    assert _extract_json('{"score": 5}') == {"score": 5}


def test_extract_json_with_code_fence():
    raw = '```json\n{"score": 77, "offer": "сайт"}\n```'
    assert _extract_json(raw)["score"] == 77


def test_extract_json_with_surrounding_text():
    raw = 'Вот результат: {"score": 10} — готово.'
    assert _extract_json(raw) == {"score": 10}


def test_extract_json_no_object_raises():
    with pytest.raises(AIError, match="No JSON"):
        _extract_json("просто текст без json")


def test_extract_json_invalid_raises():
    with pytest.raises(AIError, match="Invalid JSON"):
        _extract_json('{"score": }')


def test_extract_json_non_object_raises():
    with pytest.raises(AIError):
        _extract_json("[1, 2, 3]")


# ---------- analyze_company ----------

async def test_analyze_company_happy_path():
    payload = {"score": 85, "weaknesses": ["нет сайта", "нет онлайн-записи"], "offer": "сделать лендинг"}
    client = FakeClient(response_text=json.dumps(payload, ensure_ascii=False))
    score, analysis, has_booking = await analyze_company("Барбершоп", address="Ленина 1", client=client)
    assert score == 85
    assert "нет сайта" in analysis
    assert "сделать лендинг" in analysis
    # поля has_online_booking в ответе нет -> None (не «да» и не «нет»)
    assert has_booking is None


async def test_analyze_company_parses_has_online_booking_false():
    payload = {"score": 60, "weaknesses": [], "offer": "лендинг", "has_online_booking": False}
    client = FakeClient(response_text=json.dumps(payload, ensure_ascii=False))
    score, analysis, has_booking = await analyze_company("Кафе", client=client)
    assert has_booking is False
    # при false в текст анализа детерминированно добавляется наш оффер
    assert "Telegram-бота" in analysis


async def test_analyze_company_parses_has_online_booking_true():
    payload = {"score": 30, "weaknesses": [], "offer": "", "has_online_booking": True}
    client = FakeClient(response_text=json.dumps(payload, ensure_ascii=False))
    _, analysis, has_booking = await analyze_company("Салон", client=client)
    assert has_booking is True
    # при true оффер записи через бота НЕ навязываем
    assert "Telegram-бота" not in analysis


async def test_analyze_company_parses_has_online_booking_null():
    payload = {"score": 50, "weaknesses": [], "offer": "", "has_online_booking": None}
    client = FakeClient(response_text=json.dumps(payload, ensure_ascii=False))
    _, analysis, has_booking = await analyze_company("Бар", client=client)
    assert has_booking is None
    assert "Telegram-бота" not in analysis


async def test_analyze_company_has_online_booking_string_coerced():
    # модель иногда отдаёт строку "false" вместо bool — приводим мягко
    payload = {"score": 50, "weaknesses": [], "offer": "", "has_online_booking": "false"}
    client = FakeClient(response_text=json.dumps(payload, ensure_ascii=False))
    _, _, has_booking = await analyze_company("Бар", client=client)
    assert has_booking is False


async def test_analyze_company_invalid_json():
    client = FakeClient(response_text="извини, не могу ответить в JSON")
    with pytest.raises(AIError):
        await analyze_company("X", client=client)


async def test_analyze_company_score_out_of_range():
    client = FakeClient(response_text='{"score": 150, "weaknesses": [], "offer": ""}')
    with pytest.raises(AIError, match="invalid score"):
        await analyze_company("X", client=client)


async def test_analyze_company_score_not_int():
    client = FakeClient(response_text='{"score": "высокий", "weaknesses": [], "offer": ""}')
    with pytest.raises(AIError, match="invalid score"):
        await analyze_company("X", client=client)


async def test_analyze_company_rate_limit_is_distinct():
    client = FakeClient(exc=_rate_limit_error())
    with pytest.raises(AIRateLimitError):
        await analyze_company("X", client=client)


async def test_analyze_company_api_error():
    client = FakeClient(exc=_api_error(500))
    with pytest.raises(AIError):
        await analyze_company("X", client=client)
    # но это не rate-limit
    try:
        await analyze_company("X", client=client)
    except AIRateLimitError:
        pytest.fail("APIStatusError не должен превращаться в AIRateLimitError")
    except AIError:
        pass


async def test_analyze_company_timeout():
    client = FakeClient(exc=TimeoutError("timed out"))
    with pytest.raises(AIError, match="failed"):
        await analyze_company("X", client=client)


async def test_analyze_company_empty_response():
    client = FakeClient(response_text="")
    with pytest.raises(AIError):
        await analyze_company("X", client=client)
