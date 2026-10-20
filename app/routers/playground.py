"""놀이터 - 가상 머니로 하는 작은 게임들. (진짜 돈이 아니에요)

- 놀이터가 닫혀 있으면 등급과 상관없이 아무도 못 들어와요.
- 새 게임을 만들 때는 GAMES 에 한 줄 더하고, 아래에 그 게임의 주소들을 만들면 돼요.
  돈은 언제나 app/wallet.py 로만 주고받아요.
"""
import secrets
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import wallet
from ..auth import require_permission
from ..database import get_db
from ..models import Coinflip, MoneyLog, User, now_kst
from ..templating import flash, render

router = APIRouter(prefix="/playground")

# 놀이터 게임 목록 (이름, 아이콘, 설명, 주소)
GAMES = [
    ("코인플립", "🪙", "판돈을 걸고 1:1로 동전 던지기! 이기면 판돈 2배를 가져가요.", "/playground/coinflip"),
]

MIN_BET = 100
MAX_MESSAGE = 100


class PlaygroundClosed(Exception):
    pass


def player(request: Request, db: Session = Depends(get_db),
           user: User = Depends(require_permission("play"))) -> User:
    """놀이터 문지기 - 닫혀 있으면 소유자도 못 들어와요. 들어오면 지갑을 만들어 줘요."""
    if not wallet.playground_open(db):
        raise PlaygroundClosed()
    wallet.ensure_wallet(db, user.id)
    return user


