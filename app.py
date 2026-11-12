"""GAME.GG: PUBG official API client. No fabricated player data."""
import json
import hmac
import secrets
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urlsplit

import requests
from werkzeug.security import generate_password_hash, check_password_hash
AUTH_DUMMY_HASH = generate_password_hash(secrets.token_hex(24))
from gamegg_config import BUILD, load_configuration, print_config_summary, normalize_admin_path
from flask import Flask, jsonify, render_template, render_template_string, request, send_file, session

ROOT = Path(__file__).resolve().parent
CONFIG_REPORT = load_configuration(ROOT)
app = Flask(__name__)
app.config.update(SECRET_KEY=os.getenv('GAMEGG_SECRET_KEY') or secrets.token_hex(32), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('GAMEGG_HTTPS','0')=='1')
ADMIN_PASSWORD = os.getenv('GAMEGG_ADMIN_PASSWORD','')
ADMIN_NICKNAME = os.getenv('GAMEGG_ADMIN_NICKNAME','GAME.GG 운영자')
ADMIN_PATH = normalize_admin_path(os.getenv('GAMEGG_ADMIN_PATH',''))
ADMIN_TOTP_SECRET = os.getenv('GAMEGG_ADMIN_TOTP_SECRET','').strip().replace(' ','').upper()
LOGIN_FAILURES = {}
LOGIN_LOCK = threading.Lock()

def admin_configured():
    return bool(ADMIN_PASSWORD and ADMIN_PATH and ADMIN_TOTP_SECRET and os.getenv('GAMEGG_SECRET_KEY')) and bool(re.fullmatch(r'[a-zA-Z0-9_-]{1,96}', ADMIN_PATH))

def totp_valid(code):
    import base64, struct, hashlib
    if not re.fullmatch(r'[0-9]{6}', str(code)):
        return False
    try:
        key = base64.b32decode(ADMIN_TOTP_SECRET + '=' * (-len(ADMIN_TOTP_SECRET) % 8), casefold=True)
    except (ValueError, Exception):
        return False
    counter = int(time.time()) // 30
    for offset in (-1,0,1):
        digest = hmac.new(key, struct.pack('>Q', counter+offset), hashlib.sha1).digest()
        pos = digest[-1] & 15
        number = (struct.unpack('>I',digest[pos:pos+4])[0] & 0x7fffffff) % 1000000
        if hmac.compare_digest(f'{number:06d}',str(code)):
            return True
    return False

ADMIN_LOGIN_HTML = '''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>GAME.GG 인증</title><style>body{margin:0;background:#101d31;color:#eaf3ff;font:15px system-ui;display:grid;place-items:center;min-height:100vh}.card{width:min(380px,90vw);padding:30px;border-radius:18px;background:#243650;border:1px solid #45607f;box-shadow:0 20px 55px #07111f}h1{font-size:23px}label{display:block;margin:18px 0 7px}input{box-sizing:border-box;width:100%;padding:13px;border:1px solid #587492;border-radius:9px;background:#17283e;color:white;font-size:16px}button{width:100%;margin-top:22px;padding:13px;border:0;border-radius:9px;background:#0284c7;color:white;font-weight:700;cursor:pointer}.error{color:#ffb4b4}</style></head><body><div class="card"><h1>GAME.GG 운영자 인증</h1><p>관리자 비밀번호와 인증 앱의 6자리 코드를 입력하세요.</p>{% if error %}<p class="error">{{ error }}</p>{% endif %}<form method="post" autocomplete="off"><input type="hidden" name="csrf" value="{{ csrf }}"><label>관리자 비밀번호</label><input type="password" name="password" autocomplete="current-password" required><label>OTP 인증번호</label><input type="text" name="otp" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" required><button type="submit">관리자 로그인</button></form></div></body></html>'''

@app.route('/<path:secret_path>',methods=['GET','POST'])
def private_admin_login(secret_path):
    if not admin_configured() or not hmac.compare_digest(secret_path.rstrip('/'), ADMIN_PATH):
        return 'Not Found',404
    client = request.remote_addr or 'unknown'
    now = time.monotonic()
    with LOGIN_LOCK:
        recent = [t for t in LOGIN_FAILURES.get(client, []) if now - t < 900]
        LOGIN_FAILURES[client] = recent
    blocked = len(recent) >= 5
    wait_seconds = max(0, int(900 - (now - recent[0])) + 1) if blocked else 0
    if request.method == 'GET':
        token = secrets.token_urlsafe(32)
        session['admin_login_csrf'] = token
        error = (f'로그인 시도 횟수 초과: 약 {(wait_seconds + 59)//60}분 후 다시 시도하세요.' if blocked else None)
        return render_template_string(ADMIN_LOGIN_HTML, csrf=token, error=error), 200, {'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow'}
    csrf = session.get('admin_login_csrf', '')
    provided = request.form.get('csrf', '')
    good_csrf = bool(csrf) and hmac.compare_digest(csrf, provided)
    password = request.form.get('password', '')
    otp = request.form.get('otp', '')
    if blocked:
        return render_template_string(ADMIN_LOGIN_HTML, csrf=csrf, error=f'로그인 시도 횟수 초과: 약 {(wait_seconds + 59)//60}분 후 다시 시도하세요.'), 429, {'Cache-Control':'no-store'}
    if not (good_csrf and hmac.compare_digest(password, ADMIN_PASSWORD) and totp_valid(otp)):
        with LOGIN_LOCK:
            LOGIN_FAILURES.setdefault(client, []).append(now)
            failures = len(LOGIN_FAILURES[client])
        if failures >= 5:
            error = '5회 실패하여 15분간 로그인이 제한됩니다.'
            status = 429
        else:
            error = f'비밀번호 또는 OTP가 올바르지 않습니다. 남은 시도: {5-failures}회'
            status = 401
        return render_template_string(ADMIN_LOGIN_HTML, csrf=csrf, error=error), status, {'Cache-Control':'no-store'}
    with LOGIN_LOCK:LOGIN_FAILURES.pop(client,None)
    session.clear()
    session['gamegg_admin']=True
    session['gamegg_csrf']=secrets.token_urlsafe(32)
    from flask import redirect
    return redirect('/notices',code=303)

BASE = 'https://api.pubg.com/shards'
DB = Path(os.getenv('GAMEGG_CACHE_DB', str(ROOT / 'cache.sqlite3')))
LOCK = threading.RLock()
CACHE_STAGE = threading.local()
SHARDS = ('steam', 'kakao', 'psn', 'xbox')
REGIONS = {'steam': ('pc-as','pc-eu','pc-jp','pc-krjp','pc-na','pc-oc','pc-ru','pc-sa','pc-sea'), 'kakao': ('pc-kakao',), 'psn': ('psn-as','psn-eu','psn-na','psn-oc'), 'xbox': ('xbox-as','xbox-eu','xbox-na','xbox-oc','xbox-sa')}
API_SHARDS = set(SHARDS) | {r for rs in REGIONS.values() for r in rs}
MODES = ('solo', 'solo-fpp', 'duo', 'duo-fpp', 'squad', 'squad-fpp')

class PUBGError(Exception):
    def __init__(self, message, code='UPSTREAM_ERROR', upstream_status=None, retry_after=None):
        super().__init__(message)
        self.code, self.upstream_status, self.retry_after = code, upstream_status, retry_after


def db_conn():
    db = sqlite3.connect(DB, timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires REAL NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS cache_metadata (key TEXT PRIMARY KEY, updated_at REAL NOT NULL)')
    return db


def cache_get(key):
    with LOCK, db_conn() as db:
        row = db.execute('SELECT value FROM cache WHERE key=? AND expires>?', (key, time.time())).fetchone()
    return json.loads(row[0]) if row else None


def cache_set(key, value, ttl):
    pending = getattr(CACHE_STAGE, 'pending', None)
    if pending is not None:
        pending[key] = (value, ttl)
        return
    with LOCK, db_conn() as db:
        db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)', (key, json.dumps(value, ensure_ascii=False), time.time()+ttl))
        db.execute('INSERT OR REPLACE INTO cache_metadata VALUES (?,?)', (key, time.time()))


def api_cache_key(shard, path, params=None):
    return 'api:' + shard + ':' + path + ':' + json.dumps(params or {}, sort_keys=True)


def cache_updated_at(key):
    with LOCK, db_conn() as db:
        row = db.execute('SELECT m.updated_at FROM cache_metadata m JOIN cache c ON m.key=c.key WHERE m.key=? AND c.expires>?', (key, time.time())).fetchone()
    return row[0] if row else None


def api_get(shard, path, *, params=None, ttl=0, authenticated=True, force=False):
    if shard not in API_SHARDS or not re.fullmatch(r'[A-Za-z0-9_./-]+', path):
        raise PUBGError('잘못된 요청 경로입니다.', 'INVALID_INPUT')
    key = api_cache_key(shard, path, params)
    if ttl and not force:
        saved = cache_get(key)
        if saved is not None:
            return saved
    headers = {'Accept':'application/vnd.api+json', 'Accept-Encoding':'gzip'}
    if authenticated:
        secret = os.getenv('PUBG_API_KEY','').strip()
        if not secret:
            raise PUBGError('실행 중인 서버가 PUBG_API_KEY를 읽지 못했습니다. check_config.bat로 확인한 뒤 서버를 다시 실행해 주세요.', 'NO_API_KEY')
        headers['Authorization'] = 'Bearer ' + secret
    try:
        resp = requests.get(f'{BASE}/{shard}/{path}', params=params, headers=headers, timeout=18)
    except requests.RequestException:
        raise PUBGError('PUBG API 연결에 실패했습니다.', 'NETWORK_ERROR')
    if resp.status_code == 404:
        raise PUBGError('PUBG 공식 API에 해당 데이터가 없습니다.', 'NOT_FOUND', 404)
    if resp.status_code == 429:
        raise PUBGError('PUBG API 요청 제한입니다. 잠시 후 다시 시도해 주세요.', 'RATE_LIMIT', 429, resp.headers.get('Retry-After'))
    if resp.status_code in (401,403):
        raise PUBGError('PUBG API 인증이 거부됐습니다.', 'AUTH_ERROR', resp.status_code)
    if resp.status_code >= 400:
        raise PUBGError('PUBG API가 오류를 반환했습니다.', 'UPSTREAM_ERROR', resp.status_code)
    try:
        payload = resp.json()
    except ValueError:
        raise PUBGError('PUBG API JSON 응답을 해석할 수 없습니다.', 'BAD_RESPONSE')
    if ttl:
        cache_set(key, payload, ttl)
    return payload


