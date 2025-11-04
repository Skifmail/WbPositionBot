"""Модуль состояний FSM (Finite State Machine) для диалогов бота.

Определяет состояния для многошаговых диалогов при добавлении артикулов
и настройке отслеживания фраз.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AddArticle(StatesGroup):
    """Состояния для процесса добавления нового артикула.

    Attributes:
        waiting_for_sku: Ожидание ввода номера артикула (SKU) от пользователя.
    """

    waiting_for_sku = State()


class AddTracking(StatesGroup):
    """Состояния для процесса добавления отслеживания поисковых фраз.

    Attributes:
        waiting_for_phrase: Ожидание ввода поисковой фразы.
        waiting_for_threshold: Ожидание ввода порога позиции для конкретной фразы.
        waiting_for_default_threshold: Ожидание ввода порога по умолчанию для всех фраз.
    """

    waiting_for_phrase = State()
    waiting_for_threshold = State()
    waiting_for_default_threshold = State()
