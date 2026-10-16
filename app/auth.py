"""로그인과 권한(Permission) 관리

- 아이디마다 역할(role)이 있어요: "superadmin"(총관리자), "admin"(관리자), "user"(일반 사용자)
- 역할마다 할 수 있는 일(permission)이 정해져 있어요.
- 총관리자는 권한표와 상관없이 모든 일을 할 수 있어요.
"""
import hashlib
import hmac
import secrets

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

ROLE_SUPER = "superadmin"
ROLE_ADMIN = "admin"
ROLE_USER = "user"

_USER_PERMS = {"view", "apply", "comment", "write"}
_ADMIN_PERMS = _USER_PERMS | {"admin_access", "content_edit", "manage_users", "manage_donate"}

# 역할별 권한표 (총관리자는 여기 없는 권한까지 전부 가져요)
ROLE_PERMISSIONS = {
    ROLE_SUPER: _ADMIN_PERMS | {"manage_admins", "manage_bank", "reset_password", "edit_site"},
    ROLE_ADMIN: _ADMIN_PERMS,
    ROLE_USER: _USER_PERMS,
}
ROLE_LABELS = {ROLE_SUPER: "총관리자", ROLE_ADMIN: "관리자", ROLE_USER: "일반 사용자"}


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
    if user.role == ROLE_SUPER:
        return True
    return permission in ROLE_PERMISSIONS.get(user.role, set())


def can_manage_user(me: User | None, target: User) -> bool:
    """me가 target의 역할을 바꾸거나 지울 수 있나요?

    - 자기 자신은 안 돼요.
    - 총관리자는 다른 사람 누구든 돼요.
    - 관리자는 일반 사용자만 돼요. (관리자끼리, 총관리자는 못 건드려요)
    """
    if me is None or target.id == me.id:
        return False
    if me.role == ROLE_SUPER:
        return True
    return has_permission(me, "manage_users") and target.role == ROLE_USER


def assignable_roles(me: User | None) -> list[str]:
    """me가 다른 사람에게 줄 수 있는 역할"""
    if me is not None and me.role == ROLE_SUPER:
        return list(ROLE_PERMISSIONS)
    if has_permission(me, "manage_users"):
        return [ROLE_ADMIN, ROLE_USER]
    return []


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
