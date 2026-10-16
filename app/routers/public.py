"""누구나 볼 수 있는 페이지들"""
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..auth import (Forbidden, get_current_user, has_permission, hash_password,
                    require_permission, verify_password)
from ..database import get_db
from ..models import (CATEGORIES, DONATION_TYPES, PAYMENT_METHODS, Application,
                      BoardPost, Comment, Donation, Post, Recruitment, User, now_kst)
from ..site import (active_bank_accounts, donate_amounts, donate_usage, get_settings,
                    split_lines)
from ..templating import flash, render

router = APIRouter()


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    posts = db.query(Post).order_by(Post.id.desc()).limit(3).all()
    recruits = (db.query(Recruitment).filter(Recruitment.is_open.is_(True))
                .order_by(Recruitment.id.desc()).limit(3).all())
    stats = {
        "posts": db.query(Post).count(),
        "people": db.query(User).count() + db.query(Application).count(),
        "donations": db.query(Donation).count(),
    }
    return render(request, "index.html", db, posts=posts, recruits=recruits, stats=stats)


@router.get("/about")
def about(request: Request, db: Session = Depends(get_db)):
    return render(request, "about.html", db)


@router.get("/activities")
def activities(request: Request, category: str = "", db: Session = Depends(get_db)):
    query = db.query(Post)
    if category in CATEGORIES:
        query = query.filter(Post.category == category)
    posts = query.order_by(Post.id.desc()).all()
    return render(request, "activities.html", db, posts=posts,
                  categories=CATEGORIES, current=category)


@router.get("/activities/{post_id}")
def activity_detail(post_id: int, request: Request, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(404)
    return render(request, "activity_detail.html", db, post=post)


# ---------- 게시판 ----------

@router.get("/board")
def board(request: Request, db: Session = Depends(get_db)):
    items = (db.query(BoardPost)
             .order_by(BoardPost.is_pinned.desc(), BoardPost.id.desc()).all())
    return render(request, "board.html", db, items=items)


def _can_edit_board(user: User | None, item: BoardPost) -> bool:
    """쓴 사람 본인이거나 관리자면 고치고 지울 수 있어요."""
    if user is None:
        return False
    return (item.user_id == user.id and has_permission(user, "write")) \
        or has_permission(user, "content_edit")


def _board_or_404(db: Session, item_id: int) -> BoardPost:
    item = db.get(BoardPost, item_id)
    if item is None:
        raise HTTPException(404)
    return item


@router.get("/board/new")
def board_new(request: Request, db: Session = Depends(get_db),
              _=Depends(require_permission("write"))):
    return render(request, "board_form.html", db, item=None)


@router.post("/board/new")
def board_create(
    request: Request, db: Session = Depends(get_db),
    user: User = Depends(require_permission("write")),
    title: str = Form(...), content: str = Form(...), is_pinned: str | None = Form(None),
):
    title, content = title.strip()[:200], content.strip()
    if not title or not content:
        flash(request, "제목과 내용을 써 주세요.")
        return RedirectResponse("/board/new", status_code=303)
    item = BoardPost(user_id=user.id, author_name=user.name, title=title, content=content,
                     is_pinned=bool(is_pinned) and has_permission(user, "content_edit"))
    db.add(item)
    db.commit()
    flash(request, "게시판에 새 글을 올렸어요.")
    return RedirectResponse(f"/board/{item.id}", status_code=303)


@router.get("/board/{item_id}/edit")
def board_edit(item_id: int, request: Request, db: Session = Depends(get_db),
               user: User = Depends(require_permission("view"))):
    item = _board_or_404(db, item_id)
    if not _can_edit_board(user, item):
        raise Forbidden()
    return render(request, "board_form.html", db, item=item)


@router.post("/board/{item_id}/edit")
def board_update(
    item_id: int, request: Request, db: Session = Depends(get_db),
    user: User = Depends(require_permission("view")),
    title: str = Form(...), content: str = Form(...), is_pinned: str | None = Form(None),
):
    item = _board_or_404(db, item_id)
    if not _can_edit_board(user, item):
        raise Forbidden()
    title, content = title.strip()[:200], content.strip()
    if not title or not content:
        flash(request, "제목과 내용을 써 주세요.")
        return RedirectResponse(f"/board/{item.id}/edit", status_code=303)
    item.title, item.content = title, content
    # 공지 고정은 관리자만 바꿀 수 있어요.
    if has_permission(user, "content_edit"):
        item.is_pinned = bool(is_pinned)
    item.updated_at = now_kst()
    db.commit()
    flash(request, "게시판 글을 수정했어요.")
    return RedirectResponse(f"/board/{item.id}", status_code=303)


@router.post("/board/{item_id}/delete")
def board_delete(item_id: int, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("view"))):
    item = _board_or_404(db, item_id)
    if not _can_edit_board(user, item):
        raise Forbidden()
    db.delete(item)
    db.commit()
    flash(request, "게시판 글을 지웠어요.")
    return RedirectResponse("/board", status_code=303)


@router.get("/board/{item_id}")
def board_detail(item_id: int, request: Request, db: Session = Depends(get_db)):
    item = _board_or_404(db, item_id)
    user = get_current_user(request, db)
    return render(request, "board_detail.html", db, item=item, user=user,
                  can_edit=_can_edit_board(user, item))


@router.post("/board/{item_id}/comments")
def comment_create(item_id: int, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("comment")),
                   content: str = Form(...)):
    item = db.get(BoardPost, item_id)
    if item is None:
        raise HTTPException(404)
    content = content.strip()[:1000]
    if content:
        db.add(Comment(board_post_id=item.id, user_id=user.id, author_name=user.name,
                       content=content))
        db.commit()
        flash(request, "댓글을 남겼어요.")
    return RedirectResponse(f"/board/{item.id}#comments", status_code=303)


