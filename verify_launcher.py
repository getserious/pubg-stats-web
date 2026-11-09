"""Offline regression tests for the one-click launcher. No public tunnel is opened."""
import io
import json
import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
import run_all as m

class Child:
    def __init__(self): self.stopped=False;self.stdout=io.StringIO('')
    def poll(self): return 0 if self.stopped else None
    def terminate(self): self.stopped=True
    def wait(self,timeout): return 0
    def kill(self): self.stopped=True

class NoThread:
    def __init__(self,**kwargs): pass
    def start(self): pass

class LauncherTests(unittest.TestCase):
    def test_url_parser(self):
        self.assertEqual(m.quick_url('Visit https://my-game.trycloudflare.com'), 'https://my-game.trycloudflare.com')
        self.assertIsNone(m.quick_url('https://api.trycloudflare.com/tunnel'))
        self.assertIsNone(m.quick_url('https://example.com'))

    def test_public_health_requires_gamegg(self):
        with patch.object(m.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps({'ok':True,'service':'GAME.GG'}).encode())):
            self.assertTrue(m.public_health('https://x.trycloudflare.com')[0])
        with patch.object(m.urllib.request,'urlopen',return_value=io.BytesIO(b'{"ok":true,"service":"other"}')):
            self.assertFalse(m.public_health('https://x.trycloudflare.com')[0])
        with patch.object(m.urllib.request,'urlopen',side_effect=urllib.error.URLError(socket.gaierror(11001,'getaddrinfo failed'))):
            ok,reason=m.public_health('https://x.trycloudflare.com');self.assertFalse(ok);self.assertIn('DNS',reason)
        with patch.object(m.urllib.request,'urlopen',side_effect=urllib.error.HTTPError('url',502,'Bad Gateway',{},None)):
            self.assertFalse(m.public_health('https://x.trycloudflare.com')[0])

    def test_probe_retries_nxdomain_then_success(self):
        output=[]
        class Messages:
            def put(self,item): output.append(item)
        class Cancel:
            def is_set(self): return False
            def wait(self,n): pass
        with patch.object(m,'public_health',side_effect=[(False,'NXDOMAIN'),(True,'ready')]):
            m.probe_until_ready('https://x.trycloudflare.com',Messages(),7,Cancel())
        self.assertEqual([x[0] for x in output],['pending','ready'])
        self.assertEqual(output[-1],('ready',7,'https://x.trycloudflare.com'))

    def test_registration_and_public_health_before_open(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);server=Child();tunnel=Child();opened=[];steps=[]
            script=[('log',1,'Visit https://my-game.trycloudflare.com'),('ready',1,'https://my-game.trycloudflare.com'),('log',1,'INF Registered tunnel connection connIndex=0'),('pending',1,'NXDOMAIN'),('ready',99,'https://stale.trycloudflare.com'),('ready',1,'https://my-game.trycloudflare.com')]
            class Messages:
                def get(self,timeout):
                    if script:
                        # Before the successful current-generation probe, neither URL nor browser is advertised.
                        if len(script)>1:
                            self_outer.assertFalse((root/'public_url.txt').exists())
                            self_outer.assertEqual(opened,[])
                        return script.pop(0)
                    raise KeyboardInterrupt
                def put(self,x):pass
            self_outer=self
            def browser(url):
                self.assertEqual((root/'public_url.txt').read_text().strip(),url)
                opened.append(url)
            with patch.object(m,'ROOT',root),patch.object(m.subprocess,'Popen',return_value=tunnel),patch.object(m.queue,'Queue',Messages),patch.object(m.threading,'Thread',NoThread),patch.object(m.webbrowser,'open',side_effect=browser):
                with self.assertRaises(KeyboardInterrupt):m.supervise_tunnel('cloudflared',server,'http://127.0.0.1:5000')
            self.assertEqual(opened,['https://my-game.trycloudflare.com'])
            self.assertTrue(tunnel.stopped)
            self.assertFalse(server.stopped) # Supervisor only owns the tunnel.
            self.assertFalse((root/'public_url.txt').exists())

    def test_timeout_restarts_http2_without_stopping_local(self):
        with tempfile.TemporaryDirectory() as temp:
            server=Child();children=[];commands=[]
            def launch(args,**kwargs):
                commands.append(args);p=Child();children.append(p);return p
            class Messages:
                def get(self,timeout):raise KeyboardInterrupt
                def put(self,x):pass
            with patch.object(m,'ROOT',Path(temp)),patch.object(m.subprocess,'Popen',side_effect=launch),patch.object(m.queue,'Queue',Messages),patch.object(m.threading,'Thread',NoThread):
                with self.assertRaises(KeyboardInterrupt):m.supervise_tunnel('cloudflared',server,'http://127.0.0.1:5000',startup_timeout=-1,max_attempts=2)
            self.assertEqual(len(commands),2)
            self.assertIn('http2',commands[1])
            self.assertTrue(all(c.stopped for c in children))
            self.assertFalse(server.stopped)

    def test_run_local_first_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);server=Child();events=[]
            with patch.object(m,'ROOT',root),patch.object(m,'load_configuration',return_value={'root':str(root),'files':[],'configured':True,'source':'test'}),patch.dict(m.os.environ,{'PORT':'5000','GAMEGG_TUNNEL_NAME':''}),patch.object(m,'ensure_free_port'),patch.object(m,'find_cloudflared',return_value='cloudflared'),patch.object(m.subprocess,'Popen',return_value=server),patch.object(m,'wait_for_server',side_effect=lambda *a:events.append('local-ready')),patch.object(m.webbrowser,'open',side_effect=lambda u:events.append(u)),patch.object(m,'supervise_tunnel',side_effect=KeyboardInterrupt):
                self.assertEqual(m.run(),0)
            self.assertEqual(events,['local-ready','http://127.0.0.1:5000'])
            self.assertTrue(server.stopped)

    def test_duplicate_port(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));sock.listen()
            with self.assertRaises(RuntimeError):m.ensure_free_port(sock.getsockname()[1])

    def test_download_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.object(m.sys,'platform','win32'),patch.object(m.shutil,'which',return_value=None),patch.object(m.platform,'machine',return_value='AMD64'),patch.object(m.urllib.request,'urlopen',return_value=io.BytesIO(b'MZ'+b'X'*1048576)):
                self.assertTrue(Path(m.find_cloudflared(root)).read_bytes().startswith(b'MZ'))
            (root/'cloudflared.exe').unlink()
            with patch.object(m.sys,'platform','win32'),patch.object(m.shutil,'which',return_value=None),patch.object(m.urllib.request,'urlopen',return_value=io.BytesIO(b'HTML error')):
                with self.assertRaises(RuntimeError):m.find_cloudflared(root)
            self.assertFalse((root/'cloudflared.exe.part').exists())
            self.assertFalse((root/'cloudflared.exe').exists())

if __name__=='__main__': unittest.main()
