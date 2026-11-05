"""Offline USB driver installation; invoked explicitly, never during normal startup."""
import ctypes as ct
import os
from pathlib import Path
import subprocess
import sys

DRIVER_FILES = ('mvu3v.inf', 'mvu3v.cat', 'mvu3v.sys', 'WdfCoInstaller01011.dll')


def bundle_root():
    return Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]/'dist/PolaMV Studio/_internal'


def driver_files(root=None):
    folder = (root or bundle_root()) / 'vendor/Drivers/Usb3.0'
    paths = [folder/name for name in DRIVER_FILES]
    missing = [p.name for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError('USB 驱动文件缺失：' + ', '.join(missing) + '。请完整解压离线包。')
    return paths


def driver_command(root=None):
    inf = driver_files(root)[0].resolve()
    return [str(Path(os.environ.get('WINDIR', 'C:/Windows'))/'System32/pnputil.exe'), '/add-driver', str(inf), '/install']


def install_usb_driver():
    from PySide6 import QtWidgets, QtGui
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    font = Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts/msyh.ttc'
    if font.exists(): QtGui.QFontDatabase.addApplicationFont(str(font))
    app.setFont(QtGui.QFont('Microsoft YaHei UI', 10))
    try:
        command = driver_command()
        if not getattr(sys, 'frozen', False):
            raise RuntimeError('驱动安装请使用发布包中的入口。')
        if not ct.windll.shell32.IsUserAnAdmin():
            launch = ct.windll.shell32.ShellExecuteW
            launch.argtypes = [ct.c_void_p, ct.c_wchar_p, ct.c_wchar_p, ct.c_wchar_p, ct.c_wchar_p, ct.c_int]
            launch.restype = ct.c_void_p
            result = launch(None, 'runas', sys.executable, '--install-usb-driver', str(Path(sys.executable).parent), 0)
            if not result or result <= 32:
                raise RuntimeError('未获得管理员权限，USB 驱动没有安装。可稍后重新运行首次使用入口。')
            return 0
        progress = QtWidgets.QLabel('正在安装海康 USB 相机驱动，请稍候……')
        progress.setWindowTitle('PolaMV · 首次使用'); progress.setMinimumSize(460, 90)
        progress.show(); app.processEvents()
        result = subprocess.run(command, capture_output=True, text=True, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
        progress.close()
        logs = Path(os.environ.get('LOCALAPPDATA', str(Path.home())))/'PolaMV'
        logs.mkdir(parents=True, exist_ok=True)
        log = logs/'usb-driver-install.log'
        log.write_text(f'ExitCode={result.returncode}\n{result.stdout}\n{result.stderr}', encoding='utf-8')
        if result.returncode not in (0, 3010):
            raise RuntimeError(f'Windows 未能安装驱动（代码 {result.returncode}）。\n{result.stdout[-1200:]}\n详情：{log}')
        message = 'USB 驱动包已安装。请连接或重新插拔相机，然后打开 PolaMV Studio.exe。'
        if result.returncode == 3010:
            message = 'USB 驱动包已安装。Windows 要求重新启动电脑，重启后再连接相机并打开软件。'
        QtWidgets.QMessageBox.information(None, 'PolaMV · 安装完成', message)
        return 0
    except Exception as exc:
        QtWidgets.QMessageBox.critical(None, 'PolaMV · 驱动未安装', str(exc))
        return 1


def sdk_module_paths():
    """Audit loaded native modules so a host MVS install cannot hide missing files."""
    psapi = ct.WinDLL('psapi', use_last_error=True)
    kernel = ct.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = ct.c_void_p
    process = kernel.GetCurrentProcess()
    modules = (ct.c_void_p*2048)(); needed = ct.c_ulong()
    psapi.EnumProcessModules.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_ulong, ct.POINTER(ct.c_ulong)]
    psapi.GetModuleFileNameExW.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_wchar_p, ct.c_ulong]
    if not psapi.EnumProcessModules(process, modules, ct.sizeof(modules), ct.byref(needed)):
        raise ct.WinError(ct.get_last_error())
    paths = []
    for module in modules[:needed.value//ct.sizeof(ct.c_void_p)]:
        buf = ct.create_unicode_buffer(32768)
        if psapi.GetModuleFileNameExW(process, module, buf, len(buf)):
            paths.append(Path(buf.value))
    runtime = bundle_root()/'vendor/Runtime/Win64_x64'
    names = {p.name.lower() for p in runtime.glob('*.dll')}
    selected = [p for p in paths if p.name.lower() in names]
    windows = Path(os.environ.get('WINDIR', 'C:/Windows')).resolve()
    external = [str(p) for p in selected if not p.resolve().is_relative_to(bundle_root().resolve()) and not p.resolve().is_relative_to(windows)]
    core = next((p for p in selected if p.name.lower() == 'mvcameracontrol.dll'), None)
    usb = next((p for p in selected if p.name.lower() == 'mvusb3vtl.dll'), None)
    local = core is not None and usb is not None and core.parent.resolve() == runtime.resolve() and usb.parent.resolve() == runtime.resolve()
    return {'core_and_usb_bundled': local, 'external_mvs_modules': external, 'modules': [str(p) for p in selected]}
