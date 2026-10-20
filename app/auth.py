"""로그인과 권한(Permission) 관리

- 아이디마다 역할(role)이 있어요. 높은 순서대로:
  "owner"(소유자) > "superadmin"(총관리자) > "admin"(관리자) > "user"(일반 사용자)
- 역할마다 할 수 있는 일(permission)이 정해져 있어요.
- 소유자는 서버에 딱 한 명(ADMIN_USERNAME)이고, 권한표와 상관없이 모든 일을 할 수 있어요.
- 다른 사람을 관리할 때는 언제나 '나보다 낮은 등급'만 건드릴 수 있어요.
- 이용 정지(밴)된 아이디는 로그인할 수 없고, 활동 정지(타임아웃) 중에는 보기와 문의만 할 수 있어요.
"""
import hashlib
import hmac
import secrets

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .database import get_db
from .models import User, now_kst

ROLE_OWNER = "owner"
ROLE_SUPER = "superadmin"
ROLE_ADMIN = "admin"
ROLE_USER = "user"

_USER_PERMS = {"view", "apply", "comment", "write", "inquiry", "play"}
_ADMIN_PERMS = _USER_PERMS | {"admin_access", "content_edit", "manage_users",
                              "manage_donations", "manage_inquiries", "manage_money",
                              "timeout"}
_SUPER_PERMS = _ADMIN_PERMS | {"manage_donate", "manage_bank", "reset_password", "edit_site",
                               "moderate", "delete_users", "manage_admins",
                               "manage_playground", "manage_own_money", "manage_quiz"}

# 역할별 권한표 (높은 등급부터. 소유자는 여기 없는 권한까지 전부 가져요)
ROLE_PERMISSIONS = {
    ROLE_OWNER: _SUPER_PERMS | {"manage_superadmins"},
    ROLE_SUPER: _SUPER_PERMS,
    ROLE_ADMIN: _ADMIN_PERMS,
    ROLE_USER: _USER_PERMS,
}
ROLE_LABELS = {ROLE_OWNER: "소유자", ROLE_SUPER: "총관리자", ROLE_ADMIN: "관리자",
               ROLE_USER: "일반 사용자"}
ROLE_RANK = {ROLE_OWNER: 3, ROLE_SUPER: 2, ROLE_ADMIN: 1, ROLE_USER: 0}

# 활동 정지(타임아웃) 중에도 할 수 있는 일 - 억울하면 문의로 알려 줄 수 있어요.
TIMEOUT_PERMS = {"view", "inquiry"}


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


def rank(user: User | None) -> int:
    return -1 if user is None else ROLE_RANK.get(user.role, 0)


def is_timed_out(user: User | None) -> bool:
    return bool(user and user.timeout_until and user.timeout_until > now_kst())


def get_current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None or user.is_banned:
        # 밴 당한 사람은 바로 로그아웃돼요.
        request.session.pop("user_id", None)
        return None
    return user


def has_permission(user: User | None, permission: str) -> bool:
    if user is None or user.is_banned:
        return False
    if user.role == ROLE_OWNER:
        return True
    if is_timed_out(user):
        return permission in TIMEOUT_PERMS
    return permission in ROLE_PERMISSIONS.get(user.role, set())


def outranks(me: User | None, target: User, permission: str) -> bool:
    """me가 이 권한을 갖고 있고, target보다 등급이 높을 때만 True (자기 자신은 언제나 안 돼요)"""
    if me is None or target.id == me.id:
        return False
    return has_permission(me, permission) and rank(me) > rank(target)


def can_manage_user(me: User | None, target: User) -> bool:
    """역할 바꾸기"""
    return outranks(me, target, "manage_users")


def can_delete_user(me: User | None, target: User) -> bool:
    """회원 삭제 (총관리자 이상)"""
    return outranks(me, target, "delete_users")


def can_timeout(me: User | None, target: User) -> bool:
    """타임아웃 걸기·풀기 (관리자 이상)"""
    return outranks(me, target, "timeout")


def can_moderate(me: User | None, target: User) -> bool:
    """밴 (총관리자 이상)"""
    return outranks(me, target, "moderate")


def can_edit_profile(me: User | None, target: User) -> bool:
    """남의 이름·비밀번호 다시 정해 주기 (총관리자 이상)"""
    return outranks(me, target, "reset_password")


def can_manage_money(me: User | None, target: User) -> bool:
    """놀이터 돈 관리 (관리자 이상) - 나보다 낮은 등급의 돈.
    내 돈은 총관리자 이상만 바꿀 수 있어요. (관리자는 자기 돈을 못 바꿔요)"""
    if me is None or not has_permission(me, "manage_money"):
        return False
    if target.id == me.id:
        return has_permission(me, "manage_own_money")
    return rank(me) > rank(target)


def assignable_roles(me: User | None) -> list[str]:
    """me가 다른 사람에게 줄 수 있는 역할 - 나보다 낮은 역할만, 소유자는 절대 안 돼요."""
    if not has_permission(me, "manage_users"):
        return []
    return [role for role in ROLE_PERMISSIONS
            if role != ROLE_OWNER and ROLE_RANK[role] < rank(me)]


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
