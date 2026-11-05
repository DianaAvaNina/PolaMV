from dataclasses import dataclass
import queue
import threading
import time
from .processing import ProcessingOptions, process
from .storage import save_tiff


@dataclass(frozen=True)
class SaveRequest:
    page: str
    directory: str
    prefix: str
    timestamp: bool


class Pipeline:
    """Bounded queues, newest live preview, and loss-reported external saves."""
    def __init__(self):
        self.camera = None
        self.running = threading.Event()
        self.capture_done = threading.Event()
        self.jobs = queue.Queue(maxsize=4)
        self.saves = queue.Queue(maxsize=4)
        self.events = queue.Queue()
        self.lock = threading.Lock()
        self.latest = None
        self.live = None
        self.options = ProcessingOptions()
        self.save_request = None
        self.auto_save = False
        self.received = self.processed = self.skipped = self.saved = self.transport_gaps = 0
        self.last_id = None
        self.last_received = 0
        self.threads = []
        self.save_shutdown = threading.Event()
        self.writer = threading.Thread(target=self._save_loop, name='TIFF writer', daemon=True)
        self.writer.start()

    def configure(self, options, request, auto_save):
        with self.lock:
            self.options, self.save_request, self.auto_save = options, request, auto_save

    def start(self, camera):
        if self.running.is_set() or any(t.is_alive() for t in self.threads):
            raise RuntimeError('上一次采集仍在结束，请稍候')
        self.camera = camera
        self.capture_done.clear()
        self.last_id = None
        self.live = self.latest = None
        camera.start()
        self.running.set()
        self.threads = [threading.Thread(target=self._capture, name='Camera receive', daemon=True),
                        threading.Thread(target=self._process, name='Polarization processing', daemon=True)]
        for t in self.threads:
            t.start()

    def _capture(self):
        try:
            while self.running.is_set():
                raw = self.camera.read()
                if raw is None:
                    continue
                self.received += 1
                self.last_received = time.monotonic()
                if self.last_id is not None and raw.frame_id > self.last_id + 1:
                    gap = raw.frame_id - self.last_id - 1
                    self.transport_gaps += gap
                    self.events.put(('warning', f'相机帧号出现缺口：{gap} 帧，当前 Frame {raw.frame_id}'))
                self.last_id = raw.frame_id
                with self.lock:
                    request, options = self.save_request, self.options
                    external = raw.metadata.get('TriggerMode') == 'On' and raw.metadata.get('TriggerSource') not in ('Software', None)
                    auto = self.auto_save and external
                    job = (raw, options, request if auto else None)
                    if not auto:
                        if self.live is not None:
                            self.skipped += 1
                        self.live = job
                if auto:
                    try:
                        self.jobs.put_nowait(job)
                    except queue.Full:
                        raise RuntimeError(f'自动保存处理队列已满，Frame {raw.frame_id} 未保存。已停止接收；请降低触发频率。')
        except Exception as exc:
            self.events.put(('error', str(exc)))
            self.running.clear()
        finally:
            self.capture_done.set()

    def _process(self):
        while not self.capture_done.is_set() or not self.jobs.empty() or self.live is not None:
            queued = False
            try:
                job = self.jobs.get_nowait()
                queued = True
            except queue.Empty:
                with self.lock:
                    job, self.live = self.live, None
            if job is None:
                time.sleep(.003)
                continue
            raw, options, request = job
            try:
                frame = process(raw, options)
                self.processed += 1
                with self.lock:
                    self.latest = frame
                if request:
                    self.enqueue_save(frame, request)
            except Exception as exc:
                self.events.put(('error', f'Frame {raw.frame_id} 处理/保存失败：{exc}'))
                if request:
                    self.running.clear()
            finally:
                if queued:
                    self.jobs.task_done()

    def take_latest(self):
        with self.lock:
            frame, self.latest = self.latest, None
        return frame

    def enqueue_save(self, frame, request):
        try:
            self.saves.put_nowait((frame, request))
        except queue.Full:
            raise RuntimeError(f'TIFF 写入队列已满，Frame {frame.source.frame_id} 未保存；请降低触发频率')

    def _save_loop(self):
        while not self.save_shutdown.is_set() or not self.saves.empty():
            try:
                frame, request = self.saves.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                path = save_tiff(frame, request.page, request.directory, request.prefix, request.timestamp)
                self.saved += 1
                self.events.put(('saved', str(path)))
            except Exception as exc:
                self.events.put(('error', f'Frame {frame.source.frame_id} TIFF 保存失败：{exc}'))
                self.running.clear()
            finally:
                self.saves.task_done()

    def stop(self):
        self.running.clear()
        for thread in self.threads:
            thread.join()
        try:
            if self.camera:
                self.camera.stop()
        finally:
            self.threads = []

    def close(self):
        try:
            self.stop()
        finally:
            self.save_shutdown.set()
            self.writer.join()