PLATFORM_NAMES = {'steam':'Steam', 'kakao':'Kakao', 'psn':'PlayStation', 'xbox':'Xbox'}


def platform_from_shard(value):
    if not isinstance(value, str): return None
    value=value.lower().strip()
    if value in SHARDS: return value
    return next((platform for platform, regions in REGIONS.items() if value in regions), None)


def validate_reported_platform(attrs, requested):
    reported=platform_from_shard(attrs.get('shardId'))
    if reported and reported != requested:
        raise PUBGError(f'{PLATFORM_NAMES[requested]}에서 조회할 수 없는 계정입니다. 응답 플랫폼은 {PLATFORM_NAMES[reported]}입니다. 올바른 플랫폼을 선택해 주세요.', 'PLATFORM_MISMATCH', 404)
    return reported


def account_from_payload(payload, shard):
    items = payload.get('data') or []
    if isinstance(items, dict): items = [items]
    if not items or not items[0].get('id'):
        raise PUBGError('선택한 플랫폼에서 이 닉네임을 찾을 수 없습니다. 닉네임과 Steam/Kakao 등 플랫폼을 확인해 주세요.', 'NOT_FOUND', 404)
    item = items[0]
    reported=validate_reported_platform(item.get('attributes') or {}, shard)
    match_ids = [x['id'] for x in ((item.get('relationships') or {}).get('matches') or {}).get('data', []) if x.get('id')]
    return {'account_id':item['id'], 'nickname':item.get('attributes',{}).get('name',''), 'platform':shard, 'reported_platform':reported, 'match_ids':match_ids}


def lookup(nickname, shard, *, force=False):
    if not nickname or len(nickname)>80 or any(ord(c)<32 for c in nickname):
        raise PUBGError('닉네임을 확인해 주세요.', 'INVALID_INPUT')
    if shard not in SHARDS:
        raise PUBGError('조회할 플랫폼을 정확히 선택해 주세요.', 'INVALID_INPUT')
    shards = (shard,)  # 다른 플랫폼으로 자동 검색하지 않음
    for s in shards:
        key = f'player:v2:{s}:{nickname.casefold()}'
        cached = None if force else cache_get(key)
        if cached is not None and cached.get('platform') == s and cached.get('nickname','').casefold() == nickname.casefold():
            return cached
        try:
            player = account_from_payload(api_get(s, 'players', params={'filter[playerNames]':nickname}, ttl=PLAYER_CACHE_TTL, force=force), s)
            if player['platform'] != s or player['nickname'].casefold() != nickname.casefold():
                raise PUBGError('선택한 플랫폼에서 해당 닉네임이 조회되지 않습니다. 올바른 플랫폼으로 다시 검색해 주세요.', 'NOT_FOUND', 404)
            cache_set(key, player, PLAYER_CACHE_TTL)
            return player
        except PUBGError as e:
            if e.code != 'NOT_FOUND': raise
    raise PUBGError('선택한 플랫폼에서 해당 닉네임이 조회되지 않습니다. 닉네임과 플랫폼을 확인해 주세요.', 'NOT_FOUND', 404)


def seasons_for(shard):
    items = api_get(shard,'seasons',ttl=3600).get('data') or []
    unique={}
    tokens={'steam':('.pc-',),'kakao':('.pc-',),'psn':('.console-','.playstation-'),'xbox':('.console-','.xbox-')}.get(shard,())
    def score(item): return (item['current'],any(token in item['id'] for token in tokens))
    for raw in items:
        sid=raw.get('id');attrs=raw.get('attributes') or {}
        if not sid or attrs.get('isOffseason') or attrs.get('isOffSeason'): continue
        number=sid.rsplit('-',1)[-1]
        if number.isdigit(): number=str(int(number))
        item={'id':sid,'current':bool(attrs.get('isCurrentSeason')),'number':number}
        if number not in unique or score(item)>score(unique[number]): unique[number]=item
    return sorted(unique.values(),key=lambda item:(item['current'],int(item['number']) if item['number'].isdigit() else -1),reverse=True)


def player_stats(shard, player_id, season_id, ranked=False, *, force=False):
    path = f'players/{quote(player_id,safe="")}/seasons/{quote(season_id,safe="")}'
    if ranked: path += '/ranked'
    payload = api_get(shard, path, ttl=STATS_CACHE_TTL, force=force)
    attrs = (payload.get('data') or {}).get('attributes') or {}
    validate_reported_platform(attrs, shard)
    return attrs.get('rankedGameModeStats' if ranked else 'gameModeStats') or {}


def gamegg_tier(rp):
    """GAME.GG custom RP tier, never PUBG official tier."""
    if rp is None: return None
    try: value = max(0, int(float(rp)))
    except (ValueError, TypeError): return None
    for minimum, label in ((9500,'HighRanker'),(6000,'챌린저'),(5500,'그랜드마스터'),(4800,'마스터'),
                           (4000,'다이아몬드'),(3200,'플래티넘'),(2400,'골드'),
                           (1600,'실버'),(800,'브론즈'),(0,'아이언')):
        if value >= minimum: return {'name':label,'minimum':minimum,'rp':value}


def leaderboard_for(region, season_id, mode):
    if region not in API_SHARDS or mode not in MODES:
        raise PUBGError('지역 또는 모드가 올바르지 않습니다.', 'INVALID_INPUT')
    payload = api_get(region, f'leaderboards/{quote(season_id,safe="")}/{mode}', ttl=0)
    data = payload.get('data') or {}
    rows = ((data.get('relationships') or {}).get('players') or {}).get('data') or []
    included = {p.get('id'):p for p in (payload.get('included') or []) if isinstance(p,dict)}
    output=[]
    for index, row in enumerate(rows,1):
        item = included.get(row.get('id'), {})
        attrs = item.get('attributes') or {}
        stats = attrs.get('stats') or {}
        rp = stats.get('rankPoints',stats.get('currentRankPoint'))
        output.append({'position':attrs.get('rank') or index,'nickname':attrs.get('name') or stats.get('name') or '이름 미제공',
                       'rp':rp,'gamegg_tier':gamegg_tier(rp),'official_tier':({'tier':stats['tier'],'subTier':stats.get('subTier')} if isinstance(stats.get('tier'),str) and stats.get('tier') else stats.get('tier') or stats.get('currentTier')),
                       'account_id':row.get('id'), 'kda':stats.get('kda'), 'mode':mode})
    output.sort(key=lambda item: int(item['position']) if str(item['position']).isdigit() else 999999)
    return output[:10]

def safe_section(fn):
    try: return {'available':True,'data':fn()}
    except PUBGError as e:
        return {'available':False,'data':None,'reason':str(e),'code':e.code,'upstream_status':e.upstream_status,'retry_after':e.retry_after}


def parse_match(payload, account_id):
    root = payload.get('data') or {}
    attrs = root.get('attributes') or {}
    included = payload.get('included') or []
    participant = next((x for x in included if x.get('type')=='participant' and (x.get('attributes',{}).get('stats') or {}).get('playerId')==account_id), None)
    if not participant: return None
    stats = (participant.get('attributes') or {}).get('stats') or {}
    rank = stats.get('winPlace')
    for roster in included:
        if roster.get('type')!='roster': continue
        participants = ((roster.get('relationships') or {}).get('participants') or {}).get('data') or []
        if any(x.get('id')==participant.get('id') for x in participants):
            rank = ((roster.get('attributes') or {}).get('stats') or {}).get('rank',rank)
            break
    return {'id':root.get('id'),'createdAt':attrs.get('createdAt'),'map':attrs.get('mapName'),'mode':attrs.get('gameMode'),'type':attrs.get('matchType'), 'rank':rank, 'kills':stats.get('kills',0),'assists':stats.get('assists',0),'damage':stats.get('damageDealt',0),'survival':stats.get('timeSurvived',0),'headshots':stats.get('headshotKills',0),'distance':sum(float(stats.get(k) or 0) for k in ('walkDistance','rideDistance','swimDistance')), 'stats':stats}


def recent_matches(shard, account_id, match_ids, limit):
    ids = list(dict.fromkeys(match_ids))[:limit]
    if not ids: return {'matches':[],'requested':0,'failed':0,'note':'PUBG API 플레이어 목록에 최근 경기 ID가 없습니다.'}
    result=[]; failed=0
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(api_get,shard,'matches/'+quote(mid,safe=''),ttl=1800,authenticated=False) for mid in ids]
        for future in as_completed(futures):
            try:
                match = parse_match(future.result(),account_id)
                if match: result.append(match)
                else: failed+=1
            except (PUBGError, ValueError, KeyError, TypeError): failed+=1
    result.sort(key=lambda x:x.get('createdAt') or '',reverse=True)
    return {'matches':result,'requested':len(ids),'failed':failed,'note':'최근 경기만 표시합니다. 시즌 전체 통계와 혼합하지 않습니다.'}


def response_ok(data): return jsonify({'ok':True,**data}),200


def endpoint(fn):
    try: return response_ok(fn())
    except PUBGError as e:
        # Intentional HTTP 200 for application-level failures; do not disguise error in JSON.
        return jsonify({'ok':False,'error':str(e),'code':e.code,'upstream_status':e.upstream_status,'retry_after':e.retry_after}),200
    except Exception:
        app.logger.exception('Unhandled application exception')
        return jsonify({'ok':False,'error':'서버 내부 처리 오류가 발생했습니다. CMD 로그를 확인해 주세요.','code':'INTERNAL_ERROR'}),200


def query_player():
    nickname = request.args.get('nickname','').strip()
    platform = request.args.get('platform','').strip().lower()
    if platform not in SHARDS:
        raise PUBGError('플랫폼을 선택해 주세요.', 'INVALID_INPUT')
    return lookup(nickname,platform)


@app.get('/')
def home(): return render_template('index.html', active_page='home')

@app.get('/search')
@app.get('/teams')
@app.get('/notices')
def site_section():
    return render_template('index.html', active_page=request.path.strip('/'))

