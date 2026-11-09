"""Regression tests with fake keys only; diagnostics must never reveal them."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import gamegg_config as c
import check_config

class ConfigTests(unittest.TestCase):
    def load_fake(self,content,encoding='utf-8',inherited='',filename='.env'):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'PUBG_API_KEY':inherited},clear=True):
            root=Path(tmp);(root/filename).write_bytes(content.encode(encoding))
            report=c.load_configuration(root)
            return report,os.environ.get('PUBG_API_KEY')

    def test_windows_bom_and_encodings(self):
        for encoding in ('utf-8','utf-8-sig','utf-16','cp949'):
            with self.subTest(encoding=encoding):
                report,key=self.load_fake('PUBG_API_KEY=fake-test-key\nGAMEGG_ADMIN_NICKNAME=운영자\n',encoding)
                self.assertTrue(report['configured']);self.assertEqual(key,'fake-test-key')

    def test_file_wins_over_inherited(self):
        for inherited in ('','stale-key','YOUR_PUBG_API_KEY'):
            self.assertEqual(self.load_fake('PUBG_API_KEY=fake-project-key',inherited=inherited)[1],'fake-project-key')

    def test_env_only(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'PUBG_API_KEY':'fake-env-key'},clear=True):
            report=c.load_configuration(Path(tmp));self.assertTrue(report['configured']);self.assertEqual(report['source'],'process environment')

    def test_txt_fallback_and_precedence(self):
        self.assertEqual(self.load_fake('PUBG_API_KEY=fake-txt-key',filename='.env.txt')[1],'fake-txt-key')
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            root=Path(tmp);(root/'.env').write_text('PUBG_API_KEY=\nGAMEGG_ADMIN_PASSWORD=original\n');(root/'.env.txt').write_text('PUBG_API_KEY=fake-txt-key\nGAMEGG_ADMIN_PASSWORD=other\n')
            report=c.load_configuration(root);self.assertEqual(report['source'],'.env.txt');self.assertEqual(os.environ['GAMEGG_ADMIN_PASSWORD'],'original')
            (root/'.env').write_text('PUBG_API_KEY=fake-primary-key\n');report=c.load_configuration(root);self.assertEqual(os.environ['PUBG_API_KEY'],'fake-primary-key')

    def test_bearer_and_quotes(self):
        self.assertEqual(self.load_fake('PUBG_API_KEY="Bearer fake-quoted-key"')[1],'fake-quoted-key')

    def test_empty_placeholder(self):
        for value in ('','YOUR_PUBG_API_KEY','YOUR_API_KEY'):
            report,key=self.load_fake('PUBG_API_KEY='+value);self.assertFalse(report['configured']);self.assertIsNone(key)

    def test_diagnostics_do_not_leak_key(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            root=Path(tmp);(root/'.env').write_text('PUBG_API_KEY=DO_NOT_PRINT_THIS_FAKE_KEY\n')
            report=c.load_configuration(root);out=io.StringIO()
            with contextlib.redirect_stdout(out):c.print_config_summary(report)
            self.assertIn('LOADED',out.getvalue());self.assertNotIn('DO_NOT_PRINT',out.getvalue());self.assertNotIn('DO_NOT_PRINT',json.dumps(report))

    def test_old_server_detection(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            root=Path(tmp);(root/'.env').write_text('PUBG_API_KEY=fake-diag-key\n')
            opener=type('Opener',(),{'open':lambda *a,**kw:io.BytesIO(b'{"service":"GAME.GG","configured":false}')})()
            out=io.StringIO()
            with patch.object(check_config,'ROOT',root),patch.object(check_config.urllib.request,'build_opener',return_value=opener),contextlib.redirect_stdout(out):check_config.main()
            self.assertIn('OLD / DIFFERENT SERVER',out.getvalue());self.assertNotIn('fake-diag-key',out.getvalue())

if __name__=='__main__':unittest.main()
