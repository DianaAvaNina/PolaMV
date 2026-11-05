from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

project = Path(SPECPATH)
sdk = Path('C:/Program Files (x86)/MVS/Development/Samples/Python/MvImport')
common = Path('C:/Program Files (x86)/Common Files/MVS')
datas = [(str(project/'polamv/processing.py'), 'polamv')]
if sdk.exists():
    datas.extend((str(p), 'vendor/Development/Samples/Python/MvImport') for p in sdk.glob('*.py'))
else:
    raise RuntimeError('Official MVS Python declarations are required for release builds')
runtime = common / 'Runtime/Win64_x64'
for required in ('MvCameraControl.dll', 'MvUsb3vTL.dll', 'FormatConversion.dll'):
    if not (runtime / required).is_file():
        raise RuntimeError(f'Missing MVS runtime: {required}')
datas.extend((str(p), 'vendor/Runtime/Win64_x64') for p in runtime.iterdir() if p.is_file())
# SDK libraries include VC90 side-by-side dependencies. Keep their matching private
# assembly manifest beside DLLs collected at the PyInstaller top level as well.
for name in ('Microsoft.VC90.CRT.manifest', 'msvcr90.dll', 'msvcp90.dll', 'msvcm90.dll'):
    datas.append((str(runtime/name), '.'))
for name in ('mvu3v.inf', 'mvu3v.cat', 'mvu3v.sys', 'WdfCoInstaller01011.dll'):
    path = common / 'Drivers/Usb3.0' / name
    if not path.is_file():
        raise RuntimeError(f'Missing USB driver file: {path}')
    datas.append((str(path), 'vendor/Drivers/Usb3.0'))
datas.append((str(common/'Licenses'), 'vendor/Licenses'))
hidden = collect_submodules('numba', filter=lambda name: '.tests' not in name and '.testing' not in name)
a = Analysis(['run_polamv.py'], pathex=[str(project)], binaries=collect_dynamic_libs('llvmlite'),
             datas=datas, hiddenimports=hidden, hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=['PyQt5', 'matplotlib', 'pandas', 'scipy', 'IPython', 'notebook', 'pytest', 'tkinter'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='PolaMV Studio', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='PolaMV Studio')
