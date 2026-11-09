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
from urllib.parse import quote

import requests
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
    return db


def cache_get(key):
    with LOCK, db_conn() as db:
        row = db.execute('SELECT value FROM cache WHERE key=? AND expires>?', (key, time.time())).fetchone()
    return json.loads(row[0]) if row else None


def cache_set(key, value, ttl):
    with LOCK, db_conn() as db:
        db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)', (key, json.dumps(value, ensure_ascii=False), time.time()+ttl))


def api_get(shard, path, *, params=None, ttl=0, authenticated=True):
    if shard not in API_SHARDS or not re.fullmatch(r'[A-Za-z0-9_./-]+', path):
        raise PUBGError('잘못된 요청 경로입니다.', 'INVALID_INPUT')
    key = 'api:' + shard + ':' + path + ':' + json.dumps(params or {}, sort_keys=True)
    if ttl:
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


def lookup(nickname, shard):
    if not nickname or len(nickname)>80 or any(ord(c)<32 for c in nickname):
        raise PUBGError('닉네임을 확인해 주세요.', 'INVALID_INPUT')
    if shard not in SHARDS:
        raise PUBGError('조회할 플랫폼을 정확히 선택해 주세요.', 'INVALID_INPUT')
    shards = (shard,)  # 다른 플랫폼으로 자동 검색하지 않음
    for s in shards:
        key = f'player:v2:{s}:{nickname.casefold()}'
        cached = cache_get(key)
        if cached is not None and cached.get('platform') == s and cached.get('nickname','').casefold() == nickname.casefold():
            return cached
        try:
            player = account_from_payload(api_get(s, 'players', params={'filter[playerNames]':nickname}, ttl=120), s)
            if player['platform'] != s or player['nickname'].casefold() != nickname.casefold():
                raise PUBGError('선택한 플랫폼에서 해당 닉네임이 조회되지 않습니다. 올바른 플랫폼으로 다시 검색해 주세요.', 'NOT_FOUND', 404)
            cache_set(key, player, 120)
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


def player_stats(shard, player_id, season_id, ranked=False):
    path = f'players/{quote(player_id,safe="")}/seasons/{quote(season_id,safe="")}'
    if ranked: path += '/ranked'
    payload = api_get(shard, path, ttl=600)
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


@app.get('/api/profile')
def profile():
    def run():
        p = query_player()
        all_seasons = seasons_for(p['platform'])
        current = next((s for s in all_seasons if s['current']),None)
        ranked=safe_section(lambda: player_stats(p['platform'],p['account_id'],current['id'],True)) if current else {'available':False,'data':None,'reason':'현재 시즌 없음'}
        normal=safe_section(lambda: player_stats(p['platform'],p['account_id'],current['id'])) if current else {'available':False,'data':None,'reason':'현재 시즌 없음'}
        for section in (ranked,normal):
            if section.get('code')=='PLATFORM_MISMATCH':
                raise PUBGError(section['reason'],'PLATFORM_MISMATCH',404)
        records=bool(p.get('match_ids')) or bool(has_rounds(ranked) or has_rounds(normal))
        failed=not ranked.get('available') or not normal.get('available')
        message='' if records else (f"{PLATFORM_NAMES[p['platform']]}에서 이 닉네임의 전적을 확인할 수 없습니다. 플랫폼과 시즌을 확인해 주세요. " + ('전적 조회 요청이 실패했습니다.' if failed else '현재 시즌 기록과 최근 경기 목록이 없습니다. 과거 시즌 기록은 별도로 확인할 수 있습니다.'))
        return {'player':{k:v for k,v in p.items() if k!='match_ids'},'current_season':current,'seasons':all_seasons,'ranked':ranked,'normal':normal,
                'records_available':records,'record_status':'AVAILABLE' if records else 'QUERY_FAILED' if failed else 'NO_CURRENT_RECORDS','platform_message':message}
    return endpoint(run)

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
        cache_key = 'killlog:v5:complete:' + platform + ':' + match_id + ':' + player['account_id']
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
        result = {'match_id':match_id,'nickname':player['nickname'],'platform':platform,'kills':kills,'deaths':deaths,'events_checked':len(events),'match_killfeed':match_killfeed}
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


