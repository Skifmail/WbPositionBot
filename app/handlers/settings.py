from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from app.db.base import async_session_factory
from app.db.models import User
from app.data.regions import DISTRICTS

router = Router()


def _settings_kb(user: User) -> InlineKeyboardBuilder:
	kb = InlineKeyboardBuilder()
	kb.button(text=("Отключить автообновление" if user.auto_update_enabled else "Включить автообновление"), callback_data="settings:toggle_auto")
	kb.button(text=f"Устройство: {user.device}", callback_data="settings:device")
	kb.button(text=f"Регион", callback_data="settings:region")
	kb.button(text="Назад", callback_data="menu:back")
	kb.adjust(1)
	return kb


@router.message(F.text == "Настройки")
async def open_settings_by_text(message: Message) -> None:
	async with async_session_factory() as session:
		user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
	await message.answer("Настройки:", reply_markup=_settings_kb(user).as_markup())


@router.callback_query(F.data == "menu:settings")
async def open_settings(cb: CallbackQuery) -> None:
	async with async_session_factory() as session:
		user = await session.scalar(select(User).where(User.telegram_id == cb.from_user.id))
	await cb.message.edit_text("Настройки:", reply_markup=_settings_kb(user).as_markup())
	await cb.answer()


@router.callback_query(F.data == "settings:toggle_auto")
async def toggle_auto(cb: CallbackQuery) -> None:
	async with async_session_factory() as session:
		user = await session.scalar(select(User).where(User.telegram_id == cb.from_user.id))
		user.auto_update_enabled = not user.auto_update_enabled
		await session.commit()
	await open_settings(cb)


@router.callback_query(F.data == "settings:device")
async def choose_device(cb: CallbackQuery) -> None:
	kb = InlineKeyboardBuilder()
	for d in ["pc", "android", "ios", "iphone", "tablet"]:
		kb.button(text=d, callback_data=f"settings:device:{d}")
	kb.button(text="Назад", callback_data="menu:settings")
	kb.adjust(3, 2)
	await cb.message.edit_text("Выберите устройство:", reply_markup=kb.as_markup())
	await cb.answer()


@router.callback_query(F.data.startswith("settings:device:"))
async def set_device(cb: CallbackQuery) -> None:
	device = cb.data.split(":")[-1]
	async with async_session_factory() as session:
		user = await session.scalar(select(User).where(User.telegram_id == cb.from_user.id))
		user.device = device
		await session.commit()
	await open_settings(cb)


@router.callback_query(F.data == "settings:region")
async def choose_district(cb: CallbackQuery) -> None:
	kb = InlineKeyboardBuilder()
	for district in DISTRICTS:
		kb.button(text=district.name, callback_data=f"settings:district:{district.code}")
	kb.button(text="Назад", callback_data="menu:settings")
	kb.adjust(1)
	await cb.message.edit_text("Выберите федеральный округ:", reply_markup=kb.as_markup())
	await cb.answer()


@router.callback_query(F.data.startswith("settings:district:"))
async def choose_city(cb: CallbackQuery) -> None:
	district_code = cb.data.split(":")[-1]
	district = next(d for d in DISTRICTS if d.code == district_code)
	kb = InlineKeyboardBuilder()
	for city in district.cities:
		kb.button(text=city.name, callback_data=f"settings:city:{district.code}:{city.code}")
	kb.button(text="Назад", callback_data="settings:region")
	kb.adjust(1)
	await cb.message.edit_text(f"Округ: {district.name}. Выберите город:", reply_markup=kb.as_markup())
	await cb.answer()


@router.callback_query(F.data.startswith("settings:city:"))
async def set_city(cb: CallbackQuery) -> None:
	_, _, district_code, city_code = cb.data.split(":")
	district = next(d for d in DISTRICTS if d.code == district_code)
	city = next(c for c in district.cities if c.code == city_code)
	async with async_session_factory() as session:
		user = await session.scalar(select(User).where(User.telegram_id == cb.from_user.id))
		user.region_district = district.name
		user.region_city = city.name
		user.dest_code = city.dest
		await session.commit()
	await open_settings(cb)
