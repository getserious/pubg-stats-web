import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app as m

class SeasonPlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old_db=m.DB;m.DB=Path(self.temp.name)/'cache.db';self.client=m.app.test_client()
        self.player={'nickname':'Tester','platform':'steam','account_id':'account.test','match_ids':[]}
        self.seasons=[{'id':f'division.bro.official.pc-2018-{n}','number':str(n),'current':n==44} for n in range(1,45)]
    def tearDown(self):m.DB=self.old_db;self.temp.cleanup()
    def query(self,extra):return self.client.get('/api/season-chart?platform=steam&nickname=Tester&mode=squad&'+extra).json
    def test_latest_first_for_6_12_and_all(self):
        for limit in (6,12,100):
            calls=[]
            def stats(platform,account,sid,ranked):
                calls.append(int(sid.rsplit('-',1)[-1]));return {'squad':{'roundsPlayed':10,'wins':2,'currentRankPoint':2500}}
            with patch.object(m,'lookup',return_value=self.player),patch.object(m,'seasons_for',return_value=self.seasons),patch.object(m,'player_stats',side_effect=stats):d=self.query(f'limit={limit}')
            self.assertTrue(d['ok']);self.assertEqual(calls,[44,43,42,41,40,39]);self.assertEqual(d['points'][-1]['season']['number'],'44');self.assertEqual(d['requested'],min(limit,44))
    def test_offset_and_rate_limit_resume(self):
        calls=[]
        def stats(platform,account,sid,ranked):
            n=int(sid.rsplit('-',1)[-1]);calls.append(n)
            if n==37:raise m.PUBGError('rate limited','RATE_LIMIT',429,'60')
            return {'squad':{'roundsPlayed':10,'wins':2,'currentRankPoint':n*100}}
        with patch.object(m,'lookup',return_value=self.player),patch.object(m,'seasons_for',return_value=self.seasons),patch.object(m,'player_stats',side_effect=stats):d=self.query('limit=12&offset=6')
        self.assertEqual(calls,[38,37]);self.assertTrue(d['rate_limited']);self.assertEqual(d['next_offset'],7);self.assertTrue(d['has_more']);self.assertTrue(any(p['available'] for p in d['points']));self.assertEqual(d['retry_after'],'60')
        self.assertEqual(d['points'][0]['code'],'RATE_LIMIT')
    def test_pre_ranked_seasons_do_not_use_requests(self):
        with patch.object(m,'lookup',return_value=self.player),patch.object(m,'seasons_for',return_value=self.seasons),patch.object(m,'player_stats') as stats:d=self.query('limit=100&offset=38')
        stats.assert_not_called();self.assertTrue(all(p['status']=='UNSUPPORTED' for p in d['points']))
    def test_full_pagination_and_connection_pause(self):
        with patch.object(m,'lookup',return_value=self.player),patch.object(m,'seasons_for',return_value=self.seasons),patch.object(m,'player_stats',return_value={'squad':{'roundsPlayed':10,'currentRankPoint':2500}}):
            for limit,total in ((12,12),(100,44)):
                offset=0;rows=[]
                while True:
                    d=self.query(f'limit={limit}&offset={offset}');rows.extend(d['points'])
                    if not d['has_more']:break
                    self.assertGreater(d['next_offset'],offset);offset=d['next_offset']
                self.assertEqual(len(rows),total);self.assertEqual(len({p['season']['id'] for p in rows}),total)
        with patch.object(m,'lookup',return_value=self.player),patch.object(m,'seasons_for',return_value=self.seasons),patch.object(m,'player_stats',side_effect=m.PUBGError('연결 실패','NETWORK_ERROR')) as calls:d=self.query('limit=100')
        self.assertEqual(calls.call_count,1);self.assertTrue(d['paused']);self.assertFalse(d['rate_limited']);self.assertEqual(d['pause_code'],'NETWORK_ERROR')

    def test_explicit_cross_platform_response_rejected(self):
        payload={'data':[{'id':'account.test','attributes':{'name':'Tester','shardId':'steam'},'relationships':{}}]}
        with self.assertRaises(m.PUBGError) as caught:m.account_from_payload(payload,'kakao')
        self.assertEqual(caught.exception.code,'PLATFORM_MISMATCH');self.assertIn('Kakao',str(caught.exception));self.assertIn('Steam',str(caught.exception))
        payload['data'][0]['attributes']['shardId']='pc-kakao';self.assertEqual(m.account_from_payload(payload,'kakao')['reported_platform'],'kakao')
    def test_wrong_platform_does_not_query_other_platform(self):
        calls=[]
        def api(platform,*args,**kw):calls.append(platform);return {'data':[]}
        with patch.object(m,'cache_get',return_value=None),patch.object(m,'api_get',side_effect=api):
            d=self.client.get('/api/profile?platform=kakao&nickname=Tester').json
        self.assertFalse(d['ok']);self.assertEqual(calls,['kakao'])
    def test_name_only_is_not_reported_as_record_success(self):
        player={**self.player,'platform':'kakao'}
        with patch.object(m,'lookup',return_value=player),patch.object(m,'seasons_for',return_value=self.seasons),patch.object(m,'player_stats',return_value={}):d=self.client.get('/api/profile?platform=kakao&nickname=Tester').json
        self.assertTrue(d['ok']);self.assertFalse(d['records_available']);self.assertEqual(d['record_status'],'NO_CURRENT_RECORDS');self.assertIn('Kakao',d['platform_message']);self.assertIn('전적을 확인할 수 없습니다',d['platform_message'])
    def test_profile_upstream_error_is_not_no_history(self):
        with patch.object(m,'lookup',return_value=self.player),patch.object(m,'seasons_for',return_value=self.seasons),patch.object(m,'player_stats',side_effect=m.PUBGError('제한','RATE_LIMIT',429)):
            d=self.client.get('/api/profile?platform=steam&nickname=Tester').json
        self.assertFalse(d['records_available']);self.assertEqual(d['record_status'],'QUERY_FAILED')
    def test_season_modes_stay_distinct(self):
        with patch.object(m,'lookup',return_value=self.player),patch.object(m,'seasons_for',return_value=self.seasons),patch.object(m,'player_stats',return_value={'duo':{'roundsPlayed':10,'currentRankPoint':2000}}):d=self.query('limit=6')
        self.assertTrue(all(p['status']=='NO_RECORD' and not p['available'] for p in d['points']))

if __name__=='__main__':unittest.main()