def playstyle_for(nickname, platform, limit=20):
    player=lookup(nickname,platform)
    matches=(player.get('match_ids') or [])[:limit]
    if not matches: raise PUBGError('최근 경기 기록이 없습니다.','NO_MATCHES')
    from flask import current_app
    # Reuse the authenticated, validated telemetry endpoint and its cache.
    early=0; passive=0; observed=0; errors=0; early_kills_total=0
    for mid in matches:
        try:
            with app.test_request_context('/api/match-telemetry',query_string={'match_id':mid,'nickname':nickname,'platform':platform}):
                response=match_telemetry()
                result=response[0].get_json() if isinstance(response,tuple) else response.get_json()
            if not result.get('ok'): errors+=1;continue
            times=[x.get('elapsed_seconds') for x in result.get('kills',[]) if isinstance(x.get('elapsed_seconds'),(int,float))]
            if not times: 
                # Zero kills qualifies for passive only if match survived 7 min.
                pass
            match=api_get(platform,'matches/'+quote(mid,safe=''),ttl=1800,authenticated=False)
            detail=parse_match(match,player['account_id'])
            if not detail: errors+=1;continue
            duration=float(detail.get('survival') or 0)
            if not times and result.get('kills'):
                errors+=1;continue
            if result.get('kills') and len(times)!=len(result['kills']): errors+=1;continue
            first5=sum(1 for t in times if 0<=t<=300)
            early_kills_total+=first5
            if first5>=5: early+=1
            if duration>=420 and not any(t<=420 for t in times): passive+=1
            observed+=1
        except (PUBGError, ValueError, TypeError, KeyError): errors+=1
    if not observed: raise PUBGError('분석 가능한 텔레메트리 경기가 없습니다.','NO_STYLE_DATA')
    # 0..100 scores: per-match frequency; balance rewards having BOTH patterns.
    a=round(15+85*early/observed,1); b=round(15+85*passive/observed,1)
    balance=round(min(a,b),1)
    return {'nickname':player['nickname'],'platform':platform,'matches_analyzed':observed,'matches_requested':len(matches),'matches_failed':errors,
            'early_matches':early,'passive_matches':passive,'early_kills_total':early_kills_total,
            'scores':{'yeopo':a,'jonbeo':b,'balance':balance},'base_score':15,'definition':'기본점수 15점. 여포: 경기 시작 5분 이내 5킬 이상인 경기 비율; 존버: 7분 이상 생존하고 7분 내 0킬인 경기 비율; 밸런스: 두 비율 중 작은 값'}

@app.get('/api/playstyle')
def playstyle():
    def run():
        nickname=request.args.get('nickname','').strip(); platform=request.args.get('platform','steam').lower()
        if platform not in SHARDS: raise PUBGError('잘못된 플랫폼입니다.','INVALID_INPUT')
        try: limit=min(20,max(1,int(request.args.get('limit','20'))))
        except ValueError: raise PUBGError('limit은 숫자여야 합니다.','INVALID_INPUT')
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
            key='style-sample:'+platform+':'+selected_mode+':'+p['account_id']
            cache_set(key,{'nickname':p['nickname'],'rp':rp,'scores':result['scores'],'platform':platform},86400)
            with LOCK,db_conn() as db:
                rows=db.execute("SELECT value FROM cache WHERE key LIKE ? AND expires>?",('style-sample:'+platform+':'+selected_mode+':%',time.time())).fetchall()
            peers=[]
            for row in rows:
                try: sample=json.loads(row[0])
                except ValueError: continue
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




