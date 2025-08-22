from __future__ import annotations

import asyncio
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func

from app.db.base import async_session_factory
from app.db.models import Tracking, Article, User
from app.services.wb_client import WBClient
from app.states import AddTracking

router = Router()


async def _get_positions_for_phrases(client: WBClient, *, sku: int, device: str, dest: int, phrases: list[str], semaphore: asyncio.Semaphore) -> list[tuple[str, int | None]]:
	async def one(phrase: str) -> tuple[str, int | None]:
		async with semaphore:
			pos = await client.get_product_position(sku=sku, query=phrase, device=device, dest=dest)
			return phrase, pos
	return await asyncio.gather(*(one(p) for p in phrases))


async def _render_trackings_for_article(message: Message, article_id: int) -> None:
	async with async_session_factory() as session:
		trackings = list((await session.scalars(select(Tracking).where(Tracking.article_id == article_id).order_by(Tracking.id.asc()))).all())
		kb = InlineKeyboardBuilder()
		for t in trackings:
			kb.button(text=f"{t.phrase} (≤{t.threshold_position})", callback_data=f"tracking:edit:{t.id}")
		kb.button(text="Добавить", callback_data=f"tracking:add:{article_id}")
		kb.button(text="Назад", callback_data=f"article:{article_id}")
		kb.adjust(1)
		text = "Список фраз:" if trackings else "Фраз пока нет."
	await message.edit_text(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("tracking:list:"))
async def list_trackings(cb: CallbackQuery) -> None:
	article_id = int(cb.data.split(":")[-1])
	await _render_trackings_for_article(cb.message, article_id)
	await cb.answer()


@router.callback_query(F.data.startswith("tracking:add:"))
async def ask_add_phrase(cb: CallbackQuery, state: FSMContext) -> None:
	article_id = int(cb.data.split(":")[-1])
	await state.set_state(AddTracking.waiting_for_phrase)
	await state.update_data(article_id=article_id)
	await cb.message.edit_text("Введите фразу(ы). Можно несколько: через запятую или с новой строки.\nТакже можно указать порог сразу: 'фраза=число'.")
	await cb.answer()


def _parse_bulk_phrases(text: str) -> list[tuple[str, int | None]]:
	raw = [part.strip() for line in text.splitlines() for part in line.split(",")]
	pairs: list[tuple[str, int | None]] = []
	for item in raw:
		if not item:
			continue
		if "=" in item:
			phrase, th = item.split("=", 1)
			phrase = phrase.strip()
			try:
				threshold = int(th.strip())
			except ValueError:
				threshold = None
			pairs.append((phrase, threshold))
		else:
			pairs.append((item, None))
	return pairs


@router.message(AddTracking.waiting_for_phrase, F.text & ~F.via_bot)
async def handle_phrase_input(message: Message, state: FSMContext) -> None:
	pairs = _parse_bulk_phrases(message.text or "")
	if not pairs:
		await message.answer("Пустой ввод. Повторите ввод фраз.")
		return
	await state.update_data(pairs=pairs)
	need_default = any(th is None for _, th in pairs)
	if need_default:
		await state.set_state(AddTracking.waiting_for_default_threshold)
		await message.answer("Введите общий порог (позиция, число) для фраз без порога:")
		return
	# Все фразы имеют пороги — сразу записываем
	data = await state.get_data()
	article_id: int = int(data["article_id"])  # type: ignore[index]
	async with async_session_factory() as session:
		article = await session.scalar(
			select(Article).join(User, Article.user_id == User.id).where(
				Article.id == article_id,
				User.telegram_id == message.from_user.id,
			)
		)
		if article is None:
			await state.clear()
			await message.answer("Артикул не найден или уже удалён.")
			return
		existing = set((await session.scalars(select(Tracking.phrase).where(Tracking.article_id == article.id))).all())
		for phrase, th in pairs:
			if phrase in existing:
				continue
			session.add(Tracking(article_id=article.id, phrase=phrase, threshold_position=th if th is not None else 20))
		await session.commit()
	await state.clear()
	await message.answer("Фразы добавлены.")


@router.message(AddTracking.waiting_for_default_threshold, F.text.regexp(r"^\d{1,4}$"))
async def set_default_threshold_for_bulk(message: Message, state: FSMContext) -> None:
	default_th = int(message.text)
	data = await state.get_data()
	article_id: int = int(data["article_id"])  # type: ignore[index]
	pairs: list[tuple[str, int | None]] = data.get("pairs", [])  # type: ignore[assignment]
	async with async_session_factory() as session:
		article = await session.scalar(
			select(Article).join(User, Article.user_id == User.id).where(
				Article.id == article_id,
				User.telegram_id == message.from_user.id,
			)
		)
		if article is None:
			await state.clear()
			await message.answer("Артикул не найден или уже удалён.")
			return
		existing = set((await session.scalars(select(Tracking.phrase).where(Tracking.article_id == article.id))).all())
		for phrase, th in pairs:
			if phrase in existing:
				continue
			threshold = th if th is not None else default_th
			session.add(Tracking(article_id=article.id, phrase=phrase, threshold_position=threshold))
		await session.commit()
	await state.clear()
	await message.answer("Фразы добавлены.")


