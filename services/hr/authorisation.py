from typing import Callable, List, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.hr.jwt import TokenClaims, decode_hr_access_token

COOKIE_NAME = "hr_access_token"

# auto_error=False prevents FastAPI from rejecting requests with no Authorization header,
# allowing fallback to the session cookie while still enabling the Swagger UI "Authorize" button.
bearer_scheme = HTTPBearer(auto_error=False)


# ==========================================
# 1. AUTHENTICATION DEPENDENCY
# ==========================================

async def authenticated_user(
    request: Request,
    bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> TokenClaims:
    """
    Authenticate the request using either:
    1. Authorization: Bearer <token> header (takes precedence if supplied)
    2. hr_access_token session cookie (fallback when no Authorization header is sent)
    """
    token: Optional[str] = None

    if bearer_credentials is not None:
        token = bearer_credentials.credentials
    elif request.headers.get("Authorization"):
        # An Authorization header was sent, but it wasn't a valid Bearer token
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    else:
        token = request.cookies.get(COOKIE_NAME)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Missing Bearer token or session cookie.",
            headers={"WWW-Authenticate": "Bearer"},
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
    allowed_roles = {role.lower() for role in required_groups}

    async def role_checker(
        current_user: TokenClaims = Depends(authenticated_user),
    ) -> TokenClaims:
        user_role = current_user.role.lower()
        has_permission = user_role in allowed_roles

        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: requires membership in one of {required_groups}",
            )
        return current_user

    return role_checker