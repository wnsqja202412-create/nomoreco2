"""로그인과 권한(Permission) 관리

- 아이디마다 역할(role)이 있어요: "admin"(관리자) 또는 "user"(일반 사용자)
- 역할마다 할 수 있는 일(permission)이 정해져 있어요.
"""
import hashlib
import hmac
import secrets

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

ROLE_ADMIN = "admin"
ROLE_USER = "user"

# 역할별 권한표
ROLE_PERMISSIONS = {
    ROLE_ADMIN: {"view", "apply", "comment", "admin_access", "content_edit", "manage_users"},
    ROLE_USER: {"view", "apply", "comment"},
}
ROLE_LABELS = {ROLE_ADMIN: "관리자", ROLE_USER: "일반 사용자"}


class LoginRequired(Exception):
    pass


class Forbidden(Exception):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return hmac.compare_digest(check, digest)


def get_current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, user_id)


def has_permission(user: User | None, permission: str) -> bool:
    if user is None:
        return False
    return permission in ROLE_PERMISSIONS.get(user.role, set())


def require_permission(permission: str):
    """이 권한이 없는 사람은 들어오지 못하게 막는 문지기"""

    def checker(request: Request, db: Session = Depends(get_db)) -> User:
        user = get_current_user(request, db)
        if user is None:
            raise LoginRequired()
        if not has_permission(user, permission):
            raise Forbidden()
        return user

    return checker
