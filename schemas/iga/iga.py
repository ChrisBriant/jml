from datetime import date
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from database.jml.models.enums import EmploymentStatus, EmploymentType


class HREmployeeToIGAUser(BaseModel):
    """
    Validates and normalises an employee object returned by GET /hr/employees
    into the exact types and field names expected by IGAUser.upsert_from_source.
    """
    model_config = ConfigDict(extra="ignore")

    source_id: UUID = Field(..., alias="employee_id")
    username: Optional[str] = None
    first_name: str
    last_name: str
    email: Optional[str] = None
    job_title: str
    department_id: Optional[UUID] = None
    manager_id: Optional[UUID] = None
    employment_status: EmploymentStatus
    employment_type: EmploymentType
    start_date: date
    end_date: Optional[date] = None

    def to_upsert_kwargs(self, source_system: str = "HR_SYSTEM") -> Dict[str, Any]:
        """Return kwargs matching IGAUser.upsert_from_source(...)."""
        return {
            "source_system": source_system,
            "source_id": str(self.source_id),
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "job_title": self.job_title,
            "department_id": self.department_id,
            "manager_id": self.manager_id,
            "employment_status": self.employment_status,
            "employment_type": self.employment_type,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }