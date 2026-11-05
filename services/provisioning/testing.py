from services.ldap.ldap import LDAPService
from schemas.ldap.directory import LDAPUser

def main():
    ldap_service = LDAPService()
    #Create a user
    # test_user = LDAPUser(
    #     uid="jsmith",
    #     cn="John Smith",
    #     sn="Smith",
    #     given_name="John",
    #     mail="john.smith@neuropunk.co.uk",
    #     department="IT",
    #     title="Systems Administrator"
    # )
    # add_user_result = ldap_service.create_user(test_user)
    #print("NEW USER", add_user_result)
    users = ldap_service.get_users()
    print("THESE ARE THE USERS", users)

if __name__ == "__main__":
    main()