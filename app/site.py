"""관리자가 '사이트 설정'과 '후원 페이지 관리'에서 고칠 수 있는 문구들"""
from sqlalchemy.orm import Session

from .models import BankAccount, Setting

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
    ("contact_email", "연락처 이메일", "hello@nomoreco2.example", False),
    ("address", "주소", "(예시) 서울특별시 초록구 맑은공기로 2", False),
]

# 후원 페이지 문구 - '후원 페이지 관리'에서 고쳐요.
DONATE_FIELDS = [
    ("donate_open", "후원 신청 받기 (1 = 받기, 0 = 잠시 멈추기)", "1", False),
    ("donate_title", "후원 페이지 큰 제목", "지구를 위한 가장 확실한 행동, 후원", False),
    ("donate_lead", "후원 페이지 설명",
     "NomoreCO2는 정부·기업의 돈을 받지 않아요. 오직 여러분의 후원으로 이산화탄소를 줄이는 활동을 합니다.", True),
    ("donate_notice", "신청서 위 안내 상자 (비우면 안 보여요)",
     "학교 과제용 사이트라서 실제 결제는 되지 않아요. 신청서만 저장되고, 관리자가 확인해요.", True),
    ("donate_closed_message", "신청을 멈췄을 때 보여 줄 문구",
     "지금은 후원 신청을 잠시 받지 않아요. 아래 계좌로 직접 보내 주셔도 고맙게 받을게요.", True),
    ("donate_amounts", "추천 금액 (한 줄에 하나씩: 금액|설명)",
     "5000|친환경 장바구니 1개를 나눠 줄 수 있어요\n"
     "10000|어린 나무 2그루를 심을 수 있어요\n"
     "30000|한 반 친구들에게 기후 수업을 1번 할 수 있어요\n"
     "50000|동네 플로깅 캠페인을 1번 열 수 있어요", True),
    ("donate_usage", "후원금 사용 비율 (한 줄에 하나씩: 이름|퍼센트)",
     "📢 기후 캠페인|40\n🌳 나무 심기·현장활동|30\n📚 기후 교육|20\n🏠 단체 운영|10", True),
    ("donate_faq", "자주 묻는 질문 (한 줄에 하나씩: 질문|답변)",
     "정기후원은 언제든지 그만하거나 금액을 바꿀 수 있나요?|네! 아래 연락처 이메일로 연락 주시면 언제든지 바꾸거나 멈출 수 있어요.\n"
     "기부금 영수증을 받을 수 있나요?|실제 비영리단체로 등록된 곳은 연말정산용 기부금 영수증을 발급해요. NomoreCO2는 과제용 가상 단체라 발급하지 않아요.\n"
     "후원금이 어디에 쓰였는지 알 수 있나요?|매년 활동 보고서를 '우리가 하는 일' 게시판에 올려 투명하게 공개할 거예요.\n"
     "어린이도 후원할 수 있나요?|용돈으로 하는 작은 후원도 큰 힘이 돼요! 꼭 보호자와 함께 신청해 주세요. 돈이 아니어도 '함께하기'에서 자원봉사로 함께할 수 있어요.", True),
]


def get_settings(db: Session) -> dict:
    saved = {s.key: s.value for s in db.query(Setting).all()}
    return {key: saved.get(key, default) for key, _, default, _ in SETTING_FIELDS + DONATE_FIELDS}


def save_settings(db: Session, fields: list, form) -> None:
    for key, *_rest in fields:
        if key not in form:
            continue
        row = db.get(Setting, key)
        if row:
            row.value = str(form[key])
        else:
            db.add(Setting(key=key, value=str(form[key])))
    db.commit()


def split_lines(value: str) -> list[list[str]]:
    """'앞|뒤' 줄들을 [[앞, 뒤], ...] 로 나눠요. 모양이 틀린 줄은 건너뛰어요."""
    rows = []
    for line in (value or "").splitlines():
        if "|" in line:
            left, right = (part.strip() for part in line.split("|", 1))
            if left and right:
                rows.append([left, right])
    return rows


def _to_int(text: str) -> int:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def donate_amounts(site: dict) -> list[tuple[int, str]]:
    return [(_to_int(a), text) for a, text in split_lines(site["donate_amounts"]) if _to_int(a) > 0]


def donate_usage(site: dict) -> list[tuple[str, int]]:
    return [(label, min(_to_int(p), 100)) for label, p in split_lines(site["donate_usage"])]


def active_bank_accounts(db: Session) -> list[BankAccount]:
    return (db.query(BankAccount).filter(BankAccount.is_active.is_(True))
            .order_by(BankAccount.sort_order, BankAccount.id).all())
