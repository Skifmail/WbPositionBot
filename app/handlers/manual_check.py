"""Обработчики ручной проверки позиций товаров."""

from __future__ import annotations

import asyncio
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from app.db.base import async_session_factory
from app.db.models import User, Article, Tracking
from app.services.wb_client import WBClient

router = Router()


def _manual_kb(articles: list[Article]) -> InlineKeyboardBuilder:
    """Создаёт клавиатуру для ручной проверки позиций.

    Args:
        articles: Список артикулов пользователя.

    Returns:
        Клавиатура с кнопками артикулов и общей проверки.
    """
    kb = InlineKeyboardBuilder()
    for a in articles:
        kb.button(text=f"📦 {a.sku}", callback_data=f"manual:one:{a.id}")
    kb.button(text="🧾 Все артикулы", callback_data="manual:all")
    kb.button(text="⬅️ Назад", callback_data="menu:back")
    kb.adjust(2, 1, 1)
    return kb


async def _ensure_user_by_id(telegram_id: int) -> User:
    """Получает пользователя из БД, создаёт если отсутствует.

    Args:
        telegram_id: Telegram ID пользователя.

    Returns:
        Объект User из БД.
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


async def _get_positions_for_phrases(
    client: WBClient,
    *,
    sku: int,
    device: str,
    dest: int,
    phrases: list[str],
    semaphore: asyncio.Semaphore
) -> list[tuple[str, int | None]]:
    """Получает позиции товара по списку фраз параллельно.

    Args:
        client: Экземпляр WB-клиента.
        sku: SKU товара.
        device: Тип устройства ('mobile' / 'desktop').
        dest: Код региона доставки.
        phrases: Список поисковых фраз.
        semaphore: Семафор для ограничения конкуренции.

    Returns:
        Список кортежей (фраза, позиция). Позиция None, если не найдено.
    """
    async def one(phrase: str) -> tuple[str, int | None]:
        async with semaphore:
            pos = await client.get_product_position(
                sku=sku, query=phrase, device=device, dest=dest
            )
            return phrase, pos
    return await asyncio.gather(*(one(p) for p in phrases))


@router.message(F.text.endswith("Проверить позиции"))
async def open_manual_by_text(message: Message) -> None:
    """Открывает меню ручной проверки позиций из главного меню по тексту.

    Args:
        message: Сообщение с текстом кнопки.
    """
    user = await _ensure_user_by_id(message.from_user.id)
    async with async_session_factory() as session:
        articles = await session.scalars(
            select(Article)
            .where(Article.user_id == user.id)
            .order_by(Article.id.asc())
        )
        article_list = list(articles)
    await message.answer(
        "Проверка текущих позиций:",
        reply_markup=_manual_kb(article_list).as_markup()
    )


@router.callback_query(F.data == "menu:manual_check")
async def open_manual(cb: CallbackQuery) -> None:
    """Открывает меню ручной проверки позиций из главного меню по callback.

    Args:
        cb: Callback query пользователя.
    """
    user = await _ensure_user_by_id(cb.from_user.id)
    async with async_session_factory() as session:
        articles = await session.scalars(
            select(Article)
            .where(Article.user_id == user.id)
            .order_by(Article.id.asc())
        )
        article_list = list(articles)
    await cb.message.edit_text(
        "Проверка текущих позиций:",
        reply_markup=_manual_kb(article_list).as_markup()
    )
    await cb.answer()


@router.callback_query(F.data.startswith("manual:one:"))
async def check_one(cb: CallbackQuery) -> None:
    """Проверяет позиции одного артикула по всем фразам.

    Args:
        cb: Callback query с ID артикула.
    """
    await cb.answer("Проверяю...", show_alert=False)
    article_id = int(cb.data.split(":")[-1])
    async with async_session_factory() as session:
        row = await session.execute(
            select(
                Article.sku,
                User.device,
                User.dest_code,
                User.auto_update_enabled,
                User.region_city,
                User.region_district
            )
            .join(User, Article.user_id == User.id)
            .where(Article.id == article_id, User.telegram_id == cb.from_user.id)
        )
        res = row.first()
        if not res:
            await cb.message.edit_text("Не найдено")
            return
        sku, device, dest, auto_update_enabled, region_city, region_district = res
        phrases = list(
            (await session.scalars(
                select(Tracking.phrase).where(Tracking.article_id == article_id)
            )).all()
        )
    async with WBClient() as client:
        name, _, page_url = await client.get_product_preview(
            sku=sku, device=device, dest=dest or -1257786
        )
        progress = await cb.message.answer(
            f"Ищу позиции для {sku}... 0/{len(phrases)}"
        )
        sem = asyncio.Semaphore(6)
        results: list[tuple[str, int | None]] = []
        for idx, item in enumerate(
            await _get_positions_for_phrases(
                client,
                sku=sku,
                device=device,
                dest=dest or -1257786,
                phrases=phrases,
                semaphore=sem
            ),
            start=1
        ):
            results.append(item)
            try:
                await progress.edit_text(
                    f"Ищу позиции для {sku}... {idx}/{len(phrases)}"
                )
            except Exception:
                pass
        lines = [
            f"{phrase}: {pos if pos is not None else '—'}"
            for phrase, pos in results
        ]
        region = region_city or region_district or "Не выбран"
        status = (
            f"\n\n⚙️ Устройство: <b>{device}</b> | "
            f"🗺️ Регион: <b>{region}</b> | "
            f"🔁 Автообновление: <b>"
            f"{'Включено' if auto_update_enabled else 'Отключено'}</b>"
        )
        caption = (
            (name or f"Артикул {sku}") +
            f"\n" + "\n".join(lines) +
            f"\n\nСсылка: {page_url}" + status
        )
        # сначала текст
        msg = await cb.message.answer(caption)
        # пробуем быстро подгрузить картинку отдельно
        img_bytes = await client.fetch_image_bytes_for_sku(sku)
        if img_bytes:
            try:
                await msg.delete()
            except Exception:
                pass
            await cb.message.answer_photo(photo=img_bytes, caption=caption)
    try:
        await cb.message.delete()
    except Exception:
        pass
    try:
        await progress.delete()
    except Exception:
        pass
    await cb.message.answer("Все позиции найдены")


@router.callback_query(F.data == "manual:all")
async def check_all(cb: CallbackQuery) -> None:
    """Проверяет позиции всех артикулов пользователя параллельно.

    Args:
        cb: Callback query пользователя.
    """
    await cb.answer("Проверяю...", show_alert=False)
    user = await _ensure_user_by_id(cb.from_user.id)
    async with async_session_factory() as session:
        rows = list(
            (await session.execute(
                select(Article.sku, Tracking.phrase).where(
                    Article.user_id == user.id,
                    Tracking.article_id == Article.id
                )
            )).all()
        )
        device = user.device
        dest = user.dest_code or -1257786
        region = user.region_city or user.region_district or "Не выбран"
    sku_to_phrases: dict[int, list[str]] = {}
    for sku, phrase in rows:
        sku_to_phrases.setdefault(int(sku), []).append(phrase)
    total = len(sku_to_phrases)
    try:
        await cb.message.delete()
    except Exception:
        pass
    progress = await cb.message.answer(f"Ищу позиции... 0/{total} артикулов")
    processed = 0
    async with WBClient() as client:
        sem = asyncio.Semaphore(8)

        async def process_sku(sku: int, phrases: list[str]) -> None:
            """Обрабатывает один артикул: получает позиции, формирует отчёт с картинкой."""
            name, _, page_url = await client.get_product_preview(
                sku=sku, device=device, dest=dest
            )
            pairs = await _get_positions_for_phrases(
                client,
                sku=sku,
                device=device,
                dest=dest,
                phrases=phrases,
                semaphore=sem
            )
            lines = [
                f"- {phrase}: {pos if pos is not None else '—'}"
                for phrase, pos in pairs
            ]
            status = (
                f"\n\n⚙️ Устройство: <b>{device}</b> | "
                f"🗺️ Регион: <b>{region}</b> | "
                f"🔁 Автообновление: <b>"
                f"{'Включено' if user.auto_update_enabled else 'Отключено'}</b>"
            )
            caption = (
                f"{sku} — {name or ''}\n" +
                "\n".join(lines) +
                f"\nСсылка: {page_url}" + status
            )
            # сначала текст
            msg = await cb.message.answer(caption)
            img_bytes = await client.fetch_image_bytes_for_sku(sku)
            if img_bytes:
                try:
                    await msg.delete()
                except Exception:
                    pass
                await cb.message.answer_photo(photo=img_bytes, caption=caption)
            nonlocal processed
            processed += 1
            try:
                await progress.edit_text(
                    f"Ищу позиции... {processed}/{total} артикулов"
                )
            except Exception:
                pass

        await asyncio.gather(
            *(process_sku(s, p) for s, p in sku_to_phrases.items())
        )
    try:
        await progress.edit_text(f"Готово: {processed}/{total} артикулов")
    except Exception:
        pass
    await cb.message.answer("Все позиции найдены")