@app.get('/api/health')
def health(): return response_ok({'service':'GAME.GG','build':BUILD,'configured':bool(os.getenv('PUBG_API_KEY','').strip())})

@app.get('/api/search')
def search():
    return endpoint(lambda: {'player':{k:v for k,v in query_player().items() if k!='match_ids'}})

def has_rounds(section):
    return section.get('available') and any(isinstance(stats,dict) and float(stats.get('roundsPlayed') or 0)>0 for stats in (section.get('data') or {}).values())


# Player refresh metadata and cooldown live in SQLite so workers share the limit.
PLAYER_CACHE_TTL = 1800
STATS_CACHE_TTL = 1800
REFRESH_COOLDOWN = 120
REFRESH_LEASE = 180


def refresh_conn():
    db = db_conn()
    db.execute('CREATE TABLE IF NOT EXISTS player_refresh (key TEXT PRIMARY KEY, last_success REAL, next_allowed REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0, token TEXT)')
    return db


def refresh_key(nickname, platform):
    return platform + ':' + nickname.casefold()


def refresh_metadata(nickname, platform, fetched_at=None):
    now = time.time()
    with LOCK, refresh_conn() as db:
        row = db.execute('SELECT last_success,next_allowed,lease_until FROM player_refresh WHERE key=?', (refresh_key(nickname, platform),)).fetchone()
    return {'fetched_at': fetched_at or (row[0] if row else None),
            'next_allowed_at': max(row[1], row[2]) if row else 0,
            'server_time': now, 'cooldown_seconds': REFRESH_COOLDOWN,
            'cache_ttl_seconds': PLAYER_CACHE_TTL,
            'refreshing': bool(row and row[2] > now)}


def claim_refresh(nickname, platform):
    now = time.time(); key = refresh_key(nickname, platform); token = secrets.token_hex(16)
    with LOCK, refresh_conn() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT next_allowed,lease_until FROM player_refresh WHERE key=?', (key,)).fetchone()
        if row and max(row) > now:
            wait = max(1, int(max(row) - now) + 1)
            raise PUBGError('정보 갱신 대기시간입니다. 잠시 후 다시 시도해 주세요.', 'REFRESH_COOLDOWN', retry_after=wait)
        db.execute('INSERT INTO player_refresh(key,next_allowed,lease_until,token) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET next_allowed=excluded.next_allowed,lease_until=excluded.lease_until,token=excluded.token', (key, now + REFRESH_COOLDOWN, now + REFRESH_LEASE, token))
    return token


def finish_refresh(nickname, platform, token, success=False, retry_after=None):
    now = time.time()
    try: wait = max(REFRESH_COOLDOWN, min(3600, int(float(retry_after or 0))))
    except (ValueError, TypeError): wait = REFRESH_COOLDOWN
    with LOCK, refresh_conn() as db:
        db.execute('UPDATE player_refresh SET last_success=CASE WHEN ? THEN ? ELSE last_success END,next_allowed=?,lease_until=0,token=NULL WHERE key=? AND token=?', (bool(success), now, now + wait, refresh_key(nickname, platform), token))


def profile_payload(p, *, force=False):
    all_seasons = seasons_for(p['platform'])
    current = next((s for s in all_seasons if s['current']), None)
    if force:
        # Stop at the first failure. Never mark a partially refreshed profile as successful.
        ranked = {'available': True, 'data': player_stats(p['platform'], p['account_id'], current['id'], True, force=True)} if current else {'available': False, 'data': None, 'reason': '현재 시즌 없음'}
        normal = {'available': True, 'data': player_stats(p['platform'], p['account_id'], current['id'], force=True)} if current else {'available': False, 'data': None, 'reason': '현재 시즌 없음'}
    else:
        ranked = safe_section(lambda: player_stats(p['platform'], p['account_id'], current['id'], True)) if current else {'available': False, 'data': None, 'reason': '현재 시즌 없음'}
        normal = safe_section(lambda: player_stats(p['platform'], p['account_id'], current['id'])) if current else {'available': False, 'data': None, 'reason': '현재 시즌 없음'}
    for section in (ranked, normal):
        if section.get('code') == 'PLATFORM_MISMATCH': raise PUBGError(section['reason'], 'PLATFORM_MISMATCH', 404)
    records = bool(p.get('match_ids')) or bool(has_rounds(ranked) or has_rounds(normal))
    failed = not ranked.get('available') or not normal.get('available')
    message = '' if records else (f"{PLATFORM_NAMES[p['platform']]}에서 이 닉네임의 전적을 확인할 수 없습니다. 플랫폼과 시즌을 확인해 주세요. " + ('전적 조회 요청이 실패했습니다.' if failed else '현재 시즌 기록과 최근 경기 목록이 없습니다. 과거 시즌 기록은 별도로 확인할 수 있습니다.'))
    # This timestamp describes the oldest required source response, not the page-open time.
    keys = [api_cache_key(p['platform'], 'players', {'filter[playerNames]': p['nickname']})]
    if current:
        base = f"players/{quote(p['account_id'],safe='')}/seasons/{quote(current['id'],safe='')}"
        keys.extend([api_cache_key(p['platform'], base), api_cache_key(p['platform'], base + '/ranked')])
    times = [cache_updated_at(k) for k in keys]
    fetched = min(times) if all(times) else None
    return {'player': {k:v for k,v in p.items() if k != 'match_ids'}, 'current_season': current, 'seasons': all_seasons, 'ranked': ranked, 'normal': normal, 'records_available': records, 'record_status': 'AVAILABLE' if records else 'QUERY_FAILED' if failed else 'NO_CURRENT_RECORDS', 'platform_message': message,
            'refresh': refresh_metadata(p['nickname'], p['platform'], fetched)}


@app.post('/api/profile/refresh')
def refresh_profile():
    nickname = ''; platform = ''; token = None
    try:
        origin = request.headers.get('Origin')
        if origin and urlsplit(origin).netloc.lower() != request.host.lower():
            raise PUBGError('다른 사이트에서 보낸 갱신 요청은 허용하지 않습니다.', 'INVALID_ORIGIN')
        data = request.get_json(silent=True)
        if not isinstance(data, dict): raise PUBGError('갱신 요청을 확인해 주세요.', 'INVALID_INPUT')
        nickname = str(data.get('nickname', '')).strip(); platform = str(data.get('platform', '')).strip().lower()
        if platform not in SHARDS or not nickname or len(nickname)>80 or any(ord(c)<32 for c in nickname):
            raise PUBGError('닉네임과 플랫폼을 확인해 주세요.', 'INVALID_INPUT')
        selected = str(data.get('season') or '').strip()
        if selected and selected not in {x['id'] for x in seasons_for(platform)}:
            raise PUBGError('시즌 목록에 없는 ID입니다.', 'INVALID_INPUT')
        token = claim_refresh(nickname, platform)
        CACHE_STAGE.pending = {}
        player = lookup(nickname, platform, force=True)
        result = profile_payload(player, force=True)
        if selected and selected != (result.get('current_season') or {}).get('id'):
            result['selected_season'] = {'id': selected,
                'ranked': {'available': True, 'data': player_stats(platform, player['account_id'], selected, True, force=True)},
                'normal': {'available': True, 'data': player_stats(platform, player['account_id'], selected, force=True)}}
        pending = CACHE_STAGE.pending
        CACHE_STAGE.pending = None
        # Publish all refreshed source data together. A failed refresh keeps the old cache.
        with LOCK, db_conn() as db:
            saved_at = time.time()
            for key, (value, ttl) in pending.items():
                db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)', (key,json.dumps(value,ensure_ascii=False),saved_at+ttl))
                db.execute('INSERT OR REPLACE INTO cache_metadata VALUES (?,?)', (key,saved_at))
        finish_refresh(nickname, platform, token, success=True)
        result['refresh'] = refresh_metadata(nickname, platform)
        return response_ok(result)
    except PUBGError as e:
        if token: finish_refresh(nickname, platform, token, retry_after=e.retry_after)
        meta = refresh_metadata(nickname, platform) if nickname and platform in SHARDS else None
        return jsonify(ok=False, error=str(e), code=e.code, retry_after=e.retry_after, refresh=meta), 200
    except Exception:
        if token: finish_refresh(nickname, platform, token)
        app.logger.exception('Profile refresh failed')
        return jsonify(ok=False,error='갱신에 실패했습니다. 기존 화면의 기록은 유지됩니다.',code='INTERNAL_ERROR',refresh=refresh_metadata(nickname,platform) if nickname and platform in SHARDS else None),200

    finally:
        CACHE_STAGE.pending = None


@app.get('/api/profile')
def profile():
    return endpoint(lambda: profile_payload(query_player()))

@app.get('/api/season')
def season():
    def run():
        p=query_player(); sid=request.args.get('season','')
        all_seasons=seasons_for(p['platform'])
        if sid not in {x['id'] for x in all_seasons}: raise PUBGError('시즌 목록에 없는 ID입니다.','INVALID_INPUT')
        return {'season':next(x for x in all_seasons if x['id']==sid), 'ranked':safe_section(lambda:player_stats(p['platform'],p['account_id'],sid,True)), 'normal':safe_section(lambda:player_stats(p['platform'],p['account_id'],sid))}
    return endpoint(run)

@app.get('/api/history')
def history():
    def run():
        p=query_player()
        try: limit=min(20,max(1,int(request.args.get('limit','10'))))
        except ValueError: raise PUBGError('limit은 1~20 사이의 숫자여야 합니다.', 'INVALID_INPUT')
        return {'player':{k:v for k,v in p.items() if k!='match_ids'},**recent_matches(p['platform'],p['account_id'],p.get('match_ids') or [],limit)}
    return endpoint(run)

