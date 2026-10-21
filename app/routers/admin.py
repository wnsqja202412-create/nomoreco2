"""관리자 전용 페이지 - 'admin_access' 권한이 있는 아이디만 들어올 수 있어요."""
from datetime import timedelta
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from .. import wallet
from ..auth import (ROLE_PERMISSIONS, assignable_roles, can_delete_user, can_edit_profile,
                    can_manage_money, can_manage_user, can_moderate, can_timeout,
                    hash_password, is_timed_out, require_permission)
from ..database import get_db
from ..images import delete_image_url, photo_upload, resolve_image
from ..models import (APPLICATION_STATUSES, CATEGORIES, DONATION_STATUSES, INQUIRY_STATUSES,
                      Application, BankAccount, BoardPost, Coinflip, Comment, Donation, Image,
                      Inquiry, InquiryMessage, MoneyLog, Post, QuizGame, QuizQuestion,
                      Recruitment, User, Wallet, now_kst)
from ..site import (DONATE_FIELDS, LOCK_FIELDS, LOCK_MODES, PLAYGROUND_FIELDS, QUIZ_FIELDS,
                    QUIZ_MATCH_MODES, SETTING_FIELDS, SETTING_GROUPS, get_settings, lock_mode, save_settings)
from ..templating import flash, render
from .playground import cancel_flip
from . import quiz
from .quiz import QUESTIONS_PER_MATCH, cancel_game

router = APIRouter(prefix="/admin", dependencies=[Depends(require_permission("admin_access"))])
content_editor = require_permission("content_edit")
user_manager = require_permission("manage_users")
donations_manager = require_permission("manage_donations")
inquiry_manager = require_permission("manage_inquiries")
donate_manager = require_permission("manage_donate")
bank_manager = require_permission("manage_bank")
super_admin = require_permission("reset_password")
moderator = require_permission("moderate")
timeout_giver = require_permission("timeout")
user_deleter = require_permission("delete_users")
site_editor = require_permission("edit_site")
money_manager = require_permission("manage_money")
playground_manager = require_permission("manage_playground")
quiz_manager = require_permission("manage_quiz")
# 권한표 어디에도 없는 권한이라 소유자만 가져요.
site_locker = require_permission("lock_site")

# 타임아웃 시간 단위 (보여 줄 이름, 분) - 숫자와 단위를 직접 골라요.
TIMEOUT_UNITS = {"분": 1, "시간": 60, "일": 60 * 24}
TIMEOUT_MAX_MINUTES = 60 * 24 * 365  # 최대 1년


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
        "inquiries": db.query(Inquiry).filter_by(status="답변대기").count(),
    }
    total = db.query(func.coalesce(func.sum(Donation.amount), 0)).scalar()
    recent_apps = db.query(Application).order_by(Application.id.desc()).limit(5).all()
    recent_dons = db.query(Donation).order_by(Donation.id.desc()).limit(5).all()
    recent_inqs = (db.query(Inquiry).filter_by(status="답변대기")
                   .order_by(Inquiry.updated_at).limit(5).all())
    return render(request, "admin/dashboard.html", db, counts=counts, total=total,
                  recent_apps=recent_apps, recent_dons=recent_dons, recent_inqs=recent_inqs)


# ---------- 활동 글 ----------

@router.get("/posts")
def posts(request: Request, db: Session = Depends(get_db)):
    items = db.query(Post).order_by(Post.id.desc()).all()
    return render(request, "admin/posts.html", db, items=items)


@router.get("/posts/new")
def post_new(request: Request, db: Session = Depends(get_db), _=Depends(content_editor)):
    return render(request, "admin/post_form.html", db, post=None, categories=CATEGORIES)


def _post_form_error(request, db, post, error, **values):
    """사진 문제로 저장 못 했을 때, 쓴 글을 그대로 둔 채 다시 보여 줘요."""
    db.rollback()
    draft = SimpleNamespace(image_url=post.image_url if post else "", **values)
    return render(request, "admin/post_form.html", db, status_code=400, post=post,
                  draft=draft, error=error, categories=CATEGORIES)


