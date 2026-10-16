"""관리자가 '사이트 설정'과 '후원 페이지 관리'에서 고칠 수 있는 문구들"""
from sqlalchemy.orm import Session

from .models import BankAccount, Setting

# 사이트 문구 - 총관리자만 '사이트 문구 설정'에서 고쳐요.
# (묶음 이름, [(키, 이름, 기본값, 여러 줄 입력 여부), ...])
# 여러 줄 칸에서 **굵게** 처럼 쓰면 굵은 글씨가 돼요.
SETTING_GROUPS = [
    ("공통 (모든 페이지 위·아래)", [
        ("site_description", "검색에 보이는 사이트 설명", "이산화탄소를 줄여 기후변화를 막는 청소년 환경 NGO, NomoreCO2", False),
        ("footer_tagline", "맨 아래 한 줄 소개", "이산화탄소를 줄여 기후변화를 막는 청소년 환경 NGO", False),
        ("contact_email", "연락처 이메일", "hello@nomoreco2.example", False),
        ("address", "주소", "(예시) 서울특별시 초록구 맑은공기로 2", False),
        ("notice", "맨 아래 안내 문구",
         "이 사이트는 초등학교 6학년 과제로 만든 가상의 NGO 홈페이지예요. 실제 결제나 송금은 이루어지지 않아요.", False),
        ("copyright", "저작권 표시", "© NomoreCO2", False),
    ]),
    ("홈", [
        ("home_eyebrow", "큰 제목 위 작은 글씨", "기후위기 대응 청소년 NGO", False),
        ("hero_title", "메인 큰 제목", "숨 쉬는 지구, 우리가 지켜요", False),
        ("hero_subtitle", "메인 설명",
         "NomoreCO2는 이산화탄소(CO₂)를 줄여 기후변화를 막기 위해 행동하는 청소년 환경 단체입니다.", True),
        ("home_btn_donate", "후원 버튼 글자", "지금 후원하기", False),
        ("home_btn_join", "함께하기 버튼 글자", "함께 행동하기", False),
        ("home_stat_labels", "숫자 칸 이름 (한 줄에 하나씩: 활동 수 / 함께하는 사람 / 후원 신청)",
         "우리가 한 활동\n함께하는 사람\n후원 신청", True),
        ("home_stat_extra", "네 번째 숫자 칸 (값|단위|설명, 비우면 안 보여요)", "420+|ppm|지금 공기 속 CO₂ 농도", False),
        ("home_work_title", "'하는 일' 제목", "NomoreCO2가 하는 일", False),
        ("home_work_lead", "'하는 일' 설명", "이산화탄소를 줄이기 위해 세 가지 방법으로 행동해요.", False),
        ("home_pillars", "'하는 일' 카드 (한 줄에 하나씩: 아이콘|제목|설명)",
         "📢|캠페인|텀블러 쓰기, 전기 아끼기처럼 모두가 함께하는 탄소 줄이기 운동을 펼쳐요.\n"
         "🌳|현장활동|나무를 심고, 플로깅을 하며 직접 지구를 돌봐요.\n"
         "📚|교육|기후변화가 왜 생기는지 친구들과 동생들에게 쉽게 알려 줘요.", True),
        ("home_news_title", "최근 활동 제목", "최근 활동 소식", False),
        ("home_recruit_title", "모집 제목", "지금 함께할 사람을 찾고 있어요", False),
        ("home_tips_title", "탄소 줄이기 팁 제목", "오늘부터 할 수 있는 탄소 줄이기", False),
        ("home_tips", "탄소 줄이기 팁 (한 줄에 하나씩)",
         "🚶 가까운 곳은 걷거나 자전거 타기\n💡 안 쓰는 전등·플러그 끄기\n🥤 일회용 컵 대신 텀블러\n"
         "🍚 음식 남기지 않기\n♻️ 분리배출 제대로 하기\n👕 물건 오래 쓰고 나눠 쓰기", True),
        ("home_cta_title", "맨 아래 띠 제목", "당신의 후원이 지구의 온도를 지킵니다", False),
        ("home_cta_text", "맨 아래 띠 설명", "NomoreCO2는 시민의 후원만으로 독립적으로 활동해요.", False),
    ]),
    ("단체 소개", [
        ("about_eyebrow", "큰 제목 위 작은 글씨", "ABOUT US", False),
        ("about_title", "큰 제목", "No more CO₂ — 이제 이산화탄소는 그만!", False),
        ("about_lead", "큰 제목 설명", "NomoreCO2는 기후변화를 막기 위해 모인 청소년 환경 단체예요.", True),
        ("about_mission_title", "미션 제목", "우리의 미션", False),
        ("mission", "우리의 미션",
         "우리는 이산화탄소를 줄이는 작은 행동이 모이면 지구의 온도를 지킬 수 있다고 믿어요.\n"
         "캠페인, 현장활동, 교육을 통해 더 많은 사람이 기후위기를 알고 함께 행동하도록 만드는 것이 우리의 미션입니다.", True),
        ("about_explain_title", "설명 제목", "기후변화, 왜 이산화탄소가 문제일까요?", False),
        ("about_explain", "설명 (한 줄에 하나씩: 아이콘|문장)",
         "🏭|석탄·석유를 태우면 **이산화탄소(CO₂)**가 나와요.\n"
         "🌫️|이산화탄소는 지구를 감싸는 **이불**처럼 열을 가둬요.\n"
         "🌡️|이불이 두꺼워질수록 **지구의 온도**가 올라가요.\n"
         "🌊|폭염, 가뭄, 홍수, 빙하 녹음 같은 **기후위기**가 생겨요.", True),
        ("about_promise_title", "약속 제목", "우리의 약속", False),
        ("about_promises", "약속 카드 (한 줄에 하나씩: 아이콘|제목|설명)",
         "🤝|독립성|정부나 기업의 돈을 받지 않고, 시민의 후원만으로 활동해요. 그래서 누구의 눈치도 보지 않고 바른 목소리를 낼 수 있어요.\n"
         "🕊️|평화|누구도 다치게 하지 않는 평화로운 방법으로만 행동해요.\n"
         "🔍|투명성|후원금을 어디에 썼는지 모두에게 공개해요.", True),
        ("about_team_title", "팀 제목", "우리 팀", False),
        ("about_team", "팀 소개 (한 줄에 하나씩: 아이콘|이름|설명)",
         "🧑‍🎓|대표|단체를 이끌고 활동 계획을 세워요\n"
         "📢|캠페인팀|탄소 줄이기 캠페인을 기획해요\n"
         "🌳|현장활동팀|나무 심기, 플로깅을 준비해요\n"
         "📸|홍보팀|홈페이지와 소식지를 만들어요", True),
        ("about_cta_title", "맨 아래 띠 제목", "연락하기", False),
    ]),
    ("우리가 하는 일 · 게시판", [
        ("activities_title", "'우리가 하는 일' 제목", "우리가 하는 일", False),
        ("activities_lead", "'우리가 하는 일' 설명", "NomoreCO2가 이산화탄소를 줄이기 위해 해 온 활동들이에요.", True),
        ("board_title", "게시판 제목", "게시판", False),
        ("board_lead", "게시판 설명", "NomoreCO2의 공지와 소식, 그리고 여러분의 이야기를 나눠요.", True),
    ]),
    ("함께하기", [
        ("join_title", "큰 제목", "지구를 지키는 일, 함께해요", False),
        ("join_lead", "큰 제목 설명",
         "자원봉사, 기자단, 온라인 서포터즈까지! 나에게 맞는 방법으로 NomoreCO2와 함께하세요.", True),
        ("join_ways_title", "참여 방법 제목", "참여 방법", False),
        ("join_ways", "참여 방법 카드 (한 줄에 하나씩: 아이콘|제목|설명)",
         "🙋|활동가로 참여|아래 모집 공고에 지원하고 직접 현장에서 활동해요.\n"
         "📱|온라인으로 참여|캠페인 글을 공유하고 친구들에게 알려 주세요.\n"
         "🏠|일상에서 참여|전기 아끼기, 텀블러 쓰기로 오늘부터 탄소를 줄여요.", True),
        ("join_agree", "지원서 동의 문구", "연락을 위해 이름과 연락처를 저장하는 데 동의하고, 보호자에게 허락을 받았어요.", True),
    ]),
]
SETTING_FIELDS = [field for _group, fields in SETTING_GROUPS for field in fields]

