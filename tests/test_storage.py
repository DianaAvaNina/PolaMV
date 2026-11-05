import json
import numpy as np
import tifffile
import pytest
from polamv.processing import RawFrame, process
from polamv.storage import save_tiff, Settings


@pytest.mark.parametrize('bits,dtype', [(8,np.uint8), (10,np.uint16), (12,np.uint16)])
def test_tiff_quantitative_roundtrip(tmp_path, bits, dtype):
    raw = np.full((12, 14), (1 << bits)//4, dtype)
    raw[:, :4] = 0
    f = process(RawFrame(raw, 123, bits, {'PixelFormat': f'Mono{bits}', 'ExposureTime': 5000}))
    for page, expected_dtype in [('RAW', dtype), ('Gray', dtype), ('AoLP', np.float32), ('DoLP', np.float32)]:
        a = save_tiff(f, page, tmp_path, '实验', False)
        b = save_tiff(f, page, tmp_path, '实验', False)
        assert a != b
        with tifffile.TiffFile(a) as t:
            data = t.asarray()
            meta = json.loads(t.pages[0].description)
        assert data.dtype == expected_dtype
        assert meta['frame_id'] == 123 and meta['camera']['ExposureTime'] == 5000
        if page == 'RAW': np.testing.assert_array_equal(data, raw)
        if page in ('AoLP', 'DoLP'):
            assert np.isnan(data[:, 0]).all()
            np.testing.assert_array_equal(data, f.aolp if page == 'AoLP' else f.dolp)


def test_settings_roundtrip(tmp_path):
    s = Settings(auto_save=True, histogram_four=True, minimum_dolp_enabled=True, minimum_dolp=.12)
    s.camera_values = {'sim': {'TriggerSource': 0}}
    s.save(tmp_path/'settings.json')
    assert Settings.load(tmp_path/'settings.json') == s


def test_invalid_save_path_is_reported(tmp_path):
    target = tmp_path/'file'; target.write_text('file')
    f = process(RawFrame(np.zeros((2, 2), np.uint8), 1, 8))
    with pytest.raises(OSError): save_tiff(f, 'RAW', target)
