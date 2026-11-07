import os
import jwt
from typing import Optional
from pydantic import BaseModel, Field
from fastapi import HTTPException, status
from pathlib import Path
import dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
dotenv.load_dotenv(ROOT_DIR / ".env")



JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "change-me-in-production-super-secret-key")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")


class TokenClaims(BaseModel):
    """Pydantic model representing decoded JWT claims."""
    sub: str = Field(description="Username / UID")
    email: Optional[str] = None
    name: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    department: Optional[str] = None
    title: Optional[str] = None
    groups: list[str] = Field(default_factory=list)
    exp: Optional[int] = None
    iat: Optional[int] = None


def decode_and_validate_jwt(token: str) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM]
        )
        print("DECODING WITH KEY:", repr(JWT_SECRET_KEY))
        return TokenClaims(**payload)

    except Exception as e:
        # <-- THIS WILL PRINT THE EXACT REASON
        print(">>> JWT DECODE ERROR:", type(e).__name__, "-", str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {str(e)}",
        )