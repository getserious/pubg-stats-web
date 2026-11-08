"""Run once to generate a private admin URL, app secret and TOTP setup URI."""
import base64, secrets, urllib.parse, getpass
from pathlib import Path
p=Path(__file__).with_name('.env')
if p.exists():
    print('Existing .env detected. Copy the printed settings into it; do not overwrite your PUBG key.')
password=getpass.getpass('Choose a strong admin password: ')
if len(password)<12: raise SystemExit('Use at least 12 characters.')
path=secrets.token_urlsafe(36).replace('-','_')
secret=base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
key=secrets.token_urlsafe(48)
print('\nAdd these lines to your existing .env (keep them private):')
print('GAMEGG_ADMIN_PASSWORD='+password)
print('GAMEGG_ADMIN_PATH='+path)
print('GAMEGG_ADMIN_TOTP_SECRET='+secret)
print('GAMEGG_SECRET_KEY='+key)
uri='otpauth://totp/'+urllib.parse.quote('GAME.GG:Admin')+'?'+urllib.parse.urlencode({'secret':secret,'issuer':'GAME.GG','digits':6,'period':30})
print('\nAdd this OTP account to Google Authenticator / Microsoft Authenticator using the setup key: '+secret)
print('OTP URI (private): '+uri)
print('\nPrivate login address: http://127.0.0.1:5000/'+path)
print('For a public deployment, use HTTPS and GAMEGG_HTTPS=1 in .env.')