@app.get('/api/leaderboard')
def leaderboard():
    def run():
        platform = request.args.get('platform','steam').lower()
        if platform not in SHARDS: raise PUBGError('플랫폼이 올바르지 않습니다.','INVALID_INPUT')
        region = request.args.get('region','') or REGIONS[platform][0]
        if region not in REGIONS[platform]: raise PUBGError('플랫폼에 해당하지 않는 지역입니다.','INVALID_INPUT')
        mode = request.args.get('mode','squad')
        all_seasons = seasons_for(platform)
        sid = request.args.get('season','') or next((x['id'] for x in all_seasons if x['current']),None)
        if not sid: raise PUBGError('공식 API에서 현재 시즌을 찾지 못했습니다.','NO_CURRENT_SEASON')
        if sid not in {x['id'] for x in all_seasons}: raise PUBGError('유효하지 않은 시즌입니다.','INVALID_INPUT')
        return {'platform':platform,'region':region,'season':sid,'mode':mode,
                'leaders':leaderboard_for(region,sid,mode),'regions':REGIONS[platform]}
    return endpoint(run)

@app.get('/api/season-chart')
def season_chart():
    def run():
        p=query_player()
        mode=request.args.get('mode','squad')
        if mode not in MODES: raise PUBGError('게임 모드가 올바르지 않습니다.','INVALID_INPUT')
        try:
            limit=max(1,min(100,int(request.args.get('limit','6'))))
            offset=max(0,int(request.args.get('offset','0')))
            batch=max(1,min(6,int(request.args.get('batch_size','6'))))
        except ValueError: raise PUBGError('시즌 범위/위치는 숫자여야 합니다.','INVALID_INPUT')
        unique={}
        for item in seasons_for(p['platform']):
            if item['number'] not in unique or item['current']: unique[item['number']]=item
        ordered=sorted(unique.values(),key=lambda x:int(x['number']) if x['number'].isdigit() else -1,reverse=True)
        end_season=request.args.get('end_season','').strip()
        if end_season:
            anchor=next((i for i,item in enumerate(ordered) if item['id']==end_season),None)
            if anchor is None: raise PUBGError('선택한 시즌을 찾을 수 없습니다.','INVALID_INPUT')
            ordered=ordered[anchor:]
        ordered=ordered[:limit]
        points=[]; next_offset=min(offset,len(ordered)); paused=False; retry_after=None; pause_code=None; pause_reason=None
        for index,item in enumerate(ordered[offset:offset+batch],offset):
            if item['number'].isdigit() and int(item['number'])<7:
                section={'available':False,'data':None,'code':'UNSUPPORTED','reason':'경쟁전 통계 제공 이전 시즌입니다.'}
            else:
                section=safe_section(lambda sid=item['id']:player_stats(p['platform'],p['account_id'],sid,True))
            stats=(section.get('data') or {}).get(mode) if section['available'] else None
            played=isinstance(stats,dict) and float(stats.get('roundsPlayed') or 0)>0
            status='AVAILABLE' if played else 'NO_RECORD' if section['available'] else section.get('code','QUERY_FAILED')
            rp=stats.get('currentRankPoint',stats.get('rankPoints')) if played else None
            points.append({'season':item,'available':played,'status':status,'wins':stats.get('wins') if played else None,
                           'rounds':stats.get('roundsPlayed') if isinstance(stats,dict) else None,'rp':rp,
                           'gamegg_tier':gamegg_tier(rp),'official_tier':stats.get('currentTier') if played else None,
                           'stats':stats if played else None,'error':section.get('reason'),'code':None if played else status})
            if status in ('RATE_LIMIT','AUTH_ERROR','NO_API_KEY','NETWORK_ERROR','UPSTREAM_ERROR','BAD_RESPONSE'):
                paused=True;pause_code=status;pause_reason=section.get('reason');retry_after=section.get('retry_after');next_offset=index;break
            next_offset=index+1
        points.sort(key=lambda x:int(x['season']['number']) if x['season']['number'].isdigit() else -1)
        return {'mode':mode,'points':points,'season_list':ordered,'requested':len(ordered),'offset':offset,
                'next_offset':next_offset,'has_more':next_offset<len(ordered),'rate_limited':pause_code=='RATE_LIMIT','paused':paused,'pause_code':pause_code,'pause_reason':pause_reason,'retry_after':retry_after}
    return endpoint(run)

@app.get('/api/extra')
def extra():
    def run():
        p=query_player(); section=request.args.get('section','')
        if section not in ('lifetime','weapon_mastery','survival_mastery'):
            raise PUBGError('지원하지 않는 조회 항목입니다.','INVALID_INPUT')
        path = f'players/{quote(p["account_id"],safe="")}/'
        if section=='lifetime': path+='seasons/lifetime'
        else: path+=section
        return {'section':section,'result':safe_section(lambda: (api_get(p['platform'],path,ttl=1800).get('data') or {}).get('attributes') or {})}
    return endpoint(run)

@app.get('/api/diagnose')
def diagnose():
    def run():
        p=query_player()
        return {'player':{k:v for k,v in p.items() if k!='match_ids'},'recent_match_ids':len(p.get('match_ids') or [])}
    return endpoint(run)



# PUBG match telemetry: the match must belong to the searched player.
@app.get('/api/match-telemetry')
def match_telemetry():
    def run():
        from urllib.parse import urlparse
        platform = request.args.get('platform', 'steam').lower()
        nickname = request.args.get('nickname', '').strip()
        match_id = request.args.get('match_id', '').strip()
        if platform not in SHARDS or not re.fullmatch(r'[A-Za-z0-9_.-]{8,180}', match_id):
            raise PUBGError('플랫폼 또는 경기 ID가 올바르지 않습니다.', 'INVALID_INPUT')
        player = lookup(nickname, platform)
        if match_id not in (player.get('match_ids') or []):
            raise PUBGError('해당 플레이어의 최근 경기 목록에 없는 경기입니다.', 'MATCH_NOT_FOUND', 404)
        match = api_get(platform, 'matches/' + quote(match_id, safe=''), ttl=1800, authenticated=False)
        included = match.get('included') or []
        assets = ((match.get('data') or {}).get('relationships') or {}).get('assets') or {}
        ids = {item.get('id') for item in (assets.get('data') or [])}
        asset = next((item for item in included if item.get('type') == 'asset' and item.get('id') in ids and (item.get('attributes') or {}).get('URL')), None)
        if not asset:
            raise PUBGError('이 경기에는 텔레메트리 파일이 제공되지 않습니다.', 'NO_TELEMETRY')
        url = (asset.get('attributes') or {}).get('URL', '')
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or not (parsed.hostname == 'telemetry-cdn.pubg.com' or parsed.hostname.endswith('.telemetry-cdn.pubg.com')):
            raise PUBGError('텔레메트리 URL을 검증할 수 없습니다.', 'BAD_TELEMETRY_URL')
        cache_key = 'killlog:v6:combat:' + platform + ':' + match_id + ':' + player['account_id']
        cached = cache_get(cache_key)
        if cached is not None: return cached
        try:
            resp = requests.get(url, headers={'Accept': 'application/vnd.api+json', 'Accept-Encoding': 'gzip'}, timeout=35, allow_redirects=False, stream=True)
            resp.raise_for_status()
            content = bytearray()
            for chunk in resp.iter_content(chunk_size=65536):
                content.extend(chunk)
                if len(content) > 35 * 1024 * 1024:
                    raise PUBGError('텔레메트리 파일 크기가 허용 범위를 초과했습니다.', 'TELEMETRY_TOO_LARGE')
            events = json.loads(content)
            if not isinstance(events, list): raise ValueError('unexpected telemetry format')
        except PUBGError: raise
        except (requests.RequestException, ValueError, TypeError):
            raise PUBGError('텔레메트리 데이터를 다운로드하거나 분석할 수 없습니다.', 'TELEMETRY_ERROR')
        account = player['account_id']
        def same(character):
            return isinstance(character, dict) and character.get('accountId') == account
        def actor(character):
            if not isinstance(character, dict): return '정보 없음'
            return character.get('name') or '정보 없음'
        weapon_names = {
            'WeapAUG_C':'AUG', 'WeapM24_C':'M24', 'WeapM416_C':'M416',
            'WeapBerylM762_C':'베릴 M762', 'WeapMP5K_C':'MP5K',
            'WeapACE32_C':'ACE32', 'WeapQBZ95_C':'QBZ', 'WeapAK47_C':'AKM',
            'WeapSCAR-L_C':'SCAR-L', 'WeapSCAR_L_C':'SCAR-L',
            'WeapKar98k_C':'Kar98k', 'WeapAWM_C':'AWM', 'WeapMini14_C':'Mini14',
            'WeapSKS_C':'SKS', 'WeapSLR_C':'SLR', 'WeapMk14_C':'Mk14',
            'WeapMk12_C':'Mk12', 'WeapM16A4_C':'M16A4', 'WeapGroza_C':'Groza',
            'WeapVector_C':'Vector', 'WeapUMP_C':'UMP45', 'WeapUZI_C':'Micro UZI',
            'WeapP90_C':'P90', 'WeapM249_C':'M249', 'WeapDP28_C':'DP-28',
            'WeapMG3_C':'MG3', 'WeapWin94_C':'Win94', 'WeapMosinNagant_C':'모신나강',
            'WeapPan_C':'프라이팬', 'WeapGrenade_C':'수류탄', 'WeapMolotov_C':'화염병',
            'WeapCrossbow_1_C':'석궁', 'WeapDBS_C':'DBS', 'WeapS12K_C':'S12K',
            'WeapS1897_C':'S1897', 'WeapS686_C':'S686', 'WeapJS9_C':'JS9',
            'WeapFamasG2_C':'FAMAS', 'WeapDragunov_C':'드라구노프'
        }
        def readable_weapon(raw):
            if not raw: return '무기 정보 없음'
            return weapon_names.get(str(raw), str(raw).removeprefix('Weap').removesuffix('_C'))
        def meters_from_cm(raw):
            # PUBG telemetry positions and damage-info distance use centimeters.
            try:
                value = float(raw)
                return round(value / 100, 1) if value >= 0 and value < 1e9 else None
            except (ValueError, TypeError):
                return None
        def damage(event):
            for field in ('killerDamageInfo', 'finishDamageInfo', 'dBNODamageInfo'):
                item = event.get(field)
                if isinstance(item, dict) and item.get('damageCauserName'):
                    return readable_weapon(item.get('damageCauserName')), meters_from_cm(item.get('distance')), str(item.get('damageCauserName') or ''), str(item.get('damageReason') or '')
            return readable_weapon(event.get('damageCauserName')), meters_from_cm(event.get('distance')), str(event.get('damageCauserName') or ''), str(event.get('damageReason') or '')
        # Match start timestamp is needed to compute early kills, not wall-clock time.
        from datetime import datetime, timezone
        def timestamp(value):
            try: return datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
            except (TypeError, ValueError): return None
        start_times=[timestamp(e.get('_D')) for e in events if isinstance(e,dict) and e.get('_T')=='LogMatchStart']
        start=next((t for t in start_times if t is not None),None)
        kills, deaths, match_killfeed = [], [], []
        for event in events:
            if not isinstance(event, dict) or event.get('_T') not in ('LogPlayerKillV2', 'LogPlayerKill'): continue
            victim = event.get('victim') or {}
            killer = event.get('killer') or {}
            finisher = event.get('finisher') or {}
            # In V2, killer is the credited killer; finisher may be a different teammate.
            weapon, distance, weapon_code, reason = damage(event)
            headshot = 'headshot' in reason.casefold().replace('_','').replace(' ','')
            match_killfeed.append({'killer':actor(killer or finisher),'victim':actor(victim),'weapon':weapon,'weapon_code':weapon_code,'distance':distance,'headshot':headshot,'time':event.get('_D'),'elapsed_seconds':round(timestamp(event.get('_D'))-start,1) if start is not None and timestamp(event.get('_D')) is not None else None,'my_kill':same(killer),'my_death':same(victim)})
            if same(killer) and not same(victim):
                kills.append({'victim':actor(victim),'weapon':weapon or '정보 없음','weapon_code':weapon_code,'headshot':headshot,'distance':distance,'time':event.get('_D'),'elapsed_seconds':round(timestamp(event.get('_D'))-start,1) if start is not None and timestamp(event.get('_D')) is not None else None})
            if same(victim):
                source = killer if killer else finisher
                deaths.append({'killer':actor(source),'weapon':weapon or '정보 없음','weapon_code':weapon_code,'headshot':headshot,'distance':distance,'time':event.get('_D'),'suicide':bool(event.get('isSuicide')),'elapsed_seconds':round(timestamp(event.get('_D'))-start,1) if start is not None and timestamp(event.get('_D')) is not None else None})
        result = {'match_id':match_id,'nickname':player['nickname'],'platform':platform,'kills':kills,'deaths':deaths,'events_checked':len(events),'match_killfeed':match_killfeed,'style_features':combat_features(events,player['account_id'])}
        cache_set(cache_key,result,3600)
        return result
    return endpoint(run)


