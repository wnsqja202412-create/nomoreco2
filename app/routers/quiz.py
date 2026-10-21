"""기후 퀴즈 대결 (/quiz) - 놀이터와 상관없는 따로 된 페이지예요. 돈은 쓰지 않아요.

- 자동 매칭: '대결 시작'을 누르면 기다리던 사람과 1:1로 바로 이어져요. 아무도 없으면 내가 기다려요.
- 수동 매칭: 방을 만들면 목록에 올라가고, 여러 명(2명 ~ 방 최대 인원)이 들어올 수 있어요.
  2명 이상 모이면 방장이 '게임 시작'을 누르고, 방이 꽉 차면 자동으로 시작해요.
- 시작하면 "상대를 찾았습니다!" 와 함께 카운트다운(기본 3초) 뒤에 문제가 나와요.
- 방마다 사용 중인 문제 중 10문제를 무작위로 골라, 모두 같은 문제를 서로 다른 순서로 풀어요.
- 문제마다 한 번씩만 답해요. 제한 시간(기본 2분) 안에 가장 많이 맞힌 사람이 이겨요.
- 결과(점수·순위)는 모두 끝나거나 시간이 다 됐을 때 함께 공개돼요.
- 매칭 방법·시간·인원·문구·문제는 총관리자 이상이 '퀴즈 관리'에서 바꿔요.
"""
import random
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import require_permission
from ..database import get_db
from ..models import QuizPlayer, QuizQuestion, QuizRoom, User, now_kst
from ..site import QUIZ_MATCH_MODES, get_settings
from ..templating import flash, render

router = APIRouter(prefix="/quiz")
quizzer = require_permission("quiz")

QUESTIONS_PER_MATCH = 10
MAX_MESSAGE = 100
STALE_SECONDS = 15   # 기다리는 화면이 이만큼 소식이 없으면 자리를 비운 걸로 보고 방에서 빼요.
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
                countdown=_int_setting(site, "quiz_countdown", 3, 0, 30),
                room_max=_int_setting(site, "quiz_room_max", 6, 2, 20))


# ---------- 도우미 ----------

def _ids(text: str) -> list[int]:
    return [int(x) for x in text.split(",") if x]


def _room_or_404(db: Session, room_id: int) -> QuizRoom:
    room = db.get(QuizRoom, room_id)
    if room is None:
        raise HTTPException(404)
    return room


def _me(room: QuizRoom, user_id: int) -> QuizPlayer | None:
    return next((p for p in room.players if p.user_id == user_id), None)


def _active_questions(db: Session) -> list[int]:
    return [q.id for q in db.query(QuizQuestion).filter(QuizQuestion.is_active.is_(True))
            if len(q.choice_list) >= 2]


def shuffled_choices(room: QuizRoom, user_id: int, question: QuizQuestion) -> list[tuple[int, str]]:
    """보기를 사람마다 다른 순서로 섞어요. (새로고침해도 순서는 그대로예요)"""
    choices = list(enumerate(question.choice_list))
    random.Random(f"{room.id}-{user_id}-{question.id}").shuffle(choices)
    return choices


def ranking(room: QuizRoom) -> list[tuple[int, QuizPlayer]]:
    """(등수, 사람) - 점수가 높은 순서. 점수가 같으면 같은 등수예요. (먼저 끝낸 사람이 위에 보여요)"""
    far = room.ends_at or now_kst()
    players = sorted(room.players, key=lambda p: (-p.score, p.done_at or far, p.id))
    return [(1 + sum(1 for o in players if o.score > p.score), p) for p in players]


def settle(db: Session, room: QuizRoom) -> None:
    """모두 다 풀었거나 시간이 끝났으면 결과를 정해요. (누가 화면을 열 때마다 확인해요)"""
    if room.status != "playing" or room.ends_at is None:
        return
    now = now_kst()
    all_done = all(p.done_at is not None for p in room.players)
    if not all_done and now < room.ends_at + timedelta(seconds=ANSWER_GRACE):
        return
    top = max((p.score for p in room.players), default=0)
    winners = [p.name for p in room.players if p.score == top]
    result = "draw" if len(winners) == len(room.players) else "win"
    done = (db.query(QuizRoom).filter(QuizRoom.id == room.id, QuizRoom.status == "playing")
            .update({"status": "done", "result": result,
                     "winner_name": ", ".join(winners)[:300] if result == "win" else "",
                     "finished_at": now}, synchronize_session=False))
    db.commit()
    if done:
        db.refresh(room)


def _fix_host(db: Session, room: QuizRoom) -> None:
    """방장이 나가면 가장 먼저 들어온 사람이 방장이 돼요. 아무도 없으면 방을 닫아요."""
    db.flush()
    db.refresh(room)
    if room.status != "waiting":
        return
    if not room.players:
        room.status, room.finished_at = "cancelled", now_kst()
    elif room.host_id not in {p.user_id for p in room.players}:
        room.host_id, room.host_name = room.players[0].user_id, room.players[0].name


