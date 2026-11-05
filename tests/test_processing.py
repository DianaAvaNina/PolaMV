import numpy as np
import pytest
from polamv.processing import RawFrame, ProcessingOptions, process, OFFSETS


def mosaic(values, shape=(16, 20), dtype=np.uint16):
    raw = np.empty(shape, dtype)
    for value, (y, x) in zip(values, OFFSETS):
        raw[y::2, x::2] = value
    return raw


@pytest.mark.parametrize('values, angle, degree', [
    ((1000, 500, 0, 500), 0, 1),
    ((500, 1000, 500, 0), 45, 1),
    ((500, 0, 500, 1000), -45, 1),
    ((0, 500, 1000, 500), -90, 1),
    ((500, 500, 500, 500), 0, 0),
])
def test_known_stokes(values, angle, degree):
    f = process(RawFrame(mosaic(values), 1, 12))
    np.testing.assert_allclose(f.gray, 500)
    np.testing.assert_allclose(f.aolp, angle, atol=1e-5)
    np.testing.assert_allclose(f.dolp, degree)


def test_staggered_bilinear_preserves_samples_and_affine_fields():
    h, w = 18, 24
    raw = np.zeros((h, w), np.uint16)
    for k, (oy, ox) in enumerate(OFFSETS):
        y, x = np.mgrid[oy:h:2, ox:w:2]
        raw[oy::2, ox::2] = 100+k*100+2*x+3*y
    f = process(RawFrame(raw, 2, 12))
    y, x = np.mgrid[:h, :w]
    for k, (oy, ox) in enumerate(OFFSETS):
        np.testing.assert_array_equal(f.channels[k, oy::2, ox::2], raw[oy::2, ox::2])
        np.testing.assert_allclose(f.channels[k, 1:-1, 1:-1], (100+k*100+2*x+3*y)[1:-1, 1:-1])
        assert f.channels[k].min() >= raw[oy::2, ox::2].min()
        assert f.channels[k].max() <= raw[oy::2, ox::2].max()


@pytest.mark.parametrize('bits', [8, 10, 12])
def test_low_signal_adapts_to_bitdepth(bits):
    fs = (1 << bits)-1
    low = process(RawFrame(mosaic([int(.02*fs)]*4), 1, bits))
    high = process(RawFrame(mosaic([int(.02*fs)+1]*4), 2, bits))
    assert np.isnan(low.aolp).all() and np.isnan(low.dolp).all()
    assert np.isfinite(low.gray).all()
    assert np.isfinite(high.aolp).all() and np.isfinite(high.dolp).all()


def test_optional_degree_mask_and_histogram_counts():
    raw = mosaic([500]*4, (17, 21))
    f = process(RawFrame(raw, 3, 12), ProcessingOptions(True, .05))
    assert np.isnan(f.aolp).all()
    assert (f.dolp == 0).all()
    assert f.histograms[0].sum() == raw.size
    for hist, (y, x) in zip(f.histograms[1:], OFFSETS):
        assert hist.sum() == raw[y::2, x::2].size
    assert not f.gray.flags.writeable


def test_unsigned_subtraction_and_nonphysical_overshoot():
    f = process(RawFrame(mosaic([0, 0, 4095, 4095]), 1, 12))
    np.testing.assert_allclose(f.aolp, -67.5)
    assert (f.dolp == 1).all()
