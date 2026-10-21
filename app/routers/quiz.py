"""기후 퀴즈 대결 (/quiz) - 놀이터와 상관없는 따로 된 페이지예요. 돈은 쓰지 않아요.

- 자동 매칭: '대결 시작'을 누르면 기다리던 사람과 바로 이어져요. 아무도 없으면 내가 기다려요.
- 수동 매칭: 방을 만들면 목록에 올라가고, 다른 사람이 골라서 들어와요.
- 이어지면 "상대를 찾았습니다!" 와 함께 카운트다운(기본 3초) 뒤에 시작해요.
- 사용 중인 문제 중 10문제를 무작위로 골라, 두 사람이 같은 문제를 서로 다른 순서로 풀어요.
- 문제마다 한 번씩만 답해요. 제한 시간(기본 2분) 안에 더 많이 맞힌 사람이 이겨요. 같으면 무승부.
- 결과(점수)는 두 사람이 모두 끝나거나 시간이 다 됐을 때 함께 공개돼요.
- 매칭 방법·시간·문구·문제는 총관리자 이상이 '퀴즈 관리'에서 바꿔요.
"""
import random
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..auth import require_permission
from ..database import get_db
from ..models import QuizGame, QuizQuestion, User, now_kst
from ..site import QUIZ_MATCH_MODES, get_settings
from ..templating import flash, render

router = APIRouter(prefix="/quiz")
quizzer = require_permission("quiz")

QUESTIONS_PER_MATCH = 10
MAX_MESSAGE = 100
STALE_SECONDS = 15   # 기다리는 화면이 이만큼 소식이 없으면 자리를 비운 걸로 봐요.
ANSWER_GRACE = 3     # 시간이 막 끝날 때 보낸 답은 조금 봐줘요. (인터넷이 느릴 수 있어서)
_rng = secrets.SystemRandom()


