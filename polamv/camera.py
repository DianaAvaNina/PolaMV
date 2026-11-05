"""MVS adapter. Uses the vendor's ctypes declarations, never guessed layouts."""
import ctypes as ct
import importlib
import os
from pathlib import Path
import sys
import threading
import time
from dataclasses import dataclass
import numpy as np
from .processing import RawFrame
from .pixels import unpack_mono


@dataclass
class Node:
    key: str
    kind: str
    value: object
    writable: bool = True
    minimum: float = 0
    maximum: float = 0
    increment: float = 0
    choices: tuple = ()


NODE_TYPES = {
    'ExposureAuto': 'enum', 'ExposureTime': 'float',
    'GainAuto': 'enum', 'Gain': 'float', 'PixelFormat': 'enum',
    'AcquisitionMode': 'enum', 'AcquisitionFrameRateEnable': 'bool', 'AcquisitionFrameRate': 'float',
    'TriggerSelector': 'enum', 'TriggerMode': 'enum', 'TriggerSource': 'enum',
    'TriggerActivation': 'enum', 'TriggerDelay': 'float',
    'AcquisitionBurstFrameCount': 'int', 'TriggerCacheEnable': 'bool',
    'LineSelector': 'enum', 'LineMode': 'enum', 'LineDebouncerTime': 'float',
}
_sdk = None
_dll_directories = []
_native_libraries = []


def load_sdk():
    global _sdk
    if _sdk is not None:
        return _sdk
    roots = [Path(os.environ.get('MVS_HOME', 'C:/Program Files (x86)/MVS')),
             Path('C:/Program Files/MVS')]
    if getattr(sys, 'frozen', False):
        # A release must use its own runtime; never silently borrow an installed SDK.
        roots = [Path(sys._MEIPASS) / 'vendor']
    if os.environ.get('POLAMV_SDK_ROOT'):
        roots = [Path(os.environ['POLAMV_SDK_ROOT'])]
    for root in roots:
        wrapper = root / 'Development/Samples/Python/MvImport'
        if not wrapper.exists():
            continue
        folders = [root / 'Runtime/Win64_x64', root / 'Development/Bin/win64']
        if not getattr(sys, 'frozen', False) and not os.environ.get('POLAMV_SDK_ROOT'):
            folders.append(Path('C:/Program Files (x86)/Common Files/MVS/Runtime/Win64_x64'))
        core = next((folder / 'MvCameraControl.dll' for folder in folders if (folder / 'MvCameraControl.dll').exists()), None)
        if core is None:
            continue
        for folder in folders:
            if folder.exists():
                _dll_directories.append(os.add_dll_directory(str(folder)))
                os.environ['PATH'] = str(folder) + os.pathsep + os.environ['PATH']
        sys.path.insert(0, str(wrapper))
        try:
            # Absolute loading ensures the vendor's name-based wrapper reuses this DLL.
            _native_libraries.append(ct.WinDLL(str(core.resolve()), winmode=0x1100))
            for name in ('MvUsb3vTL.dll', 'FormatConversion.dll'):
                dependency = core.parent / name
                if dependency.exists():
                    _native_libraries.append(ct.WinDLL(str(dependency.resolve()), winmode=0x1100))
            _sdk = importlib.import_module('MvCameraControl_class')
            return _sdk
        except (ImportError, OSError) as exc:
            raise RuntimeError(f'MVS SDK 加载失败：{exc}。请完整解压软件包并保留 _internal 文件夹。') from exc
    raise RuntimeError('未找到完整 MVS 运行库；请重新完整解压软件包。源码运行可设置 MVS_HOME。')


def check(code, action):
    if code:
        raise RuntimeError(f'{action}失败：MVS 0x{code & 0xffffffff:08X}')


def decode(value):
    return bytes(value).split(b'\0', 1)[0].decode('utf-8', errors='replace')