# Find official PUBG assets regardless of whether the user extracted the archive
# into static/api-assets-master or static/weapon-icons. Only PNG/WebP files under static.
@app.get('/api/weapon-icon/<code>')
def weapon_icon(code):
    if not re.fullmatch(r'[A-Za-z0-9_-]{2,90}',code):
        return ('',404)
    root=ROOT/'static'
    if not root.exists(): return ('',404)
    clean=code.removeprefix('Weap').removesuffix('_C')
    clean={'M416':'HK416','AK47':'AK47','BerylM762':'BerylM762','SCAR_L':'SCAR-L','UMP':'UMP','Crossbow_1':'Crossbow'}.get(clean,clean)
    variants={code.lower(),clean.lower(),'item_weapon_'+clean.lower()+'_c','item_weapon_'+clean.lower(),'weap'+clean.lower()+'_c'}
    # Restrict scan to likely weapon asset folders; never serve unrelated files.
    folders=[root/'weapon-icons',root/'icons',root/'api-assets-master'/'Assets'/'Icons'/'Item'/'Weapon',root/'static'/'weapon-icons',root/'static'/'icons']
    for folder in folders:
        if not folder.is_dir(): continue
        for path in folder.rglob('*'):
            if path.is_file() and path.suffix.lower() in ('.png','.webp') and path.stem.lower() in variants:
                return send_file(path)
    return ('',404)


PLAYSTYLE_VERSION = 'combat-v2'
# Long telemetry work must not keep a hosting HTTP worker waiting for 20 files.
STYLE_WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix='gamegg-style')
STYLE_PROGRESS = threading.local()
STYLE_JOB_PREFIX = 'style-job:v1:'


def style_job_write(key, token, payload):
    """Compare the job token so an interrupted worker cannot overwrite its retry."""
    with LOCK, db_conn() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM cache WHERE key=?', (key,)).fetchone()
        if not row or json.loads(row[0]).get('token') != token: return
        state = json.loads(row[0])
        state.update(payload, updated_at=time.time())
        ttl = 180 if state.get('state') == 'ready' else 20 if state.get('state') == 'failed' else 1800
        db.execute('UPDATE cache SET value=?,expires=? WHERE key=?', (json.dumps(state,ensure_ascii=False),time.time()+ttl,key))


def run_style_job(key, token, params):
    try:
        STYLE_PROGRESS.callback = lambda done,total: style_job_write(key,token,{'completed':done,'total':total})
        # No browser session or Flask request object crosses thread boundaries.
        with app.test_request_context('/api/playstyle', query_string=params):
            response = playstyle()
            result = response[0].get_json() if isinstance(response,tuple) else response.get_json()
        style_job_write(key,token,{'state':'ready' if result.get('ok') else 'failed','result':result})
    except Exception:
        app.logger.exception('Playstyle background job failed')
        style_job_write(key,token,{'state':'failed','result':{'ok':False,'code':'STYLE_JOB_ERROR','error':'전투 성향 분석 중 서버 오류가 발생했습니다. 잠시 후 다시 검색해 주세요.'}})
    finally:
        STYLE_PROGRESS.callback = None


def request_style_job(nickname, platform, limit, selected_mode):
    import hashlib
    digest=hashlib.sha256(json.dumps([nickname.casefold(),platform,limit,selected_mode]).encode()).hexdigest()
    key=STYLE_JOB_PREFIX+digest
    now=time.time();token=secrets.token_hex(16);submit=False
    with LOCK, db_conn() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT value FROM cache WHERE key=? AND expires>?',(key,now)).fetchone()
        state=json.loads(row[0]) if row else None
        # Heartbeat is updated after every bounded upstream request. Recover a
        # job interrupted by deployment/restart, including across Gunicorn workers.
        if state and state.get('state')=='pending' and now-state.get('updated_at',0)>150:state=None
        if state is None:
            rows=db.execute('SELECT value FROM cache WHERE key LIKE ? AND expires>?',(STYLE_JOB_PREFIX+'%',now)).fetchall()
            active=sum(1 for r in rows if (s:=json.loads(r[0])).get('state')=='pending' and now-s.get('updated_at',0)<=150)
            if active>=1:raise PUBGError('다른 전투 성향을 분석 중입니다. 잠시 후 다시 시도해 주세요.','STYLE_BUSY',retry_after=10)
            state={'token':token,'state':'pending','created_at':now,'updated_at':now,'completed':0,'total':limit}
            db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)',(key,json.dumps(state),now+1800))
            submit=True
    if submit:
        try:STYLE_WORKER.submit(run_style_job,key,token,{'nickname':nickname,'platform':platform,'limit':limit,'mode':selected_mode})
        except RuntimeError:
            style_job_write(key,token,{'state':'failed','result':{'ok':False,'code':'STYLE_JOB_ERROR','error':'분석 작업을 시작하지 못했습니다. 잠시 후 다시 시도해 주세요.'}})
            raise PUBGError('분석 작업을 시작하지 못했습니다. 잠시 후 다시 시도해 주세요.','STYLE_JOB_ERROR')
    if state.get('state') in ('ready','failed'):
        result=state['result']
        if not result.get('ok'):raise PUBGError(result.get('error','분석에 실패했습니다.'),result.get('code','NO_STYLE_DATA'),result.get('upstream_status'),result.get('retry_after'))
        return {**result,'analysis_state':'ready'}
    return {'analysis_state':'pending','completed':state['completed'],'total':state['total'],'retry_after':3,
        'message':'최근 경기 텔레메트리를 분석 중입니다. 첫 조회는 시간이 걸릴 수 있습니다.'}


