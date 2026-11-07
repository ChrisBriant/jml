import os
import dotenv
from ldap3 import Server, Connection, MODIFY_REPLACE, MODIFY_ADD, MODIFY_DELETE, SUBTREE
from schemas.ldap.directory import (
    LDAPUser,
    LDAPUserUpdate,
    LDAPGroup,
    LDAPGroupCreate,
    LDAPGroupMemberAction,
    LDAPOU,
    LDAPOUCreate,
    LDAPMoveObject,
)
from datetime import datetime, timezone, timedelta
import jwt
from pathlib import Path
from ldap3 import SUBTREE  # Ensure this is imported at top of ldap.py

ROOT_DIR = Path(__file__).resolve().parents[2]
dotenv.load_dotenv(ROOT_DIR / ".env")

# JWT Settings (add to your .env or keep sensible defaults)
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "change-me-in-production-super-secret-key")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_MINUTES = int(os.environ.get("JWT_EXPIRATION_MINUTES", 480))  # 8 hours


# LOAD ENVIRONMENT
PROJECT_ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if (parent / ".env").exists()
)

dotenv_file = f"{PROJECT_ROOT}/.env"
print(dotenv_file)
if os.path.isfile(dotenv_file):
    dotenv.load_dotenv(dotenv_file)

LDAP_HOST = os.environ.get("LDAP_HOST", "localhost")
LDAP_BASE_DN = os.environ.get("LDAP_BASE_DN", "dc=neuropunk")
LDAP_BIND_DN = os.environ.get("LDAP_BIND_DN", f"cn=admin,{LDAP_BASE_DN}")
LDAP_SERVICE_PASSWORD = os.environ.get("LDAP_SERVICE_PASSWORD")
print("LDAP SERVICE PASSWORD", LDAP_SERVICE_PASSWORD)

