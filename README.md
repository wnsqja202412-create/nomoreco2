# 🌍 NomoreCO2 홈페이지

이산화탄소를 줄여 기후변화를 막는 청소년 NGO **NomoreCO2**의 홈페이지예요.
(그린피스 홈페이지 구성을 참고했어요. 학교 과제용 가상 단체예요.)

## 📁 폴더 구성

```
nomoreco2/
├─ api/index.py          ← Vercel이 실행하는 입구
├─ app/
│  ├─ main.py            ← 앱 시작점
│  ├─ auth.py            ← 로그인 + 권한(Permission) 표
│  ├─ models.py          ← 데이터베이스 표 (회원, 활동글, 모집, 지원서, 후원, 설정)
│  ├─ database.py        ← 데이터베이스 연결
│  ├─ seed.py            ← 관리자 아이디와 예시 글 자동 생성
│  ├─ site.py            ← 관리자가 바꿀 수 있는 사이트 문구
│  └─ routers/
│     ├─ public.py       ← 누구나 보는 페이지 (홈, 소개, 활동, 후원, 함께하기)
│     ├─ auth.py         ← 로그인, 회원가입
│     └─ admin.py        ← 관리자 페이지
├─ templates/            ← 화면(HTML)
├─ public/static/css/    ← 디자인(CSS)
├─ requirements.txt      ← 필요한 파이썬 패키지
└─ vercel.json           ← Vercel 설정
```

## 🗺️ 페이지

| 주소 | 내용 | 누가 볼 수 있나요? |
|---|---|---|
| `/` | 홈 (메인 문구, 활동 소식, 모집, 탄소 줄이기 팁) | 모두 |
| `/about` | 단체 소개 (미션, 기후변화 설명, 약속, 팀) | 모두 |
| `/activities` | 우리가 하는 일 (활동 게시판) | 모두 |
| `/donate` | 후원하기 (종류, 금액별 효과, 사용처, 절차, 신청서, FAQ) | 모두 |
| `/join` | 함께하기 (모집 공고 + 지원서) | 모두 |
| `/mypage` | 내 후원·지원 내역 | 로그인한 사람 |
| `/admin` | 관리자 페이지 (글·모집·지원서·후원·회원·문구 관리) | **관리자 아이디만** |

## 🔑 권한(Permission)

| 역할 | 할 수 있는 일 |
|---|---|
| 일반 사용자 (`user`) | 보기(view), 후원·지원 신청(apply) |
| 관리자 (`admin`) | 위의 것 + 관리자 페이지, 글 쓰기·수정·삭제, 회원 권한 바꾸기 |

- 회원가입하면 누구나 **일반 사용자**예요.
- 관리자 아이디는 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 로 정해요. (기본값: `admin` / `nomoreco2!` → **꼭 바꾸세요!**)
- 관리자는 `/admin/users` 에서 다른 아이디를 관리자로 바꿀 수도 있어요.
- 권한표는 [app/auth.py](app/auth.py) 의 `ROLE_PERMISSIONS` 에 있어요.

## 💻 내 컴퓨터에서 실행하기

1. [python.org](https://www.python.org/downloads/) 에서 Python 설치 (설치할 때 **"Add python.exe to PATH" 체크!**)
2. VS Code 터미널에서:

```powershell
cd C:\Users\wnsqj\nomoreco2
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

3. 브라우저에서 http://127.0.0.1:8000 열기
4. 관리자 로그인: `admin` / `nomoreco2!` (자세한 방법은 [ADMIN_GUIDE.md](ADMIN_GUIDE.md))

---

## 🚀 Vercel에 올리기

> 👨‍👩‍👧 Vercel과 GitHub 가입은 **부모님이나 선생님과 함께** 하세요.

### 1단계. GitHub에 코드 올리기
1. [github.com](https://github.com) 가입
2. [GitHub Desktop](https://desktop.github.com) 설치 → 로그인
3. `File → Add local repository` → `nomoreco2` 폴더 선택 → "create a repository" 클릭
4. `Commit to main` → `Publish repository` (Private 체크해도 괜찮아요)

### 2단계. Vercel에서 프로젝트 만들기
1. [vercel.com](https://vercel.com) → **Continue with GitHub** 로 가입 (Hobby 무료 플랜)
2. `Add New… → Project` → `nomoreco2` 저장소 **Import**
3. Framework Preset: **Other** (자동으로 잡히면 그대로)
4. **Environment Variables** 에 아래 3개 추가

| Name | Value |
|---|---|
| `SECRET_KEY` | 아무도 모르는 아주 긴 글자 (예: 키보드로 막 친 40글자) |
| `ADMIN_USERNAME` | 내가 쓸 관리자 아이디 |
| `ADMIN_PASSWORD` | 나만 아는 관리자 비밀번호 |

5. **Deploy** 클릭 → 1~2분 뒤 `https://nomoreco2-xxxx.vercel.app` 주소가 생겨요 🎉

### 3단계. 데이터베이스 연결하기 (중요!)
Vercel은 서버가 자주 새로 시작돼서, 데이터베이스가 없으면 **새로 쓴 글·회원·후원 신청이 사라져요.**
1. Vercel 프로젝트 → **Storage** 탭 → **Create Database** → **Neon (Postgres)** 선택 → 무료 플랜
2. 프로젝트에 연결(Connect)하면 `DATABASE_URL` 이 자동으로 생겨요
3. **Deployments** 탭 → 맨 위 배포의 `⋯` → **Redeploy**

코드는 `DATABASE_URL` 이 있으면 자동으로 그 데이터베이스를 써요. 따로 고칠 것 없어요!

### 4단계. 주소(도메인) 바꾸기
- 무료: Settings → **Domains** 에서 `nomoreco2.vercel.app` 처럼 원하는 이름으로 바꾸기 (이미 있으면 다른 이름)
- 내 도메인: 도메인을 산 뒤 Settings → Domains → Add 하고, 안내에 나오는 DNS 값을 도메인 회사에 입력

### 5단계. 수정하면?
코드를 고치고 GitHub Desktop에서 `Commit → Push` 하면 Vercel이 **자동으로 다시 배포**해요.

## ⚠️ 꼭 알아 두기
- 이 사이트는 **실제 결제가 되지 않아요.** 진짜 후원을 받으려면 단체 등록, 기부금품법, 결제대행(PG) 계약이 필요해요.
- 후원 계좌는 예시예요. **진짜 계좌번호를 올리지 마세요.**
- 다른 사람의 이름·연락처를 모으게 되니, 관리자 비밀번호를 꼭 어렵게 만들고 과제가 끝나면 데이터를 지워 주세요.