def go(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# ---------- 설정 ----------

def _int_setting(site: dict, key: str, default: int, low: int, high: int) -> int:
    digits = "".join(ch for ch in site[key] if ch.isdigit())
    return max(low, min(int(digits), high)) if digits else default


def quiz_config(db: Session) -> dict:
    site = get_settings(db)
    mode = site["quiz_match_mode"].strip()
    return dict(open=site["quiz_enabled"].strip() != "0",
                mode=mode if mode in QUIZ_MATCH_MODES else "both",
                time_limit=_int_setting(site, "quiz_time_limit", 120, 10, 3600),
                countdown=_int_setting(site, "quiz_countdown", 3, 0, 30))


# ---------- 도우미 ----------

def _ids(text: str) -> list[int]:
    return [int(x) for x in text.split(",") if x]


def _side(game: QuizGame, user_id: int) -> str | None:
    """이 사람이 대결에서 어느 쪽인지 - 'creator', 'joiner', 아니면 None(구경꾼)"""
    if game.creator_id == user_id:
        return "creator"
    if game.joiner_id is not None and game.joiner_id == user_id:
        return "joiner"
    return None


def _other(side: str) -> str:
    return "joiner" if side == "creator" else "creator"


def _game_or_404(db: Session, game_id: int) -> QuizGame:
    game = db.get(QuizGame, game_id)
    if game is None:
        raise HTTPException(404)
    return game


def _active_questions(db: Session) -> list[int]:
    return [q.id for q in db.query(QuizQuestion).filter(QuizQuestion.is_active.is_(True))
            if len(q.choice_list) >= 2]


def shuffled_choices(game: QuizGame, user_id: int, question: QuizQuestion) -> list[tuple[int, str]]:
    """보기를 사람마다 다른 순서로 섞어요. (새로고침해도 순서는 그대로예요)"""
    choices = list(enumerate(question.choice_list))
    random.Random(f"{game.id}-{user_id}-{question.id}").shuffle(choices)
    return choices


def settle(db: Session, game: QuizGame) -> None:
    """두 사람이 다 풀었거나 시간이 끝났으면 결과를 정해요. (누가 화면을 열 때마다 확인해요)"""
    now = now_kst()
    if game.status != "playing" or game.ends_at is None:
        return
    both_done = game.creator_done_at is not None and game.joiner_done_at is not None
    if not both_done and now < game.ends_at + timedelta(seconds=ANSWER_GRACE):
        return
    if game.creator_score > game.joiner_score:
        result, winner = "creator", game.creator_name
    elif game.joiner_score > game.creator_score:
        result, winner = "joiner", game.joiner_name
    else:
        result, winner = "draw", ""
    done = (db.query(QuizGame).filter(QuizGame.id == game.id, QuizGame.status == "playing")
            .update({"status": "done", "result": result, "winner_name": winner,
                     "finished_at": now}, synchronize_session=False))
    db.commit()
    if done:
        db.refresh(game)


def _clean_stale(db: Session) -> None:
    """자리를 오래 비운 기다리는 대결은 취소해요."""
    (db.query(QuizGame)
     .filter(QuizGame.status == "waiting",
             QuizGame.creator_seen_at < now_kst() - timedelta(seconds=60))
     .update({"status": "cancelled", "finished_at": now_kst()}, synchronize_session=False))
    db.commit()


def _my_active_game(db: Session, user_id: int) -> QuizGame | None:
    games = (db.query(QuizGame)
             .filter(QuizGame.status.in_(["waiting", "playing"]),
                     or_(QuizGame.creator_id == user_id, QuizGame.joiner_id == user_id))
             .order_by(QuizGame.id.desc()).all())
    for game in games:
        settle(db, game)
        if game.status in ("waiting", "playing"):
            return game
    return None


def _busy_game(db: Session, user: User, keep_mode: str | None = None) -> QuizGame | None:
    """이미 하고 있는 대결이 있으면 돌려줘요. 기다리기만 하던 대결은 (keep_mode가 아니면) 취소해요."""
    active = _my_active_game(db, user.id)
    if active and active.status == "waiting" and active.mode != keep_mode:
        cancel_game(db, active)
        db.commit()
        return None
    return active


def _claim(db: Session, game: QuizGame, user: User, cfg: dict) -> bool:
    """기다리던 대결에 들어가요. 두 사람이 동시에 들어와도 한 명만 성공해요."""
    order = _ids(game.creator_questions)
    mine = order[:]
    while mine == order:
        _rng.shuffle(mine)  # 같은 10문제를 다른 순서로
    starts = now_kst() + timedelta(seconds=cfg["countdown"])
    taken = (db.query(QuizGame).filter(QuizGame.id == game.id, QuizGame.status == "waiting")
             .update({"status": "playing", "joiner_id": user.id, "joiner_name": user.name,
                      "joiner_questions": ",".join(map(str, mine)),
                      "time_limit": cfg["time_limit"], "starts_at": starts,
                      "ends_at": starts + timedelta(seconds=cfg["time_limit"])},
                     synchronize_session=False))
    db.commit()
    return taken > 0


def _new_game(db: Session, user: User, mode: str, message: str = "") -> QuizGame | None:
    ids = _active_questions(db)
    if len(ids) < QUESTIONS_PER_MATCH:
        return None
    game = QuizGame(mode=mode, creator_id=user.id, creator_name=user.name,
                    message=message.strip()[:MAX_MESSAGE], creator_seen_at=now_kst(),
                    creator_questions=",".join(map(str, _rng.sample(ids, QUESTIONS_PER_MATCH))))
    db.add(game)
    db.commit()
    return game


def cancel_game(db: Session, game: QuizGame) -> bool:
    """기다리거나 진행 중인 대결을 취소해요. (관리자 화면에서도 써요)"""
    return (db.query(QuizGame)
            .filter(QuizGame.id == game.id, QuizGame.status.in_(["waiting", "playing"]))
            .update({"status": "cancelled", "finished_at": now_kst()},
                    synchronize_session=False)) > 0


def forget_user(db: Session, user_id: int) -> None:
    """회원을 지울 때 그 회원의 기다리던·하던 대결은 취소하고, 기록에서 이름표만 떼요."""
    (db.query(QuizGame)
     .filter(QuizGame.status.in_(["waiting", "playing"]),
             or_(QuizGame.creator_id == user_id, QuizGame.joiner_id == user_id))
     .update({"status": "cancelled", "finished_at": now_kst()}, synchronize_session=False))
    for column in (QuizGame.creator_id, QuizGame.joiner_id):
        db.query(QuizGame).filter(column == user_id).update({column: None},
                                                            synchronize_session=False)


def _phase(game: QuizGame, side: str | None) -> str:
    """화면에 보여 줄 단계"""
    if game.status in ("waiting", "done", "cancelled"):
        return game.status
    if now_kst() < game.starts_at:
        return "countdown"
    if side and (getattr(game, f"{side}_done_at") is not None or now_kst() >= game.ends_at):
        return "finished"  # 나는 다 풀었거나 시간이 끝났고, 상대를 기다려요
    return "playing" if side else "watching"


# ---------- 목록 · 매칭 ----------

@router.get("")
def quiz_list(request: Request, db: Session = Depends(get_db), user: User = Depends(quizzer)):
    _clean_stale(db)
    cfg = quiz_config(db)
    fresh = now_kst() - timedelta(seconds=STALE_SECONDS)
    rooms = (db.query(QuizGame)
             .filter(QuizGame.status == "waiting", QuizGame.mode == "manual",
                     QuizGame.creator_seen_at >= fresh)
             .order_by(QuizGame.id.desc()).all())
    recent = (db.query(QuizGame).filter(QuizGame.status == "done")
              .order_by(QuizGame.finished_at.desc()).limit(10).all())
    return render(request, "quiz/list.html", db, me=user, cfg=cfg, rooms=rooms, recent=recent,
                  active=_my_active_game(db, user.id),
                  enough=len(_active_questions(db)) >= QUESTIONS_PER_MATCH,
                  per_match=QUESTIONS_PER_MATCH)


def _can_start(request: Request, db: Session, cfg: dict, kind: str) -> bool:
    if not cfg["open"]:
        flash(request, "퀴즈 대결이 지금 닫혀 있어요.")
    elif cfg["mode"] not in (kind, "both"):
        flash(request, "지금은 그 매칭 방법을 쓸 수 없어요.")
    elif len(_active_questions(db)) < QUESTIONS_PER_MATCH:
        flash(request, f"사용 중인 문제가 {QUESTIONS_PER_MATCH}개보다 적어서 대결을 할 수 없어요.")
    else:
        return True
    return False


@router.post("/start")
def quiz_auto_start(request: Request, db: Session = Depends(get_db),
                    user: User = Depends(quizzer)):
    """자동 매칭 - 기다리는 사람이 있으면 바로 이어지고, 없으면 내가 기다려요."""
    cfg = quiz_config(db)
    if not _can_start(request, db, cfg, "auto"):
        return go("/quiz")
    active = _busy_game(db, user, keep_mode="auto")
    if active:
        return go(f"/quiz/{active.id}")
    fresh = now_kst() - timedelta(seconds=STALE_SECONDS)
    waiting = (db.query(QuizGame)
               .filter(QuizGame.status == "waiting", QuizGame.mode == "auto",
                       QuizGame.creator_id != user.id, QuizGame.creator_seen_at >= fresh)
               .order_by(QuizGame.id).limit(5).all())
    for game in waiting:
        if _claim(db, game, user, cfg):
            return go(f"/quiz/{game.id}")
    game = _new_game(db, user, "auto")
    return go(f"/quiz/{game.id}" if game else "/quiz")


@router.post("/room")
def quiz_room_create(request: Request, db: Session = Depends(get_db),
                     user: User = Depends(quizzer), message: str = Form("")):
    """수동 매칭 - 방을 만들어 목록에 올려요."""
    cfg = quiz_config(db)
    if not _can_start(request, db, cfg, "manual"):
        return go("/quiz")
    active = _busy_game(db, user)
    if active:
        flash(request, "이미 하고 있는 대결이 있어요.")
        return go(f"/quiz/{active.id}")
    game = _new_game(db, user, "manual", message)
    return go(f"/quiz/{game.id}" if game else "/quiz")


@router.post("/{game_id}/join")
def quiz_join(game_id: int, request: Request, db: Session = Depends(get_db),
              user: User = Depends(quizzer)):
    game = _game_or_404(db, game_id)
    cfg = quiz_config(db)
    if not _can_start(request, db, cfg, "manual"):
        return go("/quiz")
    if game.creator_id == user.id:
        return go(f"/quiz/{game.id}")
    if game.status != "waiting" or game.mode != "manual":
        flash(request, "이미 시작했거나 끝난 대결이에요.")
        return go("/quiz")
    if game.creator_seen_at < now_kst() - timedelta(seconds=STALE_SECONDS):
        cancel_game(db, game)
        db.commit()
        flash(request, "방을 만든 사람이 자리를 비워서 방이 없어졌어요.")
        return go("/quiz")
    active = _busy_game(db, user)
    if active:
        flash(request, "이미 하고 있는 대결이 있어요.")
        return go(f"/quiz/{active.id}")
    if not _claim(db, game, user, cfg):
        flash(request, "한 발 늦었어요! 다른 사람이 먼저 들어갔어요.")
        return go("/quiz")
    return go(f"/quiz/{game.id}")


@router.post("/{game_id}/cancel")
def quiz_cancel(game_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(quizzer)):
    game = _game_or_404(db, game_id)
    if game.creator_id == user.id and game.status == "waiting" and cancel_game(db, game):
        db.commit()
        flash(request, "대결을 취소했어요.")
    return go("/quiz")


# ---------- 대결 화면 ----------

@router.get("/{game_id}")
def quiz_detail(game_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(quizzer)):
    game = _game_or_404(db, game_id)
    settle(db, game)
    side = _side(game, user.id)
    if game.status == "waiting" and side == "creator":
        game.creator_seen_at = now_kst()
        db.commit()
    now, phase = now_kst(), _phase(game, side)
    context = dict(game=game, side=side, phase=phase, per_match=QUESTIONS_PER_MATCH)
    if game.starts_at:
        context["starts_in"] = max(0.0, (game.starts_at - now).total_seconds())
        context["ends_in"] = max(0.0, (game.ends_at - now).total_seconds())
    if phase == "playing":
        my_ids = _ids(getattr(game, f"{side}_questions"))
        step = len(_ids(getattr(game, f"{side}_answers")))
        question = db.get(QuizQuestion, my_ids[step])
        context.update(step=step, question=question,
                       choices=shuffled_choices(game, user.id, question) if question else [])
    if side:
        context["opp_answered"] = len(_ids(getattr(game, f"{_other(side)}_answers")))
        context["my_answered"] = len(_ids(getattr(game, f"{side}_answers")))
    if phase == "done":
        # 결과와 함께 문제·정답·해설을 보여 줘요. (내 순서대로, 구경꾼은 만든 사람 순서)
        view = side or "creator"
        order = _ids(getattr(game, f"{view}_questions"))
        picked = _ids(getattr(game, f"{view}_answers"))
        found = {q.id: q for q in db.query(QuizQuestion).filter(QuizQuestion.id.in_(order))}
        context["review"] = [(found.get(qid), picked[i] if i < len(picked) else None)
                             for i, qid in enumerate(order)]
        context["review_side"] = view
    return render(request, "quiz/detail.html", db, me=user, **context)


@router.get("/{game_id}/state")
def quiz_state(game_id: int, db: Session = Depends(get_db), user: User = Depends(quizzer)):
    """대결 화면이 자주 물어봐요: 상대가 왔나요? 몇 문제 풀었나요? 결과가 나왔나요?"""
    game = _game_or_404(db, game_id)
    settle(db, game)
    side = _side(game, user.id)
    if game.status == "waiting" and side == "creator":
        game.creator_seen_at = now_kst()
        db.commit()
    data = {"phase": _phase(game, side), "joiner": game.joiner_name}
    if side:
        data["opp_answered"] = len(_ids(getattr(game, f"{_other(side)}_answers")))
    return JSONResponse(data)


@router.post("/{game_id}/answer")
def quiz_answer(game_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(quizzer), step: int = Form(...), choice: int = Form(...)):
    game = _game_or_404(db, game_id)
    back = f"/quiz/{game.id}"
    settle(db, game)
    side = _side(game, user.id)
    now = now_kst()
    if (side is None or game.status != "playing" or now < game.starts_at
            or now > game.ends_at + timedelta(seconds=ANSWER_GRACE)):
        return go(back)
    old = getattr(game, f"{side}_answers")
    if step != len(_ids(old)) or step >= QUESTIONS_PER_MATCH:
        return go(back)  # 버튼을 두 번 눌렀거나 오래된 화면이에요.
    question = db.get(QuizQuestion, _ids(getattr(game, f"{side}_questions"))[step])
    correct = question is not None and choice == question.answer
    answers_col = getattr(QuizGame, f"{side}_answers")
    score_col = getattr(QuizGame, f"{side}_score")
    values = {answers_col: f"{old},{choice}" if old else str(choice),
              score_col: score_col + (1 if correct else 0)}
    if step + 1 >= QUESTIONS_PER_MATCH:
        values[getattr(QuizGame, f"{side}_done_at")] = now
    # 답은 '지금까지 고른 답'이 그대로일 때만 저장해요. (두 번 눌러도 한 번만)
    (db.query(QuizGame).filter(QuizGame.id == game.id, QuizGame.status == "playing",
                               answers_col == old)
     .update(values, synchronize_session=False))
    db.commit()
    db.refresh(game)
    settle(db, game)
    return go(back)