@router.post("/posts/new")
def post_create(
    request: Request, db: Session = Depends(get_db), me: User = Depends(content_editor),
    title: str = Form(...), category: str = Form(...), summary: str = Form(""),
    content: str = Form(...), image_url: str = Form(""),
    photo: UploadFile | None = Depends(photo_upload),
):
    try:
        image = resolve_image(db, "", photo, image_url, user=me)
    except ValueError as e:
        return _post_form_error(request, db, None, str(e), title=title, category=category,
                                summary=summary, content=content)
    post = Post(title=title, category=category, summary=summary, content=content,
                image_url=image)
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
    post_id: int, request: Request, db: Session = Depends(get_db),
    me: User = Depends(content_editor),
    title: str = Form(...), category: str = Form(...), summary: str = Form(""),
    content: str = Form(...), image_url: str = Form(""),
    photo: UploadFile | None = Depends(photo_upload), remove_image: str | None = Form(None),
):
    post = get_or_404(db, Post, post_id)
    try:
        image = resolve_image(db, post.image_url, photo, image_url, bool(remove_image), me)
    except ValueError as e:
        return _post_form_error(request, db, post, str(e), title=title, category=category,
                                summary=summary, content=content)
    post.title, post.category, post.summary = title, category, summary
    post.content, post.image_url = content, image
    post.updated_at = now_kst()
    db.commit()
    flash(request, "활동 글을 수정했어요.")
    return go(f"/activities/{post.id}")


@router.post("/posts/{post_id}/delete")
def post_delete(post_id: int, request: Request, db: Session = Depends(get_db),
                _=Depends(content_editor)):
    post = get_or_404(db, Post, post_id)
    delete_image_url(db, post.image_url)
    db.delete(post)
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
                    _=Depends(donations_manager), status: str = Form(...)):
    item = get_or_404(db, Donation, item_id)
    if status in DONATION_STATUSES:
        item.status = status
        db.commit()
        flash(request, f"{item.donor_name}님의 후원 상태를 '{status}'(으)로 바꿨어요.")
    return go("/admin/donations")


@router.post("/donations/{item_id}/delete")
def donation_delete(item_id: int, request: Request, db: Session = Depends(get_db),
                    _=Depends(donations_manager)):
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
                  can_delete=can_delete_user, can_timeout=can_timeout,
                  can_moderate=can_moderate, can_edit_profile=can_edit_profile,
                  is_timed_out=is_timed_out, assignable=assignable_roles(me),
                  timeout_units=TIMEOUT_UNITS)


def _checked_target(db: Session, request: Request, me: User, user_id: int, allowed) -> User | None:
    """me가 건드릴 수 있는 회원이면 돌려주고, 아니면 안내 문구를 남겨요."""
    target = get_or_404(db, User, user_id)
    if target.id == me.id:
        flash(request, "자기 자신은 바꾸거나 지울 수 없어요.")
        return None
    if not allowed(me, target):
        flash(request, "나보다 등급이 같거나 높은 계정은 건드릴 수 없어요.")
        return None
    return target


def _managed_target(db: Session, request: Request, me: User, user_id: int) -> User | None:
    return _checked_target(db, request, me, user_id, can_manage_user)


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
                me: User = Depends(user_deleter)):
    target = _checked_target(db, request, me, user_id, can_delete_user)
    if target is None:
        return go("/admin/users")
    for model in (Application, Donation, Comment, BoardPost, Inquiry, InquiryMessage, Image):
        db.query(model).filter_by(user_id=target.id).update({"user_id": None})
    wallet.forget_user(db, target.id)
    quiz.forget_user(db, target.id)
    db.delete(target)
    db.commit()
    flash(request, f"{target.username} 회원을 지웠어요.")
    return go("/admin/users")


@router.post("/users/{user_id}/profile")
def user_profile(user_id: int, request: Request, db: Session = Depends(get_db),
                 me: User = Depends(super_admin), name: str = Form(""), password: str = Form("")):
    """총관리자 이상: 나보다 낮은 등급의 이름을 고치거나 비밀번호를 새로 정해 줄 수 있어요."""
    target = _checked_target(db, request, me, user_id, can_edit_profile)
    if target is None:
        return go("/admin/users")
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


