"""Тесты Chat Lead Monitor без Telethon/OpenRouter сети."""

import json
from datetime import datetime

from chat_monitor.filtering import find_keywords, passes_keyword_filter
from chat_monitor.processor import ChatMessageCandidate, process_candidate
from db import repo
from services.ai import LLMClient, score_nail_chat_message

OWNER = 987654321


class FakeLLM(LLMClient):
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    async def _complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.payload, ensure_ascii=False)


def test_keyword_filter_finds_nail_signal():
    text = "Девочки, есть свободное окошко на маникюр завтра, принимаю на дому"
    matches = find_keywords(text)
    assert "маникюр" in matches
    assert "свободное окошко" in matches
    assert passes_keyword_filter(text)


def test_keyword_filter_skips_irrelevant_text():
    assert not passes_keyword_filter("Продам кресло для парикмахера, самовывоз сегодня")


async def test_score_nail_chat_message_parses_llm_json():
    client = FakeLLM(
        {
            "score": 0.86,
            "reasoning": "Автор предлагает запись на маникюр как частный мастер.",
            "is_solo_master": True,
        }
    )

    score, reasoning, is_solo_master = await score_nail_chat_message(
        "Свободное окошко на маникюр", username="nail_pro", source_chat="nail chat", client=client
    )

    assert score == 0.86
    assert is_solo_master is True
    assert "частный мастер" in reasoning
    assert "соло-мастер" in client.prompts[0]


async def test_process_candidate_saves_relevant_chat_lead(session_factory):
    client = FakeLLM(
        {
            "score": 0.92,
            "reasoning": "Пишет как соло-мастер, есть свободное окно для записи.",
            "is_solo_master": True,
        }
    )
    candidate = ChatMessageCandidate(
        source_chat="Nails Astana (-100123)",
        user_id=777,
        username="nail_pro",
        message_text="Свободное окошко на маникюр завтра, принимаю на дому",
        message_date=datetime(2026, 7, 10, 12, 30),
        message_id=55,
    )

    lead = await process_candidate(
        candidate,
        session_factory,
        owner_tg_id=OWNER,
        min_score=0.7,
        llm_client=client,
    )

    assert lead is not None
    async with session_factory() as session:
        stored = await repo.get_lead(session, lead.id, OWNER)
        leads = await repo.list_leads(session, OWNER)

    assert len(leads) == 1
    assert stored is not None
    assert stored.source == "chat_monitor"
    assert stored.niche == "nail"
    assert stored.chat_username == "nail_pro"
    assert stored.chat_user_id == 777
    assert stored.chat_message_id == 55
    assert stored.message_text.startswith("Свободное окошко")
    assert stored.relevance_score == 0.92
    assert stored.ai_score == 92
    assert "Ключевые слова" in stored.ai_analysis


async def test_process_candidate_skips_below_threshold(session_factory):
    client = FakeLLM(
        {
            "score": 0.2,
            "reasoning": "Клиент ищет мастера, а не предлагает запись.",
            "is_solo_master": False,
        }
    )
    candidate = ChatMessageCandidate(
        source_chat="Nails chat",
        user_id=888,
        username=None,
        message_text="Ищу мастера на маникюр сегодня",
        message_date=datetime(2026, 7, 10, 12, 30),
        message_id=56,
    )

    lead = await process_candidate(candidate, session_factory, OWNER, 0.7, llm_client=client)

    assert lead is None
    async with session_factory() as session:
        assert await repo.list_leads(session, OWNER) == []
