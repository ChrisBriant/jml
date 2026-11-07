from typing import List, Callable
from fastapi import Request, Depends, HTTPException, status

from services.ldap.jwt import TokenClaims, decode_and_validate_jwt

COOKIE_NAME = "access_token"

# ==========================================
# PERMISSION DEFINITIONS
# (Expand with more roles/groups here)
# ==========================================
READ_ALL_GROUPS = ["GLOBAL_ADMIN", "GLOBAL_READER"]
WRITE_ALL_GROUPS = ["GLOBAL_ADMIN"]


# ==========================================
# 1. AUTHENTICATION DEPENDENCY
# ==========================================

async def authenticated_user(request: Request) -> TokenClaims:
    print(">>> ALL COOKIES RECEIVED:", request.cookies)
    token = request.cookies.get(COOKIE_NAME)
    print(">>> TOKEN FOUND:", token is not None)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Missing session cookie.",
        )
    return decode_and_validate_jwt(token)


# ==========================================
# 2. GROUP AUTHORIZATION FACTORY
# ==========================================

def require_groups(required_groups: List[str]) -> Callable:
    """
    Dependency factory to enforce group membership.
    User needs at least ONE of the required groups to pass.
    """
    async def group_checker(
        current_user: TokenClaims = Depends(authenticated_user)
    ) -> TokenClaims:
        user_groups_set = set(current_user.groups)
        has_permission = any(group in user_groups_set for group in required_groups)

        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: requires membership in one of {required_groups}",
            )
        return current_user

    return group_checker


# ==========================================
# 3. CONCRETE PERMISSION DEPENDENCIES
# ==========================================

# Read-all permission: ["GLOBAL_ADMIN", "GLOBAL_READER"]
allowed_read_all = require_groups(READ_ALL_GROUPS)

# Write-all permission: ["GLOBAL_ADMIN"]
allowed_write_all = require_groups(WRITE_ALL_GROUPS)