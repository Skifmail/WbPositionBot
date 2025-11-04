"""Модели базы данных для хранения пользователей, артикулов и отслеживания.

Определяет ORM модели SQLAlchemy для хранения информации о пользователях бота,
их артикулах Wildberries и настройках отслеживания поисковых фраз.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    """Модель пользователя Telegram бота.

    Хранит настройки пользователя: регион, устройство, флаг автообновления.

    Attributes:
        id: Уникальный идентификатор пользователя в базе данных.
        telegram_id: ID пользователя в Telegram.
        auto_update_enabled: Флаг включения автоматического отслеживания.
        device: Тип устройства для поиска (pc/android/ios).
        region_district: Название федерального округа.
        region_city: Название города.
        dest_code: Код региона Wildberries для API запросов.
        created_at: Дата и время регистрации пользователя.
        articles: Список артикулов пользователя.
    """

    __tablename__ = "users"
    __table_args__ = {"schema": "wbpos"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    auto_update_enabled: Mapped[bool] = mapped_column(default=True)
    device: Mapped[str] = mapped_column(String(32), default="pc")
    region_district: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    region_city: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dest_code: Mapped[Optional[int]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    articles: Mapped[list[Article]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )


class Article(Base):
    """Модель артикула товара Wildberries.

    Хранит информацию о товаре пользователя, который нужно отслеживать.

    Attributes:
        id: Уникальный идентификатор артикула в базе данных.
        user_id: ID пользователя-владельца артикула.
        sku: Номер артикула (SKU) на Wildberries.
        title: Название товара (опционально).
        created_at: Дата и время добавления артикула.
        user: Владелец артикула.
        trackings: Список отслеживаемых поисковых фраз для этого артикула.
    """

    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("user_id", "sku", name="uq_user_sku"),
        {"schema": "wbpos"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("wbpos.users.id", ondelete="CASCADE")
    )
    sku: Mapped[int] = mapped_column(index=True)
    title: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="articles")
    trackings: Mapped[list[Tracking]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan"
    )


class Tracking(Base):
    """Модель отслеживания позиции артикула по поисковой фразе.

    Хранит настройки и историю отслеживания позиций конкретного артикула
    по заданной поисковой фразе.

    Attributes:
        id: Уникальный идентификатор записи отслеживания.
        article_id: ID артикула, который отслеживается.
        phrase: Поисковая фраза для отслеживания.
        threshold_position: Пороговая позиция для уведомлений.
        last_position: Последняя найденная позиция.
        last_checked_at: Дата и время последней проверки.
        last_notified_position: Позиция, о которой было отправлено последнее уведомление.
        enabled: Флаг активности отслеживания.
        article: Связанный артикул.
    """

    __tablename__ = "trackings"
    __table_args__ = (
        UniqueConstraint("article_id", "phrase", name="uq_article_phrase"),
        {"schema": "wbpos"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("wbpos.articles.id", ondelete="CASCADE")
    )
    phrase: Mapped[str] = mapped_column(String(256))
    threshold_position: Mapped[int] = mapped_column(default=20)
    last_position: Mapped[Optional[int]] = mapped_column(nullable=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_notified_position: Mapped[Optional[int]] = mapped_column(nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)

    article: Mapped[Article] = relationship(back_populates="trackings")
