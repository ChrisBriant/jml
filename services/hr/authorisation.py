from typing import List, Callable
from fastapi import Request, Depends, HTTPException, status

from services.hr.jwt import TokenClaims, decode_hr_access_token

COOKIE_NAME = "hr_access_token"



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
    return decode_hr_access_token(token)


# ==========================================
# 2. ROLE AUTHORIZATION FACTORY
# ==========================================

def require_roles(required_groups: List[str]) -> Callable:
    """
    Dependency factory to enforce role membership.
    User needs at least ONE of the required roles to pass.
    """
    async def role_checker(
        current_user: TokenClaims = Depends(authenticated_user)
    ) -> TokenClaims:
        user_role = current_user.role
        has_permission = user_role in required_groups

        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: requires membership in one of {required_groups}",
            )
        return current_user

    return role_checker
