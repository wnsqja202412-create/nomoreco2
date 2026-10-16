import re
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy.orm import Session

from .auth import ROLE_LABELS, get_current_user, has_permission, is_timed_out
from .site import get_settings, split_lines

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

CATEGORY_EMOJI = {"캠페인": "📢", "현장활동": "🌳", "교육": "📚", "소식": "📰"}


def nl2br(value) -> Markup:
    text = str(escape(value or "")).replace("\r\n", "\n")
    return Markup(text.replace("\n", "<br>"))


def rich(value) -> Markup:
    """줄바꿈 + **굵게** 를 보여 줘요. 다른 HTML은 글자 그대로 보여요."""
    text = str(nl2br(value))
    return Markup(re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text))


def lines(value) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def won(value) -> str:
    return f"{int(value or 0):,}원"


def datefmt(value) -> str:
    return value.strftime("%Y.%m.%d") if value else ""


def datetimefmt(value) -> str:
    return value.strftime("%Y.%m.%d %H:%M") if value else ""


templates.env.filters.update(nl2br=nl2br, rich=rich, lines=lines, rows=split_lines,
                             won=won, datefmt=datefmt, datetimefmt=datetimefmt)
templates.env.globals.update(
    has_perm=has_permission, timed_out=is_timed_out, CATEGORY_EMOJI=CATEGORY_EMOJI,
    ROLE_LABELS=ROLE_LABELS
)


def render(request: Request, name: str, db: Session, status_code: int = 200, **context):
    context.setdefault("user", get_current_user(request, db))
    context["site"] = get_settings(db)
    context["flash"] = request.session.pop("flash", None)
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def flash(request: Request, message: str) -> None:
    request.session["flash"] = message
