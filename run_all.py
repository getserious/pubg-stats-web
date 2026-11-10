"""Run GAME.GG and Cloudflare together; shut down only our own children."""
from __future__ import annotations

import json
import os
import platform
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import webbrowser
from pathlib import Path

from gamegg_config import load_configuration, print_config_summary

ROOT = Path(__file__).resolve().parent
DOWNLOAD_ROOT = 'https://github.com/cloudflare/cloudflared/releases/latest/download/'
URL_PATTERN = re.compile(r'https://([a-z0-9-]+)\.trycloudflare\.com\b', re.I)


def find_cloudflared(root=ROOT):
    """Use the existing executable before downloading the official Windows build."""
    for name in ('cloudflared.exe', 'cloudflared-windows-amd64.exe', 'cloudflared-windows-386.exe'):
        candidate = root / name
        if candidate.is_file():
            return str(candidate)
    installed = shutil.which('cloudflared')
    if installed:
        return installed
    if sys.platform != 'win32':
        raise RuntimeError('Install cloudflared, then run this launcher again.')
    machine = platform.machine().lower()
    # Windows ARM64 supports the x64 build through emulation.
    arch = '386' if machine in ('x86', 'i386', 'i686') else 'amd64'
    target = root / 'cloudflared.exe'
    partial = root / 'cloudflared.exe.part'
    print('[SETUP] Downloading cloudflared from the official Cloudflare GitHub release...', flush=True)
    try:
        request = urllib.request.Request(DOWNLOAD_ROOT + f'cloudflared-windows-{arch}.exe', headers={'User-Agent': 'GAMEGG-launcher'})
        with urllib.request.urlopen(request, timeout=60) as response, partial.open('wb') as output:
            size = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > 150 * 1024 * 1024:
                    raise RuntimeError('The cloudflared download is unexpectedly large.')
                output.write(chunk)
        with partial.open('rb') as stream:
            if stream.read(2) != b'MZ':
                raise RuntimeError('The cloudflared download is not a Windows executable.')
        if size < 1024 * 1024:
            raise RuntimeError('The cloudflared download is incomplete.')
        partial.replace(target)
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError('Cloudflared download failed. Put cloudflared.exe beside start.bat and retry.') from exc
    return str(target)


def ensure_free_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError as exc:
            raise RuntimeError(f'Port {port} is already in use. Close the old GAME.GG server before restarting.') from exc


