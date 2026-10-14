"""처음 실행할 때 관리자 아이디와 예시 글을 넣어 줘요."""
import os

from sqlalchemy.exc import IntegrityError

from .auth import ROLE_ADMIN, hash_password
from .database import SessionLocal
from .models import Post, Recruitment, User

SAMPLE_POSTS = [
    dict(
        category="캠페인",
        title="텀블러 쓰는 학교 만들기 캠페인",
        summary="일회용 컵 대신 텀블러! 한 달 동안 전교생과 함께 일회용 컵 줄이기에 도전했어요.",
        content="일회용 플라스틱 컵 하나를 만들 때도 이산화탄소가 나와요.\n"
                "그래서 우리는 한 달 동안 '텀블러 데이'를 열고, 텀블러를 가져온 친구에게 칭찬 스티커를 나눠 줬어요.\n\n"
                "결과: 참여 학생 200명, 줄인 일회용 컵 약 3,000개 (예시)\n\n"
                "다음 달에는 다른 학교와 함께하는 캠페인을 준비하고 있어요!",
    ),
    dict(
        category="현장활동",
        title="우리 동네 나무 심기 데이",
        summary="나무는 이산화탄소를 빨아들이는 지구의 공기청정기! 동네 공원에 어린 나무 30그루를 심었어요.",
        content="나무 한 그루는 1년 동안 이산화탄소를 꽤 많이 흡수해요.\n"
                "자원봉사자 25명이 모여 동네 공원에 어린 나무 30그루를 심었어요. (예시)\n\n"
                "심은 나무에는 이름표를 달아 주고, 매달 물 주기 당번을 정해서 돌보고 있어요.",
    ),
    dict(
        category="교육",
        title="찾아가는 기후 교실",
        summary="기후변화가 왜 생기는지, 우리가 할 수 있는 일은 무엇인지 친구들에게 직접 알려 줬어요.",
        content="온실가스, 이산화탄소, 지구 온난화… 어려운 말이지만 쉽게 설명하면 누구나 이해할 수 있어요!\n"
                "우리는 그림 카드와 퀴즈로 저학년 동생들에게 기후 수업을 했어요.\n\n"
                "수업이 끝난 뒤 동생들이 직접 '탄소 줄이기 약속 카드'를 썼답니다.",
    ),
    dict(
        category="소식",
        title="NomoreCO2가 시작합니다!",
        summary="이산화탄소를 줄이자는 마음으로 모인 청소년 환경 단체 NomoreCO2를 소개합니다.",
        content="안녕하세요, NomoreCO2입니다.\n"
                "'No more CO2'는 '이제 이산화탄소는 그만!'이라는 뜻이에요.\n\n"
                "우리는 캠페인, 현장활동, 교육으로 기후변화를 막는 데 힘을 보탤 거예요. 많은 응원 부탁드려요!",
    ),
]

SAMPLE_RECRUITMENTS = [
    dict(
        title="🌱 기후 지킴이 자원봉사자",
        field="현장활동",
        description="매달 한 번 동네 플로깅(걸으며 쓰레기 줍기)과 나무 심기 활동에 함께할 친구를 찾아요.",
        requirements="초등학교 4학년 ~ 중학생 누구나\n보호자 동의가 필요해요",
        schedule="매월 둘째 주 토요일 오전 10시 ~ 12시",
    ),
    dict(
        title="📸 청소년 기후 기자단",
        field="홍보",
        description="우리 활동을 사진과 글로 기록하고, 홈페이지와 SNS에 소식을 전해 주세요.",
        requirements="글쓰기나 사진 찍기를 좋아하는 친구\n한 달에 기사 1개 이상 작성",
        schedule="온라인 활동 + 월 1회 모임",
    ),
    dict(
        title="💻 온라인 서포터즈",
        field="온라인",
        description="집에서도 할 수 있어요! 캠페인을 공유하고, 기후 행동 챌린지에 참여해 주세요.",
        requirements="기후위기에 관심 있는 누구나",
        schedule="자유롭게 (언제든지)",
    ),
]


def seed() -> None:
    db = SessionLocal()
    try:
        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        admin = db.query(User).filter_by(username=admin_username).first()
        if admin is None:
            db.add(User(
                username=admin_username,
                name="관리자",
                role=ROLE_ADMIN,
                password_hash=hash_password(os.getenv("ADMIN_PASSWORD", "nomoreco2!")),
            ))
        elif admin.role != ROLE_ADMIN:
            admin.role = ROLE_ADMIN

        if db.query(Post).count() == 0:
            db.add_all(Post(**p) for p in reversed(SAMPLE_POSTS))
        if db.query(Recruitment).count() == 0:
            db.add_all(Recruitment(**r) for r in SAMPLE_RECRUITMENTS)
        db.commit()
    except IntegrityError:
        # 서버 여러 개가 동시에 시작하면 이미 들어가 있을 수 있어요.
        db.rollback()
    finally:
        db.close()
