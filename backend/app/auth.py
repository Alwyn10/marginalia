import time

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .db import conn

bearer = HTTPBearer(auto_error=False)
TOKEN_TTL = 7 * 24 * 3600


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def make_token(user_id: int) -> str:
    payload = {"sub": str(user_id), "exp": int(time.time()) + TOKEN_TTL}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if not cred:
        raise HTTPException(401, "Sign in to continue.")
    try:
        payload = jwt.decode(cred.credentials, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Your session expired. Sign in again.")
    with conn() as c:
        row = c.execute("SELECT id, email FROM users WHERE id = ?", (int(payload["sub"]),)).fetchone()
    if not row:
        raise HTTPException(401, "Account not found.")
    return dict(row)
