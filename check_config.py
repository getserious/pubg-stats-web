"""Local-only configuration diagnostics. Never prints key values or fragments."""
import json
import os
import urllib.request
from pathlib import Path
from gamegg_config import BUILD, load_configuration, print_config_summary, admin_configuration_status

ROOT = Path(__file__).resolve().parent

def main():
    report = load_configuration(ROOT)
    print_config_summary(report)
    missing_admin=admin_configuration_status()
    print('[ADMIN] ' + ('READY: password + OTP enabled' if not missing_admin else 'MISSING / INVALID: ' + ', '.join(missing_admin)))
    if not report['files']:
        print('[CHECK] Neither .env nor .env.txt exists in the PROJECT folder printed above.')
    elif not report['configured']:
        print('[CHECK] No usable PUBG_API_KEY value was read. Check the exact field name and remove example placeholder text.')
    try:
        port = int(os.environ.get('PORT', '5000'))
        url = f'http://127.0.0.1:{port}/api/health'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=3) as response:
            running = json.load(response)
        if running.get('service') != 'GAME.GG':
            print('[SERVER] Another service is listening on this port.')
        elif running.get('build') != BUILD:
            print('[SERVER] OLD / DIFFERENT SERVER. Close the old server window and run start.bat in this PROJECT folder.')
        elif running.get('configured') != report['configured']:
            print('[SERVER] Configuration differs from this folder. Restart the server from this PROJECT folder.')
        else:
            print('[SERVER] Current build. API key loaded: ' + ('YES' if running.get('configured') else 'NO'))
    except Exception:
        print('[SERVER] No readable local health response. Start the server from this PROJECT folder.')
    print('[DONE] No API key values were printed. Keep the output when reporting a configuration issue.')

if __name__ == '__main__':
    main()
