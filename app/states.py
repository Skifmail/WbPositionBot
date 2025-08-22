from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AddArticle(StatesGroup):
	waiting_for_sku = State()


class AddTracking(StatesGroup):
	waiting_for_phrase = State()
	waiting_for_threshold = State()
	waiting_for_default_threshold = State()
