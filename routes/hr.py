from typing import AsyncGenerator, Dict, List, Optional, Set
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status, Response
from sqlalchemy import func, or_, select

from database.hr.models import (
    AbsenceStatus,
    Department,
    Employee,
    EmployeeAbsence,
    EmploymentHistory,
    EmploymentStatus,
    EmploymentStatusHistory,
    EmploymentType,
    SystemUser,
)
from database.hr.db import AsyncSession, SessionLocal
from schemas.hr.hr import (
    ActionResponse,
    CloseAssignmentRequest,
    DepartmentCreate,
    DepartmentResponse,
    DepartmentTreeNode,
    DepartmentUpdate,
    EmployeeAbsenceCreate,
    EmployeeAbsenceResponse,
    EmployeeAbsenceStatusUpdate,
    EmployeeAbsenceUpdate,
    EmployeeCreate,
    EmployeeLifecycleOverviewResponse,
    EmployeeResponse,
    EmployeeSummary,
    EmployeeUpdate,
    EmploymentHistoryCreate,
    EmploymentHistoryResponse,
    EmploymentHistoryUpdate,
    EmploymentStatusHistoryResponse,
    EmploymentStatusHistoryUpdate,
    LifecycleActivateRequest,
    LifecycleActionRequest,
    LifecycleExitRequest,
    LifecycleLongTermAbsenceRequest,
    LifecycleReturnToWorkRequest,
    LifecycleStatusTransitionRequest,
    LifecycleTransferRequest,
    PaginatedDepartmentsResponse,
    PaginatedEmployeeAbsencesResponse,
    PaginatedEmployeesResponse,
    PaginatedEmploymentHistoryResponse,
    PaginatedStatusHistoryResponse,
    HRLoginSuccessResponse,
    HRLoginRequest,
)
from services.hr.jwt import (
    create_hr_access_token,
    HR_COOKIE_MAX_AGE,
)
import os

router = APIRouter(tags=["Personnel & HR"])


# ---------------------------------------------------------------------------
# Dependencies & Lifecycle State Machine Helpers
# ---------------------------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency provider for async database sessions."""
    async with SessionLocal() as session:
        yield session


ALLOWED_STATUS_TRANSITIONS: Dict[EmploymentStatus, Set[EmploymentStatus]] = {
    EmploymentStatus.PENDING: {
        EmploymentStatus.ACTIVE,
        EmploymentStatus.TERMINATED,
    },
    EmploymentStatus.ACTIVE: {
        EmploymentStatus.SUSPENDED,
        EmploymentStatus.LONG_TERM_ABSENCE,
        EmploymentStatus.NOTICE_PERIOD,
        EmploymentStatus.TERMINATED,
        EmploymentStatus.RETIRED,
    },
    EmploymentStatus.SUSPENDED: {
        EmploymentStatus.ACTIVE,
        EmploymentStatus.NOTICE_PERIOD,
        EmploymentStatus.TERMINATED,
        EmploymentStatus.RETIRED,
    },
    EmploymentStatus.LONG_TERM_ABSENCE: {
        EmploymentStatus.ACTIVE,
        EmploymentStatus.NOTICE_PERIOD,
        EmploymentStatus.TERMINATED,
        EmploymentStatus.RETIRED,
    },
    EmploymentStatus.NOTICE_PERIOD: {
        EmploymentStatus.ACTIVE,
        EmploymentStatus.SUSPENDED,
        EmploymentStatus.LONG_TERM_ABSENCE,
        EmploymentStatus.TERMINATED,
        EmploymentStatus.RETIRED,
    },
    EmploymentStatus.TERMINATED: set(),
    EmploymentStatus.RETIRED: set(),
}

TERMINAL_STATUSES = {
    EmploymentStatus.TERMINATED,
    EmploymentStatus.RETIRED,
}


async def _get_employee_or_404(db: AsyncSession, employee_id: UUID) -> Employee:
    employee = await Employee.get_by_id(db, employee_id)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee '{employee_id}' not found",
        )
    return employee


async def _get_department_or_404(db: AsyncSession, department_id: UUID) -> Department:
    department = await Department.get_by_id(db, department_id)
    if department is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Department '{department_id}' not found",
        )
    return department


def _validate_status_transition(
    current_status: EmploymentStatus,
    new_status: EmploymentStatus,
    force: bool = False,
) -> None:
    if current_status == new_status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Employee is already in status '{new_status.value}'",
        )

    if force:
        return

    allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        allowed_names = ", ".join(s.value for s in sorted(allowed, key=lambda x: x.value))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid lifecycle transition from '{current_status.value}' "
                f"to '{new_status.value}'. Allowed transitions: [{allowed_names or 'none'}]"
            ),
        )


