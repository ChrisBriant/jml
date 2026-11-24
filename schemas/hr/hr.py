from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from database.hr.models.enums import (
    AbsenceStatus,
    AbsenceType,
    EmploymentStatus,
    EmploymentType,
    UserRole
)

# ---------------------------------------------------------------------------
# Authorisation
# ---------------------------------------------------------------------------


class HRLoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class HRLoginSuccessResponse(BaseModel):
    success: bool = True
    message: str = "Successfully authenticated"
    username: str
    role: UserRole
    token : str


# ---------------------------------------------------------------------------
# Generic / Shared Responses
# ---------------------------------------------------------------------------

class ActionResponse(BaseModel):
    success: bool = True
    message: str


class PaginatedMeta(BaseModel):
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Lightweight Summary Schemas (prevent recursive relationship access)
# ---------------------------------------------------------------------------

class DepartmentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    department_id: UUID
    name: str
    description: Optional[str] = None
    parent_department_id: Optional[UUID] = None


class EmployeeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: UUID
    employee_number: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    job_title: str
    employment_status: EmploymentStatus
    employment_type: EmploymentType


class EmploymentHistorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employment_id: UUID
    employee_id: UUID
    department_id: UUID
    manager_id: Optional[UUID] = None
    job_title: str
    effective_from: date
    effective_to: Optional[date] = None


class EmployeeAbsenceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    absence_id: UUID
    employee_id: UUID
    absence_type: AbsenceType
    start_date: date
    end_date: Optional[date] = None
    reason: Optional[str] = None
    status: AbsenceStatus
    created_at: datetime


class EmploymentStatusHistorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status_history_id: UUID
    employee_id: UUID
    previous_status: Optional[EmploymentStatus] = None
    new_status: EmploymentStatus
    effective_date: date
    reason: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Department Schemas
# ---------------------------------------------------------------------------

class DepartmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    parent_department_id: Optional[UUID] = None


class DepartmentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    parent_department_id: Optional[UUID] = None


class DepartmentResponse(DepartmentSummary):
    created_at: datetime
    updated_at: datetime
    parent_department: Optional[DepartmentSummary] = None
    sub_departments: List[DepartmentSummary] = []
    employees: List[EmployeeSummary] = []


class DepartmentTreeNode(BaseModel):
    department_id: UUID
    name: str
    description: Optional[str] = None
    parent_department_id: Optional[UUID] = None
    children: List["DepartmentTreeNode"] = []


DepartmentTreeNode.model_rebuild()


class PaginatedDepartmentsResponse(PaginatedMeta):
    items: List[DepartmentResponse]


# ---------------------------------------------------------------------------
# Employee Schemas
# ---------------------------------------------------------------------------

class EmployeeCreate(BaseModel):
    #employee_number: str = Field(..., min_length=1, max_length=64)
    first_name: str = Field(..., min_length=1, max_length=128)
    last_name: str = Field(..., min_length=1, max_length=128)
    date_of_birth: Optional[date] = None
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None
    username: Optional[str] = None
    department_id: Optional[UUID] = None
    manager_id: Optional[UUID] = None
    job_title: str = Field(..., min_length=1, max_length=255)
    employment_status: EmploymentStatus = EmploymentStatus.PENDING
    employment_type: EmploymentType
    start_date: date
    end_date: Optional[date] = None
    contract_end_date: Optional[date] = None
    hours_per_week: Optional[Decimal] = Field(default=None, ge=0)
    fte: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("2.00"))
    probation_end_date: Optional[date] = None
    initial_status_reason: Optional[str] = "Initial employment record created"


class EmployeeUpdate(BaseModel):
    #employee_number: Optional[str] = Field(default=None, min_length=1, max_length=64)
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    date_of_birth: Optional[date] = None
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None
    username: Optional[str] = None
    department_id: Optional[UUID] = None
    manager_id: Optional[UUID] = None
    job_title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    employment_type: Optional[EmploymentType] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    contract_end_date: Optional[date] = None
    hours_per_week: Optional[Decimal] = Field(default=None, ge=0)
    fte: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("2.00"))
    probation_end_date: Optional[date] = None


class EmployeeResponse(EmployeeSummary):
    date_of_birth: Optional[date] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None
    username: Optional[str] = None
    department_id: Optional[UUID] = None
    manager_id: Optional[UUID] = None
    start_date: date
    end_date: Optional[date] = None
    contract_end_date: Optional[date] = None
    hours_per_week: Optional[Decimal] = None
    fte: Optional[Decimal] = None
    probation_end_date: Optional[date] = None
    created_at: datetime
    updated_at: datetime
    department: Optional[DepartmentSummary] = None
    manager: Optional[EmployeeSummary] = None
    direct_reports: List[EmployeeSummary] = []
    employment_history: List[EmploymentHistorySummary] = []
    absences: List[EmployeeAbsenceSummary] = []
    status_history: List[EmploymentStatusHistorySummary] = []


