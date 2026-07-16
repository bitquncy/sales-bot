"""AI-анализ компании и генерация сообщений через переключаемый LLM-провайдер.

Провайдер выбирается в .env (settings.llm_provider):
  * "anthropic"  — Anthropic Claude SDK (был исходным);
  * "openrouter" — любой OpenAI-совместимый эндпоинт (OpenRouter/Moonshot/…),
    с кастомным base_url и моделью из .env.

Абстракция: LLMClient с методами analyze_company()/generate_messages().
Конкретные реализации (AnthropicClient, OpenAICompatClient) отличаются только
низкоуровневым вызовом _complete() и маппингом ошибок провайдера в общие
AIError / AIRateLimitError / AIOverloadError. Логика промптов, парсинга JSON
и валидации — общая в базовом классе.

Все ошибки LLM заворачиваются в эти три класса — хендлеры показывают
пользователю понятные сообщения, бот не падает. Anthropic остаётся доступным
всегда (это настройка, а не необратимая миграция).
"""

import json
import logging

import anthropic

from config import settings

logger = logging.getLogger(__name__)


class AIError(Exception):
    """Общая ошибка LLM: таймаут, невалидный JSON, отказ API."""


class AIRateLimitError(AIError):
    """Rate limit от провайдера — пользователь видит отдельное сообщение."""


class AIOverloadError(AIError):
    """Провайдер/модель временно перегружены или недоступны (HTTP 5xx).

    Отдельно от rate-limit: у бесплатных моделей (общая инфраструктура) это
    штатная ситуация, пользователю показываем своё сообщение.
    """


def _extract_json(text: str) -> dict:
    """Достаёт JSON-объект из ответа модели (в т.ч. если он обёрнут в ```json ...```)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise AIError(f"No JSON object in LLM response: {text[:200]!r}")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AIError(f"Invalid JSON from LLM: {exc}") from exc
    if not isinstance(parsed, dict):
        raise AIError("LLM JSON is not an object")
    return parsed


def _coerce_bool_or_none(value) -> bool | None:
    """Мягко приводит значение из JSON к bool|None.

    Модель может вернуть настоящий bool, null, или строку "true"/"false"/"null".
    Всё непонятное трактуем как None (не «да» и не «нет»).
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    s = str(value).strip().lower()
    if s == "true":
        return True
    if s == "false":
        return False
    return None


def _company_block(name: str, address: str | None, phone: str | None, website: str | None) -> str:
    lines = [f"Название: {name}"]
    if address:
        lines.append(f"Адрес: {address}")
    if phone:
        lines.append(f"Телефон: {phone}")
    if website:
        lines.append(f"Сайт: {website}")
    else:
        lines.append("Сайт: отсутствует в открытых данных")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Абстракция LLM-провайдера
# --------------------------------------------------------------------------- #