async def _apply_status_transition(
    db: AsyncSession,
    employee: Employee,
    new_status: EmploymentStatus,
    effective_date,
    reason: Optional[str] = None,
    end_date=None,
    close_open_assignment: bool = False,
    force: bool = False,
) -> Employee:
    _validate_status_transition(
        current_status=employee.employment_status,
        new_status=new_status,
        force=force,
    )

    resolved_end_date = end_date
    if new_status in TERMINAL_STATUSES and resolved_end_date is None:
        resolved_end_date = effective_date

    if resolved_end_date is not None and resolved_end_date < employee.start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date cannot be earlier than employee start_date",
        )

    updated = await Employee.change_status(
        db=db,
        employee_id=employee.employee_id,
        new_status=new_status,
        effective_date=effective_date,
        reason=reason,
        end_date=resolved_end_date,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to transition employee lifecycle status",
        )

    if close_open_assignment and new_status in TERMINAL_STATUSES:
        await EmploymentHistory.close_current_assignment(
            db=db,
            employee_id=employee.employee_id,
            effective_to=resolved_end_date or effective_date,
        )
        updated = await Employee.get_by_id(db, employee.employee_id)

    return updated

# ===========================================================================
# AUTHORISATION
# ===========================================================================

IS_PRODUCTION = os.environ.get("ENVIRONMENT", "development").lower() == "production"
HR_COOKIE_NAME = os.environ.get("HR_COOKIE_NAME", "hr_access_token")


@router.post(
    "/login",
    response_model=HRLoginSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate HR System User and Set Cookie",
)
async def hr_login(
    credentials: HRLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate an HR system user against the local system_users table.
    On success: Issues an HR-scoped JWT and sets an HttpOnly session cookie
    distinct from the LDAP access_token cookie.
    On failure: Raises HTTP 401 Unauthorized.
    """
    # 1. Authenticate against SystemUser (checks active status and password hash)
    user = await SystemUser.authenticate(
        db=db,
        username=credentials.username,
        password=credentials.password,
    )

    # 2. If credentials failed or account is disabled, return 401
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Issue signed HR JWT
    jwt_token = create_hr_access_token(user)

    # 4. Set the distinct Secure HttpOnly cookie in the browser
    response.set_cookie(
        key=HR_COOKIE_NAME,
        value=jwt_token,
        httponly=True,            # Prevents JavaScript (XSS) access
        secure=IS_PRODUCTION,     # True in production (HTTPS only), False on http://localhost
        samesite="lax",           # Mitigates CSRF while allowing standard top-level navigation
        max_age=HR_COOKIE_MAX_AGE,
        path="/",
    )

    return HRLoginSuccessResponse(
        username=user.username,
        role=user.role,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Logout HR System User",
)
async def hr_logout(response: Response):
    """Clear the HR session cookie to log the user out without affecting LDAP."""
    response.delete_cookie(
        key=HR_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
    )
    return {"message": "Successfully logged out of HR system"}


# ===========================================================================
# DEPARTMENTS
# ===========================================================================

@router.post(
    "/departments",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Department",
)
async def create_department(
    payload: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new department, optionally nested under a parent department."""
    existing = await Department.get_by_name(db, payload.name)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Department '{payload.name}' already exists",
        )

    if payload.parent_department_id is not None:
        await _get_department_or_404(db, payload.parent_department_id)

    department = await Department.create_one(
        db=db,
        name=payload.name,
        description=payload.description,
        parent_department_id=payload.parent_department_id,
    )
    if department is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to create department",
        )

    return department


