import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
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
from .enums import EmploymentStatus, EmploymentType


class Employee(Base):
    __tablename__ = "employees"

    employee_id = Column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    employee_number = Column(String, unique=True, nullable=False, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    date_of_birth = Column(Date, nullable=True)
    email = Column(String, unique=True, nullable=True, index=True)
    phone_number = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    username = Column(String, unique=True, nullable=True, index=True)
    department_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("departments.department_id"),
        nullable=True,
        index=True,
    )
    manager_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("employees.employee_id"),
        nullable=True,
        index=True,
    )
    job_title = Column(String, nullable=False)
    employment_status = Column(
        Enum(EmploymentStatus, name="employment_status_enum"),
        nullable=False,
        default=EmploymentStatus.PENDING,
        index=True,
    )
    employment_type = Column(
        Enum(EmploymentType, name="employment_type_enum"),
        nullable=False,
        index=True,
    )
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    contract_end_date = Column(Date, nullable=True)
    hours_per_week = Column(Numeric(5, 2), nullable=True)
    fte = Column(Numeric(4, 2), nullable=True)
    probation_end_date = Column(Date, nullable=True)
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

    department = relationship(
        "Department",
        back_populates="employees",
    )
    manager = relationship(
        "Employee",
        remote_side=[employee_id],
        foreign_keys=[manager_id],
        back_populates="direct_reports",
    )
    direct_reports = relationship(
        "Employee",
        foreign_keys=[manager_id],
        back_populates="manager",
    )
    employment_history = relationship(
        "EmploymentHistory",
        foreign_keys="EmploymentHistory.employee_id",
        back_populates="employee",
    )
    managed_employment_history = relationship(
        "EmploymentHistory",
        foreign_keys="EmploymentHistory.manager_id",
        back_populates="manager",
    )
    absences = relationship(
        "EmployeeAbsence",
        back_populates="employee",
    )
    status_history = relationship(
        "EmploymentStatusHistory",
        back_populates="employee",
    )

    @classmethod
    def _default_options(cls):
        return (
            selectinload(cls.department),
            selectinload(cls.manager),
            selectinload(cls.direct_reports),
            selectinload(cls.employment_history),
            selectinload(cls.absences),
            selectinload(cls.status_history),
        )

    @classmethod
    async def create_one(
        cls,
        db: AsyncSession,
        employee_number: str,
        first_name: str,
        last_name: str,
        job_title: str,
        employment_type: EmploymentType,
        start_date: date,
        employment_status: EmploymentStatus = EmploymentStatus.PENDING,
        date_of_birth: Optional[date] = None,
        email: Optional[str] = None,
        phone_number: Optional[str] = None,
        address: Optional[str] = None,
        username: Optional[str] = None,
        department_id: Optional[uuid.UUID] = None,
        manager_id: Optional[uuid.UUID] = None,
        end_date: Optional[date] = None,
        contract_end_date: Optional[date] = None,
        hours_per_week: Optional[Decimal] = None,
        fte: Optional[Decimal] = None,
        probation_end_date: Optional[date] = None,
    ):
        now = datetime.now(timezone.utc)
        employee = cls(
            employee_number=employee_number,
            first_name=first_name,
            last_name=last_name,
            date_of_birth=date_of_birth,
            email=email,
            phone_number=phone_number,
            address=address,
            username=username,
            department_id=department_id,
            manager_id=manager_id,
            job_title=job_title,
            employment_status=employment_status,
            employment_type=employment_type,
            start_date=start_date,
            end_date=end_date,
            contract_end_date=contract_end_date,
            hours_per_week=hours_per_week,
            fte=fte,
            probation_end_date=probation_end_date,
            created_at=now,
            updated_at=now,
        )

        try:
            db.add(employee)
            await db.commit()
            await db.flush()
            await db.refresh(employee)
        except IntegrityError as ie:
            print("Error inserting employee", ie)
            await db.rollback()
            return None

        inserted_employee = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employee_id == employee.employee_id)
        )

        return inserted_employee.scalar_one_or_none()

    @classmethod
    async def update_one(
        cls,
        db: AsyncSession,
        employee_id: uuid.UUID,
        updates: dict,
    ):
        employee_result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employee_id == employee_id)
        )

        employee = employee_result.scalar_one_or_none()

        if employee is None:
            return None

        allowed_fields = {
            "employee_number",
            "first_name",
            "last_name",
            "date_of_birth",
            "email",
            "phone_number",
            "address",
            "username",
            "department_id",
            "manager_id",
            "job_title",
            "employment_status",
            "employment_type",
            "start_date",
            "end_date",
            "contract_end_date",
            "hours_per_week",
            "fte",
            "probation_end_date",
        }

        try:
            for field, value in updates.items():
                if field not in allowed_fields:
                    continue

                if hasattr(employee, field):
                    print("UPDATING", field, value)
                    setattr(employee, field, value)

            employee.updated_at = datetime.now(timezone.utc)

            await db.commit()
            await db.flush()
            await db.refresh(employee)
        except IntegrityError as ie:
            print("Error updating employee", ie)
            await db.rollback()
            return None

        updated_employee = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employee_id == employee_id)
        )

        return updated_employee.scalar_one_or_none()

    @classmethod
    async def change_status(
        cls,
        db: AsyncSession,
        employee_id: uuid.UUID,
        new_status: EmploymentStatus,
        effective_date: date,
        reason: Optional[str] = None,
        end_date: Optional[date] = None,
    ):
        """
        Update an employee's current status and record the change in EmploymentStatusHistory
        """
        from .employment_status_history import EmploymentStatusHistory

        employee_result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employee_id == employee_id)
        )
        employee = employee_result.scalar_one_or_none()

        if employee is None:
            return None

        previous_status = employee.employment_status

        try:
            employee.employment_status = new_status
            if end_date is not None:
                employee.end_date = end_date
            employee.updated_at = datetime.now(timezone.utc)

            status_history = EmploymentStatusHistory(
                employee_id=employee.employee_id,
                previous_status=previous_status,
                new_status=new_status,
                effective_date=effective_date,
                reason=reason,
                created_at=datetime.now(timezone.utc),
            )
            db.add(status_history)

            await db.commit()
            await db.flush()
            await db.refresh(employee)
        except IntegrityError as ie:
            print("Error changing employee status", ie)
            await db.rollback()
            return None

        updated_employee = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employee_id == employee_id)
        )
        return updated_employee.scalar_one_or_none()

    @classmethod
    async def update_assignment(
        cls,
        db: AsyncSession,
        employee_id: uuid.UUID,
        department_id: uuid.UUID,
        job_title: str,
        effective_from: date,
        manager_id: Optional[uuid.UUID] = None,
    ):
        """
        Close any open EmploymentHistory record and create a new organisational assignment
        """
        from .employment_history import EmploymentHistory

        employee_result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employee_id == employee_id)
        )
        employee = employee_result.scalar_one_or_none()

        if employee is None:
            return None

        current_assignment_result = await db.execute(
            select(EmploymentHistory)
            .where(
                EmploymentHistory.employee_id == employee_id,
                EmploymentHistory.effective_to.is_(None),
            )
        )
        current_assignments = current_assignment_result.scalars().all()

        try:
            close_date = effective_from - timedelta(days=1)
            for assignment in current_assignments:
                assignment.effective_to = (
                    close_date
                    if close_date >= assignment.effective_from
                    else effective_from
                )

            new_assignment = EmploymentHistory(
                employee_id=employee_id,
                department_id=department_id,
                manager_id=manager_id,
                job_title=job_title,
                effective_from=effective_from,
                effective_to=None,
            )
            db.add(new_assignment)

            employee.department_id = department_id
            employee.manager_id = manager_id
            employee.job_title = job_title
            employee.updated_at = datetime.now(timezone.utc)

            await db.commit()
            await db.flush()
            await db.refresh(employee)
        except IntegrityError as ie:
            print("Error updating employee assignment", ie)
            await db.rollback()
            return None

        updated_employee = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employee_id == employee_id)
        )
        return updated_employee.scalar_one_or_none()

    @classmethod
    async def delete_by_id(
        cls,
        db: AsyncSession,
        employee_id: uuid.UUID,
    ):
        try:
            result = await db.execute(
                delete(cls).where(cls.employee_id == employee_id)
            )
            await db.commit()
        except IntegrityError as ie:
            print("Error deleting employee", ie)
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
        employee_id: uuid.UUID,
    ):
        """
        Retrieve an employee by ID
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employee_id == employee_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_employee_number(
        cls,
        db: AsyncSession,
        employee_number: str,
    ):
        """
        Retrieve an employee by unique employee number
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employee_number == employee_number)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_email(
        cls,
        db: AsyncSession,
        email: str,
    ):
        """
        Retrieve an employee by work email
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.email == email)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_username(
        cls,
        db: AsyncSession,
        username: str,
    ):
        """
        Retrieve an employee by directory username
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.username == username)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_department_id(
        cls,
        db: AsyncSession,
        department_id: uuid.UUID,
    ):
        """
        Retrieve all employees in a department
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.department_id == department_id)
        )
        return result.scalars().all()

    @classmethod
    async def get_by_manager_id(
        cls,
        db: AsyncSession,
        manager_id: uuid.UUID,
    ):
        """
        Retrieve all direct reports for a manager
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.manager_id == manager_id)
        )
        return result.scalars().all()

    @classmethod
    async def get_by_status(
        cls,
        db: AsyncSession,
        employment_status: EmploymentStatus,
    ):
        """
        Retrieve all employees with a specific employment status
        """
        result = await db.execute(
            select(cls)
            .options(*cls._default_options())
            .where(cls.employment_status == employment_status)
        )
        return result.scalars().all()

    @classmethod
    async def get_all(cls, db: AsyncSession):
        """
        Get all employees
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
        Get all employees paginated
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