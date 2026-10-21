from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, String,
                        Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

KST = timezone(timedelta(hours=9))

CATEGORIES = ["캠페인", "현장활동", "교육", "소식"]
APPLICATION_STATUSES = ["접수", "검토중", "합격", "보류"]
DONATION_TYPES = ["정기후원", "일시후원", "기념일후원"]
PAYMENT_METHODS = ["CMS 자동이체", "신용카드", "계좌이체", "휴대폰 결제"]
DONATION_STATUSES = ["신청", "입금확인", "취소"]
INQUIRY_CATEGORIES = ["일반", "후원", "활동·모집", "회원·계정", "기타"]
INQUIRY_STATUSES = ["답변대기", "답변완료", "종료"]


def now_kst() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(20), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)
    # 제재 - 밴(로그인 못 함), 타임아웃(정해진 시간까지 보기·문의만 가능)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    ban_reason: Mapped[str] = mapped_column(String(300), default="")
    timeout_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    timeout_reason: Mapped[str] = mapped_column(String(300), default="")


class Post(Base):
    """우리가 하는 일 (활동 게시글)"""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(30))
    summary: Mapped[str] = mapped_column(String(300), default="")
    content: Mapped[str] = mapped_column(Text)
    image_url: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)


class BoardPost(Base):
    """게시판 글 (누구나 읽고, 로그인한 사람이 써요. 쓴 사람과 관리자가 고쳐요)"""

    __tablename__ = "board_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    author_name: Mapped[str] = mapped_column(String(50), default="관리자")
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    image_url: Mapped[str] = mapped_column(String(500), default="")
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    comments: Mapped[list["Comment"]] = relationship(
        back_populates="post", cascade="all, delete-orphan", order_by="Comment.id"
    )


class Comment(Base):
    """게시판 댓글 (로그인한 사람이 써요)"""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    board_post_id: Mapped[int] = mapped_column(ForeignKey("board_posts.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    author_name: Mapped[str] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    post: Mapped[BoardPost] = relationship(back_populates="comments")


class Recruitment(Base):
    """사람 모집 공고"""

    __tablename__ = "recruitments"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    field: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    requirements: Mapped[str] = mapped_column(Text, default="")
    schedule: Mapped[str] = mapped_column(String(200), default="")
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    applications: Mapped[list["Application"]] = relationship(
        back_populates="recruitment", cascade="all, delete-orphan"
    )


class Application(Base):
    """모집 지원서"""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    recruitment_id: Mapped[int] = mapped_column(ForeignKey("recruitments.id"))
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(50))
    contact: Mapped[str] = mapped_column(String(100))
    grade: Mapped[str] = mapped_column(String(50), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="접수")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    recruitment: Mapped[Recruitment] = relationship(back_populates="applications")


class Donation(Base):
    """후원 신청(약정)"""

    __tablename__ = "donations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    donor_name: Mapped[str] = mapped_column(String(50))
    contact: Mapped[str] = mapped_column(String(100))
    donation_type: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="신청")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)


class Inquiry(Base):
    """문의 - 회원과 관리자가 대화(메시지)를 주고받아요."""

    __tablename__ = "inquiries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    author_name: Mapped[str] = mapped_column(String(50))
    category: Mapped[str] = mapped_column(String(20), default="일반")
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="답변대기")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    messages: Mapped[list["InquiryMessage"]] = relationship(
        back_populates="inquiry", cascade="all, delete-orphan", order_by="InquiryMessage.id"
    )


class InquiryMessage(Base):
    """문의 안의 말 한마디"""

    __tablename__ = "inquiry_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    author_name: Mapped[str] = mapped_column(String(50))
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    inquiry: Mapped[Inquiry] = relationship(back_populates="messages")


class Image(Base):
    """내 컴퓨터에서 올린 사진 - Vercel은 파일을 오래 못 둬서 데이터베이스에 넣어요."""

    __tablename__ = "images"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    content_type: Mapped[str] = mapped_column(String(30))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)


