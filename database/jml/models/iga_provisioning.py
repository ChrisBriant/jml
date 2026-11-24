import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    delete,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError

from ..db import AsyncSession, Base
from .enums import ProvisioningAction, SyncStatus


class IGAProvisioning(Base):
    __tablename__ = "iga_provisioning"
    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity_id",
            "target_system",
            name="uq_iga_provisioning_entity_target",
        ),
    )

    provisioning_id = Column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    entity_type = Column(
        String,
        nullable=False,
        default="USER",
        index=True,
    )
    entity_id = Column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    target_system = Column(
        String,
        nullable=False,
        index=True,
    )
    source_system = Column(
        String,
        nullable=False,
        default="HR_SYSTEM",
        index=True,
    )
    target_id = Column(
        String,
        nullable=True,
        index=True,
    )
    source_id = Column(
        String,
        nullable=True,
        index=True,
    )
    sync_status = Column(
        Enum(SyncStatus, name="iga_sync_status_enum"),
        nullable=False,
        default=SyncStatus.PENDING,
        index=True,
    )
    pending_action = Column(
        Enum(ProvisioningAction, name="iga_provisioning_action_enum"),
        nullable=True,
        index=True,
    )
    retry_count = Column(
        Integer,
        nullable=False,
        default=0,
    )
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
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

    @classmethod
    async def create_one(
        cls,
        db: AsyncSession,
        entity_id: uuid.UUID,
        target_system: str,
        source_system: str = "HR_SYSTEM",
        entity_type: str = "USER",
        target_id: Optional[str] = None,
        source_id: Optional[str] = None,
        sync_status: SyncStatus = SyncStatus.PENDING,
        pending_action: Optional[ProvisioningAction] = ProvisioningAction.JOINER,
        error_message: Optional[str] = None,
    ):
        now = datetime.now(timezone.utc)
        record = cls(
            entity_type=entity_type.strip().upper(),
            entity_id=entity_id,
            target_system=target_system.strip().upper(),
            source_system=source_system.strip().upper(),
            target_id=target_id,
            source_id=str(source_id) if source_id is not None else None,
            sync_status=sync_status,
            pending_action=pending_action,
            retry_count=0,
            error_message=error_message,
            created_at=now,
            updated_at=now,
        )

        try:
            db.add(record)
            await db.commit()
            await db.flush()
            await db.refresh(record)
        except IntegrityError as ie:
            print("Error inserting IGA provisioning record", ie)
            await db.rollback()
            return None

        inserted_record = await db.execute(
            select(cls).where(cls.provisioning_id == record.provisioning_id)
        )
        return inserted_record.scalar_one_or_none()

    @classmethod
    async def upsert_target_state(
        cls,
        db: AsyncSession,
        entity_id: uuid.UUID,
        target_system: str,
        source_system: str = "HR_SYSTEM",
        entity_type: str = "USER",
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        sync_status: SyncStatus = SyncStatus.PENDING,
        pending_action: Optional[ProvisioningAction] = None,
    ):
        """
        Create or update the provisioning record for an (entity_type, entity_id, target_system) tuple.
        Useful when queuing a JOINER/MOVER/LEAVER sync job.
        """
        existing = await cls.get_by_entity_and_target(
            db=db,
            entity_id=entity_id,
            target_system=target_system,
            entity_type=entity_type,
        )

        if existing is None:
            return await cls.create_one(
                db=db,
                entity_id=entity_id,
                target_system=target_system,
                source_system=source_system,
                entity_type=entity_type,
                source_id=source_id,
                target_id=target_id,
                sync_status=sync_status,
                pending_action=pending_action,
            )

        updates = {
            "sync_status": sync_status,
            "error_message": None,
        }
        if pending_action is not None:
            updates["pending_action"] = pending_action
        if source_id is not None:
            updates["source_id"] = str(source_id)
        if target_id is not None:
            updates["target_id"] = target_id

        return await cls.update_one(
            db=db,
            provisioning_id=existing.provisioning_id,
            updates=updates,
        )

    @classmethod
    async def update_one(
        cls,
        db: AsyncSession,
        provisioning_id: uuid.UUID,
        updates: dict,
    ):
        record_result = await db.execute(
            select(cls).where(cls.provisioning_id == provisioning_id)
        )
        record = record_result.scalar_one_or_none()

        if record is None:
            return None

        allowed_fields = {
            "target_id",
            "source_id",
            "sync_status",
            "pending_action",
            "retry_count",
            "last_synced_at",
            "last_attempt_at",
            "error_message",
        }

        try:
            for field, value in updates.items():
                if field not in allowed_fields:
                    continue

                if hasattr(record, field):
                    print("UPDATING", field, value)
                    setattr(record, field, value)

            record.updated_at = datetime.now(timezone.utc)

            await db.commit()
            await db.flush()
            await db.refresh(record)
        except IntegrityError as ie:
            print("Error updating IGA provisioning record", ie)
            await db.rollback()
            return None

        updated_record = await db.execute(
            select(cls).where(cls.provisioning_id == provisioning_id)
        )
        return updated_record.scalar_one_or_none()

    @classmethod
    async def mark_in_progress(
        cls,
        db: AsyncSession,
        provisioning_id: uuid.UUID,
    ):
        """Mark a provisioning job as IN_PROGRESS before calling the target system."""
        now = datetime.now(timezone.utc)
        return await cls.update_one(
            db=db,
            provisioning_id=provisioning_id,
            updates={
                "sync_status": SyncStatus.IN_PROGRESS,
                "last_attempt_at": now,
            },
        )

    @classmethod
    async def mark_synced(
        cls,
        db: AsyncSession,
        provisioning_id: uuid.UUID,
        target_id: Optional[str] = None,
        final_status: SyncStatus = SyncStatus.SYNCED,
    ):
        """Mark provisioning as succeeded, clear error state, and store target_id."""
        now = datetime.now(timezone.utc)
        updates = {
            "sync_status": final_status,
            "pending_action": None,
            "retry_count": 0,
            "last_attempt_at": now,
            "last_synced_at": now,
            "error_message": None,
        }
        if target_id is not None:
            updates["target_id"] = target_id

        return await cls.update_one(
            db=db,
            provisioning_id=provisioning_id,
            updates=updates,
        )

    @classmethod
    async def mark_failed(
        cls,
        db: AsyncSession,
        provisioning_id: uuid.UUID,
        error_message: str,
    ):
        """Mark provisioning as FAILED, increment retry_count, and record error_message."""
        existing = await cls.get_by_id(db, provisioning_id)
        if existing is None:
            return None

        now = datetime.now(timezone.utc)
        return await cls.update_one(
            db=db,
            provisioning_id=provisioning_id,
            updates={
                "sync_status": SyncStatus.FAILED,
                "retry_count": (existing.retry_count or 0) + 1,
                "last_attempt_at": now,
                "error_message": error_message,
            },
        )

    @classmethod
    async def delete_by_id(
        cls,
        db: AsyncSession,
        provisioning_id: uuid.UUID,
    ):
        result = await db.execute(
            delete(cls).where(cls.provisioning_id == provisioning_id)
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
        provisioning_id: uuid.UUID,
    ):
        """Retrieve a provisioning record by ID."""
        result = await db.execute(
            select(cls).where(cls.provisioning_id == provisioning_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_entity(
        cls,
        db: AsyncSession,
        entity_id: uuid.UUID,
        entity_type: str = "USER",
    ):
        """Retrieve all target provisioning states for a given entity."""
        result = await db.execute(
            select(cls).where(
                cls.entity_type == entity_type.strip().upper(),
                cls.entity_id == entity_id,
            )
        )
        return result.scalars().all()

    @classmethod
    async def get_by_entity_and_target(
        cls,
        db: AsyncSession,
        entity_id: uuid.UUID,
        target_system: str,
        entity_type: str = "USER",
    ):
        """Retrieve the provisioning record for a specific entity and target system."""
        result = await db.execute(
            select(cls).where(
                cls.entity_type == entity_type.strip().upper(),
                cls.entity_id == entity_id,
                cls.target_system == target_system.strip().upper(),
            )
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_target_id(
        cls,
        db: AsyncSession,
        target_system: str,
        target_id: str,
    ):
        """Retrieve a provisioning record using the ID on the target system."""
        result = await db.execute(
            select(cls).where(
                cls.target_system == target_system.strip().upper(),
                cls.target_id == target_id,
            )
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_pending_for_target(
        cls,
        db: AsyncSession,
        target_system: str,
        entity_type: Optional[str] = None,
        limit: int = 100,
    ):
        """Fetch PENDING provisioning records queued for a target system."""
        stmt = select(cls).where(
            cls.target_system == target_system.strip().upper(),
            cls.sync_status == SyncStatus.PENDING,
        )
        if entity_type is not None:
            stmt = stmt.where(cls.entity_type == entity_type.strip().upper())

        result = await db.execute(
            stmt.order_by(cls.updated_at.asc()).limit(limit)
        )
        return result.scalars().all()

    @classmethod
    async def get_failed_for_target(
        cls,
        db: AsyncSession,
        target_system: str,
        max_retries: Optional[int] = None,
    ):
        """Fetch FAILED provisioning records (optionally capped by max_retries for retry workers)."""
        stmt = select(cls).where(
            cls.target_system == target_system.strip().upper(),
            cls.sync_status == SyncStatus.FAILED,
        )
        if max_retries is not None:
            stmt = stmt.where(cls.retry_count < max_retries)

        result = await db.execute(stmt.order_by(cls.last_attempt_at.asc()))
        return result.scalars().all()

    @classmethod
    async def get_all(cls, db: AsyncSession):
        """Get all provisioning records."""
        result = await db.execute(select(cls))
        return result.scalars().all()

    @classmethod
    async def get_all_paginated(
        cls,
        db: AsyncSession,
        page: int = 1,
        page_size: int = 10,
    ):
        """Get all provisioning records paginated."""
        total_result = await db.execute(
            select(func.count()).select_from(cls)
        )
        total = total_result.scalar_one()

        offset = (page - 1) * page_size

        result = await db.execute(
            select(cls)
            .order_by(cls.updated_at.desc())
            .offset(offset)
            .limit(page_size)
        )

        return result.scalars().all(), total