from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from .db import Database, now_iso
from .processes import terminate_process

YOUTUBE_ID_RE = re.compile(r"\[([A-Za-z0-9_-]{11})\]")
REMOTE_FILENAME_BYTES = 120

class DeviceManager:
    """Windows MTP device manager with no ADB dependency."""
    def __init__(self, db: Database, root: Path):
        self.db = db
        self.root = Path(root)

    @staticmethod
    def _ps(script: str, env: dict | None = None, timeout: int = 30, cancel_check=None) -> str:
        if os.name != 'nt':
            raise RuntimeError('Device support is available on Windows only')
        merged = os.environ.copy()
        if env: merged.update({k: str(v) for k, v in env.items()})
        # Windows PowerShell otherwise encodes redirected errors in its OEM
        # code page, even when the successful script output uses UTF-8.
        script = ('[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\ntry {\n'
                  + script + '\n} catch { [Console]::Out.WriteLine($_.Exception.ToString()); exit 1 }')
        cp = subprocess.Popen(
            ['powershell.exe','-NoProfile','-NonInteractive','-STA','-ExecutionPolicy','Bypass','-Command',script],
            text=True, encoding='utf-8', errors='replace', stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=merged,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
        )
        deadline = time.monotonic() + timeout
        try:
            while True:
                if cancel_check:
                    cancel_check()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError('PowerShell MTP command timed out')
                try:
                    stdout, stderr = cp.communicate(timeout=min(0.25, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if cp.poll() is None:
                terminate_process(cp)
                cp.communicate()
        if cp.returncode != 0:
            # The wrapper writes its caught exception to UTF-8 stdout. Native
            # COM commands can also leave auxiliary/OEM text on stderr.
            raise RuntimeError((stdout or stderr or 'PowerShell MTP command failed').strip())
        return stdout.strip()

    def refresh(self) -> list[dict]:
        if os.name != 'nt':
            return []
        script = r'''
$ErrorActionPreference='SilentlyContinue'
$items = Get-PnpDevice -Class WPD -Status OK | Where-Object { $_.FriendlyName } | Select-Object FriendlyName,InstanceId
if($null -eq $items){ '[]'; exit 0 }
@($items) | ConvertTo-Json -Compress
'''
        raw = self._ps(script, timeout=20)
        try: rows = json.loads(raw or '[]')
        except Exception: rows = []
        if isinstance(rows, dict): rows = [rows]
        found=[]; seen=set()
        with self.db.tx() as con:
            con.execute("UPDATE devices SET state='offline'")
        for row in rows:
            name=str(row.get('FriendlyName') or '').strip()
            if not name or name.casefold() in seen: continue
            seen.add(name.casefold())
            serial=name
            item={'serial':serial,'manufacturer':'','model':name,'state':'device','free_bytes':None,'total_bytes':None,'last_seen_at':now_iso()}
            found.append(item)
            with self.db.tx() as con:
                con.execute('''INSERT INTO devices(serial,manufacturer,model,state,last_seen_at,free_bytes,total_bytes) VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(serial) DO UPDATE SET model=excluded.model,state=excluded.state,last_seen_at=excluded.last_seen_at''',
                    (serial,'',name,'device',item['last_seen_at'],None,None))
        return found

    def ensure_online(self, serial: str):
        devices=self.refresh()
        if not any(d['serial']==serial and d['state']=='device' for d in devices):
            raise RuntimeError(f'Device {serial} is not available through Windows MTP. Unlock the phone/tablet and select File transfer (MTP).')

    @staticmethod
    def _folder_parts(folder: str | None):
        value=(folder or '/sdcard/Movies/RomanianCartoons').replace('\\','/').strip('/')
        parts=[p for p in value.split('/') if p]
        if parts and parts[0].casefold() in {'sdcard','storage','emulated','0'}:
            parts=parts[1:]
        if parts[:2] == ['emulated','0']: parts=parts[2:]
        return parts or ['Movies','RomanianCartoons']

    def _folder_script(self, create: bool, action: str, missing_is_empty: bool = False) -> str:
        create_literal = '$true' if create else '$false'
        missing_action = "'[]'; exit 0" if missing_is_empty else "throw 'MTP folder not found: '+$part"
        return rf'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$deviceName=$env:CD_DEVICE
$parts=($env:CD_FOLDER_PARTS | ConvertFrom-Json)
$shell=New-Object -ComObject Shell.Application
$pc=$shell.Namespace(17)
$dev=@($pc.Items()) | Where-Object {{ $_.Name -eq $deviceName }} | Select-Object -First 1
if($null -eq $dev){{ $dev=@($pc.Items()) | Where-Object {{ $_.Name -like ('*'+$deviceName+'*') }} | Select-Object -First 1 }}
if($null -eq $dev){{ throw 'MTP device not found in This PC: '+$deviceName }}
$folder=$dev.GetFolder
$storage=@($folder.Items()) | Where-Object {{ $_.IsFolder -and ($_.Name -match 'Internal|shared|storage|Phone|Tablet') }} | Select-Object -First 1
if($null -eq $storage){{ $storage=@($folder.Items()) | Where-Object {{ $_.IsFolder }} | Select-Object -First 1 }}
if($null -eq $storage){{ throw 'Internal storage not found on MTP device' }}
$folder=$storage.GetFolder
foreach($part in $parts){{
  $item=@($folder.Items()) | Where-Object {{ $_.IsFolder -and $_.Name -eq $part }} | Select-Object -First 1
  if($null -eq $item -and {create_literal}){{ $folder.NewFolder($part); Start-Sleep -Milliseconds 400; $item=@($folder.Items()) | Where-Object {{ $_.IsFolder -and $_.Name -eq $part }} | Select-Object -First 1 }}
  if($null -eq $item){{ {missing_action} }}
  $folder=$item.GetFolder
}}
{action}
'''

    def scan_folder(self, serial: str, folder: str | None = None) -> dict:
        self.ensure_online(serial)
        parts=self._folder_parts(folder or self.db.settings()['device_folder'])
        action=r'''$names=@($folder.Items()) | ForEach-Object { $_.Name }; @($names) | ConvertTo-Json -Compress'''
        raw=self._ps(self._folder_script(False, action, missing_is_empty=True), {'CD_DEVICE':serial,'CD_FOLDER_PARTS':json.dumps(parts)}, timeout=30)
        try: files=json.loads(raw or '[]')
        except Exception: files=[]
        if isinstance(files,str): files=[files]
        ids=[]
        for name in files:
            m=YOUTUBE_ID_RE.search(str(name))
            if m: ids.append(m.group(1))
        return {'folder':'/'.join(parts),'files':files,'youtube_ids':ids}

    @staticmethod
    def safe_remote_filename(title: str, youtube_id: str, extension: str = '.mp4') -> str:
        if not re.fullmatch(r'\.[A-Za-z0-9]{1,10}', extension):
            raise ValueError('Invalid device file extension')
        clean=re.sub(r'[\\/:*?"<>|\x00-\x1f]',' ',title)
        clean=re.sub(r'\s+',' ',clean).strip(' .') or 'video'
        suffix = f' [{youtube_id}]{extension}'
        budget = REMOTE_FILENAME_BYTES - len(suffix.encode('utf-8'))
        if budget < len('video'):
            raise ValueError('Device filename suffix is too long')
        # A 140-character title produced 158-character filenames rejected by
        # the tested WPD provider. Bound the whole UTF-8 name, including the ID
        # and actual container extension, without splitting a Unicode character.
        clean = clean.encode('utf-8')[:budget].decode('utf-8', errors='ignore').rstrip(' .') or 'video'
        return clean + suffix

    def copy_file(self, serial: str, local_file: Path, filename: str, folder: str | None = None, cancel_check=None):
        local_file = Path(local_file).resolve()
        if not filename or filename != Path(filename).name or re.search(r'[\\/:*?"<>|\x00-\x1f]', filename):
            raise ValueError('Invalid device filename')
        expected_size = local_file.stat().st_size
        if expected_size <= 0:
            raise ValueError('Cannot send an empty file to a device')
        self.ensure_online(serial)
        parts=self._folder_parts(folder or self.db.settings()['device_folder'])
        action=r'''
$src=$env:CD_SOURCE
$name=$env:CD_FILENAME
Add-Type -Path $env:CD_COPY_HELPER
[MtpCopy]::CopyToFolder($src, $folder.Self, $name)
# PerformOperations has finished. Allow the Shell namespace metadata to refresh.
$deadline=(Get-Date).AddSeconds(30)
$actual=-1L
do {
  $hit=@($folder.Items()) | Where-Object { -not $_.IsFolder -and $_.Name -eq $name } | Select-Object -First 1
  if($null -ne $hit){
    $size=$hit.ExtendedProperty('System.Size')
    if($null -eq $size){ $size=$hit.Size }
    if($null -ne $size){ $actual=[long]$size }
  }
  if($actual -eq [long]$env:CD_EXPECTED_SIZE){ break }
  Start-Sleep -Milliseconds 700
} while((Get-Date) -lt $deadline)
if($actual -ne [long]$env:CD_EXPECTED_SIZE){ throw 'MTP file size verification failed' }
@{completed=$true; filename=$name; file_size=$actual} | ConvertTo-Json -Compress
'''
        out=self._ps(self._folder_script(True, action), {
            'CD_DEVICE':serial,'CD_FOLDER_PARTS':json.dumps(parts),
            'CD_SOURCE':str(local_file),'CD_FILENAME':filename,
            'CD_EXPECTED_SIZE':str(expected_size),
            'CD_COPY_HELPER':str(Path(__file__).with_name('mtp_copy.cs').resolve()),
        }, timeout=660, cancel_check=cancel_check)
        try:
            result = json.loads(out)
        except (ValueError, TypeError):
            raise RuntimeError('MTP copy returned no completion receipt') from None
        if (not isinstance(result, dict) or result.get('completed') is not True
                or result.get('filename') != filename or result.get('file_size') != expected_size):
            raise RuntimeError('MTP copy could not be verified')
        return {'remote_path': '/'.join(parts+[filename]), 'file_size': expected_size}
