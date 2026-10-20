"""기후 퀴즈 대결 (/quiz) - 놀이터와 상관없는 따로 된 페이지예요. 돈은 쓰지 않아요.

- 대결을 만들면 사용 중인 문제 중 10문제를 무작위로 골라요.
- 두 사람은 같은 10문제를 서로 다른 순서로 풀어요. (보기 순서도 사람마다 달라요)
- 틀리면 몇 초 기다린 뒤 같은 문제를 다시 풀어요. 10문제를 먼저 다 맞히면 이겨요.
- 퀴즈 열기/닫기와 문제는 총관리자 이상이 '퀴즈 관리'에서 고쳐요.
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
from ..models import QuizMatch, QuizQuestion, User, now_kst
from ..site import get_settings
from ..templating import flash, render

router = APIRouter(prefix="/quiz")
quizzer = require_permission("quiz")

QUESTIONS_PER_MATCH = 10
MAX_MESSAGE = 100
_rng = secrets.SystemRandom()


def go(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def quiz_open(db: Session) -> bool:
    return get_settings(db)["quiz_enabled"].strip() != "0"


def wrong_wait_seconds(db: Session) -> int:
    digits = "".join(ch for ch in get_settings(db)["quiz_wrong_wait"] if ch.isdigit())
    return min(int(digits), 30) if digits else 3


def _ids(text: str) -> list[int]:
    return [int(x) for x in text.split(",") if x]


def _side(match: QuizMatch, user_id: int) -> str | None:
    """이 사람이 대결에서 어느 쪽인지 - 'creator', 'joiner', 아니면 None(구경꾼)"""
    if match.creator_id == user_id:
        return "creator"
    if match.joiner_id is not None and match.joiner_id == user_id:
        return "joiner"
    return None


def _match_or_404(db: Session, match_id: int) -> QuizMatch:
    match = db.get(QuizMatch, match_id)
    if match is None:
        raise HTTPException(404)
    return match


def shuffled_choices(match: QuizMatch, user_id: int, question: QuizQuestion) -> list[tuple[int, str]]:
    """보기를 사람마다 다른 순서로 섞어요. (새로고침해도 순서는 그대로예요)"""
    choices = list(enumerate(question.choice_list))
    random.Random(f"{match.id}-{user_id}-{question.id}").shuffle(choices)
    return choices


def _finish(db: Session, match: QuizMatch, winner_id: int | None, winner_name: str,
            reason: str) -> bool:
    """진행 중인 대결을 끝내요. 이미 끝났으면 False."""
    return (db.query(QuizMatch).filter(QuizMatch.id == match.id, QuizMatch.status == "playing")
            .update({"status": "done", "winner_id": winner_id, "winner_name": winner_name,
                     "end_reason": reason, "finished_at": now_kst()},
                    synchronize_session=False)) > 0


def cancel_match(db: Session, match: QuizMatch) -> bool:
    """기다리거나 진행 중인 대결을 취소해요. (관리자 화면에서도 써요)"""
    return (db.query(QuizMatch)
            .filter(QuizMatch.id == match.id, QuizMatch.status.in_(["open", "playing"]))
            .update({"status": "cancelled", "finished_at": now_kst()},
                    synchronize_session=False)) > 0


def forget_user(db: Session, user_id: int) -> None:
    """회원을 지울 때 그 회원의 기다리던·하던 대결은 취소하고, 기록에서 이름표만 떼요."""
    (db.query(QuizMatch)
     .filter(QuizMatch.status.in_(["open", "playing"]),
             or_(QuizMatch.creator_id == user_id, QuizMatch.joiner_id == user_id))
     .update({"status": "cancelled", "finished_at": now_kst()}, synchronize_session=False))
    for column in (QuizMatch.creator_id, QuizMatch.joiner_id, QuizMatch.winner_id):
        db.query(QuizMatch).filter(column == user_id).update({column: None},
                                                             synchronize_session=False)


# ---------- 목록 · 만들기 ----------

@router.get("")
def quiz_list(request: Request, db: Session = Depends(get_db), user: User = Depends(quizzer)):
    open_matches = (db.query(QuizMatch).filter(QuizMatch.status == "open")
                    .order_by(QuizMatch.id.desc()).all())
    playing = (db.query(QuizMatch).filter(QuizMatch.status == "playing")
               .order_by(QuizMatch.id.desc()).all())
    recent = (db.query(QuizMatch).filter(QuizMatch.status == "done")
              .order_by(QuizMatch.finished_at.desc()).limit(10).all())
    active = db.query(QuizQuestion).filter(QuizQuestion.is_active.is_(True)).count()
    return render(request, "quiz/list.html", db, me=user, open_matches=open_matches,
                  playing=playing, recent=recent, is_open=quiz_open(db),
                  enough=active >= QUESTIONS_PER_MATCH, per_match=QUESTIONS_PER_MATCH)


@router.post("/new")
def quiz_create(request: Request, db: Session = Depends(get_db), user: User = Depends(quizzer),
                message: str = Form("")):
    if not quiz_open(db):
        flash(request, "퀴즈 대결이 지금 닫혀 있어요.")
        return go("/quiz")
    ids = [q.id for q in db.query(QuizQuestion).filter(QuizQuestion.is_active.is_(True))
           if len(q.choice_list) >= 2]
    if len(ids) < QUESTIONS_PER_MATCH:
        flash(request, f"사용 중인 문제가 {QUESTIONS_PER_MATCH}개보다 적어서 대결을 만들 수 없어요.")
        return go("/quiz")
    match = QuizMatch(creator_id=user.id, creator_name=user.name,
                      message=message.strip()[:MAX_MESSAGE],
                      creator_questions=",".join(map(str, _rng.sample(ids, QUESTIONS_PER_MATCH))))
    db.add(match)
    db.commit()
    flash(request, "퀴즈 대결을 만들었어요! 누가 들어오면 바로 시작해요.")
    return go(f"/quiz/{match.id}")


# ---------- 대결 화면 ----------

@router.get("/{match_id}")
def quiz_detail(match_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(quizzer)):
    match = _match_or_404(db, match_id)
    side = _side(match, user.id)
    context = dict(match=match, side=side, per_match=QUESTIONS_PER_MATCH)
    if match.status == "playing" and side:
        my_ids = _ids(getattr(match, f"{side}_questions"))
        step = getattr(match, f"{side}_progress")
        question = db.get(QuizQuestion, my_ids[step]) if step < len(my_ids) else None
        wait_until = getattr(match, f"{side}_wait_until")
        wait = max(0, int((wait_until - now_kst()).total_seconds()) + 1) if wait_until else 0
        context.update(step=step, question=question, wait=wait,
                       choices=shuffled_choices(match, user.id, question) if question else [])
    elif match.status == "done":
        # 다 끝난 뒤에는 문제와 정답, 해설을 보여 줘요. (내 순서대로, 구경꾼은 만든 사람 순서)
        order = _ids(getattr(match, f"{side}_questions") if side else match.creator_questions)
        found = {q.id: q for q in db.query(QuizQuestion).filter(QuizQuestion.id.in_(order))}
        context["review"] = [found.get(i) for i in order]
    return render(request, "quiz/detail.html", db, me=user, **context)


@router.get("/{match_id}/status")
def quiz_status(match_id: int, db: Session = Depends(get_db), _=Depends(quizzer)):
    """대결 화면이 2초마다 물어봐요: 누가 들어왔나요? 상대는 몇 문제 맞혔나요?"""
    m = _match_or_404(db, match_id)
    return JSONResponse({"status": m.status, "joiner": m.joiner_name, "winner": m.winner_name,
                         "creator_progress": m.creator_progress,
                         "joiner_progress": m.joiner_progress})


@router.post("/{match_id}/join")
def quiz_join(match_id: int, request: Request, db: Session = Depends(get_db),
              user: User = Depends(quizzer)):
    match = _match_or_404(db, match_id)
    back = f"/quiz/{match.id}"
    if not quiz_open(db):
        flash(request, "퀴즈 대결이 지금 닫혀 있어요.")
        return go(back)
    if match.creator_id == user.id:
        flash(request, "내가 만든 대결에는 들어갈 수 없어요.")
        return go(back)
    if match.status != "open":
        flash(request, "이미 시작했거나 끝난 대결이에요.")
        return go(back)
    # 같은 10문제를 다른 순서로 섞어요.
    order = _ids(match.creator_questions)
    mine = order[:]
    while mine == order:
        _rng.shuffle(mine)
    # 'open' 일 때만 바꿔요 → 두 사람이 동시에 들어와도 한 명만 성공해요.
    taken = (db.query(QuizMatch).filter(QuizMatch.id == match.id, QuizMatch.status == "open")
             .update({"status": "playing", "joiner_id": user.id, "joiner_name": user.name,
                      "joiner_questions": ",".join(map(str, mine)), "started_at": now_kst()},
                     synchronize_session=False))
    db.commit()
    if taken == 0:
        flash(request, "한 발 늦었어요! 다른 사람이 먼저 들어갔어요.")
        return go("/quiz")
    flash(request, "대결 시작! 10문제를 먼저 다 맞히면 이겨요. 🏁")
    return go(back)


@router.post("/{match_id}/answer")
def quiz_answer(match_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(quizzer), step: int = Form(...), choice: int = Form(...)):
    match = _match_or_404(db, match_id)
    back = f"/quiz/{match.id}"
    side = _side(match, user.id)
    if side is None or match.status != "playing":
        return go(back)
    if step != getattr(match, f"{side}_progress"):
        return go(back)  # 버튼을 두 번 눌렀거나 오래된 화면이에요.
    now = now_kst()
    wait_until = getattr(match, f"{side}_wait_until")
    if wait_until and wait_until > now:
        flash(request, "⏳ 조금만 기다렸다가 다시 풀어 주세요.")
        return go(back)

    question = db.get(QuizQuestion, _ids(getattr(match, f"{side}_questions"))[step])
    # 대결 중에 관리자가 문제를 지웠다면 그 문제는 맞힌 걸로 쳐요.
    correct = question is None or choice == question.answer
    col = getattr(QuizMatch, f"{side}_progress")
    if not correct:
        wait = wrong_wait_seconds(db)
        wrong_col = getattr(QuizMatch, f"{side}_wrong")
        (db.query(QuizMatch).filter(QuizMatch.id == match.id, col == step)
         .update({wrong_col: wrong_col + 1,
                  getattr(QuizMatch, f"{side}_wait_until"): now + timedelta(seconds=wait)},
                 synchronize_session=False))
        db.commit()
        flash(request, f"❌ 틀렸어요! {wait}초 뒤에 다시 풀 수 있어요." if wait
              else "❌ 틀렸어요! 다시 풀어 보세요.")
        return go(back)

    # 맞힌 문제 수는 '지금 푼 문제 번호'가 맞을 때만 올려요. (두 번 눌러도 한 번만)
    moved = (db.query(QuizMatch)
             .filter(QuizMatch.id == match.id, QuizMatch.status == "playing", col == step)
             .update({col: col + 1}, synchronize_session=False))
    if moved and step + 1 >= QUESTIONS_PER_MATCH:
        _finish(db, match, user.id, user.name, "solved")
    elif moved:
        flash(request, f"⭕ 정답! 남은 문제 {QUESTIONS_PER_MATCH - step - 1}개")
    db.commit()
    return go(back)


@router.post("/{match_id}/forfeit")
def quiz_forfeit(match_id: int, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(quizzer)):
    match = _match_or_404(db, match_id)
    side = _side(match, user.id)
    if side and match.status == "playing":
        if side == "creator":
            winner_id, winner_name = match.joiner_id, match.joiner_name
        else:
            winner_id, winner_name = match.creator_id, match.creator_name
        if _finish(db, match, winner_id, winner_name, "forfeit"):
            db.commit()
            flash(request, "대결을 포기했어요.")
    return go(f"/quiz/{match.id}")


@router.post("/{match_id}/cancel")
def quiz_cancel(match_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(quizzer)):
    match = _match_or_404(db, match_id)
    if match.creator_id != user.id or match.status != "open":
        flash(request, "기다리는 중인 내 대결만 취소할 수 있어요.")
        return go(f"/quiz/{match.id}")
    if cancel_match(db, match):
        db.commit()
        flash(request, "대결을 취소했어요.")
    return go("/quiz")