def prune(db: Session, room: QuizRoom) -> None:
    """기다리는 방에서 자리를 비운 사람을 빼요."""
    if room.status != "waiting":
        return
    old = now_kst() - timedelta(seconds=STALE_SECONDS)
    gone = [p for p in room.players if p.seen_at < old]
    if gone:
        for p in gone:
            db.delete(p)
        _fix_host(db, room)
        db.commit()


def _start(db: Session, room: QuizRoom, cfg: dict) -> bool:
    """게임을 시작해요. 모두 같은 10문제를 받고, 순서는 사람마다 섞어요."""
    starts = now_kst() + timedelta(seconds=cfg["countdown"])
    taken = (db.query(QuizRoom).filter(QuizRoom.id == room.id, QuizRoom.status == "waiting")
             .update({"status": "playing", "time_limit": cfg["time_limit"], "starts_at": starts,
                      "ends_at": starts + timedelta(seconds=cfg["time_limit"])},
                     synchronize_session=False))
    if not taken:
        db.rollback()
        return False
    base = _ids(room.questions)
    used = []
    for p in db.query(QuizPlayer).filter(QuizPlayer.room_id == room.id).order_by(QuizPlayer.id):
        order = base[:]
        for _ in range(20):  # 다른 사람과 순서가 겹치지 않게 (거의 언제나 한 번에 돼요)
            _rng.shuffle(order)
            if order not in used:
                break
        used.append(order[:])
        p.questions = ",".join(map(str, order))
    db.commit()
    db.refresh(room)
    return True


def _join(db: Session, room: QuizRoom, user: User, cfg: dict) -> str:
    """방에 들어가요. 'ok' / 'full'(꽉 참) / 'late'(이미 시작함)"""
    if _me(room, user.id):
        return "ok"
    if room.status != "waiting":
        return "late"
    player = QuizPlayer(room_id=room.id, user_id=user.id, name=user.name, seen_at=now_kst())
    db.add(player)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # 버튼을 두 번 눌러서 이미 들어와 있어요.
        return "ok"
    ids = [pid for (pid,) in db.query(QuizPlayer.id).filter(QuizPlayer.room_id == room.id)
           .order_by(QuizPlayer.id)]
    db.refresh(room)
    db.refresh(player)
    # 여러 명이 동시에 들어와서 인원을 넘었거나, 들어오는 사이에 시작했으면 다시 나가요.
    if ids.index(player.id) >= room.max_players or (room.status != "waiting" and not player.questions):
        db.delete(player)
        db.commit()
        return "full" if room.status == "waiting" else "late"
    if len(ids) >= room.max_players:
        _start(db, room, cfg)  # 꽉 차면 바로 시작해요.
    return "ok"


def _leave(db: Session, room: QuizRoom, user_id: int) -> bool:
    """기다리는 방에서 나가요. (시작한 뒤에는 못 나가요)"""
    me = _me(room, user_id)
    if me is None or room.status != "waiting":
        return False
    db.delete(me)
    _fix_host(db, room)
    db.commit()
    return True


def _new_room(db: Session, user: User, mode: str, max_players: int, message: str = "") -> QuizRoom | None:
    ids = _active_questions(db)
    if len(ids) < QUESTIONS_PER_MATCH:
        return None
    room = QuizRoom(mode=mode, host_id=user.id, host_name=user.name, max_players=max_players,
                    message=message.strip()[:MAX_MESSAGE],
                    questions=",".join(map(str, _rng.sample(ids, QUESTIONS_PER_MATCH))))
    room.players.append(QuizPlayer(user_id=user.id, name=user.name, seen_at=now_kst()))
    db.add(room)
    db.commit()
    return room


def _my_active_room(db: Session, user_id: int) -> QuizRoom | None:
    rooms = (db.query(QuizRoom).join(QuizPlayer)
             .filter(QuizRoom.status.in_(["waiting", "playing"]), QuizPlayer.user_id == user_id)
             .order_by(QuizRoom.id.desc()).all())
    for room in rooms:
        settle(db, room)
        prune(db, room)
        if room.status in ("waiting", "playing") and _me(room, user_id):
            return room
    return None


def _busy_room(db: Session, user: User, keep_mode: str | None = None) -> QuizRoom | None:
    """이미 하고 있는 대결이 있으면 돌려줘요. 기다리기만 하던 방은 (keep_mode가 아니면) 나와요."""
    room = _my_active_room(db, user.id)
    if room and room.status == "waiting" and room.mode != keep_mode:
        _leave(db, room, user.id)
        return None
    return room


