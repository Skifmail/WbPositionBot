"""Обработчики главного меню и команды /start.

Содержит обработчики для стартовой команды, отображения главного меню,
отмены операций и возврата в главное меню.
"""

from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from sqlalchemy import select, func

from app.db.base import async_session_factory
from app.db.models import User, Article

router = Router()


def _main_menu_kb() -> InlineKeyboardBuilder:
    """Создаёт инлайн-клавиатуру главного меню.

    Returns:
        Инлайн-клавиатура с кнопками для основных разделов.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Артикулы", callback_data="menu:articles")
    kb.button(text="🔎 Проверить позиции", callback_data="menu:manual_check")
    kb.button(text="⚙️ Настройки", callback_data="menu:settings")
    kb.adjust(1)
    return kb


def main_reply_kb():
    """Создаёт постоянную клавиатуру главного меню.

    Returns:
        Reply-клавиатура с основными разделами бота.
    """
    kb = ReplyKeyboardBuilder()
    kb.button(text="📦 Артикулы")
    kb.button(text="🔎 Проверить позиции")
    kb.button(text="⚙️ Настройки")
    kb.adjust(2, 1)
    return kb.as_markup(resize_keyboard=True, is_persistent=True)


async def _ensure_user(telegram_id: int) -> None:
    """Создаёт пользователя в БД, если его ещё нет.

    Args:
        telegram_id: ID пользователя в Telegram.
    """
    async with async_session_factory() as session:
        res = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = res.scalar_one_or_none()
        if user is None:
            user = User(telegram_id=telegram_id)
            session.add(user)
            await session.commit()


def _info_text(
    *,
    auto_update_enabled: bool,
    region: str,
    device: str,
    articles_count: int
) -> str:
    """Формирует информационный текст для главного меню.

    Args:
        auto_update_enabled: Включено ли автообновление.
        region: Название региона пользователя.
        device: Тип устройства.
        articles_count: Количество отслеживаемых артикулов.

    Returns:
        HTML-форматированный текст с информацией о настройках.
    """
    status = "Включено" if auto_update_enabled else "Отключено"
    lines = [
        "<b>WB Position Bot</b>",
        "",
        f"Автообновление: <b>{status}</b>",
        f"Регион: <b>{region or 'Не выбран'}</b>",
        f"Устройство: <b>{device}</b>",
        f"Отслеживаемых артикулов: <b>{articles_count}</b>",
    ]
    if not region:
        lines.append(
            "\n⚠️ Рекомендуем настроить регион и устройство в разделе "
            "<b>⚙️ Настройки</b> перед проверкой позиций."
        )
    return "\n".join(lines)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Обработчик команды /start.

    Отображает главное меню с информацией о настройках пользователя
    и количестве отслеживаемых артикулов.

    Args:
        message: Входящее сообщение от пользователя.
    """
    await _ensure_user(message.from_user.id)
    async with async_session_factory() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        articles_count = await session.scalar(
            select(func.count(Article.id)).where(Article.user_id == user.id)
        )
        info = _info_text(
            auto_update_enabled=user.auto_update_enabled,
            region=user.region_city or user.region_district or "",
            device=user.device,
            articles_count=int(articles_count or 0),
        )
    await message.answer(info, reply_markup=main_reply_kb())


@router.message(F.text.endswith("cancel"))
@router.message(F.text.endswith("/cancel"))
@router.message(Command("cancel"))
async def cmd_cancel(message: Message) -> None:
    """Обработчик команды отмены текущей операции.

    Возвращает пользователя в главное меню и очищает состояние FSM.

    Args:
        message: Входящее сообщение от пользователя.
    """
    await message.answer("Отменено.", reply_markup=main_reply_kb())


@router.message(F.text.endswith("Назад"))
@router.callback_query(F.data == "menu:back")
async def back_to_menu(cb_or_msg):
    """Обработчик возврата в главное меню.

    Работает как с текстовыми сообщениями ("Назад"), так и с callback-кнопками.
    Отображает главное меню с актуальной информацией.

    Args:
        cb_or_msg: CallbackQuery или Message от пользователя.
    """
    # Унифицируем обработку для callback и message
    if isinstance(cb_or_msg, CallbackQuery):
        cb = cb_or_msg
        async with async_session_factory() as session:
            user = await session.scalar(
                select(User).where(User.telegram_id == cb.from_user.id)
            )
            articles_count = await session.scalar(
                select(func.count(Article.id)).where(Article.user_id == user.id)
            )
            info = _info_text(
                auto_update_enabled=user.auto_update_enabled,
                region=user.region_city or user.region_district or "",
                device=user.device,
                articles_count=int(articles_count or 0),
            )
        try:
            await cb.message.edit_text(info)
        except Exception:
            await cb.message.answer(info)
        finally:
            try:
                await cb.answer()
            except Exception:
                pass
    else:
        message = cb_or_msg
        await cmd_start(message)