@router.post("/board/{item_id}/comments/{comment_id}/delete")
def comment_delete(item_id: int, comment_id: int, request: Request,
                   db: Session = Depends(get_db),
                   user: User = Depends(require_permission("comment"))):
    comment = db.get(Comment, comment_id)
    if comment is None or comment.board_post_id != item_id:
        raise HTTPException(404)
    # 내가 쓴 댓글이거나 관리자일 때만 지울 수 있어요.
    if comment.user_id != user.id and not has_permission(user, "content_edit"):
        raise Forbidden()
    db.delete(comment)
    db.commit()
    flash(request, "댓글을 지웠어요.")
    return RedirectResponse(f"/board/{item_id}#comments", status_code=303)


# ---------- 후원 ----------

def _donate_page(request, db, error=None, form=None, status_code=200):
    site = get_settings(db)
    return render(request, "donate.html", db, status_code=status_code,
                  amounts=donate_amounts(site), usage=donate_usage(site),
                  faqs=split_lines(site["donate_faq"]), accounts=active_bank_accounts(db),
                  is_open=site["donate_open"].strip() != "0",
                  types=DONATION_TYPES, methods=PAYMENT_METHODS,
                  error=error, form=form or {})


@router.get("/donate")
def donate(request: Request, db: Session = Depends(get_db)):
    return _donate_page(request, db)


@router.post("/donate")
def donate_submit(
    request: Request,
    db: Session = Depends(get_db),
    donation_type: str = Form(...),
    amount: str = Form(""),
    custom_amount: str = Form(""),
    method: str = Form(...),
    donor_name: str = Form(...),
    contact: str = Form(...),
    message: str = Form(""),
    agree: str | None = Form(None),
):
    form = dict(donation_type=donation_type, amount=amount, custom_amount=custom_amount,
                method=method, donor_name=donor_name, contact=contact, message=message)
    raw = re.sub(r"[^0-9]", "", custom_amount or amount)
    value = int(raw) if raw else 0

    error = None
    if get_settings(db)["donate_open"].strip() == "0":
        error = "지금은 후원 신청을 받지 않아요."
    elif donation_type not in DONATION_TYPES or method not in PAYMENT_METHODS:
        error = "후원 종류와 결제 방법을 골라 주세요."
    elif value < 1000:
        error = "후원 금액은 1,000원 이상으로 정해 주세요."
    elif not agree:
        error = "개인정보 이용에 동의해 주세요."
    if error:
        return _donate_page(request, db, error=error, form=form, status_code=400)

    user = get_current_user(request, db)
    donation = Donation(
        user_id=user.id if user else None, donor_name=donor_name.strip(),
        contact=contact.strip(), donation_type=donation_type, amount=value,
        method=method, message=message.strip(),
    )
    db.add(donation)
    db.commit()
    request.session["last_donation_id"] = donation.id
    return RedirectResponse("/donate/thanks", status_code=303)


@router.get("/donate/thanks")
def donate_thanks(request: Request, db: Session = Depends(get_db)):
    donation_id = request.session.get("last_donation_id")
    donation = db.get(Donation, donation_id) if donation_id else None
    if donation is None:
        return RedirectResponse("/donate", status_code=303)
    return render(request, "donate_thanks.html", db, donation=donation,
                  accounts=active_bank_accounts(db))


# ---------- 함께하기 (사람 모집) ----------

@router.get("/join")
def join(request: Request, db: Session = Depends(get_db)):
    recruits = db.query(Recruitment).order_by(Recruitment.is_open.desc(), Recruitment.id.desc()).all()
    return render(request, "join.html", db, recruits=recruits)


@router.post("/join/{recruitment_id}/apply")
def apply(
    recruitment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    contact: str = Form(...),
    grade: str = Form(""),
    message: str = Form(""),
    agree: str | None = Form(None),
):
    recruitment = db.get(Recruitment, recruitment_id)
    if recruitment is None:
        raise HTTPException(404)
    if not recruitment.is_open:
        flash(request, "이미 마감된 모집이에요.")
    elif not agree:
        flash(request, "개인정보 이용과 보호자 동의에 체크해 주세요.")
    else:
        user = get_current_user(request, db)
        db.add(Application(
            recruitment_id=recruitment.id, user_id=user.id if user else None,
            name=name.strip(), contact=contact.strip(), grade=grade.strip(),
            message=message.strip(),
        ))
        db.commit()
        flash(request, f"'{recruitment.title}'에 지원해 주셔서 고마워요! 곧 연락드릴게요.")
    return RedirectResponse("/join", status_code=303)


# ---------- 마이페이지 (로그인한 사람만) ----------

@router.get("/mypage")
def mypage(request: Request, db: Session = Depends(get_db),
           user: User = Depends(require_permission("view"))):
    applications = (db.query(Application).filter_by(user_id=user.id)
                    .order_by(Application.id.desc()).all())
    donations = db.query(Donation).filter_by(user_id=user.id).order_by(Donation.id.desc()).all()
    return render(request, "mypage.html", db, user=user,
                  applications=applications, donations=donations)


@router.post("/mypage/password")
def change_password(request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("view")),
                    current: str = Form(...), password: str = Form(...),
                    password2: str = Form(...)):
    if not verify_password(current, user.password_hash):
        flash(request, "지금 비밀번호가 맞지 않아요.")
    elif len(password) < 6:
        flash(request, "새 비밀번호는 6글자 이상이어야 해요.")
    elif password != password2:
        flash(request, "새 비밀번호 확인이 달라요.")
    else:
        user.password_hash = hash_password(password)
        db.commit()
        flash(request, "비밀번호를 바꿨어요.")
    return RedirectResponse("/mypage", status_code=303)
