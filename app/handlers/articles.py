"""Обработчики управления артикулами товаров.

Содержит обработчики для добавления, удаления, просмотра артикулов
и настройки отслеживания поисковых фраз.
"""

from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from app.db.base import async_session_factory
from app.db.models import User, Article
from app.services.wb_client import WBClient
from app.states import AddArticle, AddTracking

router = Router()


def _articles_menu_kb(articles: list[Article]) -> InlineKeyboardBuilder:
    """Создаёт клавиатуру меню управления артикулами.

    Args:
        articles: Список артикулов пользователя.

    Returns:
        Клавиатура с кнопками для каждого артикула и управления.
    """
    kb = InlineKeyboardBuilder()
    for a in articles:
        kb.button(text=f"📦 {a.sku}", callback_data=f"article:{a.id}")
    kb.button(text="➕ Добавить", callback_data="article:add")
    kb.button(text="🗑️ Удалить", callback_data="article:delete")
    kb.button(text="🧾 Все позиции", callback_data="article:check_all")
    kb.button(text="⬅️ Назад", callback_data="menu:back")
    kb.adjust(2, 2, 1, 1)
    return kb


async def _ensure_user_by_id(telegram_id: int) -> User:
    """Получает или создаёт пользователя по Telegram ID.

    Args:
        telegram_id: ID пользователя в Telegram.

    Returns:
        Объект пользователя из БД.
    """
    async with async_session_factory() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == telegram_id)
        )
        if user is None:
            user = User(telegram_id=telegram_id)
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user


@router.message(F.text.endswith("Артикулы"))
async def open_articles_by_text(message: Message) -> None:
    """Открывает меню артикулов по текстовой команде.

    Args:
        message: Входящее сообщение от пользователя.
    """
    user = await _ensure_user_by_id(message.from_user.id)
    async with async_session_factory() as session:
        articles = list(
            (await session.scalars(
                select(Article).where(Article.user_id == user.id)
            )).all()
        )
    await message.answer(
        "Управление артикулами:",
        reply_markup=_articles_menu_kb(articles).as_markup()
    )


@router.callback_query(F.data == "menu:articles")
async def open_articles(cb: CallbackQuery) -> None:
    """Открывает меню артикулов по callback-кнопке.

    Args:
        cb: Callback query от пользователя.
    """
    user = await _ensure_user_by_id(cb.from_user.id)
    async with async_session_factory() as session:
        articles = list(
            (await session.scalars(
                select(Article).where(Article.user_id == user.id)
            )).all()
        )
    await cb.message.edit_text(
        "Управление артикулами:",
        reply_markup=_articles_menu_kb(articles).as_markup()
    )
    await cb.answer()


@router.callback_query(F.data == "article:add")
async def ask_add_article(cb: CallbackQuery, state: FSMContext) -> None:
    """Запрашивает у пользователя SKU для добавления нового артикула.

    Args:
        cb: Callback query от пользователя.
        state: FSM контекст для сохранения состояния.
    """
    await state.set_state(AddArticle.waiting_for_sku)
    await cb.message.edit_text("Введите артикул (число):")
    await cb.answer()


@router.message(AddArticle.waiting_for_sku, F.text.regexp(r"^\d{4,}$"))
async def add_article_by_text(message: Message, state: FSMContext) -> None:
    """Добавляет новый артикул в БД после ввода SKU.

    Проверяет на дубликаты и запрашивает поисковые фразы для отслеживания.

    Args:
        message: Сообщение пользователя с SKU артикула.
        state: FSM контекст для управления состоянием диалога.
    """
    sku = int(message.text)
    async with async_session_factory() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        dup = await session.scalar(
            select(Article.id).where(
                Article.user_id == user.id,
                Article.sku == sku
            )
        )
        if dup:
            await message.answer("Такой артикул уже добавлен.")
            await state.clear()
            return
        article = Article(user_id=user.id, sku=sku)
        session.add(article)
        await session.flush()
        await session.refresh(article)
        await session.commit()
    # Сразу просим фразы для отслеживания
    await state.set_state(AddTracking.waiting_for_phrase)
    await state.update_data(article_id=article.id)
    await message.answer(
        "✅ Артикул добавлен. Теперь введите фразу(ы) для отслеживания.\n"
        "Можно несколько: через запятую или с новой строки.\n"
        "Можно сразу задать порог: 'фраза=число'."
    )


@router.callback_query(F.data == "article:delete")
async def ask_delete_article(cb: CallbackQuery) -> None:
    """Открывает меню выбора артикула для удаления.

    Args:
        cb: Callback query от пользователя.
    """
    async with async_session_factory() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == cb.from_user.id)
        )
        articles = list(
            (await session.scalars(
                select(Article).where(Article.user_id == user.id)
            )).all()
        )
        kb = InlineKeyboardBuilder()
        for a in articles:
            kb.button(text=f"📦 {a.sku}", callback_data=f"article:del:{a.id}")
        kb.button(text="⬅️ Назад", callback_data="menu:articles")
        kb.adjust(2)
    await cb.message.edit_text(
        "Выберите артикул для удаления:",
        reply_markup=kb.as_markup()
    )
    await cb.answer()


@router.callback_query(F.data.startswith("article:del:"))
async def delete_article(cb: CallbackQuery) -> None:
    """Удаляет выбранный артикул из БД.

    Args:
        cb: Callback query с ID артикула для удаления.
    """
    article_id = int(cb.data.split(":")[-1])
    async with async_session_factory() as session:
        article = await session.get(Article, article_id)
        if article is None:
            await cb.answer("Не найдено", show_alert=True)
            return
        await session.delete(article)
        await session.commit()
    await cb.answer("Удалено")


def _article_kb(article_id: int) -> InlineKeyboardBuilder:
    """Создаёт клавиатуру управления конкретным артикулом.

    Args:
        article_id: ID артикула в БД.

    Returns:
        Клавиатура с действиями для артикула.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить фразу", callback_data=f"tracking:add:{article_id}")
    kb.button(text="📝 Фразы/пороги", callback_data=f"tracking:list:{article_id}")
    kb.button(text="🔎 Проверить", callback_data=f"tracking:check:{article_id}")
    kb.button(text="⬅️ Назад", callback_data="menu:articles")
    kb.adjust(1)
    return kb


@router.callback_query(F.data.startswith("article:"))
async def open_article(cb: CallbackQuery) -> None:
    """Открывает меню управления конкретным артикулом.

    Args:
        cb: Callback query с ID артикула.
    """
    if cb.data in {"article:add", "article:delete", "article:check_all"}:
        return
    article_id = int(cb.data.split(":")[1])
    async with async_session_factory() as session:
        article = await session.get(Article, article_id)
        if not article:
            await cb.answer("Не найдено", show_alert=True)
            return
    await cb.message.edit_text(
        f"Артикул {article.sku}",
        reply_markup=_article_kb(article_id).as_markup()
    )
    await cb.answer()


@router.callback_query(F.data == "article:check_all")
async def check_all_articles(cb: CallbackQuery) -> None:
    """Перенаправляет на проверку всех артикулов через меню ручной проверки.

    Args:
        cb: Callback query от пользователя.
    """
    async with async_session_factory() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == cb.from_user.id)
        )
        pairs = list(
            (await session.execute(
                select(Article.sku).where(Article.user_id == user.id)
            )).all()
        )
        articles = [row[0] for row in pairs]
    await cb.message.edit_text(
        "Выберите пункт 'Проверить позиции' для детальной проверки."
    )
    await cb.answer()
