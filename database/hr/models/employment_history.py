import uuid
from datetime import date
from typing import Optional

from sqlalchemy import (
    Column,
    Date,
    ForeignKey,
    String,
    Uuid,
    delete,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import relationship, selectinload

from ..db import AsyncSession, Base


class EmploymentHistory(Base):
    __tablename__ = "employment_history"

    employment_id = Column(
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
    department_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("departments.department_id"),
        nullable=False,
        index=True,
    )
    manager_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("employees.employee_id"),
        nullable=True,
        index=True,
    )
    job_title = Column(String, nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)

    employee = relationship(
        "Employee",
        foreign_keys=[employee_id],
        back_populates="employment_history",
    )
    department = relationship(
        "Department",
        back_populates="employment_history_records",
    )
    manager = relationship(
        "Employee",
        foreign_keys=[manager_id],
        back_populates="managed_employment_history",
    )

    @classmethod
    def _default_options(cls):
        return (
            selectinload(cls.employee),
            selectinload(cls.department),
            selectinload(cls.manager),
        )

    @classmethod
    async def create_one(
        cls,
        db: AsyncSession,
        employee_id: uuid.UUID,
        department_id: uuid.UUID,
        job_title: str,
        effective_from: date,
        manager_id: Optional[uuid.UUID] = None,
        effective_to: Optional[date] = None,
    ):
        employment_record = cls(
            employee_id=employee_id,
            department_id=department_id,
            manager_id=manager_id,
            job_title=job_title,
            effective_from=effective_from,
            effective_to=effective_to,
        )

        try:
            db.add(employment_record)
            await db.commit()
            await db.flush()
            await db.refresh(employment_record)
        except IntegrityError as ie:
            print("Error inserting employment history", ie)
            await db.rollback()
            return None

        inserted_record = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employment_id == employment_record.employment_id)
        )

        return inserted_record.scalar_one_or_none()

    @classmethod
    async def update_one(
        cls,
        db: AsyncSession,
        employment_id: uuid.UUID,
        updates: dict,
    ):
        record_result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employment_id == employment_id)
        )

        record = record_result.scalar_one_or_none()

        if record is None:
            return None

        allowed_fields = {
            "department_id",
            "manager_id",
            "job_title",
            "effective_from",
            "effective_to",
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
            print("Error updating employment history", ie)
            await db.rollback()
            return None

        updated_record = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employment_id == employment_id)
        )

        return updated_record.scalar_one_or_none()

    @classmethod
    async def close_current_assignment(
        cls,
        db: AsyncSession,
        employee_id: uuid.UUID,
        effective_to: date,
    ):
        """
        Close the currently open employment history record for an employee
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(
                cls.employee_id == employee_id,
                cls.effective_to.is_(None),
            )
            .order_by(cls.effective_from.desc())
        )
        record = result.scalars().first()

        if record is None:
            return None

        try:
            record.effective_to = effective_to
            await db.commit()
            await db.flush()
            await db.refresh(record)
        except IntegrityError as ie:
            print("Error closing employment history", ie)
            await db.rollback()
            return None

        closed_record = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employment_id == record.employment_id)
        )
        return closed_record.scalar_one_or_none()

    @classmethod
    async def delete_by_id(
        cls,
        db: AsyncSession,
        employment_id: uuid.UUID,
    ):
        result = await db.execute(
            delete(cls).where(cls.employment_id == employment_id)
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
        employment_id: uuid.UUID,
    ):
        """
        Retrieve an employment history record by ID
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employment_id == employment_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_employee_id(
        cls,
        db: AsyncSession,
        employee_id: uuid.UUID,
    ):
        """
        Retrieve full employment history for an employee ordered newest first
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employee_id == employee_id)
            .order_by(cls.effective_from.desc())
        )
        return result.scalars().all()

    @classmethod
    async def get_current_by_employee_id(
        cls,
        db: AsyncSession,
        employee_id: uuid.UUID,
    ):
        """
        Retrieve the currently active employment history record for an employee
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(
                cls.employee_id == employee_id,
                cls.effective_to.is_(None),
            )
            .order_by(cls.effective_from.desc())
        )
        return result.scalars().first()

    @classmethod
    async def get_all(cls, db: AsyncSession):
        """
        Get all employment history records
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
        Get all employment history records paginated
        """
        total_result = await db.execute(
            select(func.count()).select_from(cls)
        )
        total = total_result.scalar_one()

        offset = (page - 1) * page_size

        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .order_by(cls.effective_from.desc())
            .offset(offset)
            .limit(page_size)
        )

        return result.scalars().all(), total