# 후원 페이지 문구 - '후원 페이지 관리'에서 고쳐요.
DONATE_FIELDS = [
    ("donate_open", "후원 신청 받기 (1 = 받기, 0 = 잠시 멈추기)", "1", False),
    ("donate_title", "후원 페이지 큰 제목", "지구를 위한 가장 확실한 행동, 후원", False),
    ("donate_lead", "후원 페이지 설명",
     "NomoreCO2는 정부·기업의 돈을 받지 않아요. 오직 여러분의 후원으로 이산화탄소를 줄이는 활동을 합니다.", True),
    ("donate_notice", "신청서 위 안내 상자 (비우면 안 보여요)",
     "학교 과제용 사이트라서 실제 결제는 되지 않아요. 신청서만 저장되고, 관리자가 확인해요.", True),
    ("donate_closed_message", "신청을 멈췄을 때 보여 줄 문구",
     "지금은 후원 신청을 잠시 받지 않아요. 곧 다시 열게요!", True),
    ("donate_account_message", "신청 후 계좌 안내 창 문구",
     "아래 계좌로 후원금을 보내 주세요. 보내는 사람 이름을 신청서와 똑같이 적어 주시면 확인이 빨라요.", True),
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


def split_lines(value: str, parts: int = 2) -> list[list[str]]:
    """'가|나|다' 줄들을 [[가, 나, 다], ...] 로 나눠요. 칸 수가 틀린 줄은 건너뛰어요."""
    rows = []
    for line in (value or "").splitlines():
        cells = [cell.strip() for cell in line.split("|", parts - 1)]
        if len(cells) == parts and cells[-1]:
            rows.append(cells)
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
