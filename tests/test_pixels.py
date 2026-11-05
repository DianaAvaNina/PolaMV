import numpy as np
import pytest
from polamv.pixels import unpack_mono


@pytest.mark.parametrize('code,data,expected', [
    (0x010C0004, [0xff, 0x13, 0x80], [1023, 513]),
    (0x010C0006, [0xab, 0x3c, 0x12], [0xabc, 0x123]),
    (0x010A0046, [0xff, 0x07, 0x58, 0xd5, 0xaa], [1023, 513, 341, 683]),
    (0x010C0047, [0xbc, 0x3a, 0x12], [0xabc, 0x123]),
])
def test_pfnc_fixed_vectors(code, data, expected):
    raw = unpack_mono(bytes(data), code, len(expected), 1)
    assert raw.dtype == np.uint16
    np.testing.assert_array_equal(raw, [expected])
    with pytest.raises(ValueError, match='长度不足'):
        unpack_mono(bytes(data[:-1]), code, len(expected), 1)
