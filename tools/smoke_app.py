"""Exercise the actual Qt window and produce reviewable screenshots."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6 import QtWidgets, QtCore
from polamv.gui import MainWindow
from polamv.camera import SimCamera
from polamv.processing import process

output = Path('docs/screenshots'); output.mkdir(parents=True, exist_ok=True)
app = QtWidgets.QApplication([])
w = MainWindow(Path('build/smoke-settings.json'))
w.show(); app.processEvents()
w.toggle_open()
c = w.camera
c.start(); frame = process(c.read()); c.stop()
w.frame = frame
w.update_controls()
for i, page in enumerate(('RAW', 'Gray', 'AoLP', 'DoLP')):
    w.tabs.setCurrentIndex(i); w.draw_frame(); w.view.fit()
    w.query_pixel(610, 400)
    w.details.setChecked(True)
    app.processEvents()
    w.grab().save(str(output / f'{page}.png'))
w.close(); app.processEvents()
print('Qt screenshots saved:', output)
