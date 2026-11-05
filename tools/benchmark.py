from pathlib import Path
import json
import platform
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import numba
from polamv.processing import process, RawFrame

raw = np.random.default_rng(7).integers(0, 4096, (2048, 2448), dtype=np.uint16)
results = []
for workers in (1, 2, 4, 8, 16):
    if workers > numba.config.NUMBA_NUM_THREADS:
        continue
    numba.set_num_threads(workers)
    process(RawFrame(raw.copy(), 0, 12))
    timings = []
    for i in range(6):
        source = RawFrame(raw.copy(), i+1, 12)
        begin = time.perf_counter()
        frame = process(source)
        timings.append(time.perf_counter()-begin)
    results.append({'threads': workers, 'median_ms': float(np.median(timings)*1000), 'processing_fps': float(1/np.median(timings))})
report = {'platform': platform.platform(), 'python': platform.python_version(), 'resolution': [2448,2048], 'bits':12, 'includes': 'interpolation, polarization and all five full histograms; excludes camera, display and disk', 'results': results}
Path('docs/benchmark.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