def cancel_room(db: Session, room: QuizRoom) -> bool:
    """기다리거나 진행 중인 방을 취소해요. (관리자 화면에서도 써요)"""
    return (db.query(QuizRoom)
            .filter(QuizRoom.id == room.id, QuizRoom.status.in_(["waiting", "playing"]))
            .update({"status": "cancelled", "finished_at": now_kst()},
                    synchronize_session=False)) > 0


def forget_user(db: Session, user_id: int) -> None:
    """회원을 지울 때: 기다리던 방에서는 빼고, 지난 기록에서는 이름표만 떼요."""
    for player in db.query(QuizPlayer).filter(QuizPlayer.user_id == user_id).all():
        room = player.room
        if room.status == "waiting":
            db.delete(player)
            _fix_host(db, room)
        else:
            player.user_id = None
    db.query(QuizRoom).filter(QuizRoom.host_id == user_id).update({"host_id": None},
                                                                  synchronize_session=False)


def _phase(room: QuizRoom, me: QuizPlayer | None) -> str:
    """화면에 보여 줄 단계"""
    if room.status in ("waiting", "done", "cancelled"):
        return room.status
    now = now_kst()
    if now < room.starts_at:
        return "countdown"
    if me is None:
        return "watching"
    if me.done_at is not None or now >= room.ends_at:
        return "finished"  # 나는 다 풀었거나 시간이 끝났고, 다른 사람을 기다려요
    return "playing"


def _touch(db: Session, room: QuizRoom, me: QuizPlayer | None) -> None:
    """기다리는 동안 '아직 보고 있어요' 하고 알려요."""
    if room.status == "waiting" and me is not None:
        me.seen_at = now_kst()
        db.commit()


# ---------- 목록 · 매칭 ----------