# ---------- 제재 (타임아웃: 관리자 이상 / 밴: 총관리자 이상) ----------

@router.post("/users/{user_id}/timeout")
def user_timeout(user_id: int, request: Request, db: Session = Depends(get_db),
                 me: User = Depends(timeout_giver), amount: str = Form(...),
                 unit: str = Form(...), reason: str = Form("")):
    target = _checked_target(db, request, me, user_id, can_timeout)
    if target is None:
        return go("/admin/users")
    amount = amount.strip()
    if unit not in TIMEOUT_UNITS or not amount.isdigit() or int(amount) <= 0:
        flash(request, "타임아웃 시간을 1 이상의 숫자로 써 주세요.")
        return go("/admin/users")
    minutes = int(amount) * TIMEOUT_UNITS[unit]
    if minutes > TIMEOUT_MAX_MINUTES:
        flash(request, "타임아웃은 최대 365일까지 할 수 있어요. 더 길게 막으려면 밴을 써 주세요.")
        return go("/admin/users")
    target.timeout_until = now_kst() + timedelta(minutes=minutes)
    target.timeout_reason = reason.strip()[:300]
    db.commit()
    flash(request, f"{target.username}을(를) {int(amount)}{unit} 동안 타임아웃했어요.")
    return go("/admin/users")


@router.post("/users/{user_id}/untimeout")
def user_untimeout(user_id: int, request: Request, db: Session = Depends(get_db),
                   me: User = Depends(timeout_giver)):
    target = _checked_target(db, request, me, user_id, can_timeout)
    if target is not None:
        target.timeout_until, target.timeout_reason = None, ""
        db.commit()
        flash(request, f"{target.username}의 타임아웃을 풀었어요.")
    return go("/admin/users")


@router.post("/users/{user_id}/ban")
def user_ban(user_id: int, request: Request, db: Session = Depends(get_db),
             me: User = Depends(moderator), reason: str = Form("")):
    target = _checked_target(db, request, me, user_id, can_moderate)
    if target is not None:
        target.is_banned, target.ban_reason = True, reason.strip()[:300]
        db.commit()
        flash(request, f"{target.username}을(를) 밴했어요. 이제 로그인할 수 없어요.")
    return go("/admin/users")


@router.post("/users/{user_id}/unban")
def user_unban(user_id: int, request: Request, db: Session = Depends(get_db),
               me: User = Depends(moderator)):
    target = _checked_target(db, request, me, user_id, can_moderate)
    if target is not None:
        target.is_banned, target.ban_reason = False, ""
        db.commit()
        flash(request, f"{target.username}의 밴을 풀었어요.")
    return go("/admin/users")


# ---------- 문의 ----------

@router.get("/inquiries")
def inquiries(request: Request, status: str = "", db: Session = Depends(get_db),
              _=Depends(inquiry_manager)):
    query = db.query(Inquiry)
    if status in INQUIRY_STATUSES:
        query = query.filter(Inquiry.status == status)
    items = query.order_by(Inquiry.updated_at.desc()).all()
    counts = dict(db.query(Inquiry.status, func.count()).group_by(Inquiry.status).all())
    return render(request, "admin/inquiries.html", db, items=items, statuses=INQUIRY_STATUSES,
                  current=status, counts=counts)


@router.get("/inquiries/{item_id}")
def inquiry_detail(item_id: int, request: Request, db: Session = Depends(get_db),
                   _=Depends(inquiry_manager)):
    item = get_or_404(db, Inquiry, item_id)
    author = db.get(User, item.user_id) if item.user_id else None
    return render(request, "admin/inquiry_detail.html", db, item=item, author=author,
                  statuses=INQUIRY_STATUSES)


@router.post("/inquiries/{item_id}/reply")
def inquiry_reply(item_id: int, request: Request, db: Session = Depends(get_db),
                  me: User = Depends(inquiry_manager), content: str = Form(...),
                  close: str | None = Form(None)):
    item = get_or_404(db, Inquiry, item_id)
    content = content.strip()[:3000]
    if content:
        db.add(InquiryMessage(inquiry_id=item.id, user_id=me.id, author_name=me.name,
                              is_staff=True, content=content))
        item.status = "종료" if close else "답변완료"
        item.updated_at = now_kst()
        db.commit()
        flash(request, "답변을 보냈어요.")
    return go(f"/admin/inquiries/{item.id}#bottom")


