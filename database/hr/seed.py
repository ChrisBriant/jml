import asyncio
from datetime import date, timedelta
from decimal import Decimal

from database.hr.models import (
    AbsenceStatus,
    AbsenceType,
    Department,
    Employee,
    EmployeeAbsence,
    EmploymentHistory,
    EmploymentStatus,
    EmploymentStatusHistory,
    EmploymentType,
)
from database.hr.db import Base, SessionLocal, engine


async def ensure_tables():
    """Create tables if they do not already exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def seed_departments(db) -> dict[str, Department]:
    """Seed the organisational department hierarchy."""
    existing_org = await Department.get_by_name(db, "Organisation")
    if existing_org is not None:
        print("Departments already seeded — skipping.")
        all_depts = await Department.get_all(db)
        return {dept.name: dept for dept in all_depts}

    org = await Department.create_one(
        db=db,
        name="Organisation",
        description="Executive leadership and top-level organisation.",
    )

    it = await Department.create_one(
        db=db,
        name="IT",
        description="Information Technology division.",
        parent_department_id=org.department_id,
    )
    finance = await Department.create_one(
        db=db,
        name="Finance",
        description="Accounting, payroll, and financial planning.",
        parent_department_id=org.department_id,
    )
    hr = await Department.create_one(
        db=db,
        name="Human Resources",
        description="People operations, recruitment, and employee relations.",
        parent_department_id=org.department_id,
    )
    operations = await Department.create_one(
        db=db,
        name="Operations",
        description="Day-to-day business and facilities operations.",
        parent_department_id=org.department_id,
    )

    infrastructure = await Department.create_one(
        db=db,
        name="Infrastructure",
        description="Cloud, networking, and core systems infrastructure.",
        parent_department_id=it.department_id,
    )
    security = await Department.create_one(
        db=db,
        name="Security",
        description="Information security, compliance, and IAM.",
        parent_department_id=it.department_id,
    )
    development = await Department.create_one(
        db=db,
        name="Development",
        description="Software engineering and internal platforms.",
        parent_department_id=it.department_id,
    )

    depts = [
        org,
        it,
        finance,
        hr,
        operations,
        infrastructure,
        security,
        development,
    ]
    print(f"Seeded {len(depts)} departments.")
    return {dept.name: dept for dept in depts}


async def create_employee_with_initial_history(
    db,
    *,
    employee_number: str,
    first_name: str,
    last_name: str,
    job_title: str,
    department: Department,
    employment_type: EmploymentType,
    start_date: date,
    initial_status: EmploymentStatus = EmploymentStatus.ACTIVE,
    manager: Employee | None = None,
    date_of_birth: date | None = None,
    email: str | None = None,
    phone_number: str | None = None,
    address: str | None = None,
    username: str | None = None,
    contract_end_date: date | None = None,
    hours_per_week: Decimal | None = Decimal("37.50"),
    fte: Decimal | None = Decimal("1.00"),
    probation_end_date: date | None = None,
    status_reason: str = "Initial employment record created",
) -> Employee:
    """Create an employee plus their initial EmploymentHistory and EmploymentStatusHistory."""
    employee = await Employee.create_one(
        db=db,
        employee_number=employee_number,
        first_name=first_name,
        last_name=last_name,
        date_of_birth=date_of_birth,
        email=email,
        phone_number=phone_number,
        address=address,
        username=username,
        department_id=department.department_id,
        manager_id=manager.employee_id if manager else None,
        job_title=job_title,
        employment_status=initial_status,
        employment_type=employment_type,
        start_date=start_date,
        contract_end_date=contract_end_date,
        hours_per_week=hours_per_week,
        fte=fte,
        probation_end_date=probation_end_date,
    )

    await EmploymentHistory.create_one(
        db=db,
        employee_id=employee.employee_id,
        department_id=department.department_id,
        manager_id=manager.employee_id if manager else None,
        job_title=job_title,
        effective_from=start_date,
        effective_to=None,
    )

    await EmploymentStatusHistory.create_one(
        db=db,
        employee_id=employee.employee_id,
        previous_status=None,
        new_status=initial_status,
        effective_date=start_date,
        reason=status_reason,
    )

    return employee


async def seed_employees_and_histories(
    db, depts: dict[str, Department]
) -> dict[str, Employee]:
    """Seed employees, reporting hierarchy, assignment history, and status history."""
    existing = await Employee.get_by_employee_number(db, "EMP0001")
    if existing is not None:
        print("Employees already seeded — skipping.")
        all_employees = await Employee.get_all(db)
        return {emp.employee_number: emp for emp in all_employees}

    today = date.today()

    # 1. Executive & Department Heads
    eleanor = await create_employee_with_initial_history(
        db,
        employee_number="EMP0001",
        first_name="Eleanor",
        last_name="Vance",
        date_of_birth=date(1978, 4, 12),
        email="eleanor.vance@example.co.uk",
        phone_number="+44 20 7946 0101",
        address="14 Bishopsgate, London, EC2N 4BQ",
        username="evance",
        department=depts["Organisation"],
        job_title="Chief Executive Officer",
        employment_type=EmploymentType.PERMANENT_FULL_TIME,
        start_date=date(2019, 1, 7),
        probation_end_date=date(2019, 7, 7),
    )

    marcus = await create_employee_with_initial_history(
        db,
        employee_number="EMP0002",
        first_name="Marcus",
        last_name="Sterling",
        date_of_birth=date(1983, 9, 23),
        email="marcus.sterling@example.co.uk",
        phone_number="+44 20 7946 0102",
        address="28 Clerkenwell Road, London, EC1M 5PS",
        username="msterling",
        department=depts["IT"],
        manager=eleanor,
        job_title="Head of IT",
        employment_type=EmploymentType.PERMANENT_FULL_TIME,
        start_date=date(2020, 3, 2),
        probation_end_date=date(2020, 9, 2),
    )

    priya = await create_employee_with_initial_history(
        db,
        employee_number="EMP0003",
        first_name="Priya",
        last_name="Patel",
        date_of_birth=date(1985, 11, 5),
        email="priya.patel@example.co.uk",
        phone_number="+44 20 7946 0103",
        address="9 King Street, Manchester, M2 6AW",
        username="ppatel",
        department=depts["Finance"],
        manager=eleanor,
        job_title="Finance Director",
        employment_type=EmploymentType.PERMANENT_FULL_TIME,
        start_date=date(2020, 6, 15),
        probation_end_date=date(2020, 12, 15),
    )

    hannah = await create_employee_with_initial_history(
        db,
        employee_number="EMP0004",
        first_name="Hannah",
        last_name="Brooks",
        date_of_birth=date(1987, 2, 19),
        email="hannah.brooks@example.co.uk",
        phone_number="+44 20 7946 0104",
        address="41 Colmore Row, Birmingham, B3 2BS",
        username="hbrooks",
        department=depts["Human Resources"],
        manager=eleanor,
        job_title="HR Director",
        employment_type=EmploymentType.PERMANENT_FULL_TIME,
        start_date=date(2021, 1, 11),
        probation_end_date=date(2021, 7, 11),
    )

    david = await create_employee_with_initial_history(
        db,
        employee_number="EMP0005",
        first_name="David",
        last_name="Okafor",
        date_of_birth=date(1981, 7, 30),
        email="david.okafor@example.co.uk",
        phone_number="+44 20 7946 0105",
        address="7 Queen Square, Bristol, BS1 4JE",
        username="dokafor",
        department=depts["Operations"],
        manager=eleanor,
        job_title="Head of Operations",
        employment_type=EmploymentType.PERMANENT_FULL_TIME,
        start_date=date(2020, 9, 1),
        probation_end_date=date(2021, 3, 1),
    )

    # 2. IT Staff (including an internal transfer & promotion to showcase EmploymentHistory)
    liam = await create_employee_with_initial_history(
        db,
        employee_number="EMP0006",
        first_name="Liam",
        last_name="Gallagher",
        date_of_birth=date(1990, 5, 14),
        email="liam.gallagher@example.co.uk",
        phone_number="+44 20 7946 0106",
        address="19 Victoria Street, Leeds, LS1 6AA",
        username="lgallagher",
        department=depts["Infrastructure"],
        manager=marcus,
        job_title="Infrastructure Engineer",
        employment_type=EmploymentType.PERMANENT_FULL_TIME,
        start_date=date(2021, 4, 1),
        initial_status=EmploymentStatus.PENDING,
        probation_end_date=date(2021, 10, 1),
        status_reason="Offer accepted; awaiting start date",
    )
    liam = await Employee.change_status(
        db=db,
        employee_id=liam.employee_id,
        new_status=EmploymentStatus.ACTIVE,
        effective_date=date(2021, 4, 1),
        reason="Commenced employment",
    )
    # Transfer Liam from Infrastructure -> Security
    liam = await Employee.update_assignment(
        db=db,
        employee_id=liam.employee_id,
        department_id=depts["Security"].department_id,
        job_title="Senior Security Engineer",
        effective_from=date(2023, 8, 1),
        manager_id=marcus.employee_id,
    )

    sophie = await create_employee_with_initial_history(
        db,
        employee_number="EMP0007",
        first_name="Sophie",
        last_name="Turner",
        date_of_birth=date(1991, 8, 22),
        email="sophie.turner@example.co.uk",
        phone_number="+44 20 7946 0107",
        address="62 George Street, Edinburgh, EH2 2LR",
        username="sturner",
        department=depts["Development"],
        manager=marcus,
        job_title="Software Engineer",
        employment_type=EmploymentType.PERMANENT_FULL_TIME,
        start_date=date(2021, 10, 4),
        probation_end_date=date(2022, 4, 4),
    )
    # Promote Sophie within Development
    sophie = await Employee.update_assignment(
        db=db,
        employee_id=sophie.employee_id,
        department_id=depts["Development"].department_id,
        job_title="Lead Software Engineer",
        effective_from=date(2024, 1, 1),
        manager_id=marcus.employee_id,
    )

    oliver = await create_employee_with_initial_history(
        db,
        employee_number="EMP0008",
        first_name="Oliver",
        last_name="Bennett",
        date_of_birth=date(1989, 12, 3),
        email="oliver.bennett@example.co.uk",
        phone_number="+44 20 7946 0108",
        address="5 Castle Meadow, Norwich, NR1 3PY",
        username="obennett",
        department=depts["Infrastructure"],
        manager=marcus,
        job_title="Senior Infrastructure Engineer",
        employment_type=EmploymentType.PERMANENT_FULL_TIME,
        start_date=date(2022, 2, 14),
        probation_end_date=date(2022, 8, 14),
    )
    oliver = await Employee.change_status(
        db=db,
        employee_id=oliver.employee_id,
        new_status=EmploymentStatus.LONG_TERM_ABSENCE,
        effective_date=today - timedelta(days=30),
        reason="Extended medical leave",
    )

    # 3. Part-time, Fixed-term, Contractor, Intern, Apprentice, Temporary
    amelia = await create_employee_with_initial_history(
        db,
        employee_number="EMP0009",
        first_name="Amelia",
        last_name="Hughes",
        date_of_birth=date(1993, 6, 17),
        email="amelia.hughes@example.co.uk",
        phone_number="+44 20 7946 0109",
        address="33 Grey Street, Newcastle, NE1 6EE",
        username="ahughes",
        department=depts["Human Resources"],
        manager=hannah,
        job_title="HR Advisor",
        employment_type=EmploymentType.PERMANENT_PART_TIME,
        start_date=date(2022, 5, 9),
        hours_per_week=Decimal("22.50"),
        fte=Decimal("0.60"),
        probation_end_date=date(2022, 11, 9),
    )

    noah = await create_employee_with_initial_history(
        db,
        employee_number="EMP0010",
        first_name="Noah",
        last_name="Campbell",
        date_of_birth=date(1984, 1, 28),
        email="noah.campbell@example.co.uk",
        phone_number="+44 20 7946 0110",
        address="88 St Vincent Street, Glasgow, G2 5UB",
        username="ncampbell",
        department=depts["Security"],
        manager=liam,
        job_title="Cloud Security Consultant",
        employment_type=EmploymentType.CONTRACTOR,
        start_date=today - timedelta(days=90),
        contract_end_date=today + timedelta(days=180),
        hours_per_week=Decimal("40.00"),
        fte=Decimal("1.00"),
    )

    chloe = await create_employee_with_initial_history(
        db,
        employee_number="EMP0011",
        first_name="Chloe",
        last_name="Mitchell",
        date_of_birth=date(1995, 3, 9),
        email="chloe.mitchell@example.co.uk",
        phone_number="+44 20 7946 0111",
        address="12 High Pavement, Nottingham, NG1 1HN",
        username="cmitchell",
        department=depts["Finance"],
        manager=priya,
        job_title="Financial Analyst",
        employment_type=EmploymentType.FIXED_TERM_FULL_TIME,
        start_date=today - timedelta(days=120),
        contract_end_date=today + timedelta(days=245),
        probation_end_date=today - timedelta(days=30),
    )

    jack = await create_employee_with_initial_history(
        db,
        employee_number="EMP0012",
        first_name="Jack",
        last_name="Robinson",
        date_of_birth=date(1994, 10, 11),
        email="jack.robinson@example.co.uk",
        phone_number="+44 20 7946 0112",
        address="4 Westgate, Cardiff, CF10 1DD",
        username="jrobinson",
        department=depts["Operations"],
        manager=david,
        job_title="Operations Coordinator",
        employment_type=EmploymentType.FIXED_TERM_PART_TIME,
        start_date=today - timedelta(days=60),
        contract_end_date=today + timedelta(days=305),
        hours_per_week=Decimal("18.75"),
        fte=Decimal("0.50"),
    )

    mia = await create_employee_with_initial_history(
        db,
        employee_number="EMP0013",
        first_name="Mia",
        last_name="Davies",
        date_of_birth=date(2003, 7, 2),
        email="mia.davies@example.co.uk",
        phone_number="+44 20 7946 0113",
        address="21 Fargate, Sheffield, S1 2HD",
        username="mdavies",
        department=depts["Development"],
        manager=sophie,
        job_title="Software Engineering Intern",
        employment_type=EmploymentType.INTERN,
        start_date=today + timedelta(days=14),
        initial_status=EmploymentStatus.PENDING,
        contract_end_date=today + timedelta(days=104),
        status_reason="Pre-boarding in progress",
    )

    ethan = await create_employee_with_initial_history(
        db,
        employee_number="EMP0014",
        first_name="Ethan",
        last_name="Wright",
        date_of_birth=date(2004, 11, 20),
        email="ethan.wright@example.co.uk",
        phone_number="+44 20 7946 0114",
        address="17 Bold Street, Liverpool, L1 4DN",
        username="ewright",
        department=depts["Infrastructure"],
        manager=oliver,
        job_title="IT Support Apprentice",
        employment_type=EmploymentType.APPRENTICE,
        start_date=date(2024, 9, 2),
        contract_end_date=date(2026, 9, 1),
        probation_end_date=date(2024, 12, 2),
    )

    grace = await create_employee_with_initial_history(
        db,
        employee_number="EMP0015",
        first_name="Grace",
        last_name="Taylor",
        date_of_birth=date(1998, 5, 27),
        email="grace.taylor@example.co.uk",
        phone_number="+44 20 7946 0115",
        address="50 Market Street, Cambridge, CB2 3PA",
        username="gtaylor",
        department=depts["Operations"],
        manager=david,
        job_title="Temporary Operations Assistant",
        employment_type=EmploymentType.TEMPORARY,
        start_date=today - timedelta(days=75),
        contract_end_date=today + timedelta(days=14),
    )
    grace = await Employee.change_status(
        db=db,
        employee_id=grace.employee_id,
        new_status=EmploymentStatus.NOTICE_PERIOD,
        effective_date=today - timedelta(days=7),
        reason="Temporary assignment concluding",
    )

    # 4. Remaining status examples: SUSPENDED, RETIRED, TERMINATED
    lucas = await create_employee_with_initial_history(
        db,
        employee_number="EMP0016",
        first_name="Lucas",
        last_name="Edwards",
        date_of_birth=date(1988, 8, 8),
        email="lucas.edwards@example.co.uk",
        phone_number="+44 20 7946 0116",
        address="8 Guildhall Street, Exeter, EX4 3HJ",
        username="ledwards",
        department=depts["Infrastructure"],
        manager=marcus,
        job_title="Systems Administrator",
        employment_type=EmploymentType.PERMANENT_FULL_TIME,
        start_date=date(2022, 11, 1),
        probation_end_date=date(2023, 5, 1),
    )
    lucas = await Employee.change_status(
        db=db,
        employee_id=lucas.employee_id,
        new_status=EmploymentStatus.SUSPENDED,
        effective_date=today - timedelta(days=5),
        reason="Pending internal compliance review",
    )

    arthur = await create_employee_with_initial_history(
        db,
        employee_number="EMP0017",
        first_name="Arthur",
        last_name="Pendelton",
        date_of_birth=date(1959, 2, 15),
        email="arthur.pendelton@example.co.uk",
        phone_number="+44 20 7946 0117",
        address="22 Cornmarket Street, Oxford, OX1 3EY",
        username="apendelton",
        department=depts["Finance"],
        manager=priya,
        job_title="Principal Finance Controller",
        employment_type=EmploymentType.PERMANENT_FULL_TIME,
        start_date=date(2015, 5, 1),
    )
    retired_date = date(2025, 12, 31)
    arthur = await Employee.change_status(
        db=db,
        employee_id=arthur.employee_id,
        new_status=EmploymentStatus.RETIRED,
        effective_date=retired_date,
        reason="Voluntary retirement",
        end_date=retired_date,
    )
    await EmploymentHistory.close_current_assignment(
        db=db,
        employee_id=arthur.employee_id,
        effective_to=retired_date,
    )

    ruby = await create_employee_with_initial_history(
        db,
        employee_number="EMP0018",
        first_name="Ruby",
        last_name="Clarke",
        date_of_birth=date(1996, 1, 16),
        email="ruby.clarke@example.co.uk",
        phone_number="+44 20 7946 0118",
        address="11 Abbeygate Street, Bury St Edmunds, IP33 1UN",
        username="rclarke",
        department=depts["Development"],
        manager=sophie,
        job_title="Backend Developer",
        employment_type=EmploymentType.PERMANENT_FULL_TIME,
        start_date=date(2023, 3, 6),
        probation_end_date=date(2023, 9, 6),
    )
    notice_date = today - timedelta(days=60)
    exit_date = today - timedelta(days=30)
    ruby = await Employee.change_status(
        db=db,
        employee_id=ruby.employee_id,
        new_status=EmploymentStatus.NOTICE_PERIOD,
        effective_date=notice_date,
        reason="Resignation submitted",
    )
    ruby = await Employee.change_status(
        db=db,
        employee_id=ruby.employee_id,
        new_status=EmploymentStatus.TERMINATED,
        effective_date=exit_date,
        reason="Resignation completed",
        end_date=exit_date,
    )
    await EmploymentHistory.close_current_assignment(
        db=db,
        employee_id=ruby.employee_id,
        effective_to=exit_date,
    )

    employees = [
        eleanor,
        marcus,
        priya,
        hannah,
        david,
        liam,
        sophie,
        oliver,
        amelia,
        noah,
        chloe,
        jack,
        mia,
        ethan,
        grace,
        lucas,
        arthur,
        ruby,
    ]
    print(f"Seeded {len(employees)} employees with assignment and status history.")
    return {emp.employee_number: emp for emp in employees}


async def seed_absences(db, employees: dict[str, Employee]):
    """Seed sample absence records covering all AbsenceType and AbsenceStatus values."""
    existing = await EmployeeAbsence.get_all(db)
    if existing:
        print("Absences already seeded — skipping.")
        return

    today = date.today()

    absences = [
        # ONGOING - SICKNESS (matches Oliver's LONG_TERM_ABSENCE status)
        dict(
            employee_id=employees["EMP0008"].employee_id,
            absence_type=AbsenceType.SICKNESS,
            start_date=today - timedelta(days=30),
            end_date=None,
            reason="Extended post-surgery recovery",
            status=AbsenceStatus.ONGOING,
        ),
        # COMPLETED - SICKNESS
        dict(
            employee_id=employees["EMP0007"].employee_id,
            absence_type=AbsenceType.SICKNESS,
            start_date=today - timedelta(days=45),
            end_date=today - timedelta(days=43),
            reason="Seasonal flu",
            status=AbsenceStatus.COMPLETED,
        ),
        # PLANNED - MATERNITY
        dict(
            employee_id=employees["EMP0009"].employee_id,
            absence_type=AbsenceType.MATERNITY,
            start_date=today + timedelta(days=45),
            end_date=today + timedelta(days=315),
            reason="Scheduled maternity leave",
            status=AbsenceStatus.PLANNED,
        ),
        # COMPLETED - PATERNITY
        dict(
            employee_id=employees["EMP0006"].employee_id,
            absence_type=AbsenceType.PATERNITY,
            start_date=today - timedelta(days=150),
            end_date=today - timedelta(days=136),
            reason="Two-week statutory paternity leave",
            status=AbsenceStatus.COMPLETED,
        ),
        # PLANNED - ADOPTION
        dict(
            employee_id=employees["EMP0011"].employee_id,
            absence_type=AbsenceType.ADOPTION,
            start_date=today + timedelta(days=60),
            end_date=today + timedelta(days=150),
            reason="Planned adoption leave",
            status=AbsenceStatus.PLANNED,
        ),
        # CANCELLED - PARENTAL_LEAVE
        dict(
            employee_id=employees["EMP0002"].employee_id,
            absence_type=AbsenceType.PARENTAL_LEAVE,
            start_date=today + timedelta(days=20),
            end_date=today + timedelta(days=27),
            reason="Rescheduled to later in the year",
            status=AbsenceStatus.CANCELLED,
        ),
        # COMPLETED - UNPAID_LEAVE
        dict(
            employee_id=employees["EMP0014"].employee_id,
            absence_type=AbsenceType.UNPAID_LEAVE,
            start_date=today - timedelta(days=20),
            end_date=today - timedelta(days=18),
            reason="Personal family travel",
            status=AbsenceStatus.COMPLETED,
        ),
        # ONGOING - OTHER
        dict(
            employee_id=employees["EMP0005"].employee_id,
            absence_type=AbsenceType.OTHER,
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=3),
            reason="Jury service",
            status=AbsenceStatus.ONGOING,
        ),
    ]

    for item in absences:
        await EmployeeAbsence.create_one(db=db, **item)

    print(f"Seeded {len(absences)} employee absence records.")


async def seed_all():
    await ensure_tables()
    async with SessionLocal() as db:
        depts = await seed_departments(db)
        employees = await seed_employees_and_histories(db, depts)
        await seed_absences(db, employees)
    print("Database seeding complete.")


if __name__ == "__main__":
    asyncio.run(seed_all())