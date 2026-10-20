"""놀이터 지갑 - 모든 놀이터 게임이 이 파일로 돈을 주고받아요. (가상 머니예요)

돈은 언제나 '조건이 맞을 때만 바꾸는' 한 줄짜리 UPDATE 로 바꿔요.
그래서 버튼을 두 번 누르거나 두 사람이 동시에 눌러도 돈이 두 번 빠지거나 생기지 않아요.
"""
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Coinflip, MoneyLog, Wallet, now_kst
from .site import get_settings


def playground_open(db: Session) -> bool:
    return get_settings(db)["playground_enabled"].strip() != "0"


def daily_amount(db: Session) -> int:
    digits = "".join(ch for ch in get_settings(db)["playground_daily"] if ch.isdigit())
    return int(digits) if digits else 0


def ensure_wallet(db: Session, user_id: int) -> Wallet:
    """지갑이 없으면 0원짜리 지갑을 만들어요. (다른 변경 전에, 맨 처음에 불러 주세요)"""
    wallet = db.get(Wallet, user_id)
    if wallet is None:
        try:
            db.add(Wallet(user_id=user_id, balance=0))
            db.commit()
        except IntegrityError:
            db.rollback()  # 동시에 누가 이미 만들었어요.
        wallet = db.get(Wallet, user_id)
    return wallet


def _log(db: Session, user_id: int, amount: int, reason: str, actor_id: int | None) -> None:
    balance = db.query(Wallet.balance).filter_by(user_id=user_id).scalar() or 0
    db.add(MoneyLog(user_id=user_id, amount=amount, balance_after=balance, reason=reason[:200],
                    actor_id=actor_id))


def change(db: Session, user_id: int, amount: int, reason: str,
           actor_id: int | None = None) -> bool:
    """돈을 더하거나(+) 빼요(-). 돈이 모자라면 아무것도 안 하고 False 예요.
    commit 은 부르는 쪽에서 해요."""
    query = db.query(Wallet).filter(Wallet.user_id == user_id)
    if amount < 0:
        query = query.filter(Wallet.balance >= -amount)
    if query.update({Wallet.balance: Wallet.balance + amount}, synchronize_session=False) == 0:
        return False
    _log(db, user_id, amount, reason, actor_id)
    return True


def set_balance(db: Session, user_id: int, balance: int, reason: str, actor_id: int) -> None:
    """관리자가 돈을 정확한 금액으로 정해요."""
    wallet = db.get(Wallet, user_id)
    diff = balance - wallet.balance
    wallet.balance = balance
    db.flush()
    _log(db, user_id, diff, reason, actor_id)


def claim_daily(db: Session, user_id: int) -> int:
    """오늘의 용돈 받기 - 자정(한국 시간)마다 다시 받을 수 있어요. 받은 금액, 이미 받았으면 0."""
    amount, today = daily_amount(db), now_kst().date()
    updated = (db.query(Wallet)
               .filter(Wallet.user_id == user_id,
                       or_(Wallet.last_daily.is_(None), Wallet.last_daily < today))
               .update({Wallet.balance: Wallet.balance + amount, Wallet.last_daily: today},
                       synchronize_session=False))
    if updated == 0:
        return 0
    _log(db, user_id, amount, "오늘의 용돈", None)
    db.commit()
    return amount


def forget_user(db: Session, user_id: int) -> None:
    """회원을 지울 때 놀이터 기록을 정리해요. (기다리던 코인플립은 취소돼요)"""
    db.query(Coinflip).filter(Coinflip.creator_id == user_id, Coinflip.status == "open") \
        .update({"status": "cancelled"}, synchronize_session=False)
    for column in (Coinflip.creator_id, Coinflip.joiner_id, Coinflip.winner_id):
        db.query(Coinflip).filter(column == user_id).update({column: None},
                                                            synchronize_session=False)
    db.query(MoneyLog).filter(MoneyLog.user_id == user_id).update({"user_id": None},
                                                                  synchronize_session=False)
    db.query(MoneyLog).filter(MoneyLog.actor_id == user_id).update({"actor_id": None},
                                                                   synchronize_session=False)
    db.query(Wallet).filter(Wallet.user_id == user_id).delete(synchronize_session=False)