def combat_features(events, account_id):
    """Extract enemy combat only. Preserve kill-feed rendering independently."""
    from datetime import datetime
    import math
    def stamp(value):
        try: return datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
        except (TypeError,ValueError,OverflowError): return None
    def number(value):
        try:
            if isinstance(value,bool): return None
            result=float(value)
            return result if math.isfinite(result) and result>=0 else None
        except (TypeError,ValueError): return None
    def who(value):return value.get('accountId') if isinstance(value,dict) else None
    def enemy(a,b):
        if not who(a) or not who(b) or who(a)==who(b):return False
        at=a.get('teamId');bt=b.get('teamId')
        return at is None or bt is None or at!=bt
    starts=[stamp(e.get('_D')) for e in events if isinstance(e,dict) and e.get('_T')=='LogMatchStart']
    start=next((v for v in starts if v is not None),None)
    result={'version':PLAYSTYLE_VERSION,'complete':False,'reason':'경기 시작 시각 또는 플레이어 정보 부족',
        'early_damage':0.0,'early_damage_taken':0.0,'first7_damage':0.0,'first7_damage_taken':0.0,
        'later_damage':0.0,'later_damage_taken':0.0,'first_combat_seconds':None,
        'early_knocks':0,'early_kills':0,'early_successes':0,'first7_successes':0}
    if start is None:return result
    target_seen=False;invalid=False;ordered=[]
    for index,e in enumerate(events):
        if not isinstance(e,dict):continue
        if e.get('_T')=='LogMatchStart':
            target_seen=target_seen or any(who(c.get('character',c))==account_id for c in e.get('characters',[]) if isinstance(c,dict))
        actors=[e.get(k) for k in ('attacker','victim','killer','finisher','character','dBNOMaker')]
        relevant=any(who(a)==account_id for a in actors)
        target_seen=target_seen or relevant
        t=stamp(e.get('_D'))
        if relevant and e.get('_T') in ('LogPlayerTakeDamage','LogPlayerMakeGroggy','LogPlayerKill','LogPlayerKillV2') and t is None:invalid=True
        if t is not None and t>=start:ordered.append((t,index,e))
    downed={};seen_actions=set();early_targets=set();first7_targets=set();first=None
    for timestamp,index,e in sorted(ordered,key=lambda item:(item[0],item[1])):
        elapsed=timestamp-start;kind=e.get('_T');a=e.get('attacker') or {};v=e.get('victim') or {};vid=who(v)
        if kind=='LogPlayerRevive':downed.pop(vid,None);continue
        if kind=='LogPlayerRedeploy':downed.pop(who(e.get('character')),None);continue
        if kind=='LogPlayerTakeDamage':
            if not enemy(a,v):continue
            own=who(a)==account_id;received=vid==account_id
            if not(own or received):continue
            dmg=number(e.get('damage'))
            if dmg is None:invalid=True;continue
            if dmg<=0:continue
            # Damage after a knock is finishing damage, not fresh combat contribution.
            if vid in downed and timestamp>downed[vid]:continue
            first=elapsed if first is None else min(first,elapsed)
            if elapsed<=300:result['early_damage' if own else 'early_damage_taken']+=dmg
            else:result['later_damage' if own else 'later_damage_taken']+=dmg
            if elapsed<=420:result['first7_damage' if own else 'first7_damage_taken']+=dmg
        elif kind=='LogPlayerMakeGroggy':
            if vid:downed[vid]=timestamp
            if enemy(a,v) and (who(a)==account_id or vid==account_id):first=elapsed if first is None else min(first,elapsed)
            if who(a)==account_id and enemy(a,v):
                first=elapsed if first is None else min(first,elapsed)
                if elapsed<=420:first7_targets.add(vid)
                key=('knock',vid,e.get('dBNOId',e.get('attackId',timestamp)))
                if elapsed<=300 and key not in seen_actions:
                    result['early_knocks']+=1;early_targets.add(vid);seen_actions.add(key)
        elif kind in ('LogPlayerKill','LogPlayerKillV2'):
            killer=e.get('killer') or {}
            if enemy(killer,v) and (who(killer)==account_id or vid==account_id):first=elapsed if first is None else min(first,elapsed)
            if who(killer)==account_id and enemy(killer,v) and not e.get('isSuicide'):
                first=elapsed if first is None else min(first,elapsed)
                if elapsed<=420:first7_targets.add(vid)
                # Legacy/V2 duplicate credit and knock+finish of the same target do not stack bonuses.
                if elapsed<=300 and vid not in {x[1] for x in seen_actions if x[0]=='kill'}:
                    result['early_kills']+=1;early_targets.add(vid);seen_actions.add(('kill',vid))
    result['early_successes']=len(early_targets)
    result['first7_successes']=len(first7_targets)
    result['first_combat_seconds']=round(first,1) if first is not None else None
    result['complete']=bool(target_seen and not invalid)
    result['reason']='' if result['complete'] else '피해 이벤트 시각/수치 또는 플레이어 정보가 부족합니다.'
    for key in ('early_damage','early_damage_taken','first7_damage','first7_damage_taken','later_damage','later_damage_taken'):
        result[key]=round(result[key],2)
    return result


def score_combat(features, survival):
    """Project heuristic scores, not a calibrated skill rating."""
    import math
    if not features.get('complete') or features.get('version')!=PLAYSTYLE_VERSION:return None
    try:duration=float(survival)
    except (ValueError,TypeError):return None
    if not math.isfinite(duration) or duration<=0:return None
    def cap(value):return min(1.0,max(0.0,float(value)))
    damage=cap(features['early_damage']/400)
    first=features['first_combat_seconds']
    quick=cap(1-first/300) if first is not None else 0
    successes=cap(features['early_successes']/2)
    aggression=100*(.6*damage+.2*quick+.2*successes)
    passive=None;balanced=None
    if duration>=420:
        delay=cap(first/420) if first is not None else 1
        quiet=0 if features.get('first7_successes',0)>0 else 1-cap((features['first7_damage']+features['first7_damage_taken'])/200)
        passive=100*delay*quiet
        # Balance requires actual outgoing combat both before and after five minutes.
        early_presence=cap(features['early_damage']/100)
        later_presence=cap(features['later_damage']/400)
        survival_factor=cap(duration/900)
        moderation=1-abs(aggression-50)/50
        balanced=100*cap(moderation)*(.4*early_presence+.4*later_presence+.2*survival_factor) if early_presence>0 and later_presence>0 else 0
    return {'yeopo':round(aggression,2),'jonbeo':None if passive is None else round(passive,2),'balance':None if balanced is None else round(balanced,2)}


def playstyle_for(nickname, platform, limit=20):
    player=lookup(nickname,platform);matches=list(dict.fromkeys(player.get('match_ids') or []))[:min(20,limit)]
    if not matches:raise PUBGError('최근 경기 기록이 없습니다.','NO_MATCHES')
    samples=[];errors=0;failures={}
    def record_failure(code,message):
        failures.setdefault(code,{'code':code,'count':0,'message':message})['count']+=1
    def progress(done):
        callback=getattr(STYLE_PROGRESS,'callback',None)
        if callback:callback(done,len(matches))
    progress(0)
    for mid in matches:
        try:
            with app.test_request_context('/api/match-telemetry',query_string={'match_id':mid,'nickname':nickname,'platform':platform}):
                response=match_telemetry();result=response[0].get_json() if isinstance(response,tuple) else response.get_json()
            if not result.get('ok'):
                errors+=1;record_failure(result.get('code','TELEMETRY_ERROR'),result.get('error','텔레메트리 요청 실패'));continue
            features=result.get('style_features') or {}
            match=api_get(platform,'matches/'+quote(mid,safe=''),ttl=1800,authenticated=False)
            detail=parse_match(match,player['account_id'])
            scores=score_combat(features,detail.get('survival') if detail else None)
            if scores is None:
                errors+=1;record_failure('INCOMPLETE_STYLE_DATA',features.get('reason') or '플레이어의 생존 시간 또는 교전 자료가 부족합니다.');continue
            samples.append({'match_id':mid,'scores':scores,'early_damage':features['early_damage'],
                'first_combat_seconds':features['first_combat_seconds'],'early_knocks':features['early_knocks'],
                'early_kills':features['early_kills'],'survival':detail.get('survival')})
        except PUBGError as e:
            errors+=1;record_failure(e.code,str(e))
        except (ValueError,TypeError,KeyError):
            errors+=1;record_failure('BAD_STYLE_DATA','경기 또는 교전 데이터 형식을 해석하지 못했습니다.')
        finally:progress(len(samples)+errors)
    if not samples:
        reasons=' / '.join(f"{v['message']} ({v['count']}경기, {v['code']})" for v in failures.values())
        raise PUBGError('전투 성향을 분석하지 못했습니다. '+reasons,'NO_STYLE_DATA')
    axes=('yeopo','jonbeo','balance');counts={k:sum(s['scores'][k] is not None for s in samples) for k in axes}
    # Short matches contribute to aggression but not to passive/balanced classification.
    scores={k:round(15+85*(sum(s['scores'][k] for s in samples if s['scores'][k] is not None)/counts[k])/100,1) if counts[k] else 15.0 for k in axes}
    firsts=[s['first_combat_seconds'] for s in samples if s['first_combat_seconds'] is not None]
    return {'nickname':player['nickname'],'platform':platform,'algorithm_version':PLAYSTYLE_VERSION,
        'matches_analyzed':len(samples),'matches_requested':len(matches),'matches_failed':errors,'failure_reasons':list(failures.values()),
        'axis_matches':counts,'axis_available':{k:counts[k]>0 for k in axes},'base_score':15,'scores':scores,
        'early_damage_average':round(sum(s['early_damage'] for s in samples)/len(samples),1),
        'first_combat_average':round(sum(firsts)/len(firsts),1) if firsts else None,
        'early_kills_total':sum(s['early_kills'] for s in samples),'early_knocks_total':sum(s['early_knocks'] for s in samples),
        'match_samples':samples,
        'definition':'여포: 초반 5분 가한 피해 60%, 첫 교전 시점 20%, 기절·처치한 서로 다른 상대 20%. 존버: 7분 이상 생존한 경기의 첫 교전 지연과 적에게 가한·받은 피해 부족. 밸런스: 7분 이상 생존하며 초반과 5분 이후 모두 공격에 참여한 균형. 경기별 점수 평균에 기본점수 15 적용.',
        'thresholds':{'early_window_seconds':300,'passive_min_survival_seconds':420,'damage_full_score':400,'success_targets_full_score':2,'passive_damage_scale':200,'balanced_survival_scale':900}}

@app.get('/api/playstyle')
def playstyle():
    def run():
        nickname=request.args.get('nickname','').strip(); platform=request.args.get('platform','steam').lower()
        if platform not in SHARDS: raise PUBGError('잘못된 플랫폼입니다.','INVALID_INPUT')
        try: limit=min(20,max(1,int(request.args.get('limit','20'))))
        except ValueError: raise PUBGError('limit은 숫자여야 합니다.','INVALID_INPUT')
        selected_mode=request.args.get('mode','squad')
        if selected_mode not in MODES: raise PUBGError('모드를 확인해 주세요.','INVALID_INPUT')
        if not nickname or len(nickname)>80 or any(ord(c)<32 for c in nickname):raise PUBGError('닉네임을 확인해 주세요.','INVALID_INPUT')
        if request.args.get('async')=='1':return request_style_job(nickname,platform,limit,selected_mode)
        result=playstyle_for(nickname,platform,limit)
        # Cache peer samples only from users actually analyzed on this server.
        # Same-platform RP cohorts are based on the current ranked squad RP.
        p=lookup(nickname,platform); seasons=seasons_for(platform)
        cur=next((x for x in seasons if x['current']),None)
        selected_mode=request.args.get('mode','squad')
        if selected_mode not in MODES: raise PUBGError('모드를 확인해 주세요.','INVALID_INPUT')
        rp=None
        if cur:
            ranked=safe_section(lambda:player_stats(platform,p['account_id'],cur['id'],True))
            stats=(ranked.get('data') or {}).get(selected_mode) if ranked['available'] else None
            if stats: rp=stats.get('currentRankPoint',stats.get('rankPoints'))
        result['rp']=rp
        result['peer_average']=None;result['peer_count']=0
        if rp is not None:
            rp=float(rp)
            key='style-sample:'+PLAYSTYLE_VERSION+':'+platform+':'+selected_mode+':'+p['account_id']
            cache_set(key,{'nickname':p['nickname'],'rp':rp,'scores':result['scores'],'platform':platform,'algorithm_version':PLAYSTYLE_VERSION,'axis_available':result['axis_available']},86400)
            with LOCK,db_conn() as db:
                rows=db.execute("SELECT value FROM cache WHERE key LIKE ? AND expires>?",('style-sample:'+PLAYSTYLE_VERSION+':'+platform+':'+selected_mode+':%',time.time())).fetchall()
            peers=[]
            for row in rows:
                try: sample=json.loads(row[0])
                except ValueError: continue
                if sample.get('algorithm_version')!=PLAYSTYLE_VERSION or not all(sample.get('axis_available',{}).values()):continue
                if sample.get('nickname','').casefold()==p['nickname'].casefold():continue
                if abs(float(sample.get('rp',-999999))-rp)<=500: peers.append(sample['scores'])
            result['peer_count']=len(peers)
            if len(peers)>=2:
                result['peer_average']={k:round(sum(x[k] for x in peers)/len(peers),1) for k in ('yeopo','jonbeo','balance')}
        return result
    return endpoint(run)



