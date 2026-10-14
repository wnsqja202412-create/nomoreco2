from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy.orm import Session

from .auth import ROLE_LABELS, get_current_user, has_permission
from .site import get_settings

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

CATEGORY_EMOJI = {"캠페인": "📢", "현장활동": "🌳", "교육": "📚", "소식": "📰"}


def nl2br(value) -> Markup:
    text = str(escape(value or "")).replace("\r\n", "\n")
    return Markup(text.replace("\n", "<br>"))


def won(value) -> str:
    return f"{int(value or 0):,}원"


def datefmt(value) -> str:
    return value.strftime("%Y.%m.%d") if value else ""


templates.env.filters.update(nl2br=nl2br, won=won, datefmt=datefmt)
templates.env.globals.update(
    has_perm=has_permission, CATEGORY_EMOJI=CATEGORY_EMOJI, ROLE_LABELS=ROLE_LABELS
)


def render(request: Request, name: str, db: Session, status_code: int = 200, **context):
    context.setdefault("user", get_current_user(request, db))
    context["site"] = get_settings(db)
    context["flash"] = request.session.pop("flash", None)
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def flash(request: Request, message: str) -> None:
    request.session["flash"] = message
