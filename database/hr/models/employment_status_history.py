import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Text,
    Uuid,
    delete,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import relationship, selectinload

from ..db import AsyncSession, Base
from .enums import EmploymentStatus


class EmploymentStatusHistory(Base):
    __tablename__ = "employment_status_history"

    status_history_id = Column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    employee_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("employees.employee_id"),
        nullable=False,
        index=True,
    )
    previous_status = Column(
        Enum(EmploymentStatus, name="employment_status_enum"),
        nullable=True,
    )
    new_status = Column(
        Enum(EmploymentStatus, name="employment_status_enum"),
        nullable=False,
    )
    effective_date = Column(Date, nullable=False)
    reason = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    employee = relationship(
        "Employee",
        back_populates="status_history",
    )

    @classmethod
    def _default_options(cls):
        return (selectinload(cls.employee),)

    @classmethod
    async def create_one(
        cls,
        db: AsyncSession,
        employee_id: uuid.UUID,
        new_status: EmploymentStatus,
        effective_date: date,
        previous_status: Optional[EmploymentStatus] = None,
        reason: Optional[str] = None,
    ):
        status_history = cls(
            employee_id=employee_id,
            previous_status=previous_status,
            new_status=new_status,
            effective_date=effective_date,
            reason=reason,
            created_at=datetime.now(timezone.utc),
        )

        try:
            db.add(status_history)
            await db.commit()
            await db.flush()
            await db.refresh(status_history)
        except IntegrityError as ie:
            print("Error inserting employment status history", ie)
            await db.rollback()
            return None

        inserted_record = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.status_history_id == status_history.status_history_id)
        )

        return inserted_record.scalar_one_or_none()

    @classmethod
    async def update_one(
        cls,
        db: AsyncSession,
        status_history_id: uuid.UUID,
        updates: dict,
    ):
        record_result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.status_history_id == status_history_id)
        )

        record = record_result.scalar_one_or_none()

        if record is None:
            return None

        allowed_fields = {
            "previous_status",
            "new_status",
            "effective_date",
            "reason",
        }

        try:
            for field, value in updates.items():
                if field not in allowed_fields:
                    continue

                if hasattr(record, field):
                    print("UPDATING", field, value)
                    setattr(record, field, value)

            await db.commit()
            await db.flush()
            await db.refresh(record)
        except IntegrityError as ie:
            print("Error updating employment status history", ie)
            await db.rollback()
            return None

        updated_record = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.status_history_id == status_history_id)
        )

        return updated_record.scalar_one_or_none()

    @classmethod
    async def delete_by_id(
        cls,
        db: AsyncSession,
        status_history_id: uuid.UUID,
    ):
        result = await db.execute(
            delete(cls).where(cls.status_history_id == status_history_id)
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
        status_history_id: uuid.UUID,
    ):
        """
        Retrieve an employment status history record by ID
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.status_history_id == status_history_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_employee_id(
        cls,
        db: AsyncSession,
        employee_id: uuid.UUID,
    ):
        """
        Retrieve status history for an employee ordered newest first
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employee_id == employee_id)
            .order_by(cls.effective_date.desc(), cls.created_at.desc())
        )
        return result.scalars().all()

    @classmethod
    async def get_latest_by_employee_id(
        cls,
        db: AsyncSession,
        employee_id: uuid.UUID,
    ):
        """
        Retrieve the latest status change for an employee
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employee_id == employee_id)
            .order_by(cls.effective_date.desc(), cls.created_at.desc())
        )
        return result.scalars().first()

    @classmethod
    async def get_all(cls, db: AsyncSession):
        """
        Get all employment status history records
        """
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
        """
        Get all employment status history records paginated
        """
        total_result = await db.execute(
            select(func.count()).select_from(cls)
        )
        total = total_result.scalar_one()

        offset = (page - 1) * page_size

        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .order_by(cls.effective_date.desc(), cls.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )

        return result.scalars().all(), total