@app.get('/api/match-detail')
def match_detail():
    """Real participant/team standings for one of the searched player's recent matches."""
    def run():
        platform=request.args.get('platform','steam').lower()
        nickname=request.args.get('nickname','').strip()
        mid=request.args.get('match_id','').strip()
        if platform not in SHARDS or not re.fullmatch(r'[A-Za-z0-9_.-]{8,180}',mid):
            raise PUBGError('플랫폼 또는 경기 ID가 올바르지 않습니다.','INVALID_INPUT')
        player=lookup(nickname,platform)
        if mid not in (player.get('match_ids') or []):
            raise PUBGError('이 플레이어의 최근 경기 목록에 없는 경기입니다.','MATCH_NOT_FOUND',404)
        payload=api_get(platform,'matches/'+quote(mid,safe=''),ttl=1800,authenticated=False)
        included=payload.get('included') or []
        participants={}
        for item in included:
            if item.get('type')!='participant': continue
            s=(item.get('attributes') or {}).get('stats') or {}
            participants[item.get('id')]={'nickname':s.get('name') or '이름 미제공','account_id':s.get('playerId'),
                'kills':s.get('kills',0),'assists':s.get('assists',0),'damage':round(float(s.get('damageDealt') or 0),1),
                'dbnos':s.get('DBNOs',0),'headshots':s.get('headshotKills',0),'survival':round(float(s.get('timeSurvived') or 0)),
                'distance':round(sum(float(s.get(k) or 0) for k in ('walkDistance','rideDistance','swimDistance'))/1000,2),
                'longest_kill':round(float(s.get('longestKill') or 0),1),'win_place':s.get('winPlace'),
                'weapons':s.get('weaponsAcquired',0)}
        teams=[];assigned=set()
        for item in included:
            if item.get('type')!='roster': continue
            ids=[p.get('id') for p in (((item.get('relationships') or {}).get('participants') or {}).get('data') or [])]
            members=[participants[i] for i in ids if i in participants]
            if not members:continue
            assigned.update(ids)
            rank=((item.get('attributes') or {}).get('stats') or {}).get('rank')
            teams.append({'rank':rank,'members':members,'kills':sum(int(m['kills'] or 0) for m in members),
                          'damage':round(sum(float(m['damage'] or 0) for m in members),1),
                          'is_my_team':any(m['account_id']==player['account_id'] for m in members)})
        for pid,m in participants.items():
            if pid not in assigned: teams.append({'rank':m['win_place'],'members':[m],'kills':m['kills'],'damage':m['damage'],'is_my_team':m['account_id']==player['account_id']})
        teams.sort(key=lambda t:(t['rank'] is None,int(t['rank']) if str(t['rank']).isdigit() else 9999))
        return {'match_id':mid,'platform':platform,'player':player['nickname'],
                'map':((payload.get('data') or {}).get('attributes') or {}).get('mapName'),
                'mode':((payload.get('data') or {}).get('attributes') or {}).get('gameMode'),
                'teams':teams,'participants':len(participants),'team_count':len(teams)}
    return endpoint(run)




# Community membership and recruiting lifecycle.
BOARD_KINDS = ('notice', 'duo', 'squad')
RECRUIT_SECONDS = 30 * 60


# Keep PUBG API cache in SQLite; persist community data in Neon PostgreSQL.
import psycopg
from gamegg_postgres import board_conn


def is_admin():
    return admin_configured() and session.get('gamegg_admin') is True


def admin_csrf_ok():
    token = session.get('gamegg_csrf','')
    return bool(token) and hmac.compare_digest(str(request.headers.get('X-CSRF-Token','')), token)


def member():
    uid = session.get('gamegg_user_id')
    if not isinstance(uid, int): return None
    with board_conn() as db:
        row = db.execute('SELECT id,login_id,display_name FROM community_users WHERE id=?', (uid,)).fetchone()
    return dict(row) if row else None


def user_csrf():
    if not session.get('gamegg_user_csrf'): session['gamegg_user_csrf'] = secrets.token_urlsafe(32)
    return session['gamegg_user_csrf']


def require_write():
    origin = request.headers.get('Origin')
    if origin and urlsplit(origin).netloc.lower() != request.host.lower():
        raise PUBGError('다른 사이트에서 보낸 요청은 허용하지 않습니다.', 'INVALID_ORIGIN')
    token = session.get('gamegg_user_csrf','')
    if not token or not hmac.compare_digest(token, request.headers.get('X-User-CSRF-Token','')):
        raise PUBGError('로그인 상태를 다시 확인해 주세요. 새로고침 후 다시 시도해 주세요.', 'CSRF_ERROR')


def require_member():
    user = member()
    if not user: raise PUBGError('로그인 후 이용해 주세요.', 'LOGIN_REQUIRED')
    return user


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict): raise PUBGError('입력 내용을 확인해 주세요.', 'INVALID_INPUT')
    return data


def can_manage(post, user):
    return is_admin() or bool(user and post['author_user_id'] == user['id'])


def post_dict(row, user):
    data = dict(row)
    data['completed'] = bool(data.get('completed'))
    data['can_manage'] = can_manage(data, user)
    data['is_owner'] = bool(user and data.get('author_user_id') == user['id'])
    return data


@app.get('/api/auth/status')
def auth_status():
    response = jsonify(ok=True, user=member(), csrf=user_csrf(), server_time=time.time())
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.post('/api/auth/register')
def auth_register():
    def run():
        require_write(); data=json_body()
        login=str(data.get('login_id','')).strip().lower()
        name=str(data.get('display_name','')).strip()
        password=data.get('password')
        if not re.fullmatch(r'[a-z0-9_]{4,24}',login): raise PUBGError('아이디는 영문 소문자·숫자·밑줄 4~24자로 입력해 주세요.', 'INVALID_INPUT')
        if not 2<=len(name)<=24 or any(ord(c)<32 for c in name): raise PUBGError('표시 닉네임은 2~24자로 입력해 주세요.', 'INVALID_INPUT')
        if not isinstance(password,str) or not 8<=len(password)<=128: raise PUBGError('비밀번호는 8~128자로 입력해 주세요.', 'INVALID_INPUT')
        password_hash=generate_password_hash(password)
        try:
            with board_conn() as db:
                cur=db.execute('INSERT INTO community_users(login_id,display_name,password_hash,created_at) VALUES(?,?,?,?)',(login,name,password_hash,int(time.time())))
                uid=cur.lastrowid
        except psycopg.errors.UniqueViolation: raise PUBGError('이미 사용 중인 아이디입니다.', 'DUPLICATE_ACCOUNT')
        session['gamegg_user_id']=uid;session['gamegg_user_csrf']=secrets.token_urlsafe(32)
        return {'user':member(),'csrf':user_csrf()}
    return endpoint(run)


@app.post('/api/auth/login')
def auth_login():
    def run():
        require_write();data=json_body()
        login=str(data.get('login_id','')).strip().lower();password=data.get('password')
        if not re.fullmatch(r'[a-z0-9_]{4,24}',login) or not isinstance(password,str) or not 1<=len(password)<=128:
            raise PUBGError('아이디 또는 비밀번호가 올바르지 않습니다.', 'LOGIN_FAILED')
        import hashlib
        key=hashlib.sha256(((request.remote_addr or '')+':'+login).encode()).hexdigest()
        now=int(time.time())
        with board_conn() as db:
            attempt=db.execute('SELECT failures,window_start FROM community_auth_attempts WHERE key=?',(key,)).fetchone()
            if attempt and attempt['failures']>=5 and now-attempt['window_start']<900:
                raise PUBGError('로그인 시도 횟수를 초과했습니다. 15분 후 다시 시도해 주세요.', 'LOGIN_LIMIT')
            row=db.execute('SELECT * FROM community_users WHERE login_id=?',(login,)).fetchone()
        valid=check_password_hash(row['password_hash'] if row else AUTH_DUMMY_HASH,password)
        if not row or not valid:
            with board_conn() as db:
                db.execute('''INSERT INTO community_auth_attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET
                    failures=CASE WHEN ?-window_start>=900 THEN 1 ELSE failures+1 END,
                    window_start=CASE WHEN ?-window_start>=900 THEN ? ELSE window_start END''',(key,now,now,now,now))
            raise PUBGError('아이디 또는 비밀번호가 올바르지 않습니다.', 'LOGIN_FAILED')
        with board_conn() as db: db.execute('DELETE FROM community_auth_attempts WHERE key=?',(key,))
        session['gamegg_user_id']=row['id'];session['gamegg_user_csrf']=secrets.token_urlsafe(32)
        return {'user':member(),'csrf':user_csrf()}
    return endpoint(run)


@app.post('/api/auth/logout')
def auth_logout():
    def run():
        require_write();session.pop('gamegg_user_id',None);session['gamegg_user_csrf']=secrets.token_urlsafe(32)
        return {'user':None,'csrf':user_csrf()}
    return endpoint(run)


@app.get('/api/admin/status')
def admin_status():
    return jsonify(ok=True,admin=is_admin(),configured=False,csrf=session.get('gamegg_csrf') if is_admin() else None)


@app.post('/api/admin/logout')
def admin_logout():
    if not is_admin() or not admin_csrf_ok(): return jsonify(ok=False,error='권한이 없습니다.'),403
    session.pop('gamegg_admin',None);session.pop('gamegg_csrf',None)
    return jsonify(ok=True)


