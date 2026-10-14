"""관리자가 '사이트 설정'에서 고칠 수 있는 문구들"""
from sqlalchemy.orm import Session

from .models import Setting

# (키, 이름, 기본값, 여러 줄 입력 여부)
SETTING_FIELDS = [
    ("notice", "맨 아래 안내 문구",
     "이 사이트는 초등학교 6학년 과제로 만든 가상의 NGO 홈페이지예요. 실제 결제나 송금은 이루어지지 않아요.", False),
    ("hero_title", "메인 큰 제목", "숨 쉬는 지구, 우리가 지켜요", False),
    ("hero_subtitle", "메인 설명",
     "NomoreCO2는 이산화탄소(CO₂)를 줄여 기후변화를 막기 위해 행동하는 청소년 환경 단체입니다.", True),
    ("mission", "우리의 미션",
     "우리는 이산화탄소를 줄이는 작은 행동이 모이면 지구의 온도를 지킬 수 있다고 믿어요.\n"
     "캠페인, 현장활동, 교육을 통해 더 많은 사람이 기후위기를 알고 함께 행동하도록 만드는 것이 우리의 미션입니다.", True),
    ("bank_info", "후원 계좌 안내", "(예시) 지구은행 000-0000-0000 · 예금주 NomoreCO2", False),
    ("contact_email", "연락처 이메일", "hello@nomoreco2.example", False),
    ("address", "주소", "(예시) 서울특별시 초록구 맑은공기로 2", False),
]


def get_settings(db: Session) -> dict:
    saved = {s.key: s.value for s in db.query(Setting).all()}
    return {key: saved.get(key, default) for key, _, default, _ in SETTING_FIELDS}