@router.get("")
def quiz_list(request: Request, db: Session = Depends(get_db), user: User = Depends(quizzer)):
    cfg = quiz_config(db)
    waiting = (db.query(QuizRoom).filter(QuizRoom.status == "waiting")
               .order_by(QuizRoom.id.desc()).all())
    for room in waiting:
        prune(db, room)
    rooms = [r for r in waiting if r.status == "waiting" and r.mode == "manual"]
    recent = (db.query(QuizRoom).filter(QuizRoom.status == "done")
              .order_by(QuizRoom.finished_at.desc()).limit(10).all())
    return render(request, "quiz/list.html", db, me=user, cfg=cfg, rooms=rooms, recent=recent,
                  active=_my_active_room(db, user.id),
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
    """자동 매칭 - 기다리는 사람이 있으면 1:1로 바로 이어지고, 없으면 내가 기다려요."""
    cfg = quiz_config(db)
    if not _can_start(request, db, cfg, "auto"):
        return go("/quiz")
    active = _busy_room(db, user, keep_mode="auto")
    if active:
        return go(f"/quiz/{active.id}")
    waiting = (db.query(QuizRoom).filter(QuizRoom.status == "waiting", QuizRoom.mode == "auto")
               .order_by(QuizRoom.id).limit(10).all())
    for room in waiting:
        prune(db, room)
        if room.status == "waiting" and room.players and _join(db, room, user, cfg) == "ok":
            return go(f"/quiz/{room.id}")
    room = _new_room(db, user, "auto", 2)
    return go(f"/quiz/{room.id}" if room else "/quiz")


@router.post("/room")
def quiz_room_create(request: Request, db: Session = Depends(get_db),
                     user: User = Depends(quizzer), message: str = Form(""),
                     max_players: int = Form(2)):
    """수동 매칭 - 방을 만들어 목록에 올려요."""
    cfg = quiz_config(db)
    if not _can_start(request, db, cfg, "manual"):
        return go("/quiz")
    active = _busy_room(db, user)
    if active:
        flash(request, "이미 하고 있는 대결이 있어요.")
        return go(f"/quiz/{active.id}")
    room = _new_room(db, user, "manual", max(2, min(max_players, cfg["room_max"])), message)
    return go(f"/quiz/{room.id}" if room else "/quiz")


@router.post("/{room_id}/join")
def quiz_join(room_id: int, request: Request, db: Session = Depends(get_db),
              user: User = Depends(quizzer)):
    room = _room_or_404(db, room_id)
    cfg = quiz_config(db)
    if not _can_start(request, db, cfg, "manual"):
        return go("/quiz")
    if _me(room, user.id):
        return go(f"/quiz/{room.id}")
    prune(db, room)
    if room.status != "waiting" or room.mode != "manual":
        flash(request, "이미 시작했거나 없어진 방이에요.")
        return go("/quiz")
    active = _busy_room(db, user)
    if active:
        flash(request, "이미 하고 있는 대결이 있어요.")
        return go(f"/quiz/{active.id}")
    result = _join(db, room, user, cfg)
    if result != "ok":
        flash(request, "방이 꽉 찼어요." if result == "full" else "한 발 늦었어요! 이미 시작했어요.")
        return go("/quiz")
    return go(f"/quiz/{room.id}")


@router.post("/{room_id}/go")
def quiz_host_start(room_id: int, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(quizzer)):
    """방장이 '게임 시작'을 눌러요. (2명 이상일 때)"""
    room = _room_or_404(db, room_id)
    prune(db, room)
    if room.status == "waiting" and room.host_id == user.id:
        if len(room.players) < 2:
            flash(request, "2명 이상 모여야 시작할 수 있어요.")
        else:
            _start(db, room, quiz_config(db))
    return go(f"/quiz/{room.id}")


@router.post("/{room_id}/leave")
def quiz_leave(room_id: int, request: Request, db: Session = Depends(get_db),
               user: User = Depends(quizzer)):
    room = _room_or_404(db, room_id)
    if _leave(db, room, user.id):
        flash(request, "방에서 나왔어요.")
    return go("/quiz")


# ---------- 대결 화면 ----------

@router.get("/{room_id}")
def quiz_detail(room_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(quizzer)):
    room = _room_or_404(db, room_id)
    settle(db, room)
    prune(db, room)
    me = _me(room, user.id)
    _touch(db, room, me)
    now, phase = now_kst(), _phase(room, me)
    context = dict(room=room, me_player=me, phase=phase, per_match=QUESTIONS_PER_MATCH,
                   cfg=quiz_config(db), others=[p for p in room.players if p is not me])
    if room.starts_at:
        context["starts_in"] = max(0.0, (room.starts_at - now).total_seconds())
        context["ends_in"] = max(0.0, (room.ends_at - now).total_seconds())
    if phase == "playing":
        step = me.answered
        question = db.get(QuizQuestion, _ids(me.questions)[step])
        context.update(step=step, question=question,
                       choices=shuffled_choices(room, user.id, question) if question else [])
    if phase == "done":
        context["ranks"] = ranking(room)
        context["my_rank"] = next((rank for rank, p in context["ranks"] if p is me), None)
        # 결과와 함께 문제·정답·해설을 보여 줘요. (내 순서대로, 구경꾼은 방의 문제 순서)
        order = _ids(me.questions) if me else _ids(room.questions)
        picked = _ids(me.answers) if me else []
        found = {q.id: q for q in db.query(QuizQuestion).filter(QuizQuestion.id.in_(order))}
        context["review"] = [(found.get(qid), picked[i] if i < len(picked) else None)
                             for i, qid in enumerate(order)]
    return render(request, "quiz/detail.html", db, me=user, **context)


@router.get("/{room_id}/state")
def quiz_state(room_id: int, db: Session = Depends(get_db), user: User = Depends(quizzer)):
    """대결 화면이 자주 물어봐요: 누가 왔나요? 다들 몇 문제 풀었나요? 결과가 나왔나요?"""
    room = _room_or_404(db, room_id)
    settle(db, room)
    prune(db, room)
    me = _me(room, user.id)
    _touch(db, room, me)
    return JSONResponse({
        "phase": _phase(room, me),
        "players": [{"id": p.id, "name": p.name, "answered": p.answered} for p in room.players],
        "host": room.host_name,
    })


@router.post("/{room_id}/answer")
def quiz_answer(room_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(quizzer), step: int = Form(...), choice: int = Form(...)):
    room = _room_or_404(db, room_id)
    back = f"/quiz/{room.id}"
    settle(db, room)
    me = _me(room, user.id)
    now = now_kst()
    if (me is None or room.status != "playing" or now < room.starts_at
            or now > room.ends_at + timedelta(seconds=ANSWER_GRACE)):
        return go(back)
    old = me.answers
    if step != me.answered or step >= QUESTIONS_PER_MATCH:
        return go(back)  # 버튼을 두 번 눌렀거나 오래된 화면이에요.
    question = db.get(QuizQuestion, _ids(me.questions)[step])
    correct = question is not None and choice == question.answer
    values = {QuizPlayer.answers: f"{old},{choice}" if old else str(choice),
              QuizPlayer.score: QuizPlayer.score + (1 if correct else 0)}
    if step + 1 >= QUESTIONS_PER_MATCH:
        values[QuizPlayer.done_at] = now
    # 답은 '지금까지 고른 답'이 그대로일 때만 저장해요. (두 번 눌러도 한 번만)
    (db.query(QuizPlayer).filter(QuizPlayer.id == me.id, QuizPlayer.answers == old)
     .update(values, synchronize_session=False))
    db.commit()
    db.refresh(room)
    for p in room.players:
        db.refresh(p)
    settle(db, room)
    return go(back)
