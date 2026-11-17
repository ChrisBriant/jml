import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    String,
    Uuid,
    delete,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError

from ..db import AsyncSession, Base
from .enums import UserRole


class SystemUser(Base):
    __tablename__ = "system_users"

    user_id = Column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(
        Enum(UserRole, name="user_role_enum"),
        nullable=False,
        default=UserRole.READER,
        index=True,
    )
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # -----------------------------------------------------------------------
    # Password Hashing Helpers (stdlib PBKDF2-HMAC-SHA256, zero extra deps)
    # -----------------------------------------------------------------------

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a plaintext password using PBKDF2-HMAC-SHA256 with a random salt."""
        if not password or not password.strip():
            raise ValueError("Password cannot be empty")

        iterations = 600_000
        salt = secrets.token_hex(16)
        derived_key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        )
        return f"pbkdf2_sha256${iterations}${salt}${derived_key.hex()}"

    @staticmethod
    def verify_password(plain_password: str, stored_hash: str) -> bool:
        """Verify a plaintext password against a stored PBKDF2-HMAC-SHA256 hash."""
        if not plain_password or not stored_hash:
            return False

        try:
            algorithm, iter_str, salt, expected_hex = stored_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            iterations = int(iter_str)
        except ValueError:
            return False

        derived_key = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        )
        return hmac.compare_digest(derived_key.hex(), expected_hex)

    # -----------------------------------------------------------------------
    # CRUD & Server-Side Management Operations
    # -----------------------------------------------------------------------

    @classmethod
    async def create_one(
        cls,
        db: AsyncSession,
        username: str,
        password: str,
        role: UserRole = UserRole.READER,
        is_active: bool = True,
    ):
        """Create a new system user with a hashed password."""
        normalized_username = username.strip().lower()
        if not normalized_username:
            raise ValueError("Username cannot be empty")

        now = datetime.now(timezone.utc)
        user = cls(
            username=normalized_username,
            password_hash=cls.hash_password(password),
            role=role,
            is_active=is_active,
            created_at=now,
            updated_at=now,
        )

        try:
            db.add(user)
            await db.commit()
            await db.flush()
            await db.refresh(user)
        except IntegrityError as ie:
            print("Error inserting system user", ie)
            await db.rollback()
            return None

        inserted_user = await db.execute(
            select(cls).where(cls.user_id == user.user_id)
        )
        return inserted_user.scalar_one_or_none()

    @classmethod
    async def update_one(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        updates: dict,
    ):
        """Update username, role, or active flag (use reset_password_* for passwords)."""
        user_result = await db.execute(
            select(cls).where(cls.user_id == user_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            return None

        allowed_fields = {
            "username",
            "role",
            "is_active",
        }

        try:
            for field, value in updates.items():
                if field not in allowed_fields:
                    continue

                if field == "username" and isinstance(value, str):
                    value = value.strip().lower()
                    if not value:
                        continue

                if hasattr(user, field):
                    print("UPDATING", field, value)
                    setattr(user, field, value)

            user.updated_at = datetime.now(timezone.utc)

            await db.commit()
            await db.flush()
            await db.refresh(user)
        except IntegrityError as ie:
            print("Error updating system user", ie)
            await db.rollback()
            return None

        updated_user = await db.execute(
            select(cls).where(cls.user_id == user_id)
        )
        return updated_user.scalar_one_or_none()

    @classmethod
    async def update_role(
        cls,
        db: AsyncSession,
        username: str,
        role: UserRole,
    ):
        """Change a system user's role by username."""
        user = await cls.get_by_username(db, username)
        if user is None:
            return None

        return await cls.update_one(
            db=db,
            user_id=user.user_id,
            updates={"role": role},
        )

    @classmethod
    async def set_active_status(
        cls,
        db: AsyncSession,
        username: str,
        is_active: bool,
    ):
        """Enable or disable a system user by username."""
        user = await cls.get_by_username(db, username)
        if user is None:
            return None

        return await cls.update_one(
            db=db,
            user_id=user.user_id,
            updates={"is_active": is_active},
        )

    @classmethod
    async def reset_password_by_id(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        new_password: str,
    ):
        """Reset a system user's password by user_id (server-side administration)."""
        user_result = await db.execute(
            select(cls).where(cls.user_id == user_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            return None

        new_hash = cls.hash_password(new_password)

        try:
            user.password_hash = new_hash
            user.updated_at = datetime.now(timezone.utc)

            await db.commit()
            await db.flush()
            await db.refresh(user)
        except IntegrityError as ie:
            print("Error resetting password", ie)
            await db.rollback()
            return None

        updated_user = await db.execute(
            select(cls).where(cls.user_id == user_id)
        )
        return updated_user.scalar_one_or_none()

    @classmethod
    async def reset_password_by_username(
        cls,
        db: AsyncSession,
        username: str,
        new_password: str,
    ):
        """Reset a system user's password by username (server-side administration)."""
        user = await cls.get_by_username(db, username)
        if user is None:
            return None

        return await cls.reset_password_by_id(
            db=db,
            user_id=user.user_id,
            new_password=new_password,
        )

    @classmethod
    async def change_password(
        cls,
        db: AsyncSession,
        username: str,
        current_password: str,
        new_password: str,
    ):
        """Verify the current password before setting a new password."""
        user = await cls.get_by_username(db, username)
        if user is None:
            return None

        if not cls.verify_password(current_password, user.password_hash):
            return None

        return await cls.reset_password_by_id(
            db=db,
            user_id=user.user_id,
            new_password=new_password,
        )

    @classmethod
    async def authenticate(
        cls,
        db: AsyncSession,
        username: str,
        password: str,
    ):
        """Authenticate an active system user by username and password."""
        user = await cls.get_by_username(db, username)
        if user is None or not user.is_active:
            return None

        if not cls.verify_password(password, user.password_hash):
            return None

        return user

    @classmethod
    async def delete_by_id(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
    ):
        result = await db.execute(
            delete(cls).where(cls.user_id == user_id)
        )
        await db.commit()

        if result.rowcount > 0:
            return True
        else:
            return False

    @classmethod
    async def delete_by_username(
        cls,
        db: AsyncSession,
        username: str,
    ):
        normalized_username = username.strip().lower()
        result = await db.execute(
            delete(cls).where(cls.username == normalized_username)
        )
        await db.commit()

        if result.rowcount > 0:
            return True
        else:
            return False

    @classmethod
    async def get_by_id(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
    ):
        """Retrieve a system user by ID."""
        result = await db.execute(
            select(cls).where(cls.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_username(
        cls,
        db: AsyncSession,
        username: str,
    ):
        """Retrieve a system user by username."""
        normalized_username = username.strip().lower()
        result = await db.execute(
            select(cls).where(cls.username == normalized_username)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_role(
        cls,
        db: AsyncSession,
        role: UserRole,
    ):
        """Retrieve all system users with a given role."""
        result = await db.execute(
            select(cls).where(cls.role == role)
        )
        return result.scalars().all()

    @classmethod
    async def get_all(cls, db: AsyncSession):
        """Get all system users."""
        result = await db.execute(select(cls))
        return result.scalars().all()

    @classmethod
    async def get_all_paginated(
        cls,
        db: AsyncSession,
        page: int = 1,
        page_size: int = 10,
    ):
        """Get all system users paginated."""
        total_result = await db.execute(
            select(func.count()).select_from(cls)
        )
        total = total_result.scalar_one()

        offset = (page - 1) * page_size

        result = await db.execute(
            select(cls)
            .offset(offset)
            .limit(page_size)
        )

        return result.scalars().all(), total