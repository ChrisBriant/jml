from .db import SessionLocal
from .models.system_user import SystemUser
from .models.enums import UserRole
import os, dotenv, asyncio

dotenv_file = ".env"
if os.path.isfile(dotenv_file):
    dotenv.load_dotenv(dotenv_file)


HR_SYSTEM_ADMIN_PASSWORD = os.environ.get("HR_SYSTEM_ADMIN_PASSWORD")

async def main():
    async with SessionLocal() as session:
        #await SystemUser.create_one(db=session,username="admin",password=f"{HR_SYSTEM_ADMIN_PASSWORD}",role=UserRole.ADMIN)
        #await SystemUser.create_one(db=session,username="reader",password="Schim&Re4der",role=UserRole.READER)
        await SystemUser.create_one(db=session,username="jml",password="JoinMyLeg$11",role=UserRole.READER)

if __name__ == "__main__":
    asyncio.run(main())