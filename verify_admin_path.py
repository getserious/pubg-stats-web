import unittest
from unittest.mock import patch
import app as m
from gamegg_config import normalize_admin_path

class AdminPathTests(unittest.TestCase):
    def test_slug_path_and_urls(self):
        for text in ('gameggadmin','/gameggadmin','/gameggadmin/','http://127.0.0.1:5000/gameggadmin','127.0.0.1:5000/gameggadmin','localhost:5000/gameggadmin','https://test.trycloudflare.com/gameggadmin'):
            self.assertEqual(normalize_admin_path(text),'gameggadmin',text)
        for text in ('','/admin/other','../gameggadmin','ftp://example.com/gameggadmin'):
            self.assertEqual(normalize_admin_path(text),'',text)
    def test_short_path_opens_but_auth_stays_required(self):
        with patch.object(m,'ADMIN_PATH','gameggadmin'),patch.object(m,'ADMIN_PASSWORD','fake-test-password'),patch.object(m,'ADMIN_TOTP_SECRET','JBSWY3DPEHPK3PXP'),patch.dict(m.os.environ,{'GAMEGG_SECRET_KEY':'fake-session-test-key'}):
            client=m.app.test_client()
            self.assertEqual(client.get('/gameggadmin').status_code,200)
            self.assertEqual(client.get('/gameggadmin/').status_code,200)
            self.assertEqual(client.get('/wrong-admin').status_code,404)
            with client.session_transaction() as session:csrf=session['admin_login_csrf']
            with patch.object(m,'totp_valid',return_value=False):
                self.assertEqual(client.post('/gameggadmin',data={'csrf':csrf,'password':'fake-test-password','otp':'000000'}).status_code,401)
            with patch.object(m,'totp_valid',return_value=True):
                self.assertEqual(client.post('/gameggadmin',data={'csrf':csrf,'password':'fake-test-password','otp':'123456'}).status_code,303)
            self.assertTrue(client.get('/api/admin/status').json['admin'])
    def test_missing_admin_auth_not_opened(self):
        with patch.object(m,'ADMIN_PATH','gameggadmin'),patch.object(m,'ADMIN_PASSWORD',''),patch.object(m,'ADMIN_TOTP_SECRET','JBSWY3DPEHPK3PXP'),patch.dict(m.os.environ,{'GAMEGG_SECRET_KEY':'fake-session-test-key'}):
            self.assertEqual(m.app.test_client().get('/gameggadmin').status_code,404)

if __name__=='__main__':unittest.main()
