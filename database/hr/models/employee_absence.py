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
from .enums import AbsenceStatus, AbsenceType


class EmployeeAbsence(Base):
    __tablename__ = "employee_absences"

    absence_id = Column(
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
    absence_type = Column(
        Enum(AbsenceType, name="absence_type_enum"),
        nullable=False,
        index=True,
    )
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    reason = Column(Text, nullable=True)
    status = Column(
        Enum(AbsenceStatus, name="absence_status_enum"),
        nullable=False,
        default=AbsenceStatus.PLANNED,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    employee = relationship(
        "Employee",
        back_populates="absences",
    )

    @classmethod
    def _default_options(cls):
        return (selectinload(cls.employee),)

    @classmethod
    async def create_one(
        cls,
        db: AsyncSession,
        employee_id: uuid.UUID,
        absence_type: AbsenceType,
        start_date: date,
        end_date: Optional[date] = None,
        reason: Optional[str] = None,
        status: AbsenceStatus = AbsenceStatus.PLANNED,
    ):
        absence = cls(
            employee_id=employee_id,
            absence_type=absence_type,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            status=status,
            created_at=datetime.now(timezone.utc),
        )

        try:
            db.add(absence)
            await db.commit()
            await db.flush()
            await db.refresh(absence)
        except IntegrityError as ie:
            print("Error inserting employee absence", ie)
            await db.rollback()
            return None

        inserted_absence = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.absence_id == absence.absence_id)
        )

        return inserted_absence.scalar_one_or_none()

    @classmethod
    async def update_one(
        cls,
        db: AsyncSession,
        absence_id: uuid.UUID,
        updates: dict,
    ):
        absence_result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.absence_id == absence_id)
        )

        absence = absence_result.scalar_one_or_none()

        if absence is None:
            return None

        allowed_fields = {
            "absence_type",
            "start_date",
            "end_date",
            "reason",
            "status",
        }

        try:
            for field, value in updates.items():
                if field not in allowed_fields:
                    continue

                if hasattr(absence, field):
                    print("UPDATING", field, value)
                    setattr(absence, field, value)

            await db.commit()
            await db.flush()
            await db.refresh(absence)
        except IntegrityError as ie:
            print("Error updating employee absence", ie)
            await db.rollback()
            return None

        updated_absence = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.absence_id == absence_id)
        )

        return updated_absence.scalar_one_or_none()

    @classmethod
    async def update_status(
        cls,
        db: AsyncSession,
        absence_id: uuid.UUID,
        status: AbsenceStatus,
        end_date: Optional[date] = None,
    ):
        updates = {"status": status}
        if end_date is not None:
            updates["end_date"] = end_date

        return await cls.update_one(
            db=db,
            absence_id=absence_id,
            updates=updates,
        )

    @classmethod
    async def delete_by_id(
        cls,
        db: AsyncSession,
        absence_id: uuid.UUID,
    ):
        result = await db.execute(
            delete(cls).where(cls.absence_id == absence_id)
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
        absence_id: uuid.UUID,
    ):
        """
        Retrieve an absence record by ID
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.absence_id == absence_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_employee_id(
        cls,
        db: AsyncSession,
        employee_id: uuid.UUID,
    ):
        """
        Retrieve all absence records for an employee
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employee_id == employee_id)
            .order_by(cls.start_date.desc())
        )
        return result.scalars().all()

    @classmethod
    async def get_active_by_employee_id(
        cls,
        db: AsyncSession,
        employee_id: uuid.UUID,
    ):
        """
        Retrieve ongoing absences for an employee
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(
                cls.employee_id == employee_id,
                cls.status == AbsenceStatus.ONGOING,
            )
            .order_by(cls.start_date.desc())
        )
        return result.scalars().all()

    @classmethod
    async def get_by_status(
        cls,
        db: AsyncSession,
        status: AbsenceStatus,
    ):
        """
        Retrieve all absence records with a given status
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.status == status)
            .order_by(cls.start_date.desc())
        )
        return result.scalars().all()

    @classmethod
    async def get_all(cls, db: AsyncSession):
        """
        Get all absence records
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
        Get all absence records paginated
        """
        total_result = await db.execute(
            select(func.count()).select_from(cls)
        )
        total = total_result.scalar_one()

        offset = (page - 1) * page_size

        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .order_by(cls.start_date.desc())
            .offset(offset)
            .limit(page_size)
        )

        return result.scalars().all(), total