"""Структурные тесты клавиатур: callback_data и раскладка кнопок.

Проверяем именно те две клавиатуры, что раньше были не покрыты
(leads_filter_kb, statuses_kb), — это фильтр лидов и меню смены статуса.
Клавиатура не должна молча уехать по callback_data: битый data = мёртвая
кнопка у пользователя.
"""

from db.models import STATUS_LABELS, VALID_STATUSES
from keyboards.main_menu import leads_filter_kb, statuses_kb


def _all_buttons(kb):
    return [btn for row in kb.inline_keyboard for btn in row]


def test_leads_filter_kb_has_all_and_every_status():
    kb = leads_filter_kb()
    datas = [b.callback_data for b in _all_buttons(kb)]
    assert "leads:all" in datas
    for status in VALID_STATUSES:
        assert f"leads:{status}" in datas
    assert "leads:no_booking" in datas  # спец-фильтр «без онлайн-записи»
    assert "menu:main" in datas  # кнопка возврата в меню


def test_leads_filter_kb_wraps_rows_by_three():
    kb = leads_filter_kb()
    # ни один ряд не длиннее 3 кнопок (иначе на узком экране обрежется)
    for row in kb.inline_keyboard:
        assert len(row) <= 3


def test_statuses_kb_lists_all_statuses_with_lead_id():
    kb = statuses_kb(42)
    datas = [b.callback_data for b in _all_buttons(kb)]
    for status in STATUS_LABELS:
        assert f"sts:42:{status}" in datas
    assert "lead:42" in datas  # назад к карточке лида