class PaginatedEmployeesResponse(PaginatedMeta):
    items: List[EmployeeResponse]


# ---------------------------------------------------------------------------
# Employee Lifecycle Schemas
# ---------------------------------------------------------------------------

class LifecycleStatusTransitionRequest(BaseModel):
    new_status: EmploymentStatus
    effective_date: date
    reason: Optional[str] = None
    end_date: Optional[date] = None
    force: bool = False


class LifecycleActionRequest(BaseModel):
    effective_date: date
    reason: Optional[str] = None


class LifecycleActivateRequest(LifecycleActionRequest):
    start_date: Optional[date] = None
    probation_end_date: Optional[date] = None
    complete_ongoing_absences: bool = True


class LifecycleLongTermAbsenceRequest(LifecycleActionRequest):
    create_absence_record: bool = True
    absence_type: AbsenceType = AbsenceType.SICKNESS
    expected_end_date: Optional[date] = None


class LifecycleReturnToWorkRequest(LifecycleActionRequest):
    complete_ongoing_absences: bool = True


class LifecycleExitRequest(LifecycleActionRequest):
    end_date: Optional[date] = None
    close_open_assignment: bool = True


class LifecycleTransferRequest(BaseModel):
    department_id: UUID
    job_title: str = Field(..., min_length=1, max_length=255)
    effective_from: date
    manager_id: Optional[UUID] = None


class EmployeeLifecycleOverviewResponse(BaseModel):
    employee: EmployeeSummary
    start_date: date
    end_date: Optional[date] = None
    contract_end_date: Optional[date] = None
    probation_end_date: Optional[date] = None
    current_department: Optional[DepartmentSummary] = None
    current_manager: Optional[EmployeeSummary] = None
    current_assignment: Optional[EmploymentHistorySummary] = None
    allowed_next_statuses: List[EmploymentStatus]
    employment_history: List[EmploymentHistorySummary] = []
    status_history: List[EmploymentStatusHistorySummary] = []
    absences: List[EmployeeAbsenceSummary] = []


# ---------------------------------------------------------------------------
# Employment History Schemas
# ---------------------------------------------------------------------------

class EmploymentHistoryCreate(BaseModel):
    employee_id: UUID
    department_id: UUID
    manager_id: Optional[UUID] = None
    job_title: str = Field(..., min_length=1, max_length=255)
    effective_from: date
    effective_to: Optional[date] = None


class EmploymentHistoryUpdate(BaseModel):
    department_id: Optional[UUID] = None
    manager_id: Optional[UUID] = None
    job_title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


class CloseAssignmentRequest(BaseModel):
    effective_to: date


class EmploymentHistoryResponse(EmploymentHistorySummary):
    employee: Optional[EmployeeSummary] = None
    department: Optional[DepartmentSummary] = None
    manager: Optional[EmployeeSummary] = None


class PaginatedEmploymentHistoryResponse(PaginatedMeta):
    items: List[EmploymentHistoryResponse]


# ---------------------------------------------------------------------------
# Employee Absence Schemas
# ---------------------------------------------------------------------------

class EmployeeAbsenceCreate(BaseModel):
    employee_id: UUID
    absence_type: AbsenceType
    start_date: date
    end_date: Optional[date] = None
    reason: Optional[str] = None
    status: AbsenceStatus = AbsenceStatus.PLANNED


class EmployeeAbsenceUpdate(BaseModel):
    absence_type: Optional[AbsenceType] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    reason: Optional[str] = None
    status: Optional[AbsenceStatus] = None


class EmployeeAbsenceStatusUpdate(BaseModel):
    status: AbsenceStatus
    end_date: Optional[date] = None


class EmployeeAbsenceResponse(EmployeeAbsenceSummary):
    employee: Optional[EmployeeSummary] = None


class PaginatedEmployeeAbsencesResponse(PaginatedMeta):
    items: List[EmployeeAbsenceResponse]


# ---------------------------------------------------------------------------
# Employment Status History Schemas
# ---------------------------------------------------------------------------

class EmploymentStatusHistoryUpdate(BaseModel):
    previous_status: Optional[EmploymentStatus] = None
    new_status: Optional[EmploymentStatus] = None
    effective_date: Optional[date] = None
    reason: Optional[str] = None


class EmploymentStatusHistoryResponse(EmploymentStatusHistorySummary):
    employee: Optional[EmployeeSummary] = None


class PaginatedStatusHistoryResponse(PaginatedMeta):
    items: List[EmploymentStatusHistoryResponse]