# ---------- 놀이터 (가상 머니 - 진짜 돈이 아니에요) ----------

class Wallet(Base):
    """놀이터 지갑 - 모든 놀이터 게임이 같이 써요."""

    __tablename__ = "wallets"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    last_daily: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


class MoneyLog(Base):
    """돈이 들어오고 나간 기록"""

    __tablename__ = "money_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200))
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)


class Coinflip(Base):
    """코인플립 한 판 - 만든 사람과 들어온 사람 중 한 명이 판돈 2배를 가져가요."""

    __tablename__ = "coinflips"

    id: Mapped[int] = mapped_column(primary_key=True)
    creator_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    creator_name: Mapped[str] = mapped_column(String(50))
    joiner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    joiner_name: Mapped[str] = mapped_column(String(50), default="")
    winner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    winner_name: Mapped[str] = mapped_column(String(50), default="")
    bet: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open/done/cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class QuizQuestion(Base):
    """기후 퀴즈 문제 - 총관리자 이상이 '퀴즈 관리'에서 고쳐요."""

    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(String(300))
    choices: Mapped[str] = mapped_column(Text)  # 보기를 한 줄에 하나씩 (2~4개)
    answer: Mapped[int] = mapped_column(Integer, default=0)  # 정답 보기 번호 (0부터)
    explanation: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    @property
    def choice_list(self) -> list[str]:
        return [line.strip() for line in self.choices.splitlines() if line.strip()]


class QuizRoom(Base):
    """퀴즈 대결 방 - 2명 이상이 같은 10문제를 서로 다른 순서로 풀고, 시간 안에 많이 맞힌 사람이 이겨요.

    waiting(사람 기다림) → playing(카운트다운 + 문제 풀기) → done(결과) / cancelled(취소)
    """

    __tablename__ = "quiz_rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(10), default="auto")  # auto(자동 매칭) / manual(방 만들기)
    status: Mapped[str] = mapped_column(String(20), default="waiting", index=True)
    message: Mapped[str] = mapped_column(String(100), default="")
    host_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    host_name: Mapped[str] = mapped_column(String(50), default="")
    questions: Mapped[str] = mapped_column(String(200), default="")  # 이 방의 10문제 ("3,17,8,...")
    max_players: Mapped[int] = mapped_column(Integer, default=2)
    time_limit: Mapped[int] = mapped_column(Integer, default=120)  # 초
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    result: Mapped[str] = mapped_column(String(10), default="")  # win / draw
    winner_name: Mapped[str] = mapped_column(String(300), default="")  # 1등(들) 이름
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    players: Mapped[list["QuizPlayer"]] = relationship(
        back_populates="room", cascade="all, delete-orphan", order_by="QuizPlayer.id"
    )


class QuizPlayer(Base):
    """퀴즈 방에 들어온 한 사람"""

    __tablename__ = "quiz_players"
    __table_args__ = (UniqueConstraint("room_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("quiz_rooms.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(50))
    questions: Mapped[str] = mapped_column(String(200), default="")  # 내가 푸는 순서 (시작할 때 섞어요)
    answers: Mapped[str] = mapped_column(String(100), default="")  # 고른 보기 번호 ("2,0,1,...")
    score: Mapped[int] = mapped_column(Integer, default=0)
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # 기다리는 동안 화면을 보고 있는지 (오래 소식이 없으면 방에서 빠져요)
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    room: Mapped[QuizRoom] = relationship(back_populates="players")

    @property
    def answered(self) -> int:
        return len([x for x in self.answers.split(",") if x])


class BankAccount(Base):
    """후원 페이지에 보여 줄 후원 계좌 (총관리자만 고쳐요)"""

    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_name: Mapped[str] = mapped_column(String(50))
    account_number: Mapped[str] = mapped_column(String(50))
    holder: Mapped[str] = mapped_column(String(50))
    memo: Mapped[str] = mapped_column(String(200), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Setting(Base):
    """관리자가 고칠 수 있는 사이트 문구"""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
