"""누구나 볼 수 있는 페이지들"""
import re
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from starlette.datastructures import UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from ..auth import (Forbidden, get_current_user, has_permission, hash_password,
                    require_permission, verify_password)
from ..database import get_db
from ..images import delete_image_url, photo_upload, resolve_image
from ..models import (CATEGORIES, DONATION_TYPES, INQUIRY_CATEGORIES, PAYMENT_METHODS,
                      Application, BoardPost, Comment, Donation, Image, Inquiry, InquiryMessage,
                      Post, Recruitment, User, now_kst)
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


@router.get("/images/{image_id}")
def image(image_id: int, db: Session = Depends(get_db)):
    """올린 사진 보여 주기 - 사진은 바뀌지 않으니 브라우저가 오래 기억해도 돼요."""
    img = db.get(Image, image_id)
    if img is None:
        raise HTTPException(404)
    return Response(content=img.data, media_type=img.content_type, headers={
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
    })


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


def _board_form_error(request, db, item, error, title, content):
    """제목·내용이 비었거나 사진에 문제가 있으면, 쓴 글을 그대로 둔 채 다시 보여 줘요."""
    db.rollback()
    draft = SimpleNamespace(title=title, content=content,
                            image_url=item.image_url if item else "",
                            is_pinned=item.is_pinned if item else False)
    return render(request, "board_form.html", db, status_code=400, item=item, draft=draft,
                  error=error)


@router.post("/board/new")
def board_create(
    request: Request, db: Session = Depends(get_db),
    user: User = Depends(require_permission("write")),
    title: str = Form(...), content: str = Form(...), is_pinned: str | None = Form(None),
    photo: UploadFile | None = Depends(photo_upload),
):
    title, content = title.strip()[:200], content.strip()
    if not title or not content:
        return _board_form_error(request, db, None, "제목과 내용을 써 주세요.", title, content)
    try:
        image = resolve_image(db, "", photo, user=user)
    except ValueError as e:
        return _board_form_error(request, db, None, str(e), title, content)
    item = BoardPost(user_id=user.id, author_name=user.name, title=title, content=content,
                     image_url=image,
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
    photo: UploadFile | None = Depends(photo_upload), remove_image: str | None = Form(None),
):
    item = _board_or_404(db, item_id)
    if not _can_edit_board(user, item):
        raise Forbidden()
    title, content = title.strip()[:200], content.strip()
    if not title or not content:
        return _board_form_error(request, db, item, "제목과 내용을 써 주세요.", title, content)
    try:
        image = resolve_image(db, item.image_url, photo, remove=bool(remove_image), user=user)
    except ValueError as e:
        return _board_form_error(request, db, item, str(e), title, content)
    item.title, item.content, item.image_url = title, content, image
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
    delete_image_url(db, item.image_url)
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
                  faqs=split_lines(site["donate_faq"]),
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


# ---------- 문의하기 (로그인한 사람만, 관리자와 대화해요) ----------

def _my_inquiry(db: Session, user: User, item_id: int) -> Inquiry:
    item = db.get(Inquiry, item_id)
    if item is None:
        raise HTTPException(404)
    if item.user_id != user.id and not has_permission(user, "manage_inquiries"):
        raise Forbidden()
    return item


@router.get("/inquiry")
def inquiry_list(request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("inquiry"))):
    items = (db.query(Inquiry).filter_by(user_id=user.id)
             .order_by(Inquiry.updated_at.desc()).all())
    return render(request, "inquiry.html", db, items=items)


@router.get("/inquiry/new")
def inquiry_new(request: Request, db: Session = Depends(get_db),
                _=Depends(require_permission("inquiry"))):
    return render(request, "inquiry_form.html", db, categories=INQUIRY_CATEGORIES)


@router.post("/inquiry/new")
def inquiry_create(request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("inquiry")),
                   category: str = Form("일반"), title: str = Form(...),
                   content: str = Form(...)):
    title, content = title.strip()[:200], content.strip()[:3000]
    if not title or not content:
        flash(request, "제목과 내용을 써 주세요.")
        return RedirectResponse("/inquiry/new", status_code=303)
    item = Inquiry(user_id=user.id, author_name=user.name, title=title,
                   category=category if category in INQUIRY_CATEGORIES else "기타")
    item.messages.append(InquiryMessage(user_id=user.id, author_name=user.name, content=content))
    db.add(item)
    db.commit()
    flash(request, "문의를 보냈어요. 관리자가 답변하면 여기에서 볼 수 있어요.")
    return RedirectResponse(f"/inquiry/{item.id}", status_code=303)


@router.get("/inquiry/{item_id}")
def inquiry_detail(item_id: int, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("inquiry"))):
    return render(request, "inquiry_detail.html", db, item=_my_inquiry(db, user, item_id))


@router.post("/inquiry/{item_id}/reply")
def inquiry_reply(item_id: int, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("inquiry")),
                  content: str = Form(...)):
    item = _my_inquiry(db, user, item_id)
    content = content.strip()[:3000]
    if item.status == "종료":
        flash(request, "끝난 문의예요. 새 문의를 남겨 주세요.")
    elif content:
        item.messages.append(InquiryMessage(user_id=user.id, author_name=user.name,
                                            content=content))
        item.status, item.updated_at = "답변대기", now_kst()
        db.commit()
        flash(request, "메시지를 보냈어요.")
    return RedirectResponse(f"/inquiry/{item.id}#bottom", status_code=303)


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