@router.get(
    "/departments",
    response_model=PaginatedDepartmentsResponse,
    status_code=status.HTTP_200_OK,
    summary="List Departments (Paginated)",
)
async def list_departments(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a paginated list of departments."""
    items, total = await Department.get_all_paginated(
        db=db, page=page, page_size=page_size
    )
    return PaginatedDepartmentsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/departments/tree",
    response_model=List[DepartmentTreeNode],
    status_code=status.HTTP_200_OK,
    summary="Get Organisational Department Tree",
)
async def get_department_tree(db: AsyncSession = Depends(get_db)):
    """Build and return the full hierarchical department tree."""
    all_depts = await Department.get_all(db)
    nodes: Dict[UUID, DepartmentTreeNode] = {
        dept.department_id: DepartmentTreeNode(
            department_id=dept.department_id,
            name=dept.name,
            description=dept.description,
            parent_department_id=dept.parent_department_id,
            children=[],
        )
        for dept in all_depts
    }

    roots: List[DepartmentTreeNode] = []
    for dept in all_depts:
        node = nodes[dept.department_id]
        if dept.parent_department_id and dept.parent_department_id in nodes:
            nodes[dept.parent_department_id].children.append(node)
        else:
            roots.append(node)

    return roots


@router.get(
    "/departments/roots",
    response_model=List[DepartmentResponse],
    status_code=status.HTTP_200_OK,
    summary="Get Root Departments",
)
async def get_root_departments(db: AsyncSession = Depends(get_db)):
    """Retrieve top-level departments with no parent department."""
    return await Department.get_root_departments(db)


@router.get(
    "/departments/{department_id}",
    response_model=DepartmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Department by ID",
)
async def get_department(
    department_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a single department with parent, sub-departments, and employees."""
    return await _get_department_or_404(db, department_id)


@router.get(
    "/departments/{department_id}/children",
    response_model=List[DepartmentResponse],
    status_code=status.HTTP_200_OK,
    summary="Get Child Departments",
)
async def get_department_children(
    department_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve direct child departments for a given department."""
    await _get_department_or_404(db, department_id)
    return await Department.get_children(db, department_id)


@router.get(
    "/departments/{department_id}/employees",
    response_model=List[EmployeeResponse],
    status_code=status.HTTP_200_OK,
    summary="Get Department Employees",
)
async def get_department_employees(
    department_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all employees currently assigned to a department."""
    await _get_department_or_404(db, department_id)
    return await Employee.get_by_department_id(db, department_id)


@router.patch(
    "/departments/{department_id}",
    response_model=DepartmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Department",
)
async def update_department(
    department_id: UUID,
    payload: DepartmentUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update department name, description, or parent department."""
    await _get_department_or_404(db, department_id)

    updates = payload.model_dump(exclude_unset=True)
    if "parent_department_id" in updates and updates["parent_department_id"] is not None:
        if updates["parent_department_id"] == department_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A department cannot be its own parent",
            )
        await _get_department_or_404(db, updates["parent_department_id"])

    if "name" in updates and updates["name"] is not None:
        existing = await Department.get_by_name(db, updates["name"])
        if existing is not None and existing.department_id != department_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Department '{updates['name']}' already exists",
            )

    updated = await Department.update_one(
        db=db,
        department_id=department_id,
        updates=updates,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to update department",
        )
    return updated


@router.delete(
    "/departments/{department_id}",
    response_model=ActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Department",
)
async def delete_department(
    department_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a department if it has no dependent employees, child departments, or history records."""
    await _get_department_or_404(db, department_id)
    deleted = await Department.delete_by_id(db, department_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Department could not be deleted (it may still be referenced by employees or sub-departments)",
        )
    return ActionResponse(message="Department deleted successfully")


# ===========================================================================
# EMPLOYEES (CRUD & QUERIES)
# ===========================================================================

@router.post(
    "/employees",
    response_model=EmployeeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create / Onboard Employee",
)
async def create_employee(
    payload: EmployeeCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a central employee record, record the initial status in
    EmploymentStatusHistory, and create an initial EmploymentHistory assignment
    if department_id is provided.
    """
    # if await Employee.get_by_employee_number(db, payload.employee_number) is not None:
    #     raise HTTPException(
    #         status_code=status.HTTP_409_CONFLICT,
    #         detail=f"Employee number '{payload.employee_number}' already exists",
    #     )
    if payload.email and await Employee.get_by_email(db, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{payload.email}' is already in use",
        )
    if payload.username and await Employee.get_by_username(db, payload.username) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{payload.username}' is already in use",
        )
    if payload.department_id is not None:
        await _get_department_or_404(db, payload.department_id)
    if payload.manager_id is not None:
        await _get_employee_or_404(db, payload.manager_id)
    if payload.end_date is not None and payload.end_date < payload.start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date cannot be earlier than start_date",
        )

    employee = await Employee.create_one(
        db=db,
        #employee_number=payload.employee_number,
        first_name=payload.first_name,
        last_name=payload.last_name,
        date_of_birth=payload.date_of_birth,
        email=payload.email,
        phone_number=payload.phone_number,
        address=payload.address,
        username=payload.username,
        department_id=payload.department_id,
        manager_id=payload.manager_id,
        job_title=payload.job_title,
        employment_status=payload.employment_status,
        employment_type=payload.employment_type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        contract_end_date=payload.contract_end_date,
        hours_per_week=payload.hours_per_week,
        fte=payload.fte,
        probation_end_date=payload.probation_end_date,
    )
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to create employee record",
        )

    await EmploymentStatusHistory.create_one(
        db=db,
        employee_id=employee.employee_id,
        previous_status=None,
        new_status=payload.employment_status,
        effective_date=payload.start_date,
        reason=payload.initial_status_reason,
    )

    if payload.department_id is not None:
        await EmploymentHistory.create_one(
            db=db,
            employee_id=employee.employee_id,
            department_id=payload.department_id,
            manager_id=payload.manager_id,
            job_title=payload.job_title,
            effective_from=payload.start_date,
            effective_to=payload.end_date,
        )

    return await Employee.get_by_id(db, employee.employee_id)


@router.get(
    "/employees",
    response_model=PaginatedEmployeesResponse,
    status_code=status.HTTP_200_OK,
    summary="List Employees (Filtered & Paginated)",
)
async def list_employees(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    employment_status: Optional[EmploymentStatus] = Query(default=None),
    employment_type: Optional[EmploymentType] = Query(default=None),
    department_id: Optional[UUID] = Query(default=None),
    manager_id: Optional[UUID] = Query(default=None),
    search: Optional[str] = Query(
        default=None,
        description="Filter by employee_number, name, email, username, or job_title",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a paginated list of employees with optional filtering."""
    filters = []
    if employment_status is not None:
        filters.append(Employee.employment_status == employment_status)
    if employment_type is not None:
        filters.append(Employee.employment_type == employment_type)
    if department_id is not None:
        filters.append(Employee.department_id == department_id)
    if manager_id is not None:
        filters.append(Employee.manager_id == manager_id)
    if search:
        term = f"%{search.strip()}%"
        filters.append(
            or_(
                Employee.employee_number.ilike(term),
                Employee.first_name.ilike(term),
                Employee.last_name.ilike(term),
                Employee.email.ilike(term),
                Employee.username.ilike(term),
                Employee.job_title.ilike(term),
            )
        )

    count_stmt = select(func.count()).select_from(Employee)
    query_stmt = select(Employee).options(*Employee._default_options())

    if filters:
        count_stmt = count_stmt.where(*filters)
        query_stmt = query_stmt.where(*filters)

    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        query_stmt.order_by(Employee.employee_number.asc())
        .offset(offset)
        .limit(page_size)
    )
    items = result.scalars().all()

    return PaginatedEmployeesResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/employees/by-number/{employee_number}",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Employee by Employee Number",
)
async def get_employee_by_number(
    employee_number: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve an employee using their unique employee number."""
    employee = await Employee.get_by_employee_number(db, employee_number)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee with number '{employee_number}' not found",
        )
    return employee


@router.get(
    "/employees/{employee_id}",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Employee by ID",
)
async def get_employee(
    employee_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a full employee profile including history and absences."""
    return await _get_employee_or_404(db, employee_id)


@router.get(
    "/employees/{employee_id}/direct-reports",
    response_model=List[EmployeeSummary],
    status_code=status.HTTP_200_OK,
    summary="Get Employee Direct Reports",
)
async def get_direct_reports(
    employee_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all employees who report directly to the specified manager."""
    await _get_employee_or_404(db, employee_id)
    return await Employee.get_by_manager_id(db, employee_id)


@router.patch(
    "/employees/{employee_id}",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Employee Details",
)
async def update_employee(
    employee_id: UUID,
    payload: EmployeeUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update employee personal, contact, or contract fields.
    Use the /lifecycle endpoints for status transitions and departmental transfers
    so full audit history is maintained.
    """
    existing = await _get_employee_or_404(db, employee_id)
    updates = payload.model_dump(exclude_unset=True)

    if "department_id" in updates and updates["department_id"] is not None:
        await _get_department_or_404(db, updates["department_id"])

    if "manager_id" in updates and updates["manager_id"] is not None:
        if updates["manager_id"] == employee_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An employee cannot be their own manager",
            )
        await _get_employee_or_404(db, updates["manager_id"])

    effective_start = updates.get("start_date", existing.start_date)
    effective_end = updates.get("end_date", existing.end_date)
    if effective_end is not None and effective_end < effective_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date cannot be earlier than start_date",
        )

    updated = await Employee.update_one(
        db=db,
        employee_id=employee_id,
        updates=updates,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Failed to update employee (check unique constraints on employee_number, email, or username)",
        )
    return updated


@router.delete(
    "/employees/{employee_id}",
    response_model=ActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Employee",
)
async def delete_employee(
    employee_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete an employee record if no dependent records block deletion."""
    await _get_employee_or_404(db, employee_id)
    deleted = await Employee.delete_by_id(db, employee_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Employee could not be deleted (check dependent history, absences, or direct reports)",
        )
    return ActionResponse(message="Employee deleted successfully")


# ===========================================================================
# EMPLOYEE LIFECYCLE MANAGEMENT
# ===========================================================================

@router.get(
    "/employees/{employee_id}/lifecycle",
    response_model=EmployeeLifecycleOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Employee Lifecycle Overview",
)
async def get_employee_lifecycle(
    employee_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Return the consolidated lifecycle state for an employee: current status,
    allowed next transitions, current assignment, and full history timelines.
    """
    employee = await _get_employee_or_404(db, employee_id)
    current_assignment = await EmploymentHistory.get_current_by_employee_id(db, employee_id)
    status_history = await EmploymentStatusHistory.get_by_employee_id(db, employee_id)
    employment_history = await EmploymentHistory.get_by_employee_id(db, employee_id)
    absences = await EmployeeAbsence.get_by_employee_id(db, employee_id)

    allowed = sorted(
        ALLOWED_STATUS_TRANSITIONS.get(employee.employment_status, set()),
        key=lambda s: s.value,
    )

    return EmployeeLifecycleOverviewResponse(
        employee=employee,
        start_date=employee.start_date,
        end_date=employee.end_date,
        contract_end_date=employee.contract_end_date,
        probation_end_date=employee.probation_end_date,
        current_department=employee.department,
        current_manager=employee.manager,
        current_assignment=current_assignment,
        allowed_next_statuses=allowed,
        employment_history=employment_history,
        status_history=status_history,
        absences=absences,
    )


@router.post(
    "/employees/{employee_id}/lifecycle/status",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Transition Employee Lifecycle Status",
)
async def transition_employee_status(
    employee_id: UUID,
    payload: LifecycleStatusTransitionRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Validate and apply a lifecycle status change, recording the transition in
    EmploymentStatusHistory. Automatically closes open assignments when moving
    to TERMINATED or RETIRED.
    """
    employee = await _get_employee_or_404(db, employee_id)
    return await _apply_status_transition(
        db=db,
        employee=employee,
        new_status=payload.new_status,
        effective_date=payload.effective_date,
        reason=payload.reason,
        end_date=payload.end_date,
        close_open_assignment=payload.new_status in TERMINAL_STATUSES,
        force=payload.force,
    )


@router.post(
    "/employees/{employee_id}/lifecycle/activate",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate / Start Employee",
)
async def activate_employee(
    employee_id: UUID,
    payload: LifecycleActivateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Transition an employee to ACTIVE (typically from PENDING on start date,
    or returning from SUSPENDED / LONG_TERM_ABSENCE / NOTICE_PERIOD).
    """
    employee = await _get_employee_or_404(db, employee_id)

    extra_updates = {}
    if payload.start_date is not None:
        extra_updates["start_date"] = payload.start_date
    if payload.probation_end_date is not None:
        extra_updates["probation_end_date"] = payload.probation_end_date
    if extra_updates:
        employee = await Employee.update_one(db, employee_id, extra_updates)

    if payload.complete_ongoing_absences:
        ongoing_absences = await EmployeeAbsence.get_active_by_employee_id(db, employee_id)
        for absence in ongoing_absences:
            await EmployeeAbsence.update_status(
                db=db,
                absence_id=absence.absence_id,
                status=AbsenceStatus.COMPLETED,
                end_date=payload.effective_date,
            )

    return await _apply_status_transition(
        db=db,
        employee=employee,
        new_status=EmploymentStatus.ACTIVE,
        effective_date=payload.effective_date,
        reason=payload.reason or "Employee activated",
    )


@router.post(
    "/employees/{employee_id}/lifecycle/suspend",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Suspend Employee",
)
async def suspend_employee(
    employee_id: UUID,
    payload: LifecycleActionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Temporarily suspend an employee and log the status transition."""
    employee = await _get_employee_or_404(db, employee_id)
    return await _apply_status_transition(
        db=db,
        employee=employee,
        new_status=EmploymentStatus.SUSPENDED,
        effective_date=payload.effective_date,
        reason=payload.reason or "Employee suspended",
    )


@router.post(
    "/employees/{employee_id}/lifecycle/reinstate",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Reinstate Suspended Employee",
)
async def reinstate_employee(
    employee_id: UUID,
    payload: LifecycleActionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reinstate a SUSPENDED employee back to ACTIVE."""
    employee = await _get_employee_or_404(db, employee_id)
    if employee.employment_status != EmploymentStatus.SUSPENDED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only SUSPENDED employees can be reinstated (current status: '{employee.employment_status.value}')",
        )
    return await _apply_status_transition(
        db=db,
        employee=employee,
        new_status=EmploymentStatus.ACTIVE,
        effective_date=payload.effective_date,
        reason=payload.reason or "Suspension lifted; employee reinstated",
    )


@router.post(
    "/employees/{employee_id}/lifecycle/long-term-absence",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Place Employee on Long-Term Absence",
)
async def start_long_term_absence(
    employee_id: UUID,
    payload: LifecycleLongTermAbsenceRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Transition an employee to LONG_TERM_ABSENCE and optionally create a
    corresponding ONGOING absence record.
    """
    employee = await _get_employee_or_404(db, employee_id)
    updated = await _apply_status_transition(
        db=db,
        employee=employee,
        new_status=EmploymentStatus.LONG_TERM_ABSENCE,
        effective_date=payload.effective_date,
        reason=payload.reason or "Placed on long-term absence",
    )

    if payload.create_absence_record:
        await EmployeeAbsence.create_one(
            db=db,
            employee_id=employee_id,
            absence_type=payload.absence_type,
            start_date=payload.effective_date,
            end_date=payload.expected_end_date,
            reason=payload.reason,
            status=AbsenceStatus.ONGOING,
        )
        updated = await Employee.get_by_id(db, employee_id)

    return updated


@router.post(
    "/employees/{employee_id}/lifecycle/return-to-work",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Return Employee from Long-Term Absence",
)
async def return_to_work(
    employee_id: UUID,
    payload: LifecycleReturnToWorkRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Transition an employee from LONG_TERM_ABSENCE back to ACTIVE and optionally
    close any ONGOING absence records.
    """
    employee = await _get_employee_or_404(db, employee_id)
    if employee.employment_status != EmploymentStatus.LONG_TERM_ABSENCE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Only employees with status LONG_TERM_ABSENCE can use return-to-work "
                f"(current status: '{employee.employment_status.value}')"
            ),
        )

    if payload.complete_ongoing_absences:
        ongoing_absences = await EmployeeAbsence.get_active_by_employee_id(db, employee_id)
        for absence in ongoing_absences:
            await EmployeeAbsence.update_status(
                db=db,
                absence_id=absence.absence_id,
                status=AbsenceStatus.COMPLETED,
                end_date=payload.effective_date,
            )

    return await _apply_status_transition(
        db=db,
        employee=employee,
        new_status=EmploymentStatus.ACTIVE,
        effective_date=payload.effective_date,
        reason=payload.reason or "Returned to work",
    )


@router.post(
    "/employees/{employee_id}/lifecycle/notice",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Place Employee on Notice Period",
)
async def place_on_notice(
    employee_id: UUID,
    payload: LifecycleExitRequest,
    db: AsyncSession = Depends(get_db),
):
    """Transition an employee to NOTICE_PERIOD and optionally record planned end_date."""
    employee = await _get_employee_or_404(db, employee_id)
    return await _apply_status_transition(
        db=db,
        employee=employee,
        new_status=EmploymentStatus.NOTICE_PERIOD,
        effective_date=payload.effective_date,
        reason=payload.reason or "Placed on notice period",
        end_date=payload.end_date,
    )


@router.post(
    "/employees/{employee_id}/lifecycle/terminate",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Terminate Employment",
)
async def terminate_employee(
    employee_id: UUID,
    payload: LifecycleExitRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Transition an employee to TERMINATED, record end_date, log status history,
    and close their open EmploymentHistory assignment.
    """
    employee = await _get_employee_or_404(db, employee_id)
    return await _apply_status_transition(
        db=db,
        employee=employee,
        new_status=EmploymentStatus.TERMINATED,
        effective_date=payload.effective_date,
        reason=payload.reason or "Employment terminated",
        end_date=payload.end_date or payload.effective_date,
        close_open_assignment=payload.close_open_assignment,
    )


@router.post(
    "/employees/{employee_id}/lifecycle/retire",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Retire Employee",
)
async def retire_employee(
    employee_id: UUID,
    payload: LifecycleExitRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Transition an employee to RETIRED, record end_date, log status history,
    and close their open EmploymentHistory assignment.
    """
    employee = await _get_employee_or_404(db, employee_id)
    return await _apply_status_transition(
        db=db,
        employee=employee,
        new_status=EmploymentStatus.RETIRED,
        effective_date=payload.effective_date,
        reason=payload.reason or "Employee retired",
        end_date=payload.end_date or payload.effective_date,
        close_open_assignment=payload.close_open_assignment,
    )


@router.post(
    "/employees/{employee_id}/lifecycle/transfer",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Transfer / Promote Employee Assignment",
)
async def transfer_employee_assignment(
    employee_id: UUID,
    payload: LifecycleTransferRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Move an employee to a new department, job title, or manager.
    Closes the current open EmploymentHistory record and creates a new assignment.
    """
    employee = await _get_employee_or_404(db, employee_id)
    if employee.employment_status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot transfer an employee with status '{employee.employment_status.value}'",
        )

    await _get_department_or_404(db, payload.department_id)
    if payload.manager_id is not None:
        if payload.manager_id == employee_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An employee cannot be their own manager",
            )
        await _get_employee_or_404(db, payload.manager_id)

    updated = await Employee.update_assignment(
        db=db,
        employee_id=employee_id,
        department_id=payload.department_id,
        job_title=payload.job_title,
        effective_from=payload.effective_from,
        manager_id=payload.manager_id,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to update employee assignment",
        )
    return updated


# ===========================================================================
# EMPLOYMENT HISTORY
# ===========================================================================

@router.post(
    "/employment-history",
    response_model=EmploymentHistoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Employment History Record",
)
async def create_employment_history(
    payload: EmploymentHistoryCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a historical or current organisational assignment record."""
    await _get_employee_or_404(db, payload.employee_id)
    await _get_department_or_404(db, payload.department_id)
    if payload.manager_id is not None:
        if payload.manager_id == payload.employee_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An employee cannot be their own manager",
            )
        await _get_employee_or_404(db, payload.manager_id)
    if payload.effective_to is not None and payload.effective_to < payload.effective_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="effective_to cannot be earlier than effective_from",
        )

    record = await EmploymentHistory.create_one(
        db=db,
        employee_id=payload.employee_id,
        department_id=payload.department_id,
        manager_id=payload.manager_id,
        job_title=payload.job_title,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to create employment history record",
        )
    return record


@router.get(
    "/employment-history",
    response_model=PaginatedEmploymentHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="List Employment History (Paginated)",
)
async def list_employment_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a paginated list of all employment history assignments."""
    items, total = await EmploymentHistory.get_all_paginated(
        db=db, page=page, page_size=page_size
    )
    return PaginatedEmploymentHistoryResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/employment-history/{employment_id}",
    response_model=EmploymentHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Employment History Record by ID",
)
async def get_employment_history_record(
    employment_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a single employment history record."""
    record = await EmploymentHistory.get_by_id(db, employment_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employment history record '{employment_id}' not found",
        )
    return record


@router.get(
    "/employees/{employee_id}/employment-history",
    response_model=List[EmploymentHistoryResponse],
    status_code=status.HTTP_200_OK,
    summary="Get Employee Assignment History",
)
async def get_employee_employment_history(
    employee_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all employment assignment history for an employee."""
    await _get_employee_or_404(db, employee_id)
    return await EmploymentHistory.get_by_employee_id(db, employee_id)


@router.get(
    "/employees/{employee_id}/employment-history/current",
    response_model=EmploymentHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Employee Current Assignment",
)
async def get_current_employee_assignment(
    employee_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve the open (effective_to IS NULL) assignment record for an employee."""
    await _get_employee_or_404(db, employee_id)
    record = await EmploymentHistory.get_current_by_employee_id(db, employee_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No open assignment found for employee '{employee_id}'",
        )
    return record


@router.patch(
    "/employment-history/{employment_id}",
    response_model=EmploymentHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Employment History Record",
)
async def update_employment_history_record(
    employment_id: UUID,
    payload: EmploymentHistoryUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing employment history record."""
    existing = await EmploymentHistory.get_by_id(db, employment_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employment history record '{employment_id}' not found",
        )

    updates = payload.model_dump(exclude_unset=True)
    if "department_id" in updates and updates["department_id"] is not None:
        await _get_department_or_404(db, updates["department_id"])
    if "manager_id" in updates and updates["manager_id"] is not None:
        if updates["manager_id"] == existing.employee_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An employee cannot be their own manager",
            )
        await _get_employee_or_404(db, updates["manager_id"])

    effective_from = updates.get("effective_from", existing.effective_from)
    effective_to = updates.get("effective_to", existing.effective_to)
    if effective_to is not None and effective_to < effective_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="effective_to cannot be earlier than effective_from",
        )

    updated = await EmploymentHistory.update_one(db, employment_id, updates)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to update employment history record",
        )
    return updated


@router.post(
    "/employees/{employee_id}/employment-history/close",
    response_model=EmploymentHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Close Current Assignment",
)
async def close_current_assignment(
    employee_id: UUID,
    payload: CloseAssignmentRequest,
    db: AsyncSession = Depends(get_db),
):
    """Close the currently open employment assignment for an employee."""
    await _get_employee_or_404(db, employee_id)
    current = await EmploymentHistory.get_current_by_employee_id(db, employee_id)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No open assignment found for employee '{employee_id}'",
        )
    if payload.effective_to < current.effective_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="effective_to cannot be earlier than effective_from",
        )

    closed = await EmploymentHistory.close_current_assignment(
        db=db,
        employee_id=employee_id,
        effective_to=payload.effective_to,
    )
    if closed is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to close open assignment",
        )
    return closed


@router.delete(
    "/employment-history/{employment_id}",
    response_model=ActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Employment History Record",
)
async def delete_employment_history_record(
    employment_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete an employment history record by ID."""
    deleted = await EmploymentHistory.delete_by_id(db, employment_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employment history record '{employment_id}' not found",
        )
    return ActionResponse(message="Employment history record deleted successfully")


# ===========================================================================
# EMPLOYEE ABSENCES
# ===========================================================================

@router.post(
    "/absences",
    response_model=EmployeeAbsenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Employee Absence",
)
async def create_absence(
    payload: EmployeeAbsenceCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new absence record for an employee."""
    await _get_employee_or_404(db, payload.employee_id)
    if payload.end_date is not None and payload.end_date < payload.start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date cannot be earlier than start_date",
        )

    absence = await EmployeeAbsence.create_one(
        db=db,
        employee_id=payload.employee_id,
        absence_type=payload.absence_type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        reason=payload.reason,
        status=payload.status,
    )
    if absence is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to create absence record",
        )
    return absence


@router.get(
    "/absences",
    response_model=PaginatedEmployeeAbsencesResponse,
    status_code=status.HTTP_200_OK,
    summary="List Employee Absences (Paginated)",
)
async def list_absences(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    absence_status: Optional[AbsenceStatus] = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve paginated absence records, optionally filtered by absence status."""
    if absence_status is not None:
        count_stmt = (
            select(func.count())
            .select_from(EmployeeAbsence)
            .where(EmployeeAbsence.status == absence_status)
        )
        total = (await db.execute(count_stmt)).scalar_one()
        offset = (page - 1) * page_size
        result = await db.execute(
            select(EmployeeAbsence)
            .options(*EmployeeAbsence._default_options())
            .where(EmployeeAbsence.status == absence_status)
            .order_by(EmployeeAbsence.start_date.desc())
            .offset(offset)
            .limit(page_size)
        )
        items = result.scalars().all()
    else:
        items, total = await EmployeeAbsence.get_all_paginated(
            db=db, page=page, page_size=page_size
        )

    return PaginatedEmployeeAbsencesResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/absences/{absence_id}",
    response_model=EmployeeAbsenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Absence by ID",
)
async def get_absence(
    absence_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a single absence record by ID."""
    absence = await EmployeeAbsence.get_by_id(db, absence_id)
    if absence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Absence '{absence_id}' not found",
        )
    return absence


@router.get(
    "/employees/{employee_id}/absences",
    response_model=List[EmployeeAbsenceResponse],
    status_code=status.HTTP_200_OK,
    summary="Get Employee Absences",
)
async def get_employee_absences(
    employee_id: UUID,
    active_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all absences (or only ONGOING absences) for an employee."""
    await _get_employee_or_404(db, employee_id)
    if active_only:
        return await EmployeeAbsence.get_active_by_employee_id(db, employee_id)
    return await EmployeeAbsence.get_by_employee_id(db, employee_id)


@router.patch(
    "/absences/{absence_id}",
    response_model=EmployeeAbsenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Absence Record",
)
async def update_absence(
    absence_id: UUID,
    payload: EmployeeAbsenceUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update fields on an existing employee absence record."""
    existing = await EmployeeAbsence.get_by_id(db, absence_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Absence '{absence_id}' not found",
        )

    updates = payload.model_dump(exclude_unset=True)
    start_date = updates.get("start_date", existing.start_date)
    end_date = updates.get("end_date", existing.end_date)
    if end_date is not None and end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date cannot be earlier than start_date",
        )

    updated = await EmployeeAbsence.update_one(db, absence_id, updates)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to update absence record",
        )
    return updated


@router.patch(
    "/absences/{absence_id}/status",
    response_model=EmployeeAbsenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Absence Status",
)
async def update_absence_status(
    absence_id: UUID,
    payload: EmployeeAbsenceStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update the status (PLANNED, ONGOING, COMPLETED, CANCELLED) of an absence."""
    existing = await EmployeeAbsence.get_by_id(db, absence_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Absence '{absence_id}' not found",
        )
    if payload.end_date is not None and payload.end_date < existing.start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date cannot be earlier than start_date",
        )

    updated = await EmployeeAbsence.update_status(
        db=db,
        absence_id=absence_id,
        status=payload.status,
        end_date=payload.end_date,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to update absence status",
        )
    return updated


@router.delete(
    "/absences/{absence_id}",
    response_model=ActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Absence Record",
)
async def delete_absence(
    absence_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete an absence record by ID."""
    deleted = await EmployeeAbsence.delete_by_id(db, absence_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Absence '{absence_id}' not found",
        )
    return ActionResponse(message="Absence record deleted successfully")


# ===========================================================================
# EMPLOYMENT STATUS HISTORY (AUDIT LOG)
# ===========================================================================

@router.get(
    "/status-history",
    response_model=PaginatedStatusHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="List Employment Status History (Paginated)",
)
async def list_status_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve paginated employment status history entries."""
    items, total = await EmploymentStatusHistory.get_all_paginated(
        db=db, page=page, page_size=page_size
    )
    return PaginatedStatusHistoryResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/status-history/{status_history_id}",
    response_model=EmploymentStatusHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Status History Record by ID",
)
async def get_status_history_record(
    status_history_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a single employment status history record."""
    record = await EmploymentStatusHistory.get_by_id(db, status_history_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Status history record '{status_history_id}' not found",
        )
    return record


@router.get(
    "/employees/{employee_id}/status-history",
    response_model=List[EmploymentStatusHistoryResponse],
    status_code=status.HTTP_200_OK,
    summary="Get Employee Status History",
)
async def get_employee_status_history(
    employee_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve the complete employment status change timeline for an employee."""
    await _get_employee_or_404(db, employee_id)
    return await EmploymentStatusHistory.get_by_employee_id(db, employee_id)


@router.get(
    "/employees/{employee_id}/status-history/latest",
    response_model=EmploymentStatusHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Latest Employee Status Change",
)
async def get_latest_employee_status_change(
    employee_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve the most recent employment status history entry for an employee."""
    await _get_employee_or_404(db, employee_id)
    record = await EmploymentStatusHistory.get_latest_by_employee_id(db, employee_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No status history found for employee '{employee_id}'",
        )
    return record


@router.patch(
    "/status-history/{status_history_id}",
    response_model=EmploymentStatusHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Status History Record",
)
async def update_status_history_record(
    status_history_id: UUID,
    payload: EmploymentStatusHistoryUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Correct metadata (such as reason or effective_date) on a status history entry."""
    existing = await EmploymentStatusHistory.get_by_id(db, status_history_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Status history record '{status_history_id}' not found",
        )

    updates = payload.model_dump(exclude_unset=True)
    updated = await EmploymentStatusHistory.update_one(db, status_history_id, updates)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to update status history record",
        )
    return updated


@router.delete(
    "/status-history/{status_history_id}",
    response_model=ActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Status History Record",
)
async def delete_status_history_record(
    status_history_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete an employment status history record by ID."""
    deleted = await EmploymentStatusHistory.delete_by_id(db, status_history_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Status history record '{status_history_id}' not found",
        )
    return ActionResponse(message="Status history record deleted successfully")