@router.post("/inquiries/{item_id}/status")
def inquiry_status(item_id: int, request: Request, db: Session = Depends(get_db),
                   _=Depends(inquiry_manager), status: str = Form(...)):
    item = get_or_404(db, Inquiry, item_id)
    if status in INQUIRY_STATUSES:
        item.status = status
        db.commit()
        flash(request, f"문의 상태를 '{status}'(으)로 바꿨어요.")
    return go(f"/admin/inquiries/{item.id}")


@router.post("/inquiries/{item_id}/delete")
def inquiry_delete(item_id: int, request: Request, db: Session = Depends(get_db),
                   _=Depends(inquiry_manager)):
    db.delete(get_or_404(db, Inquiry, item_id))
    db.commit()
    flash(request, "문의를 지웠어요.")
    return go("/admin/inquiries")


# ---------- 사이트 문구 설정 ----------

@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db), _=Depends(site_editor)):
    return render(request, "admin/settings.html", db, groups=SETTING_GROUPS,
                  values=get_settings(db))


@router.post("/settings")
async def settings_save(request: Request, db: Session = Depends(get_db),
                        _=Depends(site_editor)):
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


# ---------- 놀이터 관리 ----------
# 돈 관리: 관리자 이상 (내 돈 + 나보다 낮은 등급) / 열기·닫기·하루 용돈: 총관리자 이상

@router.get("/playground")
def playground_admin(request: Request, db: Session = Depends(get_db),
                     me: User = Depends(money_manager)):
    users_ = db.query(User).order_by(User.id).all()
    wallets = {w.user_id: w for w in db.query(Wallet).all()}
    logs = db.query(MoneyLog).order_by(MoneyLog.id.desc()).limit(30).all()
    names = {u.id: u.name for u in users_}
    open_flips = (db.query(Coinflip).filter(Coinflip.status == "open")
                  .order_by(Coinflip.id.desc()).all())
    return render(request, "admin/playground.html", db, users=users_, wallets=wallets,
                  logs=logs, names=names, open_flips=open_flips, fields=PLAYGROUND_FIELDS,
                  values=get_settings(db), can_money=can_manage_money,
                  is_open=wallet.playground_open(db), today=str(now_kst().date()))


@router.post("/playground/settings")
async def playground_settings(request: Request, db: Session = Depends(get_db),
                              _=Depends(playground_manager)):
    save_settings(db, PLAYGROUND_FIELDS, await request.form())
    flash(request, "놀이터 설정을 저장했어요. (지금: " +
          ("열림" if wallet.playground_open(db) else "닫힘") + ")")
    return go("/admin/playground")


@router.post("/playground/money/{user_id}")
def playground_money(user_id: int, request: Request, db: Session = Depends(get_db),
                     me: User = Depends(money_manager), mode: str = Form(...),
                     amount: str = Form(...), reason: str = Form("")):
    target = get_or_404(db, User, user_id)
    if not can_manage_money(me, target):
        flash(request, "관리자는 자기 돈을 바꿀 수 없어요." if target.id == me.id
              else "나보다 등급이 같거나 높은 사람의 돈은 바꿀 수 없어요.")
        return go("/admin/playground")
    digits = "".join(ch for ch in amount if ch.isdigit())
    value = int(digits) if digits else 0
    note = f"관리자 {me.name}" + (f": {reason.strip()[:100]}" if reason.strip() else "")
    wallet.ensure_wallet(db, target.id)
    if mode == "set":
        wallet.set_balance(db, target.id, value, f"{note} (금액 정하기)", me.id)
    elif mode == "add":
        wallet.change(db, target.id, value, f"{note} (주기)", me.id)
    elif mode == "sub":
        current = db.get(Wallet, target.id).balance
        wallet.change(db, target.id, -min(value, current), f"{note} (빼기)", me.id)
    else:
        raise HTTPException(400)
    db.commit()
    flash(request, f"{target.name}님의 돈을 바꿨어요. 지금 {db.get(Wallet, target.id).balance:,}원")
    return go("/admin/playground")


