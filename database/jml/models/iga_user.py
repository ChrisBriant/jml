import uuid
from datetime import date, datetime, timezone
from enum import Enum as PyEnum
from typing import Any, Optional

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    String,
    UniqueConstraint,
    Uuid,
    delete,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import relationship, selectinload

from ..db import AsyncSession, Base  # Separate JML database Base & AsyncSession
from .enums import EmploymentStatus, EmploymentType


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, PyEnum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


class IGAUser(Base):
    __tablename__ = "iga_users"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "source_id",
            name="uq_iga_users_source_system_source_id",
        ),
    )

    user_id = Column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    source_system = Column(
        String,
        nullable=False,
        default="HR_SYSTEM",
        index=True,
    )
    source_id = Column(
        String,
        nullable=False,
        index=True,
    )
    username = Column(
        String,
        unique=True,
        nullable=True,
        index=True,
    )
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=True, index=True)
    job_title = Column(String, nullable=False)
    department_id = Column(Uuid(as_uuid=True), nullable=True, index=True)
    manager_id = Column(Uuid(as_uuid=True), nullable=True, index=True)
    employment_status = Column(
        Enum(EmploymentStatus, name="iga_employment_status_enum"),
        nullable=False,
        default=EmploymentStatus.PENDING,
        index=True,
    )
    employment_type = Column(
        Enum(EmploymentType, name="iga_employment_type_enum"),
        nullable=False,
        index=True,
    )
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
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

    # Generic polymorphic links (no DB FK so IGAProvisioning/IGAAudit work for GROUPs etc.)
    provisioning_records = relationship(
        "IGAProvisioning",
        primaryjoin=(
            "and_("
            "IGAUser.user_id == foreign(IGAProvisioning.entity_id), "
            "IGAProvisioning.entity_type == 'USER'"
            ")"
        ),
        viewonly=True,
    )
    audit_logs = relationship(
        "IGAAudit",
        primaryjoin=(
            "and_("
            "IGAUser.user_id == foreign(IGAAudit.entity_id), "
            "IGAAudit.entity_type == 'USER'"
            ")"
        ),
        viewonly=True,
    )

    @classmethod
    def _default_options(cls):
        return (
            selectinload(cls.provisioning_records),
            selectinload(cls.audit_logs),
        )

    @classmethod
    async def create_one(
        cls,
        db: AsyncSession,
        source_id: str,
        first_name: str,
        last_name: str,
        job_title: str,
        employment_type: EmploymentType,
        start_date: date,
        source_system: str = "HR_SYSTEM",
        username: Optional[str] = None,
        email: Optional[str] = None,
        department_id: Optional[uuid.UUID] = None,
        manager_id: Optional[uuid.UUID] = None,
        employment_status: EmploymentStatus = EmploymentStatus.PENDING,
        end_date: Optional[date] = None,
    ):
        now = datetime.now(timezone.utc)
        iga_user = cls(
            source_system=source_system,
            source_id=str(source_id),
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email,
            job_title=job_title,
            department_id=department_id,
            manager_id=manager_id,
            employment_status=employment_status,
            employment_type=employment_type,
            start_date=start_date,
            end_date=end_date,
            created_at=now,
            updated_at=now,
        )

        try:
            db.add(iga_user)
            await db.commit()
            await db.flush()
            await db.refresh(iga_user)
        except IntegrityError as ie:
            print("Error inserting IGA user", ie)
            await db.rollback()
            return None

        inserted_user = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.user_id == iga_user.user_id)
        )
        return inserted_user.scalar_one_or_none()

    @classmethod
    async def update_one(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        updates: dict,
    ):
        user_result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.user_id == user_id)
        )
        iga_user = user_result.scalar_one_or_none()

        if iga_user is None:
            return None

        allowed_fields = {
            "username",
            "first_name",
            "last_name",
            "email",
            "job_title",
            "department_id",
            "manager_id",
            "employment_status",
            "employment_type",
            "start_date",
            "end_date",
        }

        try:
            for field, value in updates.items():
                if field not in allowed_fields:
                    continue

                if hasattr(iga_user, field):
                    print("UPDATING", field, value)
                    setattr(iga_user, field, value)

            iga_user.updated_at = datetime.now(timezone.utc)

            await db.commit()
            await db.flush()
            await db.refresh(iga_user)
        except IntegrityError as ie:
            print("Error updating IGA user", ie)
            await db.rollback()
            return None

        updated_user = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.user_id == user_id)
        )
        return updated_user.scalar_one_or_none()

    @classmethod
    async def upsert_from_source(
        cls,
        db: AsyncSession,
        source_id: str,
        first_name: str,
        last_name: str,
        job_title: str,
        employment_type: EmploymentType,
        start_date: date,
        source_system: str = "HR_SYSTEM",
        username: Optional[str] = None,
        email: Optional[str] = None,
        department_id: Optional[uuid.UUID] = None,
        manager_id: Optional[uuid.UUID] = None,
        employment_status: EmploymentStatus = EmploymentStatus.PENDING,
        end_date: Optional[date] = None,
    ):
        """
        Ingest or update an IGAUser from a source system (e.g. HR System),
        detect JML lifecycle events (JOINER, MOVER, LEAVER, UNCHANGED),
        and automatically write an IGAAudit record.

        Returns: (IGAUser | None, event_type: str, changed_fields: dict)
        """
        from .iga_audit import IGAAudit

        source_id_str = str(source_id)
        existing = await cls.get_by_source_id(
            db=db,
            source_id=source_id_str,
            source_system=source_system,
        )

        if existing is None:
            created = await cls.create_one(
                db=db,
                source_system=source_system,
                source_id=source_id_str,
                username=username,
                first_name=first_name,
                last_name=last_name,
                email=email,
                job_title=job_title,
                department_id=department_id,
                manager_id=manager_id,
                employment_status=employment_status,
                employment_type=employment_type,
                start_date=start_date,
                end_date=end_date,
            )
            if created is None:
                return None, "ERROR", {}

            await IGAAudit.create_one(
                db=db,
                entity_type="USER",
                entity_id=created.user_id,
                action="JOINER_DETECTED",
                description=(
                    f"Ingested user '{created.first_name} {created.last_name}' "
                    f"from {source_system} (source_id={source_id_str})"
                ),
                details={"source_system": source_system, "source_id": source_id_str},
            )
            refreshed = await cls.get_by_id(db, created.user_id)
            return refreshed, "JOINER", {}

        incoming_values = {
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "job_title": job_title,
            "department_id": department_id,
            "manager_id": manager_id,
            "employment_status": employment_status,
            "employment_type": employment_type,
            "start_date": start_date,
            "end_date": end_date,
        }

        changed_fields: dict[str, dict[str, Any]] = {}
        raw_updates: dict[str, Any] = {}

        for field, new_val in incoming_values.items():
            old_val = getattr(existing, field)
            if old_val != new_val:
                raw_updates[field] = new_val
                changed_fields[field] = {
                    "old": _to_json_safe(old_val),
                    "new": _to_json_safe(new_val),
                }

        if not raw_updates:
            return existing, "UNCHANGED", {}

        terminal_statuses = {EmploymentStatus.TERMINATED, EmploymentStatus.RETIRED}
        mover_fields = {
            "department_id",
            "job_title",
            "manager_id",
            "employment_type",
            "employment_status",
        }

        if (
            "employment_status" in raw_updates
            and raw_updates["employment_status"] in terminal_statuses
        ):
            event_type = "LEAVER"
            audit_action = "LEAVER_DETECTED"
        elif any(f in raw_updates for f in mover_fields):
            event_type = "MOVER"
            audit_action = "MOVER_DETECTED"
        else:
            event_type = "UPDATED"
            audit_action = "UPDATED"

        updated = await cls.update_one(
            db=db,
            user_id=existing.user_id,
            updates=raw_updates,
        )
        if updated is None:
            return None, "ERROR", changed_fields

        await IGAAudit.create_one(
            db=db,
            entity_type="USER",
            entity_id=updated.user_id,
            action=audit_action,
            description=(
                f"{event_type} update for user '{updated.first_name} {updated.last_name}' "
                f"from {source_system}"
            ),
            details=changed_fields,
        )

        refreshed = await cls.get_by_id(db, updated.user_id)
        return refreshed, event_type, changed_fields

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
    async def get_by_id(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
    ):
        """Retrieve an IGA user by ID."""
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_source_id(
        cls,
        db: AsyncSession,
        source_id: str,
        source_system: str = "HR_SYSTEM",
    ):
        """Retrieve an IGA user by source system and source ID."""
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(
                cls.source_system == source_system,
                cls.source_id == str(source_id),
            )
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_username(
        cls,
        db: AsyncSession,
        username: str,
    ):
        """Retrieve an IGA user by username."""
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.username == username)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_email(
        cls,
        db: AsyncSession,
        email: str,
    ):
        """Retrieve an IGA user by email."""
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.email == email)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_status(
        cls,
        db: AsyncSession,
        employment_status: EmploymentStatus,
    ):
        """Retrieve all IGA users with a specific employment status."""
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employment_status == employment_status)
        )
        return result.scalars().all()

    @classmethod
    async def get_by_department_id(
        cls,
        db: AsyncSession,
        department_id: uuid.UUID,
    ):
        """Retrieve all IGA users belonging to an HR department."""
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.department_id == department_id)
        )
        return result.scalars().all()

    @classmethod
    async def get_all(cls, db: AsyncSession):
        """Get all IGA users."""
        result = await db.execute(
            select(cls).options(*cls._default_options())
        )
        return result.scalars().all()

    @classmethod
    async def get_all_paginated(
        cls,
        db: AsyncSession,
        page: int = 1,
        page_size: int = 10,
    ):
        """Get all IGA users paginated."""
        total_result = await db.execute(
            select(func.count()).select_from(cls)
        )
        total = total_result.scalar_one()

        offset = (page - 1) * page_size

        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .order_by(cls.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )

        return result.scalars().all(), total