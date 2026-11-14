import asyncio
from .db import engine, Base
from database.hr.models.department import Department
from database.hr.models.employee import Employee
from database.hr.models.employee_absence import EmployeeAbsence
from database.hr.models.employment_history import EmploymentHistory
from database.hr.models.employment_status_history import EmploymentStatusHistory
from sqlalchemy import text


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        )

        
if __name__ == "__main__":
    asyncio.run(main())