@router.post("/playground/coinflip/{flip_id}/cancel")
def playground_cancel_flip(flip_id: int, request: Request, db: Session = Depends(get_db),
                           me: User = Depends(money_manager)):
    flip = get_or_404(db, Coinflip, flip_id)
    if cancel_flip(db, flip, f"코인플립 #{flip.id} 관리자 취소 (돌려받음)", me.id):
        db.commit()
        flash(request, f"코인플립 #{flip.id}을(를) 취소하고 판돈을 돌려줬어요.")
    else:
        flash(request, "이미 끝난 게임이에요.")
    return go("/admin/playground")


# ---------- 기후 퀴즈 관리 - 총관리자 이상 ----------

@router.get("/quiz")
def quiz_admin(request: Request, db: Session = Depends(get_db), _=Depends(quiz_manager)):
    questions = db.query(QuizQuestion).order_by(QuizQuestion.id).all()
    games = (db.query(QuizGame).filter(QuizGame.status.in_(["waiting", "playing"]))
             .order_by(QuizGame.id.desc()).all())
    return render(request, "admin/quiz.html", db, questions=questions, games=games,
                  values=get_settings(db), cfg=quiz.quiz_config(db), modes=QUIZ_MATCH_MODES,
                  per_match=QUESTIONS_PER_MATCH, active=sum(q.is_active for q in questions))


@router.post("/quiz/settings")
async def quiz_settings(request: Request, db: Session = Depends(get_db),
                        _=Depends(quiz_manager)):
    form = dict(await request.form())
    if form.get("quiz_match_mode") not in QUIZ_MATCH_MODES:
        form.pop("quiz_match_mode", None)
    save_settings(db, QUIZ_FIELDS, form)
    cfg = quiz.quiz_config(db)
    flash(request, f"퀴즈 설정을 저장했어요. (매칭: {QUIZ_MATCH_MODES[cfg['mode']]}, "
          f"제한 시간 {cfg['time_limit']}초, 카운트다운 {cfg['countdown']}초 · 새 대결부터 적용돼요)")
    return go("/admin/quiz")


def _question_form(question: str, choice1: str, choice2: str, choice3: str, choice4: str,
                   answer: str, explanation: str) -> tuple[dict | None, str]:
    """문제 입력값을 확인해요. 빈 보기는 빼고, 정답 번호도 그에 맞춰 바꿔요."""
    raw = [c.strip()[:200] for c in (choice1, choice2, choice3, choice4)]
    picked = int(answer) - 1 if answer.isdigit() else -1
    if not question.strip():
        return None, "문제를 써 주세요."
    if not (0 <= picked < 4) or not raw[picked]:
        return None, "정답 보기를 고르고, 그 보기에 글을 써 주세요."
    choices = [c for c in raw if c]
    if len(choices) < 2:
        return None, "보기는 2개 이상 써 주세요."
    return dict(question=question.strip()[:300], choices="\n".join(choices),
                answer=sum(1 for c in raw[:picked] if c),
                explanation=explanation.strip()[:1000]), ""


@router.get("/quiz/new")
def quiz_question_new(request: Request, db: Session = Depends(get_db), _=Depends(quiz_manager)):
    return render(request, "admin/quiz_form.html", db, item=None)


@router.post("/quiz/new")
def quiz_question_create(
    request: Request, db: Session = Depends(get_db), _=Depends(quiz_manager),
    question: str = Form(""), choice1: str = Form(""), choice2: str = Form(""),
    choice3: str = Form(""), choice4: str = Form(""), answer: str = Form(""),
    explanation: str = Form(""), is_active: str | None = Form(None),
):
    data, error = _question_form(question, choice1, choice2, choice3, choice4, answer, explanation)
    if data is None:
        draft = SimpleNamespace(question=question, explanation=explanation, is_active=bool(is_active),
                                choice_list=[choice1, choice2, choice3, choice4],
                                answer=int(answer) - 1 if answer.isdigit() else 0)
        return render(request, "admin/quiz_form.html", db, status_code=400, item=None,
                      draft=draft, error=error)
    db.add(QuizQuestion(**data, is_active=bool(is_active)))
    db.commit()
    flash(request, "새 문제를 만들었어요.")
    return go("/admin/quiz#questions")


