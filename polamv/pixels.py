"""Lossless PFNC monochrome unpacking; legacy Packed and p differ."""
import numpy as np
from numba import njit


@njit(nogil=True, cache=True)
def _legacy(b, bits):
    out = np.empty(len(b) // 3 * 2, dtype=np.uint16)
    shift = bits - 8
    mask = (1 << shift) - 1
    for i in range(len(b) // 3):
        out[2*i] = (int(b[3*i]) << shift) | (int(b[3*i+1]) & mask)
        out[2*i+1] = (int(b[3*i+2]) << shift) | ((int(b[3*i+1]) >> 4) & mask)
    return out


def unpack_mono(payload, pixel_type, width, height):
    groups = {0x010C0004: (2, 3), 0x010C0006: (2, 3),
              0x010A0046: (4, 5), 0x010C0047: (2, 3)}
    pixels, octets = groups[pixel_type]
    if width <= 0 or height <= 0 or width % pixels:
        raise ValueError('Packed 图像宽度不符合像素打包组大小')
    size = width * height // pixels * octets
    if len(payload) < size:
        raise ValueError('Packed 图像长度不足')
    if pixel_type in (0x010C0004, 0x010C0006):
        return _legacy(np.frombuffer(payload, dtype=np.uint8, count=size),
                       10 if pixel_type == 0x010C0004 else 12).reshape(height, width)
    b = np.frombuffer(payload, dtype=np.uint8, count=size).reshape(-1, octets).astype(np.uint16)
    out = np.empty((len(b), pixels), dtype=np.uint16)
    if pixel_type == 0x010C0004:
        out[:, 0] = (b[:, 0] << 2) | (b[:, 1] & 3)
        out[:, 1] = (b[:, 2] << 2) | ((b[:, 1] >> 4) & 3)
    elif pixel_type == 0x010C0006:
        out[:, 0] = (b[:, 0] << 4) | (b[:, 1] & 15)
        out[:, 1] = (b[:, 2] << 4) | (b[:, 1] >> 4)
    elif pixel_type == 0x010A0046:
        out[:, 0] = b[:, 0] | ((b[:, 1] & 3) << 8)
        out[:, 1] = (b[:, 1] >> 2) | ((b[:, 2] & 15) << 6)
        out[:, 2] = (b[:, 2] >> 4) | ((b[:, 3] & 63) << 4)
        out[:, 3] = (b[:, 3] >> 6) | (b[:, 4] << 2)
    else:
        out[:, 0] = b[:, 0] | ((b[:, 1] & 15) << 8)
        out[:, 1] = (b[:, 1] >> 4) | (b[:, 2] << 4)
    return out.reshape(height, width)
