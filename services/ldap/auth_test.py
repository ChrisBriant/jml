from services.ldap.ldap import LDAPService


def main():
    ldap_service = LDAPService()
    #ldap_service.reset_password("alovelace","LowBattery64=")
    auth_response = ldap_service.authenticate_user("alovelace","LowBattery64=")
    print("AUTH RESPONSE CORRECT PW", auth_response)
    auth_response = ldap_service.authenticate_user("alovelace","NotAPassword64=")
    print("AUTH RESPONSE WRONG PW", auth_response)


if __name__ == "__main__":
    main()

