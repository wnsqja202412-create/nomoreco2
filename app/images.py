"""사진 올리기 - 올린 사진은 데이터베이스(images 표)에 저장하고 /images/번호 로 보여 줘요."""
import re

from fastapi import Request
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from .models import Image, User

# Vercel은 한 번에 4.5MB까지만 받아요. 사진은 올리기 전에 브라우저에서 줄여서 보내요.
MAX_BYTES = 4 * 1024 * 1024

_IMAGE_URL = re.compile(r"^/images/(\d+)$")


def _detect_type(data: bytes) -> str | None:
    """파일 이름이 아니라 내용을 보고 진짜 사진인지 확인해요. (SVG 같은 건 안 받아요)"""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def photo_upload(request: Request) -> UploadFile | None:
    """폼의 'photo' 칸에서 사진을 꺼내요. (Depends 로 써요)
    사진을 안 고르면 브라우저가 빈 칸을 보내는데, 그때는 None 이에요."""
    value = (await request.form()).get("photo")
    return value if isinstance(value, UploadFile) and value.filename else None


def save_upload(db: Session, upload: UploadFile | None, user: User | None) -> str | None:
    """사진이 있으면 저장하고 주소(/images/번호)를 돌려줘요. 사진이 없으면 None.
    사진이 아니거나 너무 크면 ValueError 를 일으켜요."""
    if upload is None:
        return None
    data = upload.file.read(MAX_BYTES + 1)
    if not data:
        return None
    if len(data) > MAX_BYTES:
        raise ValueError("사진이 너무 커요. 4MB보다 작은 사진을 올려 주세요.")
    content_type = _detect_type(data)
    if content_type is None:
        raise ValueError("JPG, PNG, GIF, WEBP 사진만 올릴 수 있어요.")
    image = Image(user_id=user.id if user else None, content_type=content_type,
                  data=data, size=len(data))
    db.add(image)
    db.flush()
    return f"/images/{image.id}"


_SAFE_LINK = re.compile(r"^https?://[^\s'\"()<>\\]+$")


def resolve_image(db: Session, current: str, upload: UploadFile | None, link: str = "",
                  remove: bool = False, user: User | None = None) -> str:
    """글을 저장할 때 사진 주소를 정해요.

    1) 새 사진을 올렸으면 → 그 사진
    2) '사진 지우기'에 체크했으면 → 사진 없음
    3) 다른 사진 링크(https://...)를 적었으면 → 그 링크
    4) 아무것도 안 했으면 → 원래 사진 그대로
    원래 사진이 우리 사이트에 올린 것이고 바뀌었다면 데이터베이스에서 지워요.
    """
    current, link = current or "", (link or "").strip()
    new = save_upload(db, upload, user)
    if new is None:
        if remove:
            new = ""
        elif link and link != current:
            if not _SAFE_LINK.match(link):
                raise ValueError("사진 링크는 https:// 로 시작하는 주소만 쓸 수 있어요.")
            new = link
        else:
            new = current
    if new != current:
        delete_image_url(db, current)
    return new


def delete_image_url(db: Session, url: str | None) -> None:
    """우리 사이트에 올린 사진이면 데이터베이스에서도 지워요. (바깥 링크는 그냥 둬요)"""
    match = _IMAGE_URL.match(url or "")
    if match:
        db.query(Image).filter_by(id=int(match.group(1))).delete()
