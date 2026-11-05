"""Create a copyable offline release from the already-built executable directory."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

root = Path(__file__).resolve().parents[1]
dist = root/'dist/PolaMV Studio'
required = ['PolaMV Studio.exe', '_internal/vendor/Runtime/Win64_x64/MvCameraControl.dll',
            '_internal/vendor/Runtime/Win64_x64/MvUsb3vTL.dll', '_internal/vendor/Drivers/Usb3.0/mvu3v.inf']
for item in required:
    if not (dist/item).is_file(): raise RuntimeError(f'Offline release incomplete: {item}')
runtime = dist/'_internal/vendor/Runtime/Win64_x64'
crt = dist/'Microsoft.VC90.CRT'; crt.mkdir(exist_ok=True)
for name in ('Microsoft.VC90.CRT.manifest', 'msvcr90.dll', 'msvcp90.dll', 'msvcm90.dll'):
    shutil.copy2(runtime/name, crt/name)
source_driver = Path('C:/Program Files (x86)/Common Files/MVS/Drivers/Usb3.0')
for name in ('mvu3v.inf', 'mvu3v.cat', 'mvu3v.sys', 'WdfCoInstaller01011.dll'):
    original = source_driver/name
    packaged = dist/'_internal/vendor/Drivers/Usb3.0'/name
    if original.read_bytes() != packaged.read_bytes():
        raise RuntimeError(f'Vendor driver bytes were changed during packaging: {name}')
(dist/'First-use-Install-USB-Driver.cmd').write_text(
    '@echo off\nstart "" "%~dp0PolaMV Studio.exe" --install-usb-driver\n', encoding='ascii')
shutil.copy2(root/'docs/offline-setup.md', dist/'READ-ME-FIRST.md')
shutil.copy2(root/'README.md', dist/'README.md')
manifest = {p.relative_to(dist).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(dist.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS.json'}
(dist/'SHA256SUMS.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
release = root/'release'; release.mkdir(exist_ok=True)
archive = release/'PolaMV-1.0.0-Windows-x64-offline.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for p in sorted(dist.rglob('*')):
        if p.is_file(): z.write(p, 'PolaMV Studio/'+p.relative_to(dist).as_posix())
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
with zipfile.ZipFile(archive) as z:
    broken = z.testzip()
    if broken: raise RuntimeError(f'Archive CRC failed: {broken}')
print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size, 'sha256': digest, 'files': len(manifest)}, ensure_ascii=True))
