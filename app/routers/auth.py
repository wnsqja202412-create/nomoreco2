"""로그인 / 회원가입 / 로그아웃"""
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import ROLE_USER, hash_password, verify_password
from ..database import get_db
from ..models import User
from ..templating import flash, render

router = APIRouter()

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{4,20}$")


def _safe_next(url: str) -> str:
    return url if url.startswith("/") and not url.startswith("//") else "/"


@router.get("/login")
def login_page(request: Request, next: str = "/", db: Session = Depends(get_db)):
    return render(request, "login.html", db, next=_safe_next(next))


@router.post("/login")
def login(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    user = db.query(User).filter_by(username=username.strip()).first()
    if user is None or not verify_password(password, user.password_hash):
        return render(request, "login.html", db, status_code=400, next=_safe_next(next),
                      error="아이디 또는 비밀번호가 맞지 않아요.", username=username)
    if user.is_banned:
        reason = f" (사유: {user.ban_reason})" if user.ban_reason else ""
        return render(request, "login.html", db, status_code=403, next=_safe_next(next),
                      error=f"이용이 정지된 아이디예요.{reason}", username=username)
    request.session.clear()
    request.session["user_id"] = user.id
    flash(request, f"{user.name}님, 반가워요!")
    return RedirectResponse(_safe_next(next), status_code=303)


@router.get("/signup")
def signup_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "signup.html", db, form={})


@router.post("/signup")
def signup(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Form(...),
    name: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    username = username.strip()
    form = dict(username=username, name=name)
    error = None
    if not USERNAME_RE.match(username):
        error = "아이디는 영어·숫자·밑줄(_)로 4~20글자로 만들어 주세요."
    elif len(password) < 6:
        error = "비밀번호는 6글자 이상이어야 해요."
    elif password != password2:
        error = "비밀번호 확인이 달라요."
    if error:
        return render(request, "signup.html", db, status_code=400, error=error, form=form)

    existing = db.query(User).filter_by(username=username).first()
    if existing is None:
        # 새로 가입한 사람은 항상 '일반 사용자'(열람만 가능)예요.
        user = User(username=username, name=name.strip(), role=ROLE_USER,
                    password_hash=hash_password(password))
        db.add(user)
        try:
            db.commit()
            return _signed_up(request, user)
        except IntegrityError:
            # 가입 버튼이 두 번 눌려서 같은 아이디가 동시에 만들어지려 한 경우예요.
            db.rollback()
            existing = db.query(User).filter_by(username=username).first()
    if existing and not existing.is_banned and verify_password(password, existing.password_hash):
        # 방금 만든 내 계정이에요. (버튼을 두 번 눌렀거나 새로고침으로 다시 보낸 경우)
        return _signed_up(request, existing)
    return render(request, "signup.html", db, status_code=400,
                  error="이미 있는 아이디예요.", form=form)


def _signed_up(request: Request, user: User) -> RedirectResponse:
    request.session.clear()
    request.session["user_id"] = user.id
    flash(request, "회원가입을 축하해요! 🌱")
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
