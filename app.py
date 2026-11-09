import os
import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

PUBG_API_BASE = "https://api.pubg.com/shards"
PUBG_API_KEY = os.getenv("PUBG_API_KEY", "").strip()
HEADERS = {
    "Authorization": f"Bearer {PUBG_API_KEY}",
    "Accept": "application/vnd.api+json",
}

PLATFORM_SHARDS = {
    "steam": "steam",
    "kakao": "kakao",
}

def pubg_get(url, params=None):
    if not PUBG_API_KEY:
        return None, (jsonify({
            "error": "서버에 PUBG_API_KEY 환경변수가 설정되지 않았습니다. Render 환경변수를 확인해 주세요."
        }), 503)
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=20)
    except requests.RequestException:
        return None, (jsonify({"error": "PUBG API 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."}), 502)

    if response.status_code == 404:
        return None, (jsonify({"error": "해당 플랫폼에서 플레이어를 찾을 수 없습니다. 닉네임과 플랫폼을 확인해 주세요."}), 404)
    if response.status_code == 401:
        return None, (jsonify({"error": "PUBG API 키가 유효하지 않습니다. Render의 PUBG_API_KEY 값을 확인해 주세요."}), 502)
    if response.status_code == 429:
        return None, (jsonify({"error": "PUBG API 요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요."}), 429)
    if not response.ok:
        return None, (jsonify({"error": f"PUBG API 오류가 발생했습니다. (HTTP {response.status_code})"}), 502)
    try:
        return response.json(), None
    except ValueError:
        return None, (jsonify({"error": "PUBG API 응답을 해석하지 못했습니다."}), 502)

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "GAME.GG"})

@app.get("/api/player")
def player_search():
    nickname = request.args.get("nickname", "").strip()
    platform = request.args.get("platform", "steam").lower().strip()

    if not nickname:
        return jsonify({"error": "닉네임을 입력해 주세요."}), 400
    if platform not in PLATFORM_SHARDS:
        return jsonify({"error": "지원하지 않는 플랫폼입니다."}), 400

    shard = PLATFORM_SHARDS[platform]
    url = f"{PUBG_API_BASE}/{shard}/players"
    payload, error = pubg_get(url, params={"filter[playerNames]": nickname})
    if error:
        return error

    players = payload.get("data", [])
    if not players:
        return jsonify({"error": "플레이어를 찾을 수 없습니다."}), 404

    player = players[0]
    attributes = player.get("attributes", {})
    player_id = player.get("id")
    seasons_payload, seasons_error = pubg_get(f"{PUBG_API_BASE}/{shard}/seasons")
    if seasons_error:
        return jsonify({
            "nickname": attributes.get("name", nickname),
            "playerId": player_id,
            "platform": platform.upper(),
            "lifetime": {},
            "season": None,
            "notice": "플레이어는 찾았지만 시즌 정보를 불러오지 못했습니다."
        })

    seasons = seasons_payload.get("data", [])
    current_season = next(
        (s for s in seasons if s.get("attributes", {}).get("isCurrentSeason")),
        None
    )
    season_stats = {}
    if current_season:
        season_id = current_season.get("id")
        stats_payload, stats_error = pubg_get(
            f"{PUBG_API_BASE}/{shard}/players/{player_id}/seasons/{season_id}"
        )
        if not stats_error and stats_payload:
            season_stats = stats_payload.get("data", {}).get("attributes", {}).get("gameModeStats", {})

    solo = season_stats.get("solo", {})
    duo = season_stats.get("duo", {})
    squad = season_stats.get("squad", {})
    modes = [m for m in (solo, duo, squad) if m]
    totals = {}
    for key in ("roundsPlayed", "wins", "kills", "assists", "damageDealt", "top10s"):
        totals[key] = sum(float(m.get(key, 0) or 0) for m in modes)

    rounds = int(totals.get("roundsPlayed", 0))
    wins = int(totals.get("wins", 0))
    kills = int(totals.get("kills", 0))
    totals["kd"] = round(kills / max(rounds - wins, 1), 2) if rounds else 0
    totals["winRate"] = round(wins / rounds * 100, 1) if rounds else 0
    totals["avgDamage"] = round(totals.get("damageDealt", 0) / rounds) if rounds else 0

    return jsonify({
        "nickname": attributes.get("name", nickname),
        "playerId": player_id,
        "platform": platform.upper(),
        "season": current_season.get("id") if current_season else None,
        "stats": totals,
        "modes": {
            "solo": solo,
            "duo": duo,
            "squad": squad
        },
        "notice": None if rounds else "현재 시즌 전적이 없거나 공개되지 않았습니다."
    })

@app.errorhandler(404)
def not_found(_):
    return jsonify({"error": "요청한 주소를 찾을 수 없습니다."}), 404

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