class LLMClient:
    """Единый интерфейс поверх LLM. Промпты/парсинг общие, вызов — в наследниках."""

    async def _complete(self, prompt: str) -> str:
        """Отправить промпт провайдеру, вернуть текст ответа. Реализуют наследники."""
        raise NotImplementedError

    async def analyze_company(
        self,
        name: str,
        address: str | None = None,
        phone: str | None = None,
        website: str | None = None,
    ) -> tuple[int, str, bool | None]:
        """Возвращает (score, текст анализа, has_online_booking).

        has_online_booking: True — есть онлайн-запись; False — нет (или сайта
        нет) -> возможность для оффера; None — определить нельзя.
        Промпт использует настройки из конфига (ARCH-1).
        """
        service_type = settings.ai_service_type
        main_offer = settings.ai_main_offer
        prompt = (
            f"Ты — эксперт по продажам {service_type} малому бизнесу. "
            f"Проанализируй компанию как потенциального клиента на {service_type}.\n\n"
            f"{_company_block(name, address, phone, website)}\n\n"
            "Отдельно оцени, есть ли у компании ОНЛАЙН-ЗАПИСЬ. Признаки: виджет/"
            "форма записи на сайте, ссылка «записаться онлайн», интеграции "
            "YCLIENTS, Fresha, Booksy, Bookly, DIKIDI, Sberbank-запись и т.п. "
            "Если сайта нет вообще — считай, что онлайн-записи нет "
            "(has_online_booking=false): это и есть возможность для оффера. Если "
            "сайт есть, но определить по доступным данным нельзя — "
            "has_online_booking=null.\n"
            f"Если онлайн-записи нет (false), в offer ОБЯЗАТЕЛЬНО предложи среди "
            f"прочего «{main_offer}».\n\n"
            "Ответь СТРОГО одним JSON-объектом без пояснений вокруг:\n"
            '{"score": <int 0-100, потенциал как клиента>, '
            '"weaknesses": ["слабое место 1", ...], '
            '"offer": "что конкретно можно предложить этой компании", '
            '"has_online_booking": <true|false|null>}'
        )
        raw = await self._complete(prompt)
        data = _extract_json(raw)

        score = data.get("score")
        if not isinstance(score, int) or not (0 <= score <= 100):
            raise AIError(f"LLM returned invalid score: {score!r}")

        weaknesses = data.get("weaknesses") or []
        if not isinstance(weaknesses, list):
            weaknesses = [str(weaknesses)]
        offer = str(data.get("offer") or "").strip()
        has_online_booking = _coerce_bool_or_none(data.get("has_online_booking"))

        analysis_lines = []
        if weaknesses:
            analysis_lines.append("Слабые места:")
            analysis_lines.extend(f"• {w}" for w in weaknesses)
        if offer:
            analysis_lines.append("")
            analysis_lines.append(f"Что предложить: {offer}")
        # Гарантируем упоминание нашего оффера, даже если модель его не вписала.
        if has_online_booking is False:
            if analysis_lines:
                analysis_lines.append("")
            main_offer = settings.ai_main_offer
            analysis_lines.append(
                f"💡 Онлайн-записи нет — предложи {main_offer} (наш оффер)."
            )
        analysis = "\n".join(analysis_lines).strip() or "Анализ без деталей."
        return score, analysis, has_online_booking

    async def generate_messages(self, name: str, analysis: str) -> tuple[str, str]:
        service_type = settings.ai_service_type
        language = settings.ai_response_language
        prompt = (
            f"Ты — специалист по холодным продажам {service_type}. "
            f'Компания: "{name}".\n'
            f"Результат анализа:\n{analysis}\n\n"
            f"Напиши 2 варианта первого сообщения владельцу этой компании "
            f"(вежливо, на {language}, без спама и давления, с конкретной пользой):\n"
            "1) короткое — 2-3 предложения;\n"
            "2) развёрнутое — 5-8 предложений.\n\n"
            "Ответь СТРОГО одним JSON-объектом без пояснений вокруг:\n"
            '{"short": "короткое сообщение", "long": "развёрнутое сообщение"}'
        )
        raw = await self._complete(prompt)
        data = _extract_json(raw)

        short = str(data.get("short") or "").strip()
        long = str(data.get("long") or "").strip()
        if not short or not long:
            raise AIError("LLM returned empty message variants")
        return short, long

    # Максимальная длина текста сообщения, передаваемого в LLM (SEC-2).
    # Ограничивает стоимость вызова и предотвращает превышение контекстного окна.
    _MAX_CHAT_MESSAGE_LEN = 2000

    async def score_nail_chat_message(
        self,
        message_text: str,
        username: str | None = None,
        source_chat: str | None = None,
    ) -> tuple[float, str, bool]:
        """Возвращает (score 0.0-1.0, reasoning, is_solo_master) для nail-чата."""
        # Обрезаем до лимита перед вставкой в промпт (SEC-2)
        truncated_text = message_text[: self._MAX_CHAT_MESSAGE_LEN]

        context = []
        if source_chat:
            context.append(f"Чат: {source_chat}")
        if username:
            context.append(f"Автор: @{username.lstrip('@')}")
        context_block = "\n".join(context) or "Контекст чата не указан"

        niche = settings.chat_monitor_niche_description
        lead_desc = settings.chat_monitor_lead_description
        offer = settings.chat_monitor_offer_product
        prompt = (
            f"Ты оцениваешь Telegram-сообщение как sales-lead для {offer}. "
            f"Ниша: {niche}.\n\n"
            f"Нужно определить, пишет ли автор КАК {lead_desc}. "
            "Высокий score ставь, если по сообщению видно, что автор "
            "сам принимает клиентов и может нуждаться в нормальной системе записи.\n"
            "Score 0 ставь, если это клиент ищет мастера, салон/сеть с готовой "
            "CRM, вакансия, обсуждение без оффера записи или нерелевантная услуга.\n\n"
            f"{context_block}\n\n"
            "Сообщение:\n"
            f"{truncated_text}\n\n"
            "Ответь СТРОГО одним JSON-объектом без пояснений вокруг:\n"
            '{"score": <float 0-1>, "reasoning": "краткое пояснение", '
            '"is_solo_master": <true|false>}'
        )
        raw = await self._complete(prompt)
        data = _extract_json(raw)

        score = data.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise AIError(f"LLM returned invalid nail chat score: {score!r}")
        score = float(score)
        if not 0.0 <= score <= 1.0:
            raise AIError(f"LLM returned out-of-range nail chat score: {score!r}")

        reasoning = str(data.get("reasoning") or "").strip() or "Без пояснения."
        is_solo_master = _coerce_bool_or_none(data.get("is_solo_master"))
        if is_solo_master is None:
            raise AIError("LLM returned invalid is_solo_master")
        return score, reasoning, is_solo_master


