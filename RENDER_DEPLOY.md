# GAME.GG - Render 배포

## Render Web Service 설정
- Runtime: Python 3
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn --bind 0.0.0.0:$PORT app:app`

## 필수 환경변수
- `PUBG_API_KEY`: PUBG Developer Portal에서 새로 발급한 API Key

## 관리자 기능을 사용할 때만 추가할 환경변수
- `GAMEGG_ADMIN_PASSWORD`
- `GAMEGG_ADMIN_PATH` (24~96자의 영문/숫자/밑줄/하이픈)
- `GAMEGG_ADMIN_TOTP_SECRET` (Authenticator 앱의 Base32 비밀키)
- `GAMEGG_SECRET_KEY` (새로 생성한 긴 무작위 문자열)
- `GAMEGG_HTTPS=1`
- `GAMEGG_ADMIN_NICKNAME` (선택)

관리자 설정값은 신뢰할 수 있는 로컬 PC에서 `setup_admin.py`로 새로 생성한 뒤 Render Environment에 개별 등록하세요. 비밀번호, OTP 키, 관리자 경로, Secret Key를 저장소나 공개 문서에 올리지 마세요.

## 보안 및 저장소 주의
- `.env`, `cache.sqlite3`, `.venv`, `cloudflared.exe`, `관리자키.txt`는 Git에 올리지 않습니다.
- 업로드된 원본 ZIP에는 비밀 환경변수가 포함되어 있었습니다. 기존 PUBG API Key와 관리자 인증값은 재발급/교체한 값만 사용하세요.
- `cache.sqlite3`는 배포 패키지에서 제외했습니다. 앱이 실행되면 캐시 DB를 다시 생성합니다.
- Render 무료 인스턴스의 로컬 파일은 영구 저장소가 아닙니다. SQLite에 저장되는 게시판 글은 재배포/재시작/인스턴스 교체 시 사라질 수 있습니다. 영구 보존이 필요하면 PostgreSQL 등 외부 DB로 이전하세요.
- PUBG API 실연동은 배포 후 새 API Key로 확인해야 합니다.