class LDAPService:

    def __init__(self):
        self.base_dn = LDAP_BASE_DN
        self.people_ou = f"ou=People,{self.base_dn}"
        self.groups_ou = f"ou=Groups,{self.base_dn}"

        self.server = Server(LDAP_HOST)
        self.connection = Connection(
            self.server,
            user=LDAP_BIND_DN,
            password=LDAP_SERVICE_PASSWORD,
            auto_bind=True
        )


    def _get_dn_by_filter(self, search_filter: str) -> str | None:
        """Find the exact DN of an entry across the directory."""
        self.connection.search(
            search_base=self.base_dn,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=[]
        )
        if self.connection.entries:
            return self.connection.entries[0].entry_dn
        return None

    # ==========================================
    # USER OPERATIONS
    # ==========================================

    def create_user(self, user: LDAPUser) -> dict:
        """Add a user using the LDAPUser schema."""
        dn = user.dn or f"uid={user.uid},{self.people_ou}"

        attributes = {
            "objectClass": user.object_classes,
            "uid": user.uid,
            "cn": user.cn,
            "sn": user.sn,
            "givenName": user.given_name,
            "mail": str(user.mail),
        }

        if user.department:
            attributes["ou"] = user.department

        if user.title:
            attributes["title"] = user.title

        self.connection.add(dn, attributes=attributes)
        return self.connection.result

    def get_users(self) -> list[LDAPUser]:
        """Retrieve users mapped to LDAPUser schemas."""
        self.connection.search(
            search_base=self.base_dn,
            search_filter="(objectClass=inetOrgPerson)",
            search_scope=SUBTREE,
            attributes=[
                "uid",
                "cn",
                "sn",
                "givenName",
                "mail",
                "ou",
                "title",
                "objectClass"
            ]
        )

        users = []
        for entry in self.connection.entries:
            users.append(
                LDAPUser(
                    uid=str(entry.uid),
                    cn=str(entry.cn),
                    sn=str(entry.sn),
                    given_name=str(entry.givenName),
                    mail=str(entry.mail),
                    department=str(entry.ou) if entry.ou else None,
                    title=str(entry.title) if entry.title else None,
                    dn=entry.entry_dn,
                    object_classes=list(entry.objectClass)
                )
            )

        return users

    def get_user(self, uid: str) -> LDAPUser | None:
        """Retrieve a single user by uid mapped to LDAPUser."""
        self.connection.search(
            search_base=self.base_dn,
            search_filter=f"(&(objectClass=inetOrgPerson)(uid={uid}))",
            search_scope=SUBTREE,
            attributes=[
                "uid",
                "cn",
                "sn",
                "givenName",
                "mail",
                "ou",
                "title",
                "objectClass"
            ]
        )

        if not self.connection.entries:
            return None

        entry = self.connection.entries[0]
        return LDAPUser(
            uid=str(entry.uid),
            cn=str(entry.cn),
            sn=str(entry.sn),
            given_name=str(entry.givenName),
            mail=str(entry.mail),
            department=str(entry.ou) if entry.ou else None,
            title=str(entry.title) if entry.title else None,
            dn=entry.entry_dn,
            object_classes=list(entry.objectClass)
        )

    def update_user(self, uid: str, updates: LDAPUserUpdate) -> dict:
        """Update user attributes using the LDAPUserUpdate schema."""
        user_dn = self._get_dn_by_filter(f"(&(objectClass=inetOrgPerson)(uid={uid}))")
        if not user_dn:
            return {"result": 32, "description": "noSuchObject"}

        # Convert non-None fields to LDAP attribute mapping
        update_data = updates.model_dump(exclude_unset=True)
        ldap_attribute_map = {
            "cn": "cn",
            "sn": "sn",
            "given_name": "givenName",
            "mail": "mail",
            "department": "ou",
            "title": "title",
        }

        changes = {}
        for field, value in update_data.items():
            ldap_attr = ldap_attribute_map.get(field)
            if ldap_attr and value is not None:
                changes[ldap_attr] = [(MODIFY_REPLACE, [str(value)])]

        if changes:
            self.connection.modify(user_dn, changes)

        return self.connection.result

    def disable_user(self, uid: str) -> dict:
        """Disable a user by setting the ppolicy pwdAccountLockedTime."""
        user_dn = self._get_dn_by_filter(f"(&(objectClass=inetOrgPerson)(uid={uid}))")
        if not user_dn:
            return {"result": 32, "description": "noSuchObject"}

        lock_timestamp = "00000101000000Z"
        self.connection.modify(
            user_dn,
            {"pwdAccountLockedTime": [(MODIFY_REPLACE, [lock_timestamp])]}
        )
        return self.connection.result

    def delete_user(self, uid: str) -> dict:
        """Delete a user entry by uid."""
        user_dn = self._get_dn_by_filter(f"(&(objectClass=inetOrgPerson)(uid={uid}))")
        if not user_dn:
            return {"result": 32, "description": "noSuchObject"}

        self.connection.delete(user_dn)
        return self.connection.result

    def authenticate_user(self, username: str, password: str) -> str | None:
        """
        Authenticate a user using the search-then-bind pattern.
        Returns an encoded JWT string with user claims if successful, or None.
        """
        if not username or not password:
            return None

        # 1. Resolve user entry and DN by uid or email
        self.connection.search(
            search_base=self.base_dn,
            search_filter=f"(|(uid={username})(mail={username}))",
            search_scope=SUBTREE,
            attributes=["uid", "cn", "sn", "givenName", "mail", "ou", "title"]
        )

        if not self.connection.entries:
            return None

        user_entry = self.connection.entries[0]
        user_dn = user_entry.entry_dn

        # 2. Attempt to bind using the user's DN and password
        user_connection = Connection(
            self.server,
            user=user_dn,
            password=password,
            auto_bind=False
        )

        try:
            if not user_connection.bind():
                return None  # Invalid credentials
        finally:
            user_connection.unbind()

        # 3. Retrieve groups where this user is a member (for RBAC)
        self.connection.search(
            search_base=self.base_dn,
            search_filter=f"(&(objectClass=groupOfNames)(member={user_dn}))",
            search_scope=SUBTREE,
            attributes=["cn"]
        )
        groups = [str(grp.cn) for grp in self.connection.entries]

        # 4. Construct JWT Claims Payload
        now = datetime.now(timezone.utc)
        payload = {
            # Standard claims
            "sub": str(user_entry.uid),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=JWT_EXPIRATION_MINUTES)).timestamp()),
            
            # User profile claims
            "email": str(user_entry.mail) if user_entry.mail else None,
            "name": str(user_entry.cn) if user_entry.cn else None,
            "given_name": str(user_entry.givenName) if user_entry.givenName else None,
            "family_name": str(user_entry.sn) if user_entry.sn else None,
            "department": str(user_entry.ou) if user_entry.ou else None,
            "title": str(user_entry.title) if user_entry.title else None,
            
            # Authorization / RBAC claim
            "groups": groups
        }

        # 5. Sign and return the JWT
        print("ENCODING WITH KEY:", repr(JWT_SECRET_KEY))
        token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        return token

    def reset_password(self, uid: str, new_password: str) -> dict:
        """
        Reset a user's password using the LDAP Password Modify
        Extended Operation (RFC 3062).
        """
        user_dn = self._get_dn_by_filter(f"(&(objectClass=inetOrgPerson)(uid={uid}))")
        if not user_dn:
            return {"result": 32, "description": "noSuchObject"}

        self.connection.extend.standard.modify_password(
            user=user_dn,
            new_password=new_password
        )
        return self.connection.result

    # ==========================================
    # GROUP OPERATIONS
    # ==========================================

    def create_group(self, group: LDAPGroupCreate) -> dict:
        """Add a group using the LDAPGroupCreate schema."""
        dn = f"cn={group.cn},{self.groups_ou}"

        # RFC 2256 groupOfNames requires at least one member.
        members = group.members if group.members else [LDAP_BIND_DN]

        attributes = {
            "objectClass": group.object_classes,
            "cn": group.cn,
            "member": members,
        }

        if group.description:
            attributes["description"] = group.description

        self.connection.add(dn, attributes=attributes)
        return self.connection.result

    def get_groups(self) -> list[LDAPGroup]:
        """Retrieve all groups across the entire directory tree."""
        self.connection.search(
            search_base=self.base_dn,  # <-- Search from root (dc=neuropunk) instead of self.groups_ou
            search_filter="(|(objectClass=groupOfNames)(objectClass=groupOfUniqueNames)(objectClass=posixGroup))",
            search_scope=SUBTREE,      # <-- Recursively traverses all child OUs
            attributes=["cn", "description", "member", "uniqueMember", "objectClass"]
        )

        groups = []
        for entry in self.connection.entries:
            # Handle member attributes whether groupOfNames or groupOfUniqueNames
            members = []
            if hasattr(entry, "member") and entry.member:
                members = list(entry.member)
            elif hasattr(entry, "uniqueMember") and entry.uniqueMember:
                members = list(entry.uniqueMember)

            groups.append(
                LDAPGroup(
                    dn=entry.entry_dn,
                    cn=str(entry.cn),
                    description=str(entry.description) if hasattr(entry, "description") and entry.description else None,
                    members=members,
                    object_classes=list(entry.objectClass)
                )
            )
        return groups

    def add_user_to_group(self, action: LDAPGroupMemberAction) -> dict:
        """Add a user's DN to a group using LDAPGroupMemberAction schema."""
        self.connection.modify(
            action.group_dn,
            {"member": [(MODIFY_ADD, [action.user_dn])]}
        )
        return self.connection.result

    def remove_user_from_group(self, action: LDAPGroupMemberAction) -> dict:
        """Remove a user's DN from a group using LDAPGroupMemberAction schema."""
        self.connection.modify(
            action.group_dn,
            {"member": [(MODIFY_DELETE, [action.user_dn])]}
        )
        return self.connection.result

    # ==========================================
    # OU & TREE OPERATIONS
    # ==========================================

    def create_ou(self, ou: LDAPOUCreate) -> dict:
        """Create an Organizational Unit using LDAPOUCreate schema."""
        parent = ou.parent_dn if ou.parent_dn else self.base_dn
        dn = f"ou={ou.name},{parent}"

        attributes = {
            "objectClass": ou.object_classes,
            "ou": ou.name,
        }

        if ou.description:
            attributes["description"] = ou.description

        self.connection.add(dn, attributes=attributes)
        return self.connection.result
    
    def move_object(self, move_action: LDAPMoveObject) -> dict:
        """Move an object to a new parent OU."""
        # Extract RDN (e.g. 'cn=GLOBAL_READER')
        rdn = move_action.current_dn.split(",", 1)[0]

        self.connection.modify_dn(
            dn=move_action.current_dn,
            relative_dn=rdn,
            new_superior=move_action.new_parent_dn
        )
        # MUST return the result dict
        return self.connection.result