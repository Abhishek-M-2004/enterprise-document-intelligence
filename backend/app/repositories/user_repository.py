"""User repository managing database operations for user accounts."""

from typing import Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    """Encapsulates data access for User entities."""

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: UUID) -> Optional[User]:
        """Retrieve a user by their unique primary key."""
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_by_email(db: AsyncSession, email: str) -> Optional[User]:
        """Retrieve a user by normalized lowercase email address."""
        normalized_email = email.strip().lower()
        stmt = select(User).where(User.email == normalized_email)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def create(db: AsyncSession, user: User) -> User:
        """Persist a new user to the database."""
        db.add(user)
        await db.flush()
        return user

    @staticmethod
    async def update(db: AsyncSession, user: User) -> User:
        """Flush changes on an existing user."""
        await db.flush()
        return user
