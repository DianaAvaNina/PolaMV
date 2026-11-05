import colorsys
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets


def make_lut(name):
    if name == 'HSV':
        return np.array([colorsys.hsv_to_rgb(i/255, .88, .96) for i in range(256)]).__mul__(255).astype(np.uint8)
    anchors = {
        'Viridis': ['440154', '482878', '3e4989', '31688e', '26828e', '1f9e89', '35b779', '6ece58', 'b5de2b', 'fde725'],
        'Cividis': ['00224e', '123570', '3b496c', '575d6d', '707173', '8b8678', 'a59c74', 'c3b369', 'e1cc55', 'fee838'],
        'Twilight': ['e2d9e2', '91b0c1', '6481bb', '634991', '441f54', '301437', '682447', 'a44950', 'ca8066', 'd9bba3', 'e2d9e2'],
    }[name]
    a = np.array([[int(s[i:i+2], 16) for i in (0, 2, 4)] for s in anchors])
    return np.stack([np.interp(np.linspace(0, len(a)-1, 256), np.arange(len(a)), a[:, k]) for k in range(3)], axis=1).astype(np.uint8)


def render(frame, page, settings):
    if page in ('RAW', 'Gray'):
        data = frame.source.raw if page == 'RAW' else frame.gray
        return np.ascontiguousarray(np.clip(data * (255.0 / ((1 << frame.source.bits)-1)), 0, 255).astype(np.uint8))
    data = frame.aolp if page == 'AoLP' else frame.dolp
    value = (data+90)/180 if page == 'AoLP' else data
    lut = make_lut(settings.aolp_map if page == 'AoLP' else settings.dolp_map)
    invalid = ~np.isfinite(value)
    index = (np.clip(np.nan_to_num(value, nan=0), 0, 1)*255).astype(np.uint8)
    rgb = lut[index]
    color = QtGui.QColor(settings.nan_color)
    rgb[invalid] = (color.red(), color.green(), color.blue())
    return np.ascontiguousarray(rgb)


def qimage(data):
    h, w = data.shape[:2]
    fmt = QtGui.QImage.Format_Grayscale8 if data.ndim == 2 else QtGui.QImage.Format_RGB888
    return QtGui.QImage(data.data, w, h, data.strides[0], fmt).copy()


class ImageView(QtWidgets.QGraphicsView):
    pixel = QtCore.Signal(int, int)
    zoom_changed = QtCore.Signal(float)

    def __init__(self):
        super().__init__()
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.item = self.scene().addPixmap(QtGui.QPixmap())
        self.setMouseTracking(True)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.fit_mode = True
        self.setBackgroundBrush(QtGui.QColor('#0a111c'))

    def set_image(self, data):
        old = self.item.pixmap().size()
        self.item.setPixmap(QtGui.QPixmap.fromImage(qimage(data)))
        self.scene().setSceneRect(self.item.boundingRect())
        if self.fit_mode or old != self.item.pixmap().size():
            self.fit()

    def fit(self):
        self.fit_mode = True
        if not self.item.pixmap().isNull():
            self.fitInView(self.item, QtCore.Qt.KeepAspectRatio)
            self.zoom_changed.emit(self.transform().m11())

    def actual(self):
        self.fit_mode = False
        self.resetTransform()
        self.zoom_changed.emit(1.)

    def wheelEvent(self, event):
        scale = 1.2 if event.angleDelta().y() > 0 else 1/1.2
        if .01 <= self.transform().m11()*scale <= 128:
            self.fit_mode = False
            self.scale(scale, scale)
            self.zoom_changed.emit(self.transform().m11())
        event.accept()

    def mouseMoveEvent(self, event):
        point = self.mapToScene(event.pos())
        self.pixel.emit(int(np.floor(point.x())), int(np.floor(point.y())))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.pixel.emit(-1, -1)
        super().leaveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit()


class ColorBar(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(56)
        self.page, self.settings = 'RAW', None

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setPen(QtGui.QColor('#bdcbdc'))
        if self.page in ('RAW', 'Gray'):
            p.drawText(self.rect(), QtCore.Qt.AlignCenter, '线性灰度显示 · TIFF 保存原始有效位深数据')
            return
        lut = make_lut(self.settings.aolp_map if self.page == 'AoLP' else self.settings.dolp_map)
        rect = QtCore.QRect(18, 5, max(20, self.width()-230), 14)
        p.drawImage(rect, qimage(lut[np.newaxis, :, :]))
        labels = ('−90°', '0°', '+90°') if self.page == 'AoLP' else ('0%', '50%', '100%')
        for x, label in zip((rect.left(), rect.center().x()-12, rect.right()-32), labels):
            p.drawText(x, 38, label)
        p.fillRect(rect.right()+24, 5, 14, 14, QtGui.QColor(self.settings.nan_color))
        p.drawText(rect.right()+44, 17, '无效 / NaN')


class Histogram(QtWidgets.QWidget):
    toggled = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(280, 260)
        self.frame = None
        self.four = False
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip('点击切换总体灰度 / 四方向原始采样直方图')

    def mousePressEvent(self, event):
        self.toggled.emit()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor('#111d2d'))
        if self.frame is None:
            p.setPen(QtGui.QColor('#8fa1b6'))
            p.drawText(self.rect(), QtCore.Qt.AlignCenter, '等待图像\n点击切换直方图模式')
            return
        indices = range(1, 5) if self.four else (0,)
        names = ('Gray · 总体', '0° · 原始', '45° · 原始', '90° · 原始', '135° · 原始')
        for position, index in enumerate(indices):
            columns = 2 if self.four else 1
            rows = 2 if self.four else 1
            cell = QtCore.QRectF((position%columns)*self.width()/columns, (position//columns)*self.height()/rows, self.width()/columns, self.height()/rows)
            graph = cell.adjusted(12, 35, -12, -27)
            hist = self.frame.histograms[index]
            bins = max(2, min(len(hist), int(graph.width())))
            edges = np.linspace(0, len(hist), bins+1).astype(int)
            values = np.array([hist[edges[i]:edges[i+1]].sum() for i in range(bins)])
            peak = max(1, int(values.max()))
            p.setPen(QtGui.QColor('#c2d1e3'))
            p.drawText(cell.adjusted(12, 2, -5, 0), QtCore.Qt.AlignTop, f'{names[index]}\n峰值 {peak:,} 像素/显示桶')
            path = QtGui.QPainterPath(QtCore.QPointF(graph.left(), graph.bottom()))
            for i, value in enumerate(values):
                path.lineTo(graph.left()+i*graph.width()/(bins-1), graph.bottom()-value/peak*graph.height())
            path.lineTo(graph.right(), graph.bottom())
            p.fillPath(path, QtGui.QColor('#266f83'))
            p.setPen(QtGui.QPen(QtGui.QColor('#55d4c2'), 1))
            p.drawPath(path)
            p.setPen(QtGui.QColor('#8fa1b6'))
            p.drawText(int(graph.left()), int(graph.bottom()+19), '0')
            p.drawText(int(graph.right()-45), int(graph.bottom()+19), str((1 << self.frame.source.bits)-1))