# GAME.GG community: server-side validation and persistent SQLite storage.
BOARD_KINDS = ('notice', 'duo', 'squad')
def board_conn():
    db=sqlite3.connect(DB,timeout=15)
    db.row_factory=sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS community_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
        nickname TEXT NOT NULL, platform TEXT NOT NULL, title TEXT NOT NULL,
        body TEXT NOT NULL, min_rp INTEGER, mode TEXT,
        created_at INTEGER NOT NULL)""")
    return db

def is_admin():
    return admin_configured() and session.get('gamegg_admin') is True

def admin_csrf_ok():
    token=session.get('gamegg_csrf','')
    return bool(token) and hmac.compare_digest(str(request.headers.get('X-CSRF-Token','')),token)

@app.get('/api/admin/status')
def admin_status():
    return jsonify(ok=True,admin=is_admin(),configured=False,csrf=session.get('gamegg_csrf') if is_admin() else None)

@app.post('/api/admin/logout')
def admin_logout():
    if not is_admin() or not admin_csrf_ok(): return jsonify(ok=False,error='권한이 없습니다.'),403
    session.clear()
    return jsonify(ok=True)

@app.delete('/api/admin/posts/<int:post_id>')
def admin_delete_post(post_id):
    if not is_admin() or not admin_csrf_ok(): return jsonify(ok=False,error='관리자 인증이 필요합니다.'),403
    with board_conn() as db:
        cur=db.execute('DELETE FROM community_posts WHERE id=?',(post_id,))
    return jsonify(ok=True,deleted=bool(cur.rowcount))

@app.get('/api/board')
def board_list():
    def run():
        category=request.args.get('category','duo')
        if category not in BOARD_KINDS: raise PUBGError('게시판 종류가 올바르지 않습니다.','INVALID_INPUT')
        with board_conn() as db:
            rows=db.execute('SELECT * FROM community_posts WHERE category=? ORDER BY id DESC LIMIT 100',(category,)).fetchall()
        return {'posts':[dict(r) for r in rows]}
    return endpoint(run)

@app.post('/api/board')
def board_create():
    def run():
        d=request.get_json(silent=True) or {}
        category=str(d.get('category','')).strip()
        nickname=str(d.get('nickname','')).strip()
        platform=str(d.get('platform','')).strip().lower()
        title=str(d.get('title','')).strip()
        body=str(d.get('body','')).strip()
        mode=str(d.get('mode','squad')).strip()
        if category not in BOARD_KINDS: raise PUBGError('게시판 종류가 올바르지 않습니다.','INVALID_INPUT')
        if category=='notice':
            if not is_admin() or not admin_csrf_ok(): return {'_forbidden': True}
            nickname=ADMIN_NICKNAME
            platform='steam'
            mode='squad'
            d['min_rp']=0
        if platform not in SHARDS or mode not in MODES: raise PUBGError('플랫폼/모드를 확인해 주세요.','INVALID_INPUT')
        if not (2<=len(nickname)<=32 and 2<=len(title)<=80 and 5<=len(body)<=1500):
            raise PUBGError('닉네임(2~32), 제목(2~80), 본문(5~1500자)을 확인해 주세요.','INVALID_INPUT')
        try: min_rp=int(d.get('min_rp',0))
        except (TypeError,ValueError): raise PUBGError('최소 RP는 숫자여야 합니다.','INVALID_INPUT')
        if not 0<=min_rp<=15000: raise PUBGError('최소 RP는 0~15000 사이여야 합니다.','INVALID_INPUT')
        # No identity verification: nicknames are self-declared, not authenticated.
        with board_conn() as db:
            cur=db.execute('INSERT INTO community_posts (category,nickname,platform,title,body,min_rp,mode,created_at) VALUES (?,?,?,?,?,?,?,?)',
                           (category,nickname,platform,title,body,min_rp,mode,int(time.time())))
            post_id=cur.lastrowid
        return {'id':post_id}
    if (request.get_json(silent=True) or {}).get('category')=='notice' and (not is_admin() or not admin_csrf_ok()):
        return jsonify(ok=False,error='관리자 로그인이 필요합니다.'),403
    return endpoint(run)

if __name__=='__main__':
    print_config_summary(CONFIG_REPORT)
    app.run(host='127.0.0.1',port=int(os.getenv('PORT','5000')),debug=False)