@app.delete('/api/admin/posts/<int:post_id>')
def admin_delete_post(post_id):
    if not is_admin() or not admin_csrf_ok(): return jsonify(ok=False,error='관리자 인증이 필요합니다.'),403
    with board_conn() as db:
        db.execute('DELETE FROM community_comments WHERE post_id=?',(post_id,))
        cur=db.execute('DELETE FROM community_posts WHERE id=?',(post_id,))
    return jsonify(ok=True,deleted=bool(cur.rowcount))


@app.get('/api/board')
def board_list():
    def run():
        category=request.args.get('category','duo')
        if category not in BOARD_KINDS: raise PUBGError('게시판 종류가 올바르지 않습니다.','INVALID_INPUT')
        user=member()
        with board_conn() as db:
            rows=db.execute('''SELECT p.*,(SELECT COUNT(*) FROM community_comments c WHERE c.post_id=p.id) AS comment_count
                FROM community_posts p WHERE p.category=? ORDER BY p.id DESC LIMIT 100''',(category,)).fetchall()
        return {'posts':[post_dict(r,user) for r in rows],'server_time':time.time()}
    return endpoint(run)


@app.post('/api/board')
def board_create():
    def run():
        require_write();d=json_body();user=member()
        category=str(d.get('category','')).strip();nickname=str(d.get('nickname','')).strip()
        platform=str(d.get('platform','')).strip().lower();title=str(d.get('title','')).strip();body=str(d.get('body','')).strip();mode=str(d.get('mode','squad')).strip()
        if category not in BOARD_KINDS: raise PUBGError('게시판 종류가 올바르지 않습니다.','INVALID_INPUT')
        if category=='notice':
            if not is_admin() or not admin_csrf_ok(): raise PUBGError('관리자 로그인이 필요합니다.','FORBIDDEN')
            nickname=ADMIN_NICKNAME;platform='steam';mode='squad';d['min_rp']=0
        elif user: nickname=user['display_name']
        elif not is_admin(): raise PUBGError('로그인 후 모집글을 작성해 주세요.','LOGIN_REQUIRED')
        if platform not in SHARDS or mode not in MODES or (category in ('duo','squad') and not mode.startswith(category)):
            raise PUBGError('게시판에 맞는 플랫폼과 모드를 선택해 주세요.','INVALID_INPUT')
        if not(2<=len(nickname)<=32 and 2<=len(title)<=80 and 5<=len(body)<=1500):raise PUBGError('닉네임·제목·본문 길이를 확인해 주세요.','INVALID_INPUT')
        try:rp=int(d.get('min_rp',0))
        except (TypeError,ValueError):raise PUBGError('최소 RP는 숫자여야 합니다.','INVALID_INPUT')
        if not 0<=rp<=15000:raise PUBGError('최소 RP는 0~15000 사이여야 합니다.','INVALID_INPUT')
        now=int(time.time())
        with board_conn() as db:
            if user:
                recent=db.execute('SELECT created_at FROM community_posts WHERE author_user_id=? ORDER BY id DESC LIMIT 1',(user['id'],)).fetchone()
                if recent and now - next(iter(recent.values())) < 10:raise PUBGError('글은 10초 간격으로 등록할 수 있습니다.','POST_COOLDOWN')
            cur=db.execute('''INSERT INTO community_posts(category,nickname,platform,title,body,min_rp,mode,created_at,author_user_id,expires_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',(category,nickname,platform,title,body,rp,mode,now,user['id'] if user else None,now+RECRUIT_SECONDS if category!='notice' else None))
            pid=cur.lastrowid
        return {'id':pid}
    return endpoint(run)


@app.delete('/api/board/<int:post_id>')
def member_delete_post(post_id):
    def run():
        require_write();user=require_member()
        with board_conn() as db:
            post=db.execute('SELECT * FROM community_posts WHERE id=?',(post_id,)).fetchone()
            if not post:raise PUBGError('게시글을 찾을 수 없습니다.','NOT_FOUND')
            if post['category']=='notice' or post['author_user_id']!=user['id']:raise PUBGError('본인의 모집글만 삭제할 수 있습니다.','FORBIDDEN')
            db.execute('DELETE FROM community_comments WHERE post_id=?',(post_id,));db.execute('DELETE FROM community_posts WHERE id=?',(post_id,))
        return {'deleted':True}
    return endpoint(run)


@app.post('/api/board/<int:post_id>/status')
def post_status(post_id):
    def run():
        require_write();user=member();d=json_body();action=d.get('action')
        if action not in ('complete','reopen','match'):raise PUBGError('모집 상태 요청을 확인해 주세요.','INVALID_INPUT')
        with board_conn() as db:
            db.execute('BEGIN IMMEDIATE')
            post=db.execute('SELECT * FROM community_posts WHERE id=?',(post_id,)).fetchone()
            if not post:raise PUBGError('게시글을 찾을 수 없습니다.','NOT_FOUND')
            if post['category']=='notice':raise PUBGError('공지사항에는 모집 상태가 없습니다.','INVALID_INPUT')
            if not can_manage(post,user):raise PUBGError('작성자 또는 관리자만 모집 상태를 바꿀 수 있습니다.','FORBIDDEN')
            now=int(time.time())
            if action=='reopen':
                db.execute("UPDATE community_posts SET completed=0,completed_at=NULL,completion_reason=NULL,matched_comment_id=NULL,matched_nickname=NULL,expires_at=? WHERE id=?",(now+RECRUIT_SECONDS,post_id))
            elif action=='match':
                if post['completed'] or post['expires_at']<=now:raise PUBGError('이미 종료된 모집입니다.','POST_COMPLETED')
                cid=d.get('comment_id')
                if not isinstance(cid,int) or isinstance(cid,bool):raise PUBGError('댓글을 선택해 주세요.','INVALID_INPUT')
                comment=db.execute('SELECT * FROM community_comments WHERE id=? AND post_id=?',(cid,post_id)).fetchone()
                if not comment:raise PUBGError('이 게시글의 댓글이 아닙니다.','NOT_FOUND')
                if comment['user_id']==post['author_user_id']:raise PUBGError('본인의 댓글은 매칭 대상으로 선택할 수 없습니다.','INVALID_INPUT')
                db.execute("UPDATE community_posts SET completed=1,completed_at=?,completion_reason='matched',matched_comment_id=?,matched_nickname=? WHERE id=?",(now,cid,comment['nickname'],post_id))
            else:db.execute("UPDATE community_posts SET completed=1,completed_at=?,completion_reason='manual' WHERE id=?",(now,post_id))
            row=db.execute('SELECT * FROM community_posts WHERE id=?',(post_id,)).fetchone()
        return {'post':post_dict(row,user),'server_time':time.time()}
    return endpoint(run)


@app.get('/api/board/<int:post_id>/comments')
def comment_list(post_id):
    def run():
        user=member()
        with board_conn() as db:
            post=db.execute('SELECT * FROM community_posts WHERE id=?',(post_id,)).fetchone()
            if not post:raise PUBGError('게시글을 찾을 수 없습니다.','NOT_FOUND')
            rows=db.execute('SELECT * FROM community_comments WHERE post_id=? ORDER BY id ASC LIMIT 200',(post_id,)).fetchall()
        comments=[]
        for row in rows:
            data=dict(row);data['can_delete']=is_admin() or bool(user and row['user_id']==user['id'])
            data['can_match']=post['category']!='notice' and not post['completed'] and can_manage(post,user) and row['user_id']!=post['author_user_id']
            comments.append(data)
        return {'post':post_dict(post,user),'comments':comments,'server_time':time.time()}
    return endpoint(run)


@app.post('/api/board/<int:post_id>/comments')
def comment_create(post_id):
    def run():
        require_write();user=require_member();body=str(json_body().get('body','')).strip()
        if not 1<=len(body)<=500:raise PUBGError('댓글은 1~500자로 입력해 주세요.','INVALID_INPUT')
        now=int(time.time())
        with board_conn() as db:
            db.execute('BEGIN IMMEDIATE')
            post=db.execute('SELECT * FROM community_posts WHERE id=?',(post_id,)).fetchone()
            if not post:raise PUBGError('게시글을 찾을 수 없습니다.','NOT_FOUND')
            if post['category']!='notice' and (post['completed'] or post['expires_at']<=now):raise PUBGError('모집이 완료되어 댓글을 작성할 수 없습니다.','POST_COMPLETED')
            recent=db.execute('SELECT created_at FROM community_comments WHERE user_id=? ORDER BY id DESC LIMIT 1',(user['id'],)).fetchone()
            if recent and now - recent['created_at'] < 5:
                raise PUBGError('댓글은 5초 간격으로 등록할 수 있습니다.', 'COMMENT_COOLDOWN')
            comment_count = db.execute(
                'SELECT COUNT(*) AS comment_count FROM community_comments WHERE post_id=?',
                (post_id,)
            ).fetchone()
            if comment_count['comment_count'] >= 200:
                raise PUBGError('이 글의 댓글 등록 한도에 도달했습니다.', 'COMMENT_LIMIT')
            cur=db.execute('INSERT INTO community_comments(post_id,user_id,nickname,body,created_at) VALUES(?,?,?,?,?)',(post_id,user['id'],user['display_name'],body,now));cid=cur.lastrowid
        return {'id':cid}
    return endpoint(run)


@app.delete('/api/board/comments/<int:comment_id>')
def comment_delete(comment_id):
    def run():
        require_write();user=member()
        with board_conn() as db:
            row=db.execute('SELECT * FROM community_comments WHERE id=?',(comment_id,)).fetchone()
            if not row:raise PUBGError('댓글을 찾을 수 없습니다.','NOT_FOUND')
            if not(is_admin() or (user and row['user_id']==user['id'])):raise PUBGError('본인 댓글만 삭제할 수 있습니다.','FORBIDDEN')
            db.execute('DELETE FROM community_comments WHERE id=?',(comment_id,))
        return {'deleted':True}
    return endpoint(run)


if __name__=='__main__':
    print_config_summary(CONFIG_REPORT)
    app.run(host='127.0.0.1',port=int(os.getenv('PORT','5000')),debug=False)
