import time
import numpy as np
import tifffile
from polamv.camera import SimCamera
from polamv.pipeline import Pipeline, SaveRequest
from polamv.processing import ProcessingOptions, process, RawFrame


def wait_until(condition, timeout=20):
    start = time.monotonic()
    while not condition():
        if time.monotonic()-start > timeout: raise AssertionError('worker timeout')
        time.sleep(.03)


def test_external_trigger_saves_each_frame_and_selected_page(tmp_path):
    p = Pipeline(); c = SimCamera(40, 32); c.open()
    c.set('TriggerMode', 1); c.set('TriggerSource', 0)
    p.configure(ProcessingOptions(), SaveRequest('AoLP', str(tmp_path), 'test', True), True)
    try:
        p.start(c)
        for _ in range(3):
            c.trigger(); time.sleep(.05)
        wait_until(lambda: p.saved == 3)
        assert p.received == 3
        assert len(list(tmp_path.glob('*.tif'))) == 3
        assert all(tifffile.imread(f).dtype == np.float32 for f in tmp_path.glob('*.tif'))
    finally: p.close(); c.close()


def test_software_trigger_does_not_auto_save(tmp_path):
    p = Pipeline(); c = SimCamera(40, 32); c.open(); c.set('TriggerMode', 1)
    p.configure(ProcessingOptions(), SaveRequest('RAW', str(tmp_path), 'test', True), True)
    try:
        p.start(c); c.trigger()
        wait_until(lambda: p.processed == 1)
        assert p.saved == 0
    finally: p.close(); c.close()


def test_manual_save_uses_retained_frame(tmp_path):
    p = Pipeline()
    f = process(RawFrame(np.full((4,4), 100, np.uint8), 73, 8))
    try:
        p.enqueue_save(f, SaveRequest('RAW', str(tmp_path), 'manual', False))
        wait_until(lambda: p.saved == 1)
        path = next(tmp_path.glob('*.tif'))
        assert 'Frame000000073' in path.name
        np.testing.assert_array_equal(tifffile.imread(path), 100)
    finally: p.close()
