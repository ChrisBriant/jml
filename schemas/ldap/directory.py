from pydantic import BaseModel, EmailStr, Field


# ==========================================
# ACTION / STATUS RESPONSE SCHEMA
# ==========================================


class LDAPLoginRequest(BaseModel):
    username: str = Field(min_length=1, description="Username (uid) or email")
    password: str = Field(min_length=1, description="Plaintext password")


class LoginSuccessResponse(BaseModel):
    success: bool = True
    message: str = "Authentication successful"


class LDAPActionResponse(BaseModel):
    """Standard response for mutations like disable, delete, move, or membership actions."""
    success: bool
    message: str
    ldap_code: int = 0
    details: str | None = None


# ==========================================
# USER SCHEMAS
# ==========================================

class LDAPUser(BaseModel):
    """Representation of an LDAP directory user."""
    uid: str = Field(min_length=1, max_length=64)
    cn: str = Field(min_length=1, max_length=256)
    sn: str = Field(min_length=1, max_length=128)
    given_name: str = Field(min_length=1, max_length=128)
    mail: EmailStr
    department: str | None = None
    title: str | None = None
    dn: str | None = None

    object_classes: list[str] = Field(
        default_factory=lambda: [
            "top",
            "person",
            "organizationalPerson",
            "inetOrgPerson",
        ]
    )


class LDAPUserUpdate(BaseModel):
    """Schema for updating user attributes."""
    cn: str | None = Field(default=None, min_length=1, max_length=256)
    sn: str | None = Field(default=None, min_length=1, max_length=128)
    given_name: str | None = Field(default=None, min_length=1, max_length=128)
    mail: EmailStr | None = None
    department: str | None = None
    title: str | None = None


# ==========================================
# GROUP SCHEMAS
# ==========================================

class LDAPGroupCreate(BaseModel):
    """Schema to create a new group."""
    cn: str = Field(min_length=1, max_length=128, description="Group name")
    description: str | None = None
    members: list[str] = Field(default_factory=list)
    object_classes: list[str] = Field(
        default_factory=lambda: [
            "top",
            "groupOfNames",
        ]
    )


class LDAPGroup(BaseModel):
    """Representation of an existing LDAP group."""
    dn: str
    cn: str
    description: str | None = None
    members: list[str] = Field(default_factory=list)
    object_classes: list[str] = Field(
        default_factory=lambda: [
            "top",
            "groupOfNames",
        ]
    )


class LDAPGroupMemberAction(BaseModel):
    """Schema to add or remove a member from a group."""
    user_dn: str = Field(min_length=1, description="Full DN of the user")
    group_dn: str = Field(min_length=1, description="Full DN of the group")


# ==========================================
# OU & MOVE SCHEMAS
# ==========================================

class LDAPOUCreate(BaseModel):
    """Schema to create an Organizational Unit (OU)."""
    name: str = Field(min_length=1, max_length=128, description="OU name (ou)")
    description: str | None = None
    parent_dn: str | None = Field(
        default=None,
        description="Parent DN where the OU will be placed. Defaults to base DN."
    )
    object_classes: list[str] = Field(
        default_factory=lambda: [
            "top",
            "organizationalUnit",
        ]
    )


class LDAPOU(BaseModel):
    """Representation of an Organizational Unit (OU)."""
    dn: str
    ou: str
    description: str | None = None
    object_classes: list[str] = Field(
        default_factory=lambda: [
            "top",
            "organizationalUnit",
        ]
    )


class LDAPMoveObject(BaseModel):
    """Schema to move an object to another parent OU."""
    current_dn: str = Field(min_length=1, description="Full DN of the object to move")
    new_parent_dn: str = Field(min_length=1, description="Target parent OU DN")


# ==========================================
# DIRECTORY SNAPSHOT & TREE SCHEMAS
# ==========================================

class LDAPDirectorySnapshot(BaseModel):
    """Flat snapshot representing all directory entries."""
    base_dn: str = Field(default="dc=neuropunk")
    ous: list[LDAPOU] = Field(default_factory=list)
    users: list[LDAPUser] = Field(default_factory=list)
    groups: list[LDAPGroup] = Field(default_factory=list)


class LDAPTreeOU(BaseModel):
    """An Organizational Unit containing its child objects and sub-OUs."""
    ou: str
    dn: str
    description: str | None = None
    users: list[LDAPUser] = Field(default_factory=list)
    groups: list[LDAPGroup] = Field(default_factory=list)
    children_ous: list["LDAPTreeOU"] = Field(default_factory=list)


# Resolve the recursive forward reference
LDAPTreeOU.model_rebuild()


class LDAPDirectoryTree(BaseModel):
    """The root of the directory tree."""
    base_dn: str = "dc=neuropunk"
    root_ous: list[LDAPTreeOU] = Field(default_factory=list)