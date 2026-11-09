"""Load project configuration, including Windows .env encodings, without logging secrets."""
from __future__ import annotations

import io
import os
from pathlib import Path
from urllib.parse import urlsplit
import re
from dotenv import dotenv_values

BUILD = 'GAMEGG-SEASON-ADMIN8'
PLACEHOLDERS = {'YOUR_PUBG_API_KEY', 'YOUR_API_KEY', 'PUT_YOUR_API_KEY_HERE', '본인의_API키'}


def normalize_admin_path(value):
    value=str(value or '').strip()
    if not value: return ''
    try:
        if '://' in value:
            parts=urlsplit(value)
            if parts.scheme.lower() not in ('http','https'): return ''
            path=parts.path
        elif '/' in value and re.fullmatch(r'(?:localhost|(?:[A-Za-z0-9-]+\.)+[A-Za-z0-9-]+)(?::[0-9]{1,5})?', value.split('/',1)[0], re.IGNORECASE):
            path=urlsplit('//'+value).path
        else:
            path=urlsplit(value).path
    except ValueError:
        return ''
    path=path.strip('/')
    return path if re.fullmatch(r'[A-Za-z0-9_-]{1,96}',path) else ''


def admin_configuration_status():
    missing=[name for name in ('GAMEGG_ADMIN_PASSWORD','GAMEGG_ADMIN_TOTP_SECRET','GAMEGG_SECRET_KEY') if not os.environ.get(name,'').strip()]
    raw=os.environ.get('GAMEGG_ADMIN_PATH','')
    if not raw.strip(): missing.append('GAMEGG_ADMIN_PATH')
    elif not normalize_admin_path(raw): missing.append('GAMEGG_ADMIN_PATH (invalid path)')
    return missing


def read_env(path):
    raw = path.read_bytes()
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16'), 'UTF-16'
    try:
        return raw.decode('utf-8-sig'), 'UTF-8 (BOM supported)'
    except UnicodeDecodeError:
        return raw.decode('cp949'), 'CP949'


def clean_key(value):
    key = str(value or '').strip().lstrip('\ufeff').strip()
    if key.lower().startswith('bearer '):
        key = key[7:].strip()
    return '' if key.upper() in PLACEHOLDERS or key in PLACEHOLDERS else key


def load_configuration(root):
    root = Path(root).resolve()
    env_before = clean_key(os.environ.get('PUBG_API_KEY'))
    report = {'root':str(root), 'files':[], 'source':None, 'configured':False, 'encoding':None}
    selected_key = ''
    for index, name in enumerate(('.env', '.env.txt')):
        path = root / name
        if not path.is_file():
            continue
        try:
            text, encoding = read_env(path)
            values = dotenv_values(stream=io.StringIO(text), interpolate=False)
        except (OSError, UnicodeError):
            report['files'].append({'name':name, 'readable':False})
            continue
        report['files'].append({'name':name, 'readable':True, 'encoding':encoding, 'has_api_key_field':'PUBG_API_KEY' in values})
        # Preserve existing settings, matching python-dotenv's normal precedence.
        # .env.txt is a key fallback, not a second source of admin configuration.
        if index == 0 or not (root / '.env').is_file():
            for field, value in values.items():
                if field != 'PUBG_API_KEY' and value is not None:
                    os.environ.setdefault(field, value)
        candidate = clean_key(values.get('PUBG_API_KEY'))
        if candidate and not selected_key:
            selected_key = candidate
            report['source'], report['encoding'] = name, encoding
    # An explicit project key wins over an inherited blank or stale system key.
    effective_key = selected_key or env_before
    if effective_key:
        os.environ['PUBG_API_KEY'] = effective_key
        if not report['source']:
            report['source'] = 'process environment'
    else:
        os.environ.pop('PUBG_API_KEY', None)
    report['configured'] = bool(effective_key)
    return report


def print_config_summary(report):
    print('[PROJECT] ' + report['root'], flush=True)
    print('[BUILD] ' + BUILD, flush=True)
    for item in report['files']:
        print('[ENV] ' + item['name'] + ': ' + (item.get('encoding', 'read error')), flush=True)
    print('[PUBG_API_KEY] ' + ('LOADED from ' + str(report['source']) if report['configured'] else 'NOT LOADED'), flush=True)
    if not report['configured']:
        print('[CONFIG] Run check_config.bat to inspect the active folder. Key values are never printed.', flush=True)
