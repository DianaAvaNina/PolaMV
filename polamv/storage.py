from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import re
import uuid
import tifffile
from .processing import quantitative, PATTERN


@dataclass
class Settings:
    minimum_dolp_enabled: bool = False
    minimum_dolp: float = 0.05
    save_directory: str = field(default_factory=lambda: str(Path.home() / 'Pictures' / 'PolaMV'))
    prefix: str = 'PolaMV'
    timestamp_names: bool = True
    auto_save: bool = False
    histogram_four: bool = False
    sync_zoom: bool = True
    aolp_map: str = 'HSV'
    dolp_map: str = 'Viridis'
    nan_color: str = '#808080'
    camera_values: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path):
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding='utf-8'))
        obj = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        if not isinstance(obj.minimum_dolp, (int, float)) or not 0 <= obj.minimum_dolp <= 1:
            obj.minimum_dolp = .05
        if obj.aolp_map not in ('HSV', 'Twilight'):
            obj.aolp_map = 'HSV'
        if obj.dolp_map not in ('Viridis', 'Cividis'):
            obj.dolp_map = 'Viridis'
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', obj.nan_color):
            obj.nan_color = '#808080'
        return obj

    def save(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, path)


def save_tiff(frame, page, directory, prefix='PolaMV', timestamp=True):
    folder = Path(directory).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    prefix = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', prefix).strip(' .')[:80] or 'PolaMV'
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f_') if timestamp else ''
    filename = f'{prefix}_{stamp}Frame{frame.source.frame_id:09d}_{page}_{uuid.uuid4().hex[:12]}.tif'
    target = folder / filename
    metadata = {
        'software': 'PolaMV Studio 1.0', 'page': page,
        'frame_id': frame.source.frame_id, 'timestamp_utc': frame.source.timestamp,
        'bits': frame.source.bits, 'unit': {'RAW': 'DN', 'Gray': 'DN', 'AoLP': 'degree', 'DoLP': 'fraction'}[page],
        'camera': frame.source.metadata, 'processing': asdict(frame.options),
        'low_signal_fraction_fs': 0.02, 'pattern_top_left': PATTERN,
        'pattern_validation': 'Reference sensor layout; target hardware verification required',
        'aolp_convention': 'image +X = 0 degrees; counterclockwise positive; [-90,90)',
        'dolp_policy': 'clipped to [0,1]',
        'interpolation': 'same-angle position-aware bilinear, clamped boundaries',
    }
    temporary = target.with_suffix('.tif.partial')
    try:
        with temporary.open('xb') as stream:
            tifffile.imwrite(stream, quantitative(frame, page), photometric='minisblack',
                             description=json.dumps(metadata, ensure_ascii=True), metadata=None,
                             software='PolaMV Studio 1.0')
        # Unique name and exclusive partial file prevent accidental overwrite.
        os.rename(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target
