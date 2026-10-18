"""Install the optional AC Python app, preserving existing files and settings."""
import argparse
import json
from datetime import datetime
from pathlib import Path
import re
import shutil

ROOT=Path(__file__).resolve().parent


def enable_app(text):
    newline='\r\n' if '\r\n' in text else '\n'
    section=re.search(r'^\[APEXBRIDGE\][^\r\n]*\r?\n(?P<body>.*?)(?=^\[|\Z)',text,re.I|re.M|re.S)
    if not section:
        return text.rstrip()+newline+newline+'[APEXBRIDGE]'+newline+'ACTIVE=1'+newline
    body=section.group('body')
    if re.search(r'^\s*ACTIVE\s*=',body,re.I|re.M):
        body=re.sub(r'^(\s*ACTIVE\s*=\s*)[^\r\n]*',r'\g<1>1',body,flags=re.I|re.M)
    else:body='ACTIVE=1'+newline+body
    return text[:section.start('body')]+body+text[section.end('body'):]


def install(ac_path,config=None):
    game=Path(ac_path).resolve()
    if not (game/'AssettoCorsa.exe').is_file():raise ValueError('Select the folder containing AssettoCorsa.exe')
    destination=game/'apps'/'python'/'ApexBridge'
    source=ROOT/'ac-plugin'/'ApexBridge'/'ApexBridge.py'
    backup=ROOT/'data'/'backups'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    destination.mkdir(parents=True,exist_ok=True)
    installed=destination/'ApexBridge.py'
    if installed.exists() and installed.read_bytes()!=source.read_bytes():
        backup.mkdir(parents=True,exist_ok=True)
        shutil.copy2(installed,backup/'ApexBridge.py')
    shutil.copy2(source,installed)
    bridge_config=ROOT/'data'/'bridge.json'
    bridge_config.parent.mkdir(parents=True,exist_ok=True)
    bridge_config.write_text(json.dumps({'roster_file':str(destination/'roster.json')},indent=2),encoding='utf-8')
    if config:
        config=Path(config).resolve()
        raw=config.read_bytes() if config.exists() else b''
        text=raw.decode('utf-8-sig')
        updated=enable_app(text)
        if updated!=text:
            backup.mkdir(parents=True,exist_ok=True)
            if config.exists():shutil.copy2(config,backup/'python.ini')
            config.parent.mkdir(parents=True,exist_ok=True)
            config.write_bytes((b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'')+updated.encode('utf-8'))
    print('Installed bridge: '+str(installed))
    if config:print('Enabled ApexBridge in: '+str(config))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ac-path',required=True)
    parser.add_argument('--config',help='Optional path to Assetto Corsa/cfg/python.ini to enable the bridge')
    args=parser.parse_args()
    install(args.ac_path,args.config)
