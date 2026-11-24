import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    String,
    Text,
    Uuid,
    delete,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError

from ..db import AsyncSession, Base


class IGAAudit(Base):
    __tablename__ = "iga_audit"

    audit_id = Column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    entity_type = Column(
        String,
        nullable=False,
        index=True,
    )
    entity_id = Column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    action = Column(
        String,
        nullable=False,
        index=True,
    )
    description = Column(Text, nullable=False)
    actor = Column(
        String,
        nullable=True,
        default="SYSTEM",
    )
    target_system = Column(
        String,
        nullable=True,
        index=True,
    )
    details = Column(JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    @classmethod
    async def create_one(
        cls,
        db: AsyncSession,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        description: str,
        actor: Optional[str] = "SYSTEM",
        target_system: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        audit_entry = cls(
            entity_type=entity_type.strip().upper(),
            entity_id=entity_id,
            action=action.strip().upper(),
            description=description,
            actor=actor,
            target_system=target_system.strip().upper() if target_system else None,
            details=details,
            created_at=datetime.now(timezone.utc),
        )

        try:
            db.add(audit_entry)
            await db.commit()
            await db.flush()
            await db.refresh(audit_entry)
        except IntegrityError as ie:
            print("Error inserting IGA audit entry", ie)
            await db.rollback()
            return None

        inserted_entry = await db.execute(
            select(cls).where(cls.audit_id == audit_entry.audit_id)
        )
        return inserted_entry.scalar_one_or_none()

    @classmethod
    async def delete_by_id(
        cls,
        db: AsyncSession,
        audit_id: uuid.UUID,
    ):
        result = await db.execute(
            delete(cls).where(cls.audit_id == audit_id)
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
        audit_id: uuid.UUID,
    ):
        """Retrieve an audit entry by ID."""
        result = await db.execute(
            select(cls).where(cls.audit_id == audit_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_entity(
        cls,
        db: AsyncSession,
        entity_type: str,
        entity_id: uuid.UUID,
    ):
        """Retrieve the full audit trail for a specific entity, newest first."""
        result = await db.execute(
            select(cls)
            .where(
                cls.entity_type == entity_type.strip().upper(),
                cls.entity_id == entity_id,
            )
            .order_by(cls.created_at.desc())
        )
        return result.scalars().all()

    @classmethod
    async def get_by_action(
        cls,
        db: AsyncSession,
        action: str,
        limit: int = 100,
    ):
        """Retrieve recent audit entries for a given action (e.g. JOINER_DETECTED, SYNC_FAILED)."""
        result = await db.execute(
            select(cls)
            .where(cls.action == action.strip().upper())
            .order_by(cls.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    @classmethod
    async def get_recent(
        cls,
        db: AsyncSession,
        limit: int = 50,
    ):
        """Retrieve the most recent audit events across the IGA system."""
        result = await db.execute(
            select(cls)
            .order_by(cls.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    @classmethod
    async def get_all(cls, db: AsyncSession):
        """Get all audit entries."""
        result = await db.execute(
            select(cls).order_by(cls.created_at.desc())
        )
        return result.scalars().all()

    @classmethod
    async def get_all_paginated(
        cls,
        db: AsyncSession,
        page: int = 1,
        page_size: int = 10,
    ):
        """Get all audit entries paginated."""
        total_result = await db.execute(
            select(func.count()).select_from(cls)
        )
        total = total_result.scalar_one()

        offset = (page - 1) * page_size

        result = await db.execute(
            select(cls)
            .order_by(cls.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )

        return result.scalars().all(), total