class AnthropicClient(LLMClient):
    """Провайдер Anthropic Claude (SDK anthropic)."""

    def __init__(self, sdk_client: "anthropic.AsyncAnthropic | None" = None) -> None:
        self._client = sdk_client or anthropic.AsyncAnthropic(
            api_key=settings.resolved_anthropic_key,
            timeout=settings.llm_timeout_seconds,
        )

    async def _complete(self, prompt: str) -> str:
        try:
            response = await self._client.messages.create(
                model=settings.resolved_anthropic_model,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.RateLimitError as exc:
            logger.error("Anthropic rate limit: %s", exc)
            raise AIRateLimitError("Anthropic rate limit") from exc
        except anthropic.APIStatusError as exc:
            status = getattr(exc, "status_code", None)
            if status is not None and status >= 500:
                logger.error("Anthropic overloaded (HTTP %s): %s", status, exc)
                raise AIOverloadError(f"Anthropic overloaded: {exc}") from exc
            logger.error("Anthropic API error: %s", exc)
            raise AIError(f"Anthropic API error: {exc}") from exc
        except anthropic.APIError as exc:
            logger.error("Anthropic API error: %s", exc)
            raise AIError(f"Anthropic API error: {exc}") from exc
        except Exception as exc:  # таймауты, сеть и прочее
            logger.error("Anthropic call failed: %s", exc)
            raise AIError(f"Anthropic call failed: {exc}") from exc

        parts = [block.text for block in response.content if getattr(block, "text", None)]
        if not parts:
            raise AIError("Empty response from LLM")
        return "".join(parts)


class OpenAICompatClient(LLMClient):
    """OpenAI-совместимый провайдер (OpenRouter, Moonshot, локальный сервер)."""

    def __init__(self, sdk_client=None) -> None:
        if sdk_client is not None:
            self._client = sdk_client
        else:
            # Ленивый импорт: openai нужен только для этого провайдера.
            import openai

            self._client = openai.AsyncOpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                timeout=settings.llm_timeout_seconds,
            )

    async def _complete(self, prompt: str) -> str:
        import openai

        try:
            response = await self._client.chat.completions.create(
                model=settings.llm_model,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
        except openai.RateLimitError as exc:
            logger.error("OpenAI-compat rate limit: %s", exc)
            raise AIRateLimitError("LLM rate limit") from exc
        except openai.APIStatusError as exc:
            status = getattr(exc, "status_code", None)
            if status is not None and status >= 500:
                logger.error("Free model overloaded (HTTP %s): %s", status, exc)
                raise AIOverloadError(f"LLM overloaded: {exc}") from exc
            logger.error("OpenAI-compat API error: %s", exc)
            raise AIError(f"LLM API error: {exc}") from exc
        except openai.APIError as exc:  # таймаут/сеть (APITimeoutError, APIConnectionError)
            logger.error("OpenAI-compat call failed: %s", exc)
            raise AIError(f"LLM call failed: {exc}") from exc
        except Exception as exc:
            logger.error("OpenAI-compat call failed: %s", exc)
            raise AIError(f"LLM call failed: {exc}") from exc

        choices = getattr(response, "choices", None) or []
        parts = [
            c.message.content
            for c in choices
            if getattr(c, "message", None) and getattr(c.message, "content", None)
        ]
        if not parts:
            raise AIError("Empty response from LLM")
        return "".join(parts)


def get_client() -> LLMClient:
    """Возвращает синглтон LLM-клиента для провайдера из настроек (ARCH-5).

    Клиент создаётся один раз при первом вызове и переиспользуется —
    нет накладных расходов на инициализацию HTTP connection pool при каждом вызове.
    """
    return _get_or_create_client()


_llm_client_instance: LLMClient | None = None


def _get_or_create_client() -> LLMClient:
    global _llm_client_instance  # noqa: PLW0603
    if _llm_client_instance is None:
        provider = (settings.llm_provider or "anthropic").lower()
        if provider == "anthropic":
            _llm_client_instance = AnthropicClient()
        elif provider in ("openrouter", "openai", "moonshot", "openai_compat"):
            _llm_client_instance = OpenAICompatClient()
        else:
            raise AIError(f"Unknown LLM provider: {settings.llm_provider!r}")
    return _llm_client_instance


def reset_client() -> None:
    """Сбрасывает синглтон. Используется в тестах для изоляции."""
    global _llm_client_instance  # noqa: PLW0603
    _llm_client_instance = None


def _resolve_client(client) -> LLMClient:
    """Приводит переданный client к LLMClient.

    * None            -> клиент по настройкам (.env);
    * LLMClient       -> как есть;
    * иной объект     -> считается низкоуровневым Anthropic-совместимым SDK
                         (обратная совместимость: тесты/вызовы передают такой).
    """
    if client is None:
        return get_client()
    if isinstance(client, LLMClient):
        return client
    return AnthropicClient(sdk_client=client)


# --------------------------------------------------------------------------- #
#  Обратно-совместимые модульные функции (их зовут хендлеры и тесты)
# --------------------------------------------------------------------------- #

async def analyze_company(
    name: str,
    address: str | None = None,
    phone: str | None = None,
    website: str | None = None,
    client=None,
) -> tuple[int, str, bool | None]:
    """Возвращает (score 0-100, текст анализа, has_online_booking).

    has_online_booking: True/False/None. Бросает AIError / AIRateLimitError / AIOverloadError.
    """
    return await _resolve_client(client).analyze_company(name, address, phone, website)


async def generate_messages(
    name: str,
    analysis: str,
    client=None,
) -> tuple[str, str]:
    """Возвращает (короткое сообщение, развёрнутое сообщение) для холодного контакта."""
    return await _resolve_client(client).generate_messages(name, analysis)


async def score_nail_chat_message(
    message_text: str,
    username: str | None = None,
    source_chat: str | None = None,
    client=None,
) -> tuple[float, str, bool]:
    """Скоринг сообщения из nail-чата. Бросает AIError / AIRateLimitError / AIOverloadError."""
    return await _resolve_client(client).score_nail_chat_message(message_text, username, source_chat)
