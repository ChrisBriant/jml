import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    Uuid,
    delete,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import relationship, selectinload

from ..db import AsyncSession, Base


class Department(Base):
    __tablename__ = "departments"

    department_id = Column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    name = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    parent_department_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("departments.department_id"),
        nullable=True,
        index=True,
    )
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

    parent_department = relationship(
        "Department",
        remote_side=[department_id],
        back_populates="sub_departments",
    )
    sub_departments = relationship(
        "Department",
        back_populates="parent_department",
    )
    employees = relationship(
        "Employee",
        back_populates="department",
    )
    employment_history_records = relationship(
        "EmploymentHistory",
        back_populates="department",
    )

    @classmethod
    def _default_options(cls):
        return (
            selectinload(cls.parent_department),
            selectinload(cls.sub_departments),
            selectinload(cls.employees),
        )

    @classmethod
    async def create_one(
        cls,
        db: AsyncSession,
        name: str,
        description: Optional[str] = None,
        parent_department_id: Optional[uuid.UUID] = None,
    ):
        now = datetime.now(timezone.utc)
        department = cls(
            name=name,
            description=description,
            parent_department_id=parent_department_id,
            created_at=now,
            updated_at=now,
        )

        try:
            db.add(department)
            await db.commit()
            await db.flush()
            await db.refresh(department)
        except IntegrityError as ie:
            print("Error inserting department", ie)
            await db.rollback()
            return None

        inserted_department = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.department_id == department.department_id)
        )

        return inserted_department.scalar_one_or_none()

    @classmethod
    async def update_one(
        cls,
        db: AsyncSession,
        department_id: uuid.UUID,
        updates: dict,
    ):
        department_result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.department_id == department_id)
        )

        department = department_result.scalar_one_or_none()

        if department is None:
            return None

        allowed_fields = {
            "name",
            "description",
            "parent_department_id",
        }

        try:
            for field, value in updates.items():
                if field not in allowed_fields:
                    continue

                if hasattr(department, field):
                    print("UPDATING", field, value)
                    setattr(department, field, value)

            department.updated_at = datetime.now(timezone.utc)

            await db.commit()
            await db.flush()
            await db.refresh(department)
        except IntegrityError as ie:
            print("Error updating department", ie)
            await db.rollback()
            return None

        updated_department = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.department_id == department_id)
        )

        return updated_department.scalar_one_or_none()

    @classmethod
    async def delete_by_id(
        cls,
        db: AsyncSession,
        department_id: uuid.UUID,
    ):
        try:
            result = await db.execute(
                delete(cls).where(cls.department_id == department_id)
            )
            await db.commit()
        except IntegrityError as ie:
            print("Error deleting department", ie)
            await db.rollback()
            return False

        if result.rowcount > 0:
            return True
        else:
            return False

    @classmethod
    async def get_by_id(
        cls,
        db: AsyncSession,
        department_id: uuid.UUID,
    ):
        """
        Retrieve a department by ID
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.department_id == department_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_name(
        cls,
        db: AsyncSession,
        name: str,
    ):
        """
        Retrieve a department by name
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.name == name)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_root_departments(cls, db: AsyncSession):
        """
        Retrieve top-level departments with no parent department
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.parent_department_id.is_(None))
        )
        return result.scalars().all()

    @classmethod
    async def get_children(
        cls,
        db: AsyncSession,
        parent_department_id: uuid.UUID,
    ):
        """
        Retrieve direct child departments for a parent department
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.parent_department_id == parent_department_id)
        )
        return result.scalars().all()

    @classmethod
    async def get_all(cls, db: AsyncSession):
        """
        Get all departments
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
        Get all departments paginated
        """
        total_result = await db.execute(
            select(func.count()).select_from(cls)
        )
        total = total_result.scalar_one()

        offset = (page - 1) * page_size

        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .offset(offset)
            .limit(page_size)
        )

        return result.scalars().all(), total