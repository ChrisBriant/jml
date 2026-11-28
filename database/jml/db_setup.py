import asyncio
from .db import engine, Base
from database.jml.models.iga_audit import IGAAudit
from database.jml.models.iga_provisioning import IGAProvisioning
from database.jml.models.iga_user import IGAUser
from database.jml.models.jml_cycle_run import JMLCycleRun
from sqlalchemy import text


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        )

        
if __name__ == "__main__":
    asyncio.run(main())