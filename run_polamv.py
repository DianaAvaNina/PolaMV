import multiprocessing
import os
import sys
from pathlib import Path

if __name__ == '__main__':
    multiprocessing.freeze_support()
    if '--install-usb-driver' in sys.argv:
        from polamv.deployment import install_usb_driver
        raise SystemExit(install_usb_driver())
    cache_root = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PolaMV'
    os.environ.setdefault('NUMBA_CACHE_DIR', str(cache_root / 'numba-cache'))
    if '--self-test' in sys.argv:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from polamv.selftest import run
        raise SystemExit(run(sys.argv[sys.argv.index('--self-test')+1]))
    from polamv.gui import main
    raise SystemExit(main())