@router.callback_query(F.data.startswith("tracking:edit:"))
async def edit_tracking(cb: CallbackQuery) -> None:
	tracking_id = int(cb.data.split(":")[-1])
	async with async_session_factory() as session:
		tracking = await session.get(Tracking, tracking_id)
		kb = InlineKeyboardBuilder()
		kb.button(text="Вкл/Выкл", callback_data=f"tracking:toggle:{tracking.id}")
		kb.button(text="Изм. порог", callback_data=f"tracking:th:{tracking.id}")
		kb.button(text="Удалить", callback_data=f"tracking:del:{tracking.id}")
		kb.button(text="Назад", callback_data=f"tracking:list:{tracking.article_id}")
		kb.adjust(2, 2)
		text = f"Фраза: {tracking.phrase}\nПорог: {tracking.threshold_position}\nСтатус: {'Вкл' if tracking.enabled else 'Выкл'}"
	await cb.message.edit_text(text, reply_markup=kb.as_markup())
	await cb.answer()


@router.callback_query(F.data.startswith("tracking:toggle:"))
async def toggle_tracking(cb: CallbackQuery) -> None:
	tracking_id = int(cb.data.split(":")[-1])
	async with async_session_factory() as session:
		tracking = await session.get(Tracking, tracking_id)
		tracking.enabled = not tracking.enabled
		await session.commit()
	await edit_tracking(cb)


@router.callback_query(F.data.startswith("tracking:th:"))
async def ask_new_threshold(cb: CallbackQuery, state: FSMContext) -> None:
	tracking_id = int(cb.data.split(":")[-1])
	await state.set_state(AddTracking.waiting_for_threshold)
	await state.update_data(tracking_id=tracking_id)
	await cb.message.edit_text(f"Введите новый порог для ID {tracking_id}:")
	await cb.answer()


@router.message(AddTracking.waiting_for_threshold, F.text.regexp(r"^\d{1,4}$"))
async def set_threshold_on_specific(message: Message, state: FSMContext) -> None:
	value = int(message.text)
	data = await state.get_data()
	tracking_id: int = int(data.get("tracking_id", 0))
	if not tracking_id:
		await state.clear()
		await message.answer("Не удалось определить фразу. Откройте меню артикула.")
		return
	async with async_session_factory() as session:
		tracking = await session.get(Tracking, tracking_id)
		if not tracking:
			await state.clear()
			await message.answer("Фраза не найдена.")
			return
		tracking.threshold_position = value
		await session.commit()
	await state.clear()
	await message.answer("Порог обновлён.")


@router.message(F.text.regexp(r"^th:\d+:\d+$"))
async def set_threshold_direct(message: Message) -> None:
	_, tid, val = message.text.split(":")
	tracking_id = int(tid)
	value = int(val)
	async with async_session_factory() as session:
		tracking = await session.get(Tracking, tracking_id)
		if tracking is None:
			await message.answer("Не найдено")
			return
		tracking.threshold_position = value
		await session.commit()
	await message.answer("Порог обновлён")


@router.callback_query(F.data.startswith("tracking:del:"))
async def delete_tracking(cb: CallbackQuery) -> None:
	tracking_id = int(cb.data.split(":")[-1])
	async with async_session_factory() as session:
		tracking = await session.get(Tracking, tracking_id)
		article_id = tracking.article_id if tracking else None
		if tracking:
			await session.delete(tracking)
			await session.commit()
	await cb.answer("Удалено")
	if article_id:
		await _render_trackings_for_article(cb.message, article_id)


@router.callback_query(F.data.startswith("tracking:check:"))
async def check_article(cb: CallbackQuery) -> None:
	article_id = int(cb.data.split(":")[-1])
	async with async_session_factory() as session:
		row = await session.execute(select(Article.sku, User.device, User.dest_code).join(User, Article.user_id == User.id).where(Article.id == article_id, User.telegram_id == cb.from_user.id))
		res = row.first()
		if not res:
			await cb.answer("Не найдено", show_alert=True)
			return
		sku, device, dest = res
		phrases = list((await session.scalars(select(Tracking.phrase).where(Tracking.article_id == article_id))).all())
	async with WBClient() as client:
		pairs = await _get_positions_for_phrases(client, sku=sku, device=device, dest=dest or -1257786, phrases=phrases, semaphore=asyncio.Semaphore(6))
	lines = [f"{phrase}: {pos if pos is not None else '—'}" for phrase, pos in pairs]
	await cb.message.edit_text("\n".join(lines) if lines else "Нет фраз.")
	await cb.answer()
