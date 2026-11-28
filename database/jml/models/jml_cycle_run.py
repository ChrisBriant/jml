import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Enum,
    Float,
    Integer,
    String,
    Text,
    Uuid,
    delete,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError

from ..db import AsyncSession, Base


class CycleStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"


class JMLCycleRun(Base):
    __tablename__ = "jml_cycle_runs"

    cycle_id = Column(
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
    target_system = Column(
        String,
        nullable=True,
        index=True,
    )
    cycle_type = Column(
        String,
        nullable=False,
        default="HR_SYNC",
        index=True,
    )
    triggered_by = Column(
        String,
        nullable=True,
        default="SCHEDULER",
    )
    status = Column(
        Enum(CycleStatus, name="jml_cycle_status_enum"),
        nullable=False,
        default=CycleStatus.RUNNING,
        index=True,
    )
    total_processed = Column(Integer, nullable=False, default=0)
    new_count = Column(Integer, nullable=False, default=0)
    moved_departments_count = Column(Integer, nullable=False, default=0)
    changed_count = Column(Integer, nullable=False, default=0)
    unchanged_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    report = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Float, nullable=True)
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

    @staticmethod
    def _calculate_duration(started_at: datetime, completed_at: datetime) -> float:
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        return round((completed_at - started_at).total_seconds(), 3)

    @classmethod
    async def create_one(
        cls,
        db: AsyncSession,
        source_system: str = "HR_SYSTEM",
        target_system: Optional[str] = None,
        cycle_type: str = "HR_SYNC",
        triggered_by: Optional[str] = "SCHEDULER",
        status: CycleStatus = CycleStatus.RUNNING,
        total_processed: int = 0,
        new_count: int = 0,
        moved_departments_count: int = 0,
        changed_count: int = 0,
        unchanged_count: int = 0,
        error_count: int = 0,
        report: Optional[dict] = None,
        error_message: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        duration_seconds: Optional[float] = None,
    ):
        now = datetime.now(timezone.utc)
        cycle = cls(
            source_system=source_system.strip().upper(),
            target_system=target_system.strip().upper() if target_system else None,
            cycle_type=cycle_type.strip().upper(),
            triggered_by=triggered_by,
            status=status,
            total_processed=total_processed,
            new_count=new_count,
            moved_departments_count=moved_departments_count,
            changed_count=changed_count,
            unchanged_count=unchanged_count,
            error_count=error_count,
            report=report,
            error_message=error_message,
            started_at=started_at or now,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            created_at=now,
            updated_at=now,
        )

        try:
            db.add(cycle)
            await db.commit()
            await db.flush()
            await db.refresh(cycle)
        except IntegrityError as ie:
            print("Error inserting JML cycle run", ie)
            await db.rollback()
            return None

        inserted_cycle = await db.execute(
            select(cls).where(cls.cycle_id == cycle.cycle_id)
        )
        return inserted_cycle.scalar_one_or_none()

    @classmethod
    async def start_cycle(
        cls,
        db: AsyncSession,
        source_system: str = "HR_SYSTEM",
        target_system: Optional[str] = None,
        cycle_type: str = "HR_SYNC",
        triggered_by: Optional[str] = "SCHEDULER",
    ):
        """Create a new JML cycle run in RUNNING status."""
        return await cls.create_one(
            db=db,
            source_system=source_system,
            target_system=target_system,
            cycle_type=cycle_type,
            triggered_by=triggered_by,
            status=CycleStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )

    @classmethod
    async def complete_cycle(
        cls,
        db: AsyncSession,
        cycle_id: uuid.UUID,
        report: Optional[dict] = None,
        total_processed: Optional[int] = None,
        new_count: Optional[int] = None,
        moved_departments_count: Optional[int] = None,
        changed_count: Optional[int] = None,
        unchanged_count: Optional[int] = None,
        error_count: Optional[int] = None,
    ):
        """
        Mark a JML cycle run as COMPLETED (or COMPLETED_WITH_ERRORS if errors > 0),
        storing summary statistics, duration, and the full JSON report snapshot.
        """
        cycle = await cls.get_by_id(db, cycle_id)
        if cycle is None:
            return None

        stats = (report or {}).get("statistics", {})

        resolved_total = total_processed if total_processed is not None else stats.get("total_processed", 0)
        resolved_new = new_count if new_count is not None else stats.get("new", 0)
        resolved_moved = (
            moved_departments_count
            if moved_departments_count is not None
            else stats.get("moved_departments", 0)
        )
        resolved_changed = changed_count if changed_count is not None else stats.get("changed", 0)
        resolved_unchanged = (
            unchanged_count if unchanged_count is not None else stats.get("unchanged", 0)
        )
        resolved_errors = error_count if error_count is not None else stats.get("errors", 0)

        now = datetime.now(timezone.utc)
        final_status = (
            CycleStatus.COMPLETED_WITH_ERRORS
            if resolved_errors > 0
            else CycleStatus.COMPLETED
        )

        return await cls.update_one(
            db=db,
            cycle_id=cycle_id,
            updates={
                "status": final_status,
                "total_processed": resolved_total,
                "new_count": resolved_new,
                "moved_departments_count": resolved_moved,
                "changed_count": resolved_changed,
                "unchanged_count": resolved_unchanged,
                "error_count": resolved_errors,
                "report": report,
                "completed_at": now,
                "duration_seconds": cls._calculate_duration(cycle.started_at, now),
            },
        )

    @classmethod
    async def fail_cycle(
        cls,
        db: AsyncSession,
        cycle_id: uuid.UUID,
        error_message: str,
        report: Optional[dict] = None,
    ):
        """Mark a JML cycle run as FAILED and capture the error message and duration."""
        cycle = await cls.get_by_id(db, cycle_id)
        if cycle is None:
            return None

        now = datetime.now(timezone.utc)
        updates = {
            "status": CycleStatus.FAILED,
            "error_message": error_message,
            "completed_at": now,
            "duration_seconds": cls._calculate_duration(cycle.started_at, now),
        }
        if report is not None:
            updates["report"] = report

        return await cls.update_one(
            db=db,
            cycle_id=cycle_id,
            updates=updates,
        )

    @classmethod
    async def update_one(
        cls,
        db: AsyncSession,
        cycle_id: uuid.UUID,
        updates: dict,
    ):
        cycle_result = await db.execute(
            select(cls).where(cls.cycle_id == cycle_id)
        )
        cycle = cycle_result.scalar_one_or_none()

        if cycle is None:
            return None

        allowed_fields = {
            "target_system",
            "cycle_type",
            "triggered_by",
            "status",
            "total_processed",
            "new_count",
            "moved_departments_count",
            "changed_count",
            "unchanged_count",
            "error_count",
            "report",
            "error_message",
            "completed_at",
            "duration_seconds",
        }

        try:
            for field, value in updates.items():
                if field not in allowed_fields:
                    continue

                if hasattr(cycle, field):
                    print("UPDATING", field, value)
                    setattr(cycle, field, value)

            cycle.updated_at = datetime.now(timezone.utc)

            await db.commit()
            await db.flush()
            await db.refresh(cycle)
        except IntegrityError as ie:
            print("Error updating JML cycle run", ie)
            await db.rollback()
            return None

        updated_cycle = await db.execute(
            select(cls).where(cls.cycle_id == cycle_id)
        )
        return updated_cycle.scalar_one_or_none()

    @classmethod
    async def delete_by_id(
        cls,
        db: AsyncSession,
        cycle_id: uuid.UUID,
    ):
        result = await db.execute(
            delete(cls).where(cls.cycle_id == cycle_id)
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
        cycle_id: uuid.UUID,
    ):
        """Retrieve a JML cycle run by ID."""
        result = await db.execute(
            select(cls).where(cls.cycle_id == cycle_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_latest(
        cls,
        db: AsyncSession,
        cycle_type: Optional[str] = None,
        source_system: Optional[str] = None,
    ):
        """Retrieve the most recent JML cycle run, optionally filtered by type/source."""
        stmt = select(cls)
        if cycle_type is not None:
            stmt = stmt.where(cls.cycle_type == cycle_type.strip().upper())
        if source_system is not None:
            stmt = stmt.where(cls.source_system == source_system.strip().upper())

        result = await db.execute(
            stmt.order_by(cls.started_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_status(
        cls,
        db: AsyncSession,
        status: CycleStatus,
        limit: int = 100,
    ):
        """Retrieve JML cycle runs matching a given status."""
        result = await db.execute(
            select(cls)
            .where(cls.status == status)
            .order_by(cls.started_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    @classmethod
    async def get_running_cycles(cls, db: AsyncSession):
        """Retrieve any cycles currently marked as RUNNING."""
        return await cls.get_by_status(db, CycleStatus.RUNNING)

    @classmethod
    async def get_all(cls, db: AsyncSession):
        """Get all JML cycle runs ordered newest first."""
        result = await db.execute(
            select(cls).order_by(cls.started_at.desc())
        )
        return result.scalars().all()

    @classmethod
    async def get_all_paginated(
        cls,
        db: AsyncSession,
        page: int = 1,
        page_size: int = 10,
    ):
        """Get all JML cycle runs paginated."""
        total_result = await db.execute(
            select(func.count()).select_from(cls)
        )
        total = total_result.scalar_one()

        offset = (page - 1) * page_size

        result = await db.execute(
            select(cls)
            .order_by(cls.started_at.desc())
            .offset(offset)
            .limit(page_size)
        )

        return result.scalars().all(), total