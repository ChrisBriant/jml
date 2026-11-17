from fastapi import HTTPException, status
from datetime import datetime,timedelta, timezone
from database.hr.models import SystemUser
import os, jwt, uuid


HR_JWT_ALGORITHM = os.environ.get("HR_JWT_ALGORITHM", "HS256")
HR_JWT_EXPIRATION_MINUTES = int(os.environ.get("HR_JWT_EXPIRATION_MINUTES", 480))
HR_COOKIE_MAX_AGE = HR_JWT_EXPIRATION_MINUTES * 60  # in seconds (8 hours)
HR_JWT_ISSUER = "hr-system"
HR_JWT_AUDIENCE = "hr-system"


def create_hr_access_token(user: SystemUser) -> str:
    """Create a signed JWT specifically for the HR system."""
    secret_key = os.environ.get("HR_JWT_SECRET_KEY")
    if not secret_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="HR_JWT_SECRET_KEY environment variable is not configured",
        )

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=HR_JWT_EXPIRATION_MINUTES)

    payload = {
        "sub": str(user.user_id),
        "username": user.username,
        "role": user.role.value,
        "token_type": "hr_access",
        "iss": HR_JWT_ISSUER,
        "aud": HR_JWT_AUDIENCE,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": expires_at,
    }

    return jwt.encode(payload, secret_key, algorithm=HR_JWT_ALGORITHM)