class MvsCamera:
    def __init__(self):
        self.sdk = load_sdk()
        self.cam = self.sdk.MvCamera()
        self.opened = self.grabbing = False
        self.lock = threading.RLock()
        self.nodes = {}
        self.identity = {}

    @staticmethod
    def enumerate():
        sdk = load_sdk()
        devices = sdk.MV_CC_DEVICE_INFO_LIST()
        check(sdk.MvCamera.MV_CC_EnumDevices(sdk.MV_USB_DEVICE | sdk.MV_GIGE_DEVICE, devices), '搜索设备')
        result = []
        for i in range(devices.nDeviceNum):
            info = ct.cast(devices.pDeviceInfo[i], ct.POINTER(sdk.MV_CC_DEVICE_INFO)).contents
            copy = sdk.MV_CC_DEVICE_INFO.from_buffer_copy(info)
            details = info.SpecialInfo.stUsb3VInfo if info.nTLayerType == sdk.MV_USB_DEVICE else info.SpecialInfo.stGigEInfo
            result.append((f'{decode(details.chModelName)} · {decode(details.chSerialNumber)}', copy))
        return result

    def open(self, info):
        check(self.cam.MV_CC_CreateHandle(info), '创建设备句柄')
        try:
            check(self.cam.MV_CC_OpenDevice(self.sdk.MV_ACCESS_Exclusive, 0), '打开相机')
        except Exception:
            self.cam.MV_CC_DestroyHandle()
            raise
        self.opened = True
        details = info.SpecialInfo.stUsb3VInfo if info.nTLayerType == self.sdk.MV_USB_DEVICE else info.SpecialInfo.stGigEInfo
        self.identity = {'model': decode(details.chModelName), 'serial': decode(details.chSerialNumber),
                         'sdk_version': f'{self.sdk.MvCamera.MV_CC_GetSDKVersion():08X}'}
        self.refresh()

    def read_node(self, key, kind):
        with self.lock:
            mode = ct.c_int()
            code = self.cam.MV_XML_GetNodeAccessMode(key, mode)
            if code or mode.value not in (3, 4):
                return None
            writable = mode.value == 4
            if kind == 'enum':
                value = self.sdk.MVCC_ENUMVALUE()
                if self.cam.MV_CC_GetEnumValue(key, value):
                    return None
                choices = []
                for number in value.nSupportValue[:value.nSupportedNum]:
                    entry = self.sdk.MVCC_ENUMENTRY()
                    entry.nValue = number
                    if self.cam.MV_CC_GetEnumEntrySymbolic(key, entry) == 0:
                        choices.append((decode(entry.chSymbolic), int(number)))
                return Node(key, kind, int(value.nCurValue), writable, choices=tuple(choices))
            if kind == 'float':
                value = self.sdk.MVCC_FLOATVALUE()
                if self.cam.MV_CC_GetFloatValue(key, value):
                    return None
                return Node(key, kind, value.fCurValue, writable, value.fMin, value.fMax)
            if kind == 'int':
                value = self.sdk.MVCC_INTVALUE_EX()
                if self.cam.MV_CC_GetIntValueEx(key, value):
                    return None
                return Node(key, kind, value.nCurValue, writable, value.nMin, value.nMax, value.nInc)
            value = ct.c_bool()
            if self.cam.MV_CC_GetBoolValue(key, value):
                return None
            return Node(key, kind, value.value, writable)

    def refresh(self):
        self.nodes = {key: node for key, kind in NODE_TYPES.items() if (node := self.read_node(key, kind)) is not None}
        return self.nodes

    def set(self, key, value):
        with self.lock:
            node = self.read_node(key, NODE_TYPES[key])
            if node is None or not node.writable:
                raise ValueError(f'{key} 当前不可写')
            if node.kind in ('int', 'float'):
                if not np.isfinite(value) or not node.minimum <= value <= node.maximum:
                    raise ValueError(f'{key} 范围为 {node.minimum}～{node.maximum}')
                if node.kind == 'int' and node.increment and (int(value)-int(node.minimum)) % int(node.increment):
                    raise ValueError(f'{key} 必须符合步进 {node.increment}')
            if node.kind == 'enum' and value not in [v for _, v in node.choices]:
                raise ValueError(f'{key} 不支持该选项')
            method = {'enum': 'MV_CC_SetEnumValue', 'float': 'MV_CC_SetFloatValue',
                      'int': 'MV_CC_SetIntValueEx', 'bool': 'MV_CC_SetBoolValue'}[node.kind]
            check(getattr(self.cam, method)(key, value), f'设置 {key}')
            self.refresh()

    def metadata(self):
        result = dict(self.identity)
        for key, node in self.nodes.items():
            result[key] = dict((v, k) for k, v in node.choices).get(node.value, node.value) if node.kind == 'enum' else node.value
        return result

    def start(self):
        self.refresh()
        pixel = self.nodes.get('PixelFormat')
        if pixel and pixel.value in (0x010C0004, 0x010C0006):
            # Compile before starting acquisition to avoid dropping startup frames.
            unpack_mono(bytes(3), pixel.value, 2, 1)
        check(self.cam.MV_CC_StartGrabbing(), '开始采集')
        self.grabbing = True

    def stop(self):
        if self.grabbing:
            try:
                check(self.cam.MV_CC_StopGrabbing(), '停止采集')
            finally:
                self.grabbing = False

    def trigger(self):
        with self.lock:
            check(self.cam.MV_CC_SetCommandValue('TriggerSoftware'), '软件触发')

    def read(self, timeout=200):
        output = self.sdk.MV_FRAME_OUT()
        with self.lock:
            code = self.cam.MV_CC_GetImageBuffer(output, timeout)
            if code:
                if not self.cam.MV_CC_IsDeviceConnected():
                    raise ConnectionError('相机已断开，请停止并重新连接')
                if code == 0x80000007:  # MV_E_NODATA: expected while waiting for trigger
                    return None
                check(code, '接收图像')
            try:
                f = output.stFrameInfo
                p = int(f.enPixelType) & 0xffffffff
                formats = {0x01080001: (8, False), 0x01100003: (10, False),
                           0x010C0004: (10, True), 0x01100005: (12, False),
                           0x010C0006: (12, True), 0x010A0046: (10, True), 0x010C0047: (12, True)}
                if p not in formats:
                    raise ValueError(f'当前像素格式 0x{p:08X} 不支持偏振定量处理，请选择 Mono8/10/12')
                bits, packed = formats[p]
                dtype = np.uint8 if bits == 8 else np.uint16
                count = f.nWidth * f.nHeight
                if packed:
                    data = unpack_mono(ct.string_at(output.pBufAddr, f.nFrameLen),
                                       p, f.nWidth, f.nHeight)
                else:
                    size = count * np.dtype(dtype).itemsize
                    if f.nFrameLen < size:
                        raise ValueError('图像长度不足')
                    data = np.frombuffer(ct.string_at(output.pBufAddr, size), dtype=dtype).copy()
                meta = self.metadata()
                # Query changing auto-exposure/gain values for each received frame.
                for key in ('ExposureTime', 'Gain'):
                    node = self.read_node(key, 'float')
                    if node:
                        meta[key] = node.value
                meta['parameter_provenance'] = 'Host readback at receive; not camera chunk exposure metadata'
                meta['device_timestamp_ticks'] = (int(f.nDevTimeStampHigh) << 32) | int(f.nDevTimeStampLow)
                if f.fExposureTime > 0:
                    meta['frame_info_exposure_us'] = float(f.fExposureTime)
                    meta['frame_info_gain_db'] = float(f.fGain)
                meta['lost_packets'] = int(f.nLostPacket)
                if f.nLostPacket:
                    raise ValueError(f'Frame {f.nFrameNum} 有 {f.nLostPacket} 个丢包，未作为有效图像处理')
                meta['pixel_type_code'] = p
                return RawFrame(data.reshape(f.nHeight, f.nWidth), int(f.nFrameNum), bits, meta)
            finally:
                check(self.cam.MV_CC_FreeImageBuffer(output), '释放 SDK 图像')

    def close(self):
        try:
            self.stop()
        finally:
            if self.opened:
                try:
                    check(self.cam.MV_CC_CloseDevice(), '关闭相机')
                finally:
                    self.cam.MV_CC_DestroyHandle()
                    self.opened = False


