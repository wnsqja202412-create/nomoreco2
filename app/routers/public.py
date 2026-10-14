"""누구나 볼 수 있는 페이지들"""
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..auth import Forbidden, get_current_user, has_permission, require_permission
from ..database import get_db
from ..models import (CATEGORIES, DONATION_TYPES, PAYMENT_METHODS, Application,
                      BoardPost, Comment, Donation, Post, Recruitment, User)
from ..templating import flash, render

router = APIRouter()

AMOUNT_CHOICES = [
    (5000, "친환경 장바구니 1개를 나눠 줄 수 있어요"),
    (10000, "어린 나무 2그루를 심을 수 있어요"),
    (30000, "한 반 친구들에게 기후 수업을 1번 할 수 있어요"),
    (50000, "동네 플로깅 캠페인을 1번 열 수 있어요"),
]


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


@router.get("/board/{item_id}")
def board_detail(item_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(BoardPost, item_id)
    if item is None:
        raise HTTPException(404)
    return render(request, "board_detail.html", db, item=item)


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
    return render(request, "donate.html", db, status_code=status_code,
                  amounts=AMOUNT_CHOICES, types=DONATION_TYPES, methods=PAYMENT_METHODS,
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
    if donation_type not in DONATION_TYPES or method not in PAYMENT_METHODS:
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
    return render(request, "donate_thanks.html", db, donation=donation)


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
