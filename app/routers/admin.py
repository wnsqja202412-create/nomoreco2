"""관리자 전용 페이지 - 'admin_access' 권한이 있는 아이디만 들어올 수 있어요."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import ROLE_PERMISSIONS, require_permission
from ..database import get_db
from ..models import (APPLICATION_STATUSES, CATEGORIES, Application, Donation, Post,
                      Recruitment, Setting, User, now_kst)
from ..site import SETTING_FIELDS, get_settings
from ..templating import flash, render

router = APIRouter(prefix="/admin", dependencies=[Depends(require_permission("admin_access"))])
content_editor = require_permission("content_edit")
user_manager = require_permission("manage_users")


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
    return render(request, "admin/donations.html", db, items=items, by_type=by_type, total=total)


@router.post("/donations/{item_id}/delete")
def donation_delete(item_id: int, request: Request, db: Session = Depends(get_db),
                    _=Depends(content_editor)):
    db.delete(get_or_404(db, Donation, item_id))
    db.commit()
    flash(request, "후원 신청을 지웠어요.")
    return go("/admin/donations")


# ---------- 회원 / 권한 ----------

@router.get("/users")
def users(request: Request, db: Session = Depends(get_db), _=Depends(user_manager)):
    items = db.query(User).order_by(User.id).all()
    return render(request, "admin/users.html", db, items=items, roles=list(ROLE_PERMISSIONS),
                  role_permissions=ROLE_PERMISSIONS)


@router.post("/users/{user_id}/role")
def user_role(user_id: int, request: Request, db: Session = Depends(get_db),
              me: User = Depends(user_manager), role: str = Form(...)):
    target = get_or_404(db, User, user_id)
    if target.id == me.id:
        flash(request, "자기 자신의 권한은 바꿀 수 없어요.")
    elif role in ROLE_PERMISSIONS:
        target.role = role
        db.commit()
        flash(request, f"{target.username}의 권한을 바꿨어요.")
    return go("/admin/users")


@router.post("/users/{user_id}/delete")
def user_delete(user_id: int, request: Request, db: Session = Depends(get_db),
                me: User = Depends(user_manager)):
    target = get_or_404(db, User, user_id)
    if target.id == me.id:
        flash(request, "자기 자신은 지울 수 없어요.")
        return go("/admin/users")
    db.query(Application).filter_by(user_id=target.id).update({"user_id": None})
    db.query(Donation).filter_by(user_id=target.id).update({"user_id": None})
    db.delete(target)
    db.commit()
    flash(request, f"{target.username} 회원을 지웠어요.")
    return go("/admin/users")


# ---------- 사이트 문구 설정 ----------

@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db), _=Depends(content_editor)):
    return render(request, "admin/settings.html", db, fields=SETTING_FIELDS, values=get_settings(db))


@router.post("/settings")
async def settings_save(request: Request, db: Session = Depends(get_db),
                        _=Depends(content_editor)):
    form = await request.form()
    for key, *_rest in SETTING_FIELDS:
        if key not in form:
            continue
        row = db.get(Setting, key)
        if row:
            row.value = str(form[key])
        else:
            db.add(Setting(key=key, value=str(form[key])))
    db.commit()
    flash(request, "사이트 문구를 저장했어요.")
    return go("/admin/settings")
