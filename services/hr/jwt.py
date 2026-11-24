import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from database.hr.models import SystemUser

HR_JWT_ALGORITHM = os.environ.get("HR_JWT_ALGORITHM", "HS256")
HR_JWT_EXPIRATION_MINUTES = int(os.environ.get("HR_JWT_EXPIRATION_MINUTES", 480))
HR_COOKIE_MAX_AGE = HR_JWT_EXPIRATION_MINUTES * 60  # in seconds (8 hours)
HR_JWT_ISSUER = "hr-system"
HR_JWT_AUDIENCE = "hr-system"


class TokenClaims(BaseModel):
    """Pydantic model representing HR JWT claims."""

    sub: str
    username: str
    role: str
    token_type: str = "hr_access"
    iss: str = HR_JWT_ISSUER
    aud: str = HR_JWT_AUDIENCE
    jti: str = Field(default_factory=lambda: str(uuid.uuid4()))
    iat: datetime
    exp: datetime


def _get_hr_jwt_secret() -> str:
    secret_key = os.environ.get("HR_JWT_SECRET_KEY")
    if not secret_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="HR_JWT_SECRET_KEY environment variable is not configured",
        )
    return secret_key


def create_hr_access_token(user: SystemUser) -> str:
    """Create a signed JWT specifically for the HR system."""
    secret_key = _get_hr_jwt_secret()

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=HR_JWT_EXPIRATION_MINUTES)

    claims = TokenClaims(
        sub=str(user.user_id),
        username=user.username,
        role=user.role.value,
        iat=now,
        exp=expires_at,
    )

    return jwt.encode(
        claims.model_dump(),
        secret_key,
        algorithm=HR_JWT_ALGORITHM,
    )


def decode_hr_access_token(token: str) -> TokenClaims:
    """Decode and validate an HR JWT into a TokenClaims model."""
    secret_key = _get_hr_jwt_secret()

    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=[HR_JWT_ALGORITHM],
            issuer=HR_JWT_ISSUER,
            audience=HR_JWT_AUDIENCE,
        )
        claims = TokenClaims.model_validate(payload)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="HR session token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except (jwt.InvalidTokenError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid HR session token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if claims.token_type != "hr_access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type for HR system",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return claims