def wait_for_server(process, url, timeout=45):
    """Do not publish a tunnel until the child web server is responding."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('GAME.GG exited before startup completed. Check the server message above.')
        try:
            with opener.open(url + '/api/health', timeout=1) as response:
                data = json.load(response)
            if isinstance(data, dict) and data.get('ok') and data.get('service') == 'GAME.GG':
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    raise RuntimeError('GAME.GG did not become ready within 45 seconds.')


def quick_url(line):
    for found in URL_PATTERN.finditer(line):
        if found.group(1).lower() not in ('api', 'www', 'update'):
            return found.group(0)
    return None


def pump_output(process, messages, generation):
    try:
        for line in process.stdout:
            messages.put(('log', generation, line.rstrip('\r\n')))
    finally:
        messages.put(('ended', generation, None))


def public_health(url):
    """Confirm DNS, HTTPS, tunnel routing AND the actual GAME.GG response."""
    request = urllib.request.Request(url + '/api/health?ready=' + str(time.time_ns()), headers={'Cache-Control': 'no-cache'})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read(65536))
        if isinstance(data, dict) and data.get('ok') and data.get('service') == 'GAME.GG':
            return True, 'ready'
        return False, 'The public address is not returning GAME.GG yet.'
    except urllib.error.HTTPError as exc:
        return False, f'Public HTTP {exc.code}; waiting for the tunnel route.'
    except (OSError, ValueError) as exc:
        reason = str(getattr(exc, 'reason', exc))
        if any(word in reason.lower() for word in ('getaddrinfo', 'name or service', 'nodename', '11001', '11004')):
            return False, 'Public DNS is not resolving yet (NXDOMAIN / DNS pending).'
        return False, 'Public HTTPS is not reachable yet. Waiting for DNS / connection.'


def probe_until_ready(url, messages, generation, cancel):
    # Run outside the supervisor, because a system DNS lookup can block.
    while not cancel.is_set():
        ok, reason = public_health(url)
        if cancel.is_set():
            return
        messages.put(('ready' if ok else 'pending', generation, url if ok else reason))
        if ok:
            return
        cancel.wait(4)


def tunnel_command(executable, local_url, name='', retry=False):
    if name:
        return [executable, 'tunnel', 'run', name]
    command = [executable, 'tunnel', '--config', str(ROOT / 'cloudflare_quick.yml')]
    if retry:
        command += ['--protocol', 'http2']
    return command + ['--url', local_url]


def supervise_tunnel(executable, server, local_url, name='', startup_timeout=90, max_attempts=3):
    messages = queue.Queue()
    child = None
    cancel = threading.Event()
    url_file = ROOT / 'public_url.txt'
    try:
        for attempt in range(1, max_attempts + 1):
            url_file.unlink(missing_ok=True)
            cancel = threading.Event()
            child = subprocess.Popen(tunnel_command(executable, local_url, name, retry=attempt > 1), cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1)
            threading.Thread(target=pump_output, args=(child, messages, attempt), daemon=True).start()
            candidate = None
            registered = probing = published = warned = False
            deadline = time.monotonic() + startup_timeout
            last_notice = 0
            while True:
                if server.poll() is not None:
                    raise RuntimeError('The website stopped. Cloudflare will also be stopped.')
                if child.poll() is not None:
                    print('[RETRY] Cloudflare exited. The local website remains running.', flush=True)
                    break
                if not name and not published and time.monotonic() > deadline and not warned:
                    warned = True
                    if attempt < max_attempts:
                        print('[RETRY] Public connection is not ready. Requesting a new address using HTTP/2...', flush=True)
                        break
                    print('[NOTICE] Public DNS/HTTPS is still unavailable. Your local website is working: ' + local_url, flush=True)
                    print('[NOTICE] Keeping this tunnel running and checking. If NXDOMAIN persists, check the network DNS resolver.', flush=True)
                try:
                    kind, generation, value = messages.get(timeout=0.25)
                except queue.Empty:
                    continue
                if generation != attempt:
                    continue
                if kind == 'log':
                    print(value, flush=True)
                    found = quick_url(value)
                    if found and not candidate:
                        candidate = found
                        print('[WAIT] Address allocated. Waiting for tunnel registration, DNS and HTTPS before opening it.', flush=True)
                    if 'registered tunnel connection' in value.casefold():
                        registered = True
                        if name:
                            print('[GAME.GG] Named tunnel connected. Use your configured public hostname.', flush=True)
                    if candidate and registered and not probing and not name:
                        probing = True
                        threading.Thread(target=probe_until_ready, args=(candidate, messages, attempt, cancel), daemon=True).start()
                elif kind == 'pending':
                    if time.monotonic() - last_notice >= 12:
                        print('[WAIT] ' + value + ' Local website is available: ' + local_url, flush=True)
                        last_notice = time.monotonic()
                elif kind == 'ready' and value == candidate and registered and not published:
                    published = True
                    url_file.write_text(candidate + '\n', encoding='utf-8')
                    print('\n[PUBLIC READY] ' + candidate, flush=True)
                    print('[GAME.GG] Verified GAME.GG through the public address. Saved in public_url.txt.\n', flush=True)
                    webbrowser.open(candidate)
            cancel.set()
            stop_child(child)
            child = None
        # Preserve local use if all tunnel processes fail; never kill a healthy site.
        print('[NOTICE] Cloudflare could not stay connected. Use ' + local_url + ' for now. Press Ctrl+C to exit.', flush=True)
        while server.poll() is None:
            time.sleep(0.5)
        raise RuntimeError('The local website stopped.')
    finally:
        cancel.set()
        stop_child(child)
        url_file.unlink(missing_ok=True)


def stop_child(process):
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run():
    print_config_summary(load_configuration(ROOT))
    server = tunnel = None
    url_file = ROOT / 'public_url.txt'
    try:
        port = int(os.getenv('PORT', '5000'))
        if not 1 <= port <= 65535:
            raise ValueError('PORT must be between 1 and 65535.')
        ensure_free_port(port)
        executable = find_cloudflared()
        local_url = f'http://127.0.0.1:{port}'
        named_tunnel = os.getenv('GAMEGG_TUNNEL_NAME', '').strip()
        url_file.unlink(missing_ok=True)
        print(f'[GAME.GG] Starting the website: {local_url}', flush=True)
        server = subprocess.Popen([sys.executable, '-u', str(ROOT / 'app.py')], cwd=ROOT)
        wait_for_server(server, local_url)
        print('[GAME.GG] Local website ready: ' + local_url, flush=True)
        print('[GAME.GG] Keep this window open. Press Ctrl+C to stop BOTH services.', flush=True)
        webbrowser.open(local_url)
        print('[GAME.GG] Starting Cloudflare. The public page will open only after verification.', flush=True)
        supervise_tunnel(executable, server, local_url, named_tunnel)
    except KeyboardInterrupt:
        print('\n[GAME.GG] Stopping the website and Cloudflare...', flush=True)
        return 0
    except Exception as exc:
        print(f'\n[ERROR] {exc}', flush=True)
        return 1
    finally:
        try:
            stop_child(tunnel)
        finally:
            stop_child(server)
            url_file.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(run())
