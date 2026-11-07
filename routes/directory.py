from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status, Response

from schemas.ldap.directory import (
    LDAPUser,
    LDAPUserUpdate,
    LDAPGroup,
    LDAPGroupCreate,
    LDAPGroupMemberAction,
    LDAPOU,
    LDAPOUCreate,
    LDAPMoveObject,
    LDAPDirectorySnapshot,
    LDAPDirectoryTree,
    LDAPActionResponse,
    LDAPLoginRequest,
    LoginSuccessResponse,
)
from services.ldap.ldap import LDAPService
from services.ldap.export_directory import fetch_all_ous, build_directory_tree
import os
from services.ldap.jwt import TokenClaims
from services.ldap.authorisation import require_groups

router = APIRouter(tags=["LDAP Directory"])

# Cookie Configuration
COOKIE_NAME = "access_token"
COOKIE_MAX_AGE = int(os.environ.get("JWT_EXPIRATION_MINUTES", 480)) * 60  # in seconds (8 hours)
IS_PRODUCTION = os.environ.get("ENVIRONMENT", "development").lower() == "production"

def get_ldap_service() -> LDAPService:
    """Dependency provider for LDAPService."""
    return LDAPService()


@router.post(
    "/login",
    response_model=LoginSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate User and Set Cookie",
)
async def login(
    credentials: LDAPLoginRequest,
    response: Response,
    service: LDAPService = Depends(get_ldap_service),
):
    """
    Authenticate against LDAP via username and password.
    On success: Sets an HttpOnly session cookie containing the JWT.
    On failure: Raises HTTP 401 Unauthorized.
    """
    # 1. Attempt authentication and retrieve signed JWT
    jwt_token = service.authenticate_user(
        username=credentials.username,
        password=credentials.password
    )

    # 2. If credentials failed, return 401
    if not jwt_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Set the Secure HttpOnly cookie in the browser
    response.set_cookie(
        key=COOKIE_NAME,
        value=jwt_token,
        httponly=True,            # Prevents JavaScript (XSS) access
        secure=IS_PRODUCTION,    # True in production (HTTPS only), False on http://localhost
        samesite="lax",           # Mitigates CSRF while allowing standard top-level navigation
        max_age=COOKIE_MAX_AGE,   # Cookie lifetime in seconds (matches JWT expiration)
        path="/",                 # Cookie is valid across the whole domain
    )

    return LoginSuccessResponse()


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Logout User",
)
async def logout(response: Response):
    """Clear the session cookie to log the user out."""
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax"
    )
    return {"message": "Successfully logged out"}


def handle_ldap_result(result: dict, success_message: str) -> LDAPActionResponse:
    """Helper to translate LDAP return codes to proper HTTP responses."""
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LDAP operation returned no result",
        )
    code = result.get("result", -1)
    description = result.get("description", "Unknown LDAP error")

    if code == 0:  # LDAP Success
        return LDAPActionResponse(success=True, message=success_message, ldap_code=code)
    elif code == 32:  # noSuchObject
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Resource not found in LDAP directory: {description}",
        )
    elif code == 68:  # entryAlreadyExists
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Entry already exists in LDAP directory: {description}",
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"LDAP Error ({code}): {description}",
        )


# ============================================================================
# USER ENDPOINTS
# ============================================================================

@router.post(
    "/users",
    response_model=LDAPUser,
    status_code=status.HTTP_201_CREATED,
    summary="Create User",
)
async def create_user_ldap(
    user: LDAPUser,
    service: LDAPService = Depends(get_ldap_service),
):
    """Create a new user entry in the LDAP directory."""
    result = service.create_user(user)
    handle_ldap_result(result, f"User {user.uid} created successfully")

    created = service.get_user(user.uid)
    return created or user


@router.get(
    "/users",
    response_model=List[LDAPUser],
    summary="List Users",
)
async def get_users_ldap(
    service: LDAPService = Depends(get_ldap_service),
    current_user: TokenClaims = Depends(require_groups(["GLOBAL_READER","GLOBAL_ADMIN"]))
):
    """Retrieve all users registered under the base directory."""
    print("CURRENT USER IS", current_user)
    return service.get_users()


@router.get(
    "/users/{uid}",
    response_model=LDAPUser,
    summary="Get User by UID",
)
async def get_user_ldap(
    uid: str,
    service: LDAPService = Depends(get_ldap_service),
):
    """Retrieve a single user by their uid."""
    user = service.get_user(uid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with uid '{uid}' not found",
        )
    return user


@router.patch(
    "/users/{uid}",
    response_model=LDAPUser,
    summary="Update User Attributes",
)
async def update_user_ldap(
    uid: str,
    updates: LDAPUserUpdate,
    service: LDAPService = Depends(get_ldap_service),
):
    """Update user attributes (title, department, name, mail, etc.)."""
    result = service.update_user(uid, updates)
    handle_ldap_result(result, f"User {uid} updated successfully")

    updated = service.get_user(uid)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found after update")
    return updated


