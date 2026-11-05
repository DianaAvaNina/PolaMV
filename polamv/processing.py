from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import numpy as np
from numba import njit, prange, get_num_threads

# Sensor coordinates, origin at the top left; verify on the target camera.
# Physical transmission axes, positive angle counterclockwise in the image.
PATTERN = ((90, 45), (135, 0))
OFFSETS = ((1, 1), (0, 1), (0, 0), (1, 0))  # 0,45,90,135


@dataclass(frozen=True)
class ProcessingOptions:
    minimum_dolp_enabled: bool = False
    minimum_dolp: float = 0.05


@dataclass(frozen=True)
class RawFrame:
    raw: np.ndarray
    frame_id: int
    bits: int
    metadata: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class ProcessedFrame:
    source: RawFrame
    channels: np.ndarray
    gray: np.ndarray
    aolp: np.ndarray
    dolp: np.ndarray
    histograms: tuple
    options: ProcessingOptions


@njit(cache=True, inline='always')
def _sample(raw, y, x, oy, ox):
    # Interpolate in the actual staggered lattice, not resize half-size images.
    h, w = raw.shape
    # All missing sites lie exactly halfway between measured sites.
    # Integer neighbours avoid division and preserve measured locations exactly.
    xmax, ymax = ox + 2*((w-1-ox)//2), oy + 2*((h-1-oy)//2)
    dx, dy = (x-ox) & 1, (y-oy) & 1
    x0, x1 = max(ox, x-dx), min(xmax, x+dx)
    y0, y1 = max(oy, y-dy), min(ymax, y+dy)
    return (float(raw[y0, x0])+float(raw[y0, x1])+float(raw[y1, x0])+float(raw[y1, x1]))*.25


@njit(cache=True, parallel=True, nogil=True)
def _calculate(raw, fs, enabled, minimum, workers):
    h, w = raw.shape
    channels = np.empty((4, h, w), np.float32)
    gray = np.empty((h, w), np.float32)
    aolp = np.empty((h, w), np.float32)
    dolp = np.empty((h, w), np.float32)
    histograms = np.zeros((workers, 5, fs+1), np.int64)
    for tid in prange(workers):
        for y in range(tid*h//workers, (tid+1)*h//workers):
            for x in range(w):
                i0 = _sample(raw, y, x, 1, 1)
                i45 = _sample(raw, y, x, 0, 1)
                i90 = _sample(raw, y, x, 0, 0)
                i135 = _sample(raw, y, x, 1, 0)
                channels[0, y, x], channels[1, y, x] = i0, i45
                channels[2, y, x], channels[3, y, x] = i90, i135
                g = (i0 + i45 + i90 + i135) * 0.25
                gray[y, x] = g
                histograms[tid, 0, int(g+.5)] += 1
                channel = (2 if (x & 1) == 0 else 1) if (y & 1) == 0 else (3 if (x & 1) == 0 else 0)
                histograms[tid, channel+1, raw[y, x]] += 1
                if g < 0.02 * fs:
                    dolp[y, x] = np.nan
                    aolp[y, x] = np.nan
                else:
                    s1, s2 = i0 - i90, i45 - i135
                    d = math.sqrt(s1*s1 + s2*s2) / (2*g)
                    # V1.0 defines saved DoLP in [0,1]. Clip nonphysical overshoot.
                    d = min(d, 1.0)
                    dolp[y, x] = d
                    a = math.atan2(s2, s1) * (90.0 / math.pi)
                    if a >= 90:
                        a -= 180
                    aolp[y, x] = np.nan if enabled and d < minimum else a
    return channels, gray, aolp, dolp, histograms.sum(axis=0)


def process(frame, options=ProcessingOptions()):
    raw = frame.raw
    if raw.ndim != 2 or min(raw.shape) < 2 or raw.dtype not in (np.uint8, np.uint16):
        raise ValueError('RAW 必须为至少 2×2 的 uint8/uint16 单通道图像')
    if frame.bits not in (8, 10, 12):
        raise ValueError('不支持的有效位深')
    if not 0 <= options.minimum_dolp <= 1:
        raise ValueError('DoLP 阈值必须在 0～100% 范围内')
    fs = (1 << frame.bits) - 1
    if raw.max() > fs:
        raise ValueError('RAW 数据超出有效位深范围，请检查像素格式与 SDK 解包')
    channels, gray, aolp, dolp, histograms = _calculate(raw, fs, options.minimum_dolp_enabled, options.minimum_dolp, get_num_threads())
    total, *hist = histograms
    for a in (raw, channels, gray, aolp, dolp, total, *hist):
        a.flags.writeable = False
    return ProcessedFrame(frame, channels, gray, aolp, dolp, (total, *hist), options)


def quantitative(frame, page):
    if page == 'RAW':
        return frame.source.raw
    if page == 'Gray':
        dtype = np.uint8 if frame.source.bits == 8 else np.uint16
        return np.floor(frame.gray + 0.5).astype(dtype)
    return {'AoLP': frame.aolp, 'DoLP': frame.dolp}[page]
