import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .auth import Forbidden, LoginRequired
from .database import Base, SessionLocal, add_missing_columns, engine
from .routers import admin, auth, playground, public
from .seed import seed
from .templating import render

BASE_DIR = Path(__file__).resolve().parent.parent

# 표를 만들고 관리자 아이디·예시 글을 넣어요.
Base.metadata.create_all(engine)
add_missing_columns()
seed()

class VercelPathFix:
    """Vercel이 주소를 /api/index... 로 바꿔 보내면 원래 주소로 돌려놔요."""

    PREFIXES = ("/api/index.py", "/api/index")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope["path"]
            for prefix in self.PREFIXES:
                if path == prefix or path.startswith(prefix + "/"):
                    path = path[len(prefix):] or "/"
                    scope = dict(scope, path=path, raw_path=path.encode())
                    break
        await self.app(scope, receive, send)


app = FastAPI(title="NomoreCO2", docs_url=None, redoc_url=None)
app.add_middleware(VercelPathFix)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "dev-secret-please-change"),
    same_site="lax",
    https_only=bool(os.getenv("VERCEL")),
)
# Vercel에서는 public 폴더를 Vercel이 직접 보여 줘서, 폴더가 없어도 멈추지 않게 했어요.
app.mount("/static", StaticFiles(directory=BASE_DIR / "public" / "static", check_dir=False),
          name="static")

app.include_router(public.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(playground.router)


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse(f"/login?next={request.url.path}", status_code=303)


def _error_page(request: Request, status_code: int, message: str):
    db = SessionLocal()
    try:
        return render(request, "error.html", db, status_code=status_code,
                      code=status_code, message=message)
    finally:
        db.close()


@app.exception_handler(Forbidden)
async def forbidden_handler(request: Request, exc: Forbidden):
    return _error_page(request, 403, "이 일을 할 권한이 없어요.")


@app.exception_handler(playground.PlaygroundClosed)
async def playground_closed_handler(request: Request, exc: playground.PlaygroundClosed):
    return _error_page(request, 403, "🛝 놀이터가 지금 닫혀 있어요. 나중에 다시 와 주세요!")


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    message = "페이지를 찾을 수 없어요." if exc.status_code == 404 else "문제가 생겼어요."
    return _error_page(request, exc.status_code, message)
