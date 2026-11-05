"""Offline deployment diagnostic, also runs from the packaged executable."""
from pathlib import Path
import json
import traceback
import numpy as np
from PySide6 import QtWidgets
from .gui import MainWindow
from .camera import SimCamera, MvsCamera
from .processing import process
from .storage import save_tiff
from .deployment import sdk_module_paths, driver_files


def run(directory):
    folder = Path(directory); folder.mkdir(parents=True, exist_ok=True)
    report = {'ok': False}
    window = None
    try:
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = MainWindow(folder/'settings.json'); window.show(); app.processEvents()
        camera = SimCamera(240, 200); camera.open(); camera.start()
        frame = process(camera.read()); camera.close()
        window.frame = frame
        for i, page in enumerate(('RAW', 'Gray', 'AoLP', 'DoLP')):
            window.tabs.setCurrentIndex(i); window.draw_frame(); app.processEvents()
            save_tiff(frame, page, folder, 'selftest')
        window.query_pixel(120, 100)
        window.grab().save(str(folder/'window.png'))
        try:
            report['sdk_devices'] = [name for name, _ in MvsCamera.enumerate()]
            report['sdk_loaded'] = True
            report['sdk_module_audit'] = sdk_module_paths()
            report['usb_driver_files'] = [p.name for p in driver_files()]
        except Exception as exc:
            report['sdk_loaded'] = False; report['sdk_error'] = str(exc)
        report['ok'] = bool(np.isnan(frame.aolp[:, 0]).all()) and report.get('sdk_loaded', False)
        audit = report.get('sdk_module_audit', {})
        report['ok'] = report['ok'] and audit.get('core_and_usb_bundled', False) and not audit.get('external_mvs_modules', [])
        report['shape'] = list(frame.gray.shape)
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        if window: window.close()
    (folder/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['ok'] else 1
