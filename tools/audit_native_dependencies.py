"""Read-only static PE dependency audit for the offline Windows distribution."""
from pathlib import Path
import json
import os
import pefile

root = Path(__file__).resolve().parents[1]
dist = root/'dist/PolaMV Studio'
files = [p for p in dist.rglob('*') if p.suffix.lower() in ('.dll', '.pyd', '.exe', '.cti', '.ax')]
available = {p.name.lower() for p in files}
windows = Path(os.environ.get('WINDIR', 'C:/Windows'))/'System32'
missing = {}
for path in files:
    try:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
        for entry in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []):
            name = entry.dll.decode('ascii').lower()
            if name.startswith(('api-ms-', 'ext-ms-')) or name in available or (windows/name).exists():
                continue
            missing.setdefault(name, []).append(str(path.relative_to(dist)))
        pe.close()
    except pefile.PEFormatError:
        pass
report = {'checked_pe_files': len(files), 'missing_static_dependencies': missing,
          'scope': 'Static PE imports; Windows API sets assumed supplied by supported Windows; not a clean-OS or hardware test'}
(root/'docs/offline-native-dependencies.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=True, indent=2))
raise SystemExit(1 if missing else 0)
