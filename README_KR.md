# GAME.GG - Render 배포용 프로젝트

## 포함 파일
- `app.py`: Flask 서버 및 PUBG API 연동
- `templates/index.html`: GAME.GG 전적 검색 화면
- `requirements.txt`: Python 패키지
- `.gitignore`: 비밀키와 가상환경 업로드 방지
- `.env.example`: 환경변수 예시

## 1. PUBG API 키 준비
PUBG Developer Portal에서 발급한 API 키가 필요합니다.
https://developer.pubg.com/

API 키는 GitHub에 올리지 마세요.

## 2. GitHub 업로드
압축을 푼 폴더 안의 파일과 `templates` 폴더를 저장소 최상위에 업로드합니다.
`GAME_GG_Render_Starter` 폴더 자체를 한 단계 더 중첩해서 올리지 않도록 주의하세요.

저장소 최상위에 `app.py`, `requirements.txt`, `templates/`가 보여야 합니다.

## 3. Render 설정
- New + -> Web Service
- GitHub 저장소 `getserious/pubg-stats-web` 선택
- Runtime: Python
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`

## 4. Render 환경변수
Render 서비스의 Environment 탭에서 추가:
- Key: `PUBG_API_KEY`
- Value: PUBG Developer Portal에서 발급한 실제 API 키

저장 후 재배포합니다.

## 5. 확인
- 사이트 주소 접속: GAME.GG 화면이 표시되는지 확인
- `/health` 접속: `{"service":"GAME.GG","status":"ok"}` 응답 확인
- 닉네임 검색: PUBG API 키가 유효하고 해당 플랫폼에 계정이 존재해야 합니다.

## 참고
이 프로젝트는 PUBG 공식 API의 플레이어 검색 및 시즌 통계를 사용합니다.
공식 API가 제공하지 않는 정보나 비공개 전적은 표시할 수 없습니다.
현재 시즌의 솔로/듀오/스쿼드 통계를 합산한 요약값을 제공합니다.