class SimCamera:
    """Deterministic polarimetric scene; clearly labelled, never a real device."""
    def __init__(self, width=960, height=800):
        self.width, self.height = width, height
        self.opened = self.grabbing = False
        self.frame_id = 0
        self.pending = threading.Semaphore(0)
        self.next_frame = 0
        self.nodes = {
            'ExposureTime': Node('ExposureTime', 'float', 5000., True, 10, 1000000),
            'Gain': Node('Gain', 'float', 0., True, 0, 24),
            'PixelFormat': Node('PixelFormat', 'enum', 12, choices=(('Mono8', 8), ('Mono10', 10), ('Mono12', 12))),
            'TriggerMode': Node('TriggerMode', 'enum', 0, choices=(('Off', 0), ('On', 1))),
            'TriggerSource': Node('TriggerSource', 'enum', 7, choices=(('Software', 7), ('Line0', 0))),
            'TriggerActivation': Node('TriggerActivation', 'enum', 0, choices=(('RisingEdge', 0), ('FallingEdge', 1))),
            'TriggerDelay': Node('TriggerDelay', 'float', 0., True, 0, 1000000),
            'AcquisitionFrameRate': Node('AcquisitionFrameRate', 'float', 30., True, 1, 100),
        }
        y, x = np.mgrid[:height, :width]
        self.theta = np.arctan2(-(y-height/2), x-width/2)
        self.intensity = 0.35 + 0.15 * np.sin(x/width * 10)
        self.intensity[:, :max(2, width//12)] = 0.005
        self.degree = np.clip(np.hypot(x-width/2, y-height/2)/max(width, height), 0, 0.9)
        self.angles = np.tile(np.array([[90, 45], [135, 0]]), ((height+1)//2, (width+1)//2))[:height, :width] * np.pi/180

    def open(self, info=None):
        self.opened = True

    def refresh(self):
        return self.nodes

    def set(self, key, value):
        node = self.nodes[key]
        if node.kind == 'float' and not node.minimum <= value <= node.maximum:
            raise ValueError('参数超出范围')
        if node.kind == 'enum' and value not in [v for _, v in node.choices]:
            raise ValueError('不支持的选项')
        node.value = value

    def metadata(self):
        return {'model': 'SIMULATED · 非真实相机', 'serial': 'SIM-001', **{
            k: dict((v, label) for label, v in n.choices).get(n.value, n.value) if n.kind == 'enum' else n.value
            for k, n in self.nodes.items()}}

    def start(self):
        self.grabbing = True
        self.next_frame = time.monotonic()

    def stop(self):
        self.grabbing = False

    def close(self):
        self.stop()
        self.opened = False

    def trigger(self):
        self.pending.release()

    def read(self, timeout=200):
        if self.nodes['TriggerMode'].value:
            if not self.pending.acquire(timeout=timeout/1000):
                return None
        else:
            delay = self.next_frame-time.monotonic()
            if delay > 0:
                time.sleep(min(delay, timeout/1000))
            self.next_frame = max(self.next_frame, time.monotonic()) + 1/self.nodes['AcquisitionFrameRate'].value
        if not self.grabbing:
            return None
        self.frame_id += 1
        bits = self.nodes['PixelFormat'].value
        value = self.intensity * (1 + self.degree*np.cos(2*(self.theta + self.frame_id*.006-self.angles)))
        raw = np.rint(np.clip(value, 0, 1) * ((1 << bits)-1)).astype(np.uint8 if bits == 8 else np.uint16)
        return RawFrame(raw, self.frame_id, bits, self.metadata())