@router.get("/quiz/{item_id}/edit")
def quiz_question_edit(item_id: int, request: Request, db: Session = Depends(get_db),
                       _=Depends(quiz_manager)):
    return render(request, "admin/quiz_form.html", db, item=get_or_404(db, QuizQuestion, item_id))


@router.post("/quiz/{item_id}/edit")
def quiz_question_update(
    item_id: int, request: Request, db: Session = Depends(get_db), _=Depends(quiz_manager),
    question: str = Form(""), choice1: str = Form(""), choice2: str = Form(""),
    choice3: str = Form(""), choice4: str = Form(""), answer: str = Form(""),
    explanation: str = Form(""), is_active: str | None = Form(None),
):
    item = get_or_404(db, QuizQuestion, item_id)
    data, error = _question_form(question, choice1, choice2, choice3, choice4, answer, explanation)
    if data is None:
        draft = SimpleNamespace(question=question, explanation=explanation, is_active=bool(is_active),
                                choice_list=[choice1, choice2, choice3, choice4],
                                answer=int(answer) - 1 if answer.isdigit() else 0)
        return render(request, "admin/quiz_form.html", db, status_code=400, item=item,
                      draft=draft, error=error)
    for key, value in data.items():
        setattr(item, key, value)
    item.is_active = bool(is_active)
    db.commit()
    flash(request, f"문제 #{item.id}을(를) 고쳤어요.")
    return go("/admin/quiz#questions")


@router.post("/quiz/{item_id}/toggle")
def quiz_question_toggle(item_id: int, request: Request, db: Session = Depends(get_db),
                         _=Depends(quiz_manager)):
    item = get_or_404(db, QuizQuestion, item_id)
    item.is_active = not item.is_active
    db.commit()
    flash(request, f"문제 #{item.id}을(를) {'사용해요' if item.is_active else '쉬게 했어요'}.")
    return go("/admin/quiz#questions")


@router.post("/quiz/{item_id}/delete")
def quiz_question_delete(item_id: int, request: Request, db: Session = Depends(get_db),
                         _=Depends(quiz_manager)):
    db.delete(get_or_404(db, QuizQuestion, item_id))
    db.commit()
    flash(request, "문제를 지웠어요.")
    return go("/admin/quiz#questions")


@router.post("/quiz/game/{game_id}/cancel")
def quiz_game_cancel(game_id: int, request: Request, db: Session = Depends(get_db),
                     _=Depends(quiz_manager)):
    game = get_or_404(db, QuizGame, game_id)
    if cancel_game(db, game):
        db.commit()
        flash(request, f"퀴즈 대결 #{game.id}을(를) 취소했어요.")
    else:
        flash(request, "이미 끝난 대결이에요.")
    return go("/admin/quiz")


# ---------- 사이트 잠금 - 소유자만 ----------

@router.get("/lock")
def lock_page(request: Request, db: Session = Depends(get_db), _=Depends(site_locker)):
    values = get_settings(db)
    return render(request, "admin/lock.html", db, modes=LOCK_MODES, values=values,
                  current=lock_mode(values))


@router.post("/lock")
async def lock_save(request: Request, db: Session = Depends(get_db), _=Depends(site_locker)):
    form = dict(await request.form())
    if form.get("site_lock") not in LOCK_MODES:
        form["site_lock"] = "off"
    save_settings(db, LOCK_FIELDS, form)
    mode = form["site_lock"]
    flash(request, f"🔒 사이트를 잠갔어요: {LOCK_MODES[mode][1]}. 이제 소유자만 들어올 수 있어요."
          if mode in LOCK_MODES else "🔓 사이트 잠금을 풀었어요. 모두 다시 들어올 수 있어요.")
    return go("/admin/lock")