@router.post(
    "/users/{uid}/disable",
    response_model=LDAPActionResponse,
    summary="Disable User Account",
)
async def disable_user_ldap(
    uid: str,
    service: LDAPService = Depends(get_ldap_service),
):
    """Lock user account via OpenLDAP ppolicy."""
    result = service.disable_user(uid)
    return handle_ldap_result(result, f"User {uid} account disabled successfully")


@router.delete(
    "/users/{uid}",
    response_model=LDAPActionResponse,
    summary="Delete User",
)
async def delete_user_ldap(
    uid: str,
    service: LDAPService = Depends(get_ldap_service),
):
    """Permanently delete a user entry from the directory."""
    result = service.delete_user(uid)
    return handle_ldap_result(result, f"User {uid} deleted successfully")


# ============================================================================
# GROUP ENDPOINTS
# ============================================================================

@router.post(
    "/groups",
    response_model=LDAPActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Group",
)
async def create_group_ldap(
    group: LDAPGroupCreate,
    service: LDAPService = Depends(get_ldap_service),
):
    """Create a new groupOfNames group entry."""
    result = service.create_group(group)
    return handle_ldap_result(result, f"Group {group.cn} created successfully")


@router.get(
    "/groups",
    response_model=List[LDAPGroup],
    summary="List Groups",
)
async def get_groups_ldap(
    service: LDAPService = Depends(get_ldap_service),
):
    """Retrieve all groups and their member lists."""
    return service.get_groups()


@router.post(
    "/groups/members",
    response_model=LDAPActionResponse,
    summary="Add Member to Group",
)
async def add_user_to_group_ldap(
    action: LDAPGroupMemberAction,
    service: LDAPService = Depends(get_ldap_service),
):
    """Add a user's DN into a target group's member list."""
    result = service.add_user_to_group(action)
    return handle_ldap_result(
        result, f"Added {action.user_dn} to group {action.group_dn}"
    )


@router.delete(
    "/groups/members",
    response_model=LDAPActionResponse,
    summary="Remove Member from Group",
)
async def remove_user_from_group_ldap(
    action: LDAPGroupMemberAction,
    service: LDAPService = Depends(get_ldap_service),
):
    """Remove a user's DN from a group's member list."""
    result = service.remove_user_from_group(action)
    return handle_ldap_result(
        result, f"Removed {action.user_dn} from group {action.group_dn}"
    )


# ============================================================================
# ORGANIZATIONAL UNIT (OU) & DIT TREE ENDPOINTS
# ============================================================================

@router.post(
    "/ous",
    response_model=LDAPActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Organizational Unit",
)
async def create_ou_ldap(
    ou: LDAPOUCreate,
    service: LDAPService = Depends(get_ldap_service),
):
    """Create an organizationalUnit entry under the base or specified parent DN."""
    result = service.create_ou(ou)
    return handle_ldap_result(result, f"OU '{ou.name}' created successfully")


@router.get(
    "/ous",
    response_model=List[LDAPOU],
    summary="List All Organizational Units",
)
async def get_ous_ldap(
    service: LDAPService = Depends(get_ldap_service),
):
    """Retrieve all organizationalUnit entries in the directory."""
    return fetch_all_ous(service)


@router.post(
    "/objects/move",
    response_model=LDAPActionResponse,
    summary="Move Object to another OU",
)
async def move_object_ldap(
    move_action: LDAPMoveObject,
    service: LDAPService = Depends(get_ldap_service),
):
    """Move any LDAP object (user, group, or child OU) to a new parent OU."""
    result = service.move_object(move_action)
    return handle_ldap_result(
        result,
        f"Moved {move_action.current_dn} to {move_action.new_parent_dn}",
    )


# ============================================================================
# DIRECTORY SNAPSHOT & TREE ENDPOINTS (ADDITIONAL CONVENIENCE)
# ============================================================================

@router.get(
    "/snapshot",
    response_model=LDAPDirectorySnapshot,
    summary="Get Full Directory Snapshot",
)
async def get_directory_snapshot(
    service: LDAPService = Depends(get_ldap_service),
):
    """Return a flat inventory of all OUs, users, and groups."""
    return LDAPDirectorySnapshot(
        base_dn=service.base_dn,
        ous=fetch_all_ous(service),
        users=service.get_users(),
        groups=service.get_groups(),
    )


@router.get(
    "/tree",
    response_model=LDAPDirectoryTree,
    summary="Get Directory Tree Hierarchy",
)
async def get_directory_tree(
    service: LDAPService = Depends(get_ldap_service),
):
    """Return a nested DIT tree structure for UI rendering and navigation."""
    ous = fetch_all_ous(service)
    users = service.get_users()
    groups = service.get_groups()
    return build_directory_tree(service.base_dn, ous, users, groups)