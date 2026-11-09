import sys,tempfile,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import app as m
m.DB=Path(tempfile.mkdtemp())/'test.sqlite3'
c=m.app.test_client()
for p in ['/','/static/app.js','/static/style.css','/static/headshot.svg','/static/ranks/Bronze-1.png','/api/weapon-icon/WeapM416_C','/api/weapon-icon/WeapSCAR-L_C']:
 r=c.get(p);assert r.status_code==200,(p,r.status_code)
assert c.get('/api/profile?platform=bad&nickname=test').json['ok']==False
ids=['match-id-'+str(i).zfill(3) for i in range(20)]
player={'nickname':'Tester','platform':'steam','account_id':'account.test','match_ids':ids}
def match(mid):
 parts=[{'type':'participant','id':f'p{i}','attributes':{'stats':{'playerId':'account.test' if i==0 else f'account.{i}','name':'Tester' if i==0 else f'Other{i}','winPlace':i+1,'kills':1,'headshotKills':1,'longestKill':99,'timeSurvived':500}}} for i in range(100)]
 rosters=[{'type':'roster','id':f'r{i}','attributes':{'stats':{'rank':i+1}},'relationships':{'participants':{'data':[{'id':f'p{i}'}]}}} for i in range(100)]
 return {'data':{'id':mid,'attributes':{'gameMode':'solo','mapName':'Baltic_Main','createdAt':'2026-11-09T00:00:00Z'},'relationships':{'assets':{'data':[{'id':'a'}]}}},'included':parts+rosters+[{'type':'asset','id':'a','attributes':{'URL':'https://telemetry-cdn.pubg.com/test'}}]}
def api(shard,path,**kwargs):return match(path.split('/')[-1])
events=[{'_T':'LogMatchStart','_D':'2026-11-09T00:00:00Z'},{'_T':'LogPlayerKillV2','_D':'2026-11-09T00:01:00Z','killer':{'accountId':'account.test','name':'Tester'},'victim':{'name':'Other'},'killerDamageInfo':{'damageCauserName':'WeapM416_C','damageReason':'HeadShot','distance':12300}}]
class Response:
 def raise_for_status(self):pass
 def iter_content(self,chunk_size):yield json.dumps(events).encode()
with patch.object(m,'lookup',return_value=player),patch.object(m,'api_get',side_effect=api),patch.object(m.requests,'get',return_value=Response()):
 q='platform=steam&nickname=Tester'
 h=c.get('/api/history?'+q+'&limit=20').json;assert len(h['matches'])==20,h
 d=c.get('/api/match-detail?'+q+'&match_id='+ids[0]).json;assert d['participants']==100 and len(d['teams'])==100,d
 t=c.get('/api/match-telemetry?'+q+'&match_id='+ids[0]).json;assert t['kills'][0]['headshot'] and t['kills'][0]['distance']==123 and t['kills'][0]['elapsed_seconds']==60,t
 assert not c.get('/api/match-detail?'+q+'&match_id=not-my-match').json['ok']
 s=m.playstyle_for('Tester','steam');assert s['matches_analyzed']==20 and min(s['scores'].values())>=15,s
season=[{'id':'division.bro.official.pc-2018-43','number':'43','current':True},{'id':'division.bro.official.pc-2018-42','number':'42','current':False}]
with patch.object(m,'lookup',return_value=player),patch.object(m,'seasons_for',return_value=season),patch.object(m,'player_stats',return_value={'squad':{'wins':3,'roundsPlayed':10,'currentRankPoint':2500,'currentTier':{'tier':'Gold','subTier':'2'}}}):
 d=c.get('/api/season-chart?platform=steam&nickname=Tester&mode=solo&limit=100').json;assert all(p['stats'] is None for p in d['points'])
 d=c.get('/api/season-chart?platform=steam&nickname=Tester&mode=squad&limit=100').json;assert [p['season']['number'] for p in d['points']]==['42','43']
print('PASS: homepage/assets, invalid input, 20 matches, 100 participants, headshot/weapon/time/distance, membership check, 20-match style and mode/season separation')
