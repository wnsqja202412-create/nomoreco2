"""관리자 전용 페이지 - 'admin_access' 권한이 있는 아이디만 들어올 수 있어요."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import (ROLE_PERMISSIONS, assignable_roles, can_manage_user, hash_password,
                    require_permission)
from ..database import get_db
from ..models import (APPLICATION_STATUSES, CATEGORIES, DONATION_STATUSES, Application,
                      BankAccount, BoardPost, Comment, Donation, Post, Recruitment, User, now_kst)
from ..site import DONATE_FIELDS, SETTING_FIELDS, get_settings, save_settings
from ..templating import flash, render

router = APIRouter(prefix="/admin", dependencies=[Depends(require_permission("admin_access"))])
content_editor = require_permission("content_edit")
user_manager = require_permission("manage_users")
donate_manager = require_permission("manage_donate")
bank_manager = require_permission("manage_bank")
super_admin = require_permission("reset_password")


def go(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def get_or_404(db: Session, model, obj_id: int):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(404)
    return obj


@router.get("")
def dashboard(request: Request, db: Session = Depends(get_db)):
    counts = {
        "posts": db.query(Post).count(),
        "board": db.query(BoardPost).count(),
        "recruitments": db.query(Recruitment).filter(Recruitment.is_open.is_(True)).count(),
        "applications": db.query(Application).count(),
        "donations": db.query(Donation).count(),
        "users": db.query(User).count(),
    }
    total = db.query(func.coalesce(func.sum(Donation.amount), 0)).scalar()
    recent_apps = db.query(Application).order_by(Application.id.desc()).limit(5).all()
    recent_dons = db.query(Donation).order_by(Donation.id.desc()).limit(5).all()
    return render(request, "admin/dashboard.html", db, counts=counts, total=total,
                  recent_apps=recent_apps, recent_dons=recent_dons)


# ---------- 활동 글 ----------

@router.get("/posts")
def posts(request: Request, db: Session = Depends(get_db)):
    items = db.query(Post).order_by(Post.id.desc()).all()
    return render(request, "admin/posts.html", db, items=items)


@router.get("/posts/new")
def post_new(request: Request, db: Session = Depends(get_db), _=Depends(content_editor)):
    return render(request, "admin/post_form.html", db, post=None, categories=CATEGORIES)


@router.post("/posts/new")
def post_create(
    request: Request, db: Session = Depends(get_db), _=Depends(content_editor),
    title: str = Form(...), category: str = Form(...), summary: str = Form(""),
    content: str = Form(...), image_url: str = Form(""),
):
    post = Post(title=title, category=category, summary=summary, content=content,
                image_url=image_url.strip())
    db.add(post)
    db.commit()
    flash(request, "새 활동 글을 올렸어요.")
    return go(f"/activities/{post.id}")


@router.get("/posts/{post_id}/edit")
def post_edit(post_id: int, request: Request, db: Session = Depends(get_db),
              _=Depends(content_editor)):
    post = get_or_404(db, Post, post_id)
    return render(request, "admin/post_form.html", db, post=post, categories=CATEGORIES)


@router.post("/posts/{post_id}/edit")
def post_update(
    post_id: int, request: Request, db: Session = Depends(get_db), _=Depends(content_editor),
    title: str = Form(...), category: str = Form(...), summary: str = Form(""),
    content: str = Form(...), image_url: str = Form(""),
):
    post = get_or_404(db, Post, post_id)
    post.title, post.category, post.summary = title, category, summary
    post.content, post.image_url = content, image_url.strip()
    post.updated_at = now_kst()
    db.commit()
    flash(request, "활동 글을 수정했어요.")
    return go(f"/activities/{post.id}")


@router.post("/posts/{post_id}/delete")
def post_delete(post_id: int, request: Request, db: Session = Depends(get_db),
                _=Depends(content_editor)):
    db.delete(get_or_404(db, Post, post_id))
    db.commit()
    flash(request, "활동 글을 지웠어요.")
    return go("/admin/posts")


# ---------- 게시판 ----------

@router.get("/board")
def board(request: Request, db: Session = Depends(get_db)):
    items = (db.query(BoardPost)
             .order_by(BoardPost.is_pinned.desc(), BoardPost.id.desc()).all())
    return render(request, "admin/board.html", db, items=items)


# 게시판 글 쓰기·수정·삭제는 /board/... 에서 해요. (쓴 사람과 관리자 모두 같은 화면)


@router.post("/board/{item_id}/pin")
def board_pin(item_id: int, request: Request, db: Session = Depends(get_db),
              _=Depends(content_editor)):
    item = get_or_404(db, BoardPost, item_id)
    item.is_pinned = not item.is_pinned
    db.commit()
    flash(request, "공지로 고정했어요." if item.is_pinned else "공지 고정을 풀었어요.")
    return go("/admin/board")


# ---------- 모집 공고 ----------

@router.get("/recruitments")
def recruitments(request: Request, db: Session = Depends(get_db)):
    items = db.query(Recruitment).order_by(Recruitment.id.desc()).all()
    return render(request, "admin/recruitments.html", db, items=items)


@router.get("/recruitments/new")
def recruitment_new(request: Request, db: Session = Depends(get_db), _=Depends(content_editor)):
    return render(request, "admin/recruitment_form.html", db, item=None)


@router.post("/recruitments/new")
def recruitment_create(
    request: Request, db: Session = Depends(get_db), _=Depends(content_editor),
    title: str = Form(...), field: str = Form(...), description: str = Form(...),
    requirements: str = Form(""), schedule: str = Form(""), is_open: str | None = Form(None),
):
    db.add(Recruitment(title=title, field=field, description=description,
                       requirements=requirements, schedule=schedule, is_open=bool(is_open)))
    db.commit()
    flash(request, "모집 공고를 만들었어요.")
    return go("/admin/recruitments")


@router.get("/recruitments/{item_id}/edit")
def recruitment_edit(item_id: int, request: Request, db: Session = Depends(get_db),
                     _=Depends(content_editor)):
    item = get_or_404(db, Recruitment, item_id)
    return render(request, "admin/recruitment_form.html", db, item=item)


@router.post("/recruitments/{item_id}/edit")
def recruitment_update(
    item_id: int, request: Request, db: Session = Depends(get_db), _=Depends(content_editor),
    title: str = Form(...), field: str = Form(...), description: str = Form(...),
    requirements: str = Form(""), schedule: str = Form(""), is_open: str | None = Form(None),
):
    item = get_or_404(db, Recruitment, item_id)
    item.title, item.field, item.description = title, field, description
    item.requirements, item.schedule, item.is_open = requirements, schedule, bool(is_open)
    db.commit()
    flash(request, "모집 공고를 수정했어요.")
    return go("/admin/recruitments")


@router.post("/recruitments/{item_id}/delete")
def recruitment_delete(item_id: int, request: Request, db: Session = Depends(get_db),
                       _=Depends(content_editor)):
    db.delete(get_or_404(db, Recruitment, item_id))
    db.commit()
    flash(request, "모집 공고와 그 지원서를 지웠어요.")
    return go("/admin/recruitments")


# ---------- 지원서 ----------

@router.get("/applications")
def applications(request: Request, db: Session = Depends(get_db)):
    items = db.query(Application).order_by(Application.id.desc()).all()
    return render(request, "admin/applications.html", db, items=items,
                  statuses=APPLICATION_STATUSES)


@router.post("/applications/{item_id}/status")
def application_status(item_id: int, request: Request, db: Session = Depends(get_db),
                       _=Depends(content_editor), status: str = Form(...)):
    item = get_or_404(db, Application, item_id)
    if status in APPLICATION_STATUSES:
        item.status = status
        db.commit()
        flash(request, f"{item.name}님의 지원 상태를 '{status}'(으)로 바꿨어요.")
    return go("/admin/applications")


@router.post("/applications/{item_id}/delete")
def application_delete(item_id: int, request: Request, db: Session = Depends(get_db),
                       _=Depends(content_editor)):
    db.delete(get_or_404(db, Application, item_id))
    db.commit()
    flash(request, "지원서를 지웠어요.")
    return go("/admin/applications")


# ---------- 후원 신청 ----------

@router.get("/donations")
def donations(request: Request, db: Session = Depends(get_db)):
    items = db.query(Donation).order_by(Donation.id.desc()).all()
    by_type = (db.query(Donation.donation_type, func.count(), func.sum(Donation.amount))
               .group_by(Donation.donation_type).all())
    total = sum(d.amount for d in items)
    return render(request, "admin/donations.html", db, items=items, by_type=by_type, total=total,
                  statuses=DONATION_STATUSES)


@router.post("/donations/{item_id}/status")
def donation_status(item_id: int, request: Request, db: Session = Depends(get_db),
                    _=Depends(donate_manager), status: str = Form(...)):
    item = get_or_404(db, Donation, item_id)
    if status in DONATION_STATUSES:
        item.status = status
        db.commit()
        flash(request, f"{item.donor_name}님의 후원 상태를 '{status}'(으)로 바꿨어요.")
    return go("/admin/donations")


@router.post("/donations/{item_id}/delete")
def donation_delete(item_id: int, request: Request, db: Session = Depends(get_db),
                    _=Depends(donate_manager)):
    db.delete(get_or_404(db, Donation, item_id))
    db.commit()
    flash(request, "후원 신청을 지웠어요.")
    return go("/admin/donations")


# ---------- 회원 / 권한 ----------

@router.get("/users")
def users(request: Request, db: Session = Depends(get_db), me: User = Depends(user_manager)):
    items = db.query(User).order_by(User.id).all()
    return render(request, "admin/users.html", db, items=items, roles=list(ROLE_PERMISSIONS),
                  role_permissions=ROLE_PERMISSIONS, can_manage=can_manage_user,
                  assignable=assignable_roles(me))


def _managed_target(db: Session, request: Request, me: User, user_id: int) -> User | None:
    """me가 건드릴 수 있는 회원이면 돌려주고, 아니면 안내 문구를 남겨요."""
    target = get_or_404(db, User, user_id)
    if target.id == me.id:
        flash(request, "자기 자신의 역할은 바꾸거나 지울 수 없어요.")
        return None
    if not can_manage_user(me, target):
        flash(request, "관리자·총관리자 계정은 총관리자만 바꿀 수 있어요.")
        return None
    return target


@router.post("/users/{user_id}/role")
def user_role(user_id: int, request: Request, db: Session = Depends(get_db),
              me: User = Depends(user_manager), role: str = Form(...)):
    target = _managed_target(db, request, me, user_id)
    if target is None:
        return go("/admin/users")
    if role not in assignable_roles(me):
        flash(request, "그 역할은 줄 수 없어요.")
    else:
        target.role = role
        db.commit()
        flash(request, f"{target.username}의 역할을 바꿨어요.")
    return go("/admin/users")


@router.post("/users/{user_id}/delete")
def user_delete(user_id: int, request: Request, db: Session = Depends(get_db),
                me: User = Depends(user_manager)):
    target = _managed_target(db, request, me, user_id)
    if target is None:
        return go("/admin/users")
    for model in (Application, Donation, Comment, BoardPost):
        db.query(model).filter_by(user_id=target.id).update({"user_id": None})
    db.delete(target)
    db.commit()
    flash(request, f"{target.username} 회원을 지웠어요.")
    return go("/admin/users")


@router.post("/users/{user_id}/profile")
def user_profile(user_id: int, request: Request, db: Session = Depends(get_db),
                 _=Depends(super_admin), name: str = Form(""), password: str = Form("")):
    """총관리자 전용: 누구든 이름을 고치거나 비밀번호를 새로 정해 줄 수 있어요."""
    target = get_or_404(db, User, user_id)
    name, changed = name.strip()[:50], []
    if name and name != target.name:
        target.name = name
        changed.append("이름")
    if password:
        if len(password) < 6:
            flash(request, "새 비밀번호는 6글자 이상이어야 해요.")
            return go("/admin/users")
        target.password_hash = hash_password(password)
        changed.append("비밀번호")
    db.commit()
    flash(request, f"{target.username}의 {'·'.join(changed)}을(를) 바꿨어요." if changed
          else "바뀐 것이 없어요.")
    return go("/admin/users")


# ---------- 사이트 문구 설정 ----------

@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db), _=Depends(content_editor)):
    return render(request, "admin/settings.html", db, fields=SETTING_FIELDS, values=get_settings(db))


@router.post("/settings")
async def settings_save(request: Request, db: Session = Depends(get_db),
                        _=Depends(content_editor)):
    save_settings(db, SETTING_FIELDS, await request.form())
    flash(request, "사이트 문구를 저장했어요.")
    return go("/admin/settings")


# ---------- 후원 페이지 관리 ----------

@router.get("/donate")
def donate_page(request: Request, db: Session = Depends(get_db), _=Depends(donate_manager)):
    accounts = db.query(BankAccount).order_by(BankAccount.sort_order, BankAccount.id).all()
    return render(request, "admin/donate.html", db, fields=DONATE_FIELDS,
                  values=get_settings(db), accounts=accounts)


@router.post("/donate")
async def donate_save(request: Request, db: Session = Depends(get_db),
                      _=Depends(donate_manager)):
    save_settings(db, DONATE_FIELDS, await request.form())
    flash(request, "후원 페이지를 저장했어요.")
    return go("/admin/donate")


def _account_form(bank_name: str, account_number: str, holder: str, memo: str,
                  sort_order: str, is_active: str | None) -> dict:
    return dict(bank_name=bank_name.strip()[:50], account_number=account_number.strip()[:50],
                holder=holder.strip()[:50], memo=memo.strip()[:200],
                sort_order=int(sort_order) if sort_order.strip().lstrip("-").isdigit() else 0,
                is_active=bool(is_active))


@router.post("/donate/accounts/new")
def account_create(
    request: Request, db: Session = Depends(get_db), _=Depends(bank_manager),
    bank_name: str = Form(...), account_number: str = Form(...), holder: str = Form(...),
    memo: str = Form(""), sort_order: str = Form("0"), is_active: str | None = Form(None),
):
    data = _account_form(bank_name, account_number, holder, memo, sort_order, is_active)
    if not (data["bank_name"] and data["account_number"] and data["holder"]):
        flash(request, "은행, 계좌번호, 예금주를 모두 써 주세요.")
    else:
        db.add(BankAccount(**data))
        db.commit()
        flash(request, "후원 계좌를 추가했어요.")
    return go("/admin/donate#accounts")


@router.post("/donate/accounts/{item_id}/edit")
def account_update(
    item_id: int, request: Request, db: Session = Depends(get_db), _=Depends(bank_manager),
    bank_name: str = Form(...), account_number: str = Form(...), holder: str = Form(...),
    memo: str = Form(""), sort_order: str = Form("0"), is_active: str | None = Form(None),
):
    item = get_or_404(db, BankAccount, item_id)
    data = _account_form(bank_name, account_number, holder, memo, sort_order, is_active)
    if not (data["bank_name"] and data["account_number"] and data["holder"]):
        flash(request, "은행, 계좌번호, 예금주를 모두 써 주세요.")
    else:
        for key, value in data.items():
            setattr(item, key, value)
        db.commit()
        flash(request, "후원 계좌를 수정했어요.")
    return go("/admin/donate#accounts")


@router.post("/donate/accounts/{item_id}/delete")
def account_delete(item_id: int, request: Request, db: Session = Depends(get_db),
                   _=Depends(bank_manager)):
    db.delete(get_or_404(db, BankAccount, item_id))
    db.commit()
    flash(request, "후원 계좌를 지웠어요.")
    return go("/admin/donate#accounts")
