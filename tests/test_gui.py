import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PySide6 import QtWidgets, QtCore
from polamv.gui import MainWindow, SettingsDialog
from polamv.processing import RawFrame, process
from polamv.display import make_lut, render


def test_gui_frame_tabs_zoom_and_pixel_query(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow(tmp_path/'settings.json')
    try:
        w.show(); app.processEvents()
        w.frame = process(RawFrame(np.full((40, 60), 500, np.uint16), 19, 12))
        w.draw_frame(); w.view.actual()
        for i in range(4):
            w.tabs.setCurrentIndex(i); app.processEvents()
            assert w.view.transform().m11() == 1
            w.query_pixel(10, 12)
            assert 'X 10' in w.pixel_label.text() and 'Y 12' in w.pixel_label.text()
            assert w.frame.source.frame_id == 19
        w.toggle_histogram(); assert w.histogram.four
        w.grab().save(str(tmp_path/'gui.png'))
    finally: w.close(); app.processEvents()


def test_nan_render_and_cyclic_colormap(tmp_path):
    from polamv.storage import Settings
    f = process(RawFrame(np.zeros((4, 4), np.uint8), 1, 8))
    image = render(f, 'AoLP', Settings())
    assert (image == 128).all()
    for name in ('HSV', 'Twilight'):
        np.testing.assert_array_equal(make_lut(name)[0], make_lut(name)[-1])


def test_settings_and_live_simulation_workflow(tmp_path):
    import time
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow(tmp_path/'settings.json')
    try:
        dialog = SettingsDialog(w.settings, w)
        dialog.minimum_enabled.setChecked(True)
        dialog.minimum.setValue(7)
        updated = dialog.result_settings()
        assert updated.minimum_dolp_enabled and updated.minimum_dolp == .07
        dialog.close()
        w.settings.save_directory = str(tmp_path/'images')
        w.toggle_open()
        assert w.camera is not None
        w.apply_node('PixelFormat', 10)
        w.configure_pipeline(); w.toggle_capture()
        deadline = time.monotonic()+15
        while w.frame is None and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.02)
        assert w.frame is not None and w.frame.source.bits == 10
        w.toggle_capture()
        displayed_id = w.frame.source.frame_id
        w.save_current()
        while w.pipeline.saved < 1 and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.02)
        assert any(f'Frame{displayed_id:09d}' in p.name for p in (tmp_path/'images').glob('*.tif'))
        w.toggle_open()
        assert w.camera is None
    finally: w.close(); app.processEvents()
