import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def _database_url() -> str:
    # Vercel에서 Neon(Postgres)을 연결하면 DATABASE_URL 또는 POSTGRES_URL 이 생겨요.
    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if url:
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    if os.getenv("VERCEL"):
        # 데이터베이스 없이 Vercel에 올리면 임시 폴더를 써요 (데이터가 가끔 초기화돼요!)
        return "sqlite:////tmp/nomoreco2.db"
    return "sqlite:///./nomoreco2.db"


DATABASE_URL = _database_url()

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
