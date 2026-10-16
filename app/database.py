import os

from sqlalchemy import create_engine, inspect, literal, text
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


def add_missing_columns() -> None:
    """예전에 만든 표에 새로 생긴 칸을 붙여 줘요. (create_all은 이미 있는 표를 고치지 않아요)"""
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            sql = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}"
            if col.default is not None and col.default.is_scalar:
                value = literal(col.default.arg, col.type).compile(
                    dialect=engine.dialect, compile_kwargs={"literal_binds": True})
                sql += f" DEFAULT {value}"
            try:
                with engine.begin() as conn:
                    conn.execute(text(sql))
            except Exception:
                # 서버 여러 개가 동시에 시작하면 이미 붙어 있을 수 있어요.
                pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