def go(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _page(request, name, db, user, **context):
    """놀이터 화면 - 내 돈은 놀이터 안에서만 보여요."""
    my_wallet = wallet.ensure_wallet(db, user.id)
    return render(request, name, db, me=user, wallet=my_wallet,
                  can_claim=my_wallet.last_daily != now_kst().date(),
                  daily=wallet.daily_amount(db), **context)


@router.get("")
def home(request: Request, db: Session = Depends(get_db), user: User = Depends(player)):
    logs = (db.query(MoneyLog).filter_by(user_id=user.id)
            .order_by(MoneyLog.id.desc()).limit(10).all())
    return _page(request, "playground/index.html", db, user, games=GAMES, logs=logs)


@router.post("/daily")
def daily(request: Request, db: Session = Depends(get_db), user: User = Depends(player)):
    amount = wallet.claim_daily(db, user.id)
    flash(request, f"오늘의 용돈 {amount:,}원을 받았어요! 💰" if amount
          else "오늘은 이미 받았어요. 밤 12시가 지나면 다시 받을 수 있어요.")
    # 버튼을 누른 놀이터 화면으로 돌아가요. (놀이터 밖 주소로는 안 가요)
    back = urlparse(request.headers.get("referer") or "").path
    return go(back if back.startswith("/playground") else "/playground")


# ---------- 코인플립 ----------

def _flip_or_404(db: Session, flip_id: int) -> Coinflip:
    flip = db.get(Coinflip, flip_id)
    if flip is None:
        raise HTTPException(404)
    return flip


@router.get("/coinflip")
def coinflip_list(request: Request, db: Session = Depends(get_db), user: User = Depends(player)):
    open_flips = (db.query(Coinflip).filter(Coinflip.status == "open")
                  .order_by(Coinflip.id.desc()).all())
    recent = (db.query(Coinflip).filter(Coinflip.status == "done")
              .order_by(Coinflip.finished_at.desc()).limit(10).all())
    return _page(request, "playground/coinflip_list.html", db, user,
                 open_flips=open_flips, recent=recent)


@router.get("/coinflip/new")
def coinflip_new(request: Request, db: Session = Depends(get_db), user: User = Depends(player)):
    return _page(request, "playground/coinflip_new.html", db, user, min_bet=MIN_BET)


@router.post("/coinflip/new")
def coinflip_create(request: Request, db: Session = Depends(get_db),
                    user: User = Depends(player), bet: str = Form(...),
                    message: str = Form("")):
    digits = "".join(ch for ch in bet if ch.isdigit())
    amount = int(digits) if digits else 0
    if amount < MIN_BET:
        flash(request, f"판돈은 {MIN_BET:,}원 이상이어야 해요.")
        return go("/playground/coinflip/new")
    flip = Coinflip(creator_id=user.id, creator_name=user.name, bet=amount,
                    message=message.strip()[:MAX_MESSAGE])
    db.add(flip)
    db.flush()
    # 판돈은 만들 때 미리 맡겨 둬요. (취소하면 돌려받아요)
    if not wallet.change(db, user.id, -amount, f"코인플립 #{flip.id} 만들기"):
        db.rollback()
        flash(request, "돈이 모자라요.")
        return go("/playground/coinflip/new")
    db.commit()
    flash(request, "코인플립을 만들었어요! 누가 들어오면 바로 시작해요.")
    return go(f"/playground/coinflip/{flip.id}")


@router.get("/coinflip/{flip_id}")
def coinflip_detail(flip_id: int, request: Request, play: int = 0,
                    db: Session = Depends(get_db), user: User = Depends(player)):
    flip = _flip_or_404(db, flip_id)
    autoplay = bool(play) and flip.status == "done"
    extra = {}
    if autoplay and flip.winner_id == user.id:
        # 애니메이션이 끝나기 전에 늘어난 돈을 보고 결과를 눈치채지 않게, 처음엔 이기기 전 돈을 보여 줘요.
        extra["shown_balance"] = wallet.ensure_wallet(db, user.id).balance - flip.bet * 2
    return _page(request, "playground/coinflip_detail.html", db, user, flip=flip,
                 autoplay=autoplay, **extra)


@router.get("/coinflip/{flip_id}/status")
def coinflip_status(flip_id: int, db: Session = Depends(get_db), _=Depends(player)):
    """만든 사람 화면이 2초마다 물어봐요: 누가 들어왔나요?"""
    flip = _flip_or_404(db, flip_id)
    return JSONResponse({"status": flip.status, "joiner": flip.joiner_name,
                         "winner": flip.winner_name})


@router.post("/coinflip/{flip_id}/join")
def coinflip_join(flip_id: int, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(player)):
    flip = _flip_or_404(db, flip_id)
    if flip.creator_id == user.id:
        flash(request, "내가 만든 게임에는 들어갈 수 없어요.")
        return go(f"/playground/coinflip/{flip.id}")
    if flip.status != "open":
        flash(request, "이미 끝났거나 취소된 게임이에요.")
        return go(f"/playground/coinflip/{flip.id}")
    if not wallet.change(db, user.id, -flip.bet, f"코인플립 #{flip.id} 참가"):
        db.rollback()
        flash(request, f"돈이 모자라요. 판돈 {flip.bet:,}원이 필요해요.")
        return go("/playground/coinflip")

    # 결과는 서버가 정해요. 화면의 5초 애니메이션은 정해진 결과를 보여 주기만 해요.
    creator_wins = secrets.randbelow(2) == 0
    winner_id = flip.creator_id if creator_wins else user.id
    winner_name = flip.creator_name if creator_wins else user.name
    # 'open' 일 때만 바꿔요 → 두 사람이 동시에 들어와도 한 명만 성공해요.
    taken = (db.query(Coinflip).filter(Coinflip.id == flip.id, Coinflip.status == "open")
             .update({"status": "done", "joiner_id": user.id, "joiner_name": user.name,
                      "winner_id": winner_id, "winner_name": winner_name,
                      "finished_at": now_kst()}, synchronize_session=False))
    if taken == 0:
        db.rollback()  # 판돈도 다시 돌아와요.
        flash(request, "한 발 늦었어요! 다른 사람이 먼저 들어갔어요.")
        return go("/playground/coinflip")
    if winner_id is not None:
        wallet.change(db, winner_id, flip.bet * 2, f"코인플립 #{flip.id} 승리")
    db.commit()
    return go(f"/playground/coinflip/{flip.id}?play=1")


@router.post("/coinflip/{flip_id}/cancel")
def coinflip_cancel(flip_id: int, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(player)):
    flip = _flip_or_404(db, flip_id)
    if flip.creator_id != user.id:
        flash(request, "내가 만든 게임만 취소할 수 있어요.")
        return go(f"/playground/coinflip/{flip.id}")
    if cancel_flip(db, flip, f"코인플립 #{flip.id} 취소 (돌려받음)"):
        db.commit()
        flash(request, f"게임을 취소하고 {flip.bet:,}원을 돌려받았어요.")
    else:
        flash(request, "이미 시작된 게임은 취소할 수 없어요.")
    return go("/playground/coinflip")


def cancel_flip(db: Session, flip: Coinflip, reason: str, actor_id: int | None = None) -> bool:
    """기다리던 게임을 취소하고 판돈을 돌려줘요. (관리자 화면에서도 써요)"""
    cancelled = (db.query(Coinflip).filter(Coinflip.id == flip.id, Coinflip.status == "open")
                 .update({"status": "cancelled", "finished_at": now_kst()},
                         synchronize_session=False))
    if cancelled == 0:
        return False
    if flip.creator_id is not None:
        wallet.change(db, flip.creator_id, flip.bet, reason, actor_id)
    return True
