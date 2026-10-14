from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

KST = timezone(timedelta(hours=9))

CATEGORIES = ["캠페인", "현장활동", "교육", "소식"]
APPLICATION_STATUSES = ["접수", "검토중", "합격", "보류"]
DONATION_TYPES = ["정기후원", "일시후원", "기념일후원"]
PAYMENT_METHODS = ["CMS 자동이체", "신용카드", "계좌이체", "휴대폰 결제"]


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
    """게시판 글 (누구나 읽고, 관리자만 쓰고 고쳐요)"""

    __tablename__ = "board_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)


class Setting(Base):
    """관리자가 고칠 수 있는 사이트 문구"""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
