GAME.GG - Original design + all platform ranked season details + official leaderboards

1. Copy .env.example to .env and set PUBG_API_KEY.
2. Run start_windows.bat on Windows.
3. Open http://127.0.0.1:5000.
4. Search on Steam / Kakao / PSN / Xbox; select a season under the chart to inspect that season's ranked RP, tier, wins and games.
5. Official TOP 10 has separate platform and region selectors; it is NOT a merged global ranking. Click refresh to request new data.

IMPORTANT:
- Player search and ranked stats use platform shards (steam/kakao/psn/xbox).
- Leaderboards use platform-region shards (pc-*, pc-kakao, psn-*, xbox-*), per PUBG official API documentation.
- Current season is read from the official isCurrentSeason flag. No player data or RP is hardcoded.
- The upstream leaderboard has its own update schedule: refresh does not guarantee changed rankings.
- Requesting 6 or 12 seasons may use many rate-limited requests. Cache season details for 10 minutes; season list for 30 days.
- An API 404/429 is returned as JSON with ok:false (HTTP 200 at the GAME.GG app boundary); it is not fabricated as a successful result.
- Prior season RP/tier can be unavailable depending on the upstream API.
- API integration was not tested against the live PUBG servers. Automated tests use mocked responses.

최근 20경기: 공식 /api/history?limit=20 응답 기반 카드, 필터, 요약, 상세 펼치기. 경쟁전/일반전은 API matchType 기준.
