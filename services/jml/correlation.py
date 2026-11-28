import asyncio
import json
from services.ldap.ldap import LDAPService
from database.jml.models.iga_user import IGAUser


async def main():
    #Get the users from the target system
    ldap_service = LDAPService()
    target_system_users = ldap_service.get_users(
        search_base="ou=People,dc=neuropunk"
    )
    print("Target System Users",json.dumps(target_system_users[0].__dict__,indent=4))
    #TODO: WORK FROM THIS IN MATCHING THE JML IGA USER DATA BASED ON employee_number



if __name__ == "__main__":
    asyncio.run(main())