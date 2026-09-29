"""屏幕抓取与图片编码（纯 Qt 实现，多显示器合成到一张虚拟桌面图）。

坐标体系说明：
- Qt 的 QScreen.geometry() 是「逻辑坐标」（含缩放）；
- grabWindow 返回的是「物理像素」位图。
两者比值记作 scale，框选时用 scale 把逻辑坐标换算回物理像素再裁剪，
这样在 125%/150% 缩放的屏幕上裁出来的图不会错位。
"""

from __future__ import annotations

import base64

from PySide6.QtCore import QBuffer, QIODevice, QRect, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap

from app.logger import get

log = get("capture")


class CaptureError(Exception):
    pass


def virtual_geometry() -> QRect:
    """所有显示器的逻辑坐标并集。"""
    screens = QGuiApplication.screens()
    if not screens:
        raise CaptureError("没有检测到任何显示器。")
    rect = QRect(screens[0].geometry())
    for s in screens[1:]:
        rect = rect.united(s.geometry())
    return rect


def grab_virtual_desktop() -> tuple[QImage, float, QRect]:
    """抓取整个虚拟桌面。

    返回 (物理像素图, scale 逻辑->物理, 逻辑坐标并集)。
    """
    screens = QGuiApplication.screens()
    if not screens:
        raise CaptureError("没有检测到任何显示器。")
    union = virtual_geometry()
    primary = QGuiApplication.primaryScreen() or screens[0]
    scale = float(primary.devicePixelRatio() or 1.0)

    width = max(1, round(union.width() * scale))
    height = max(1, round(union.height() * scale))
    canvas = QImage(width, height, QImage.Format_RGB32)
    canvas.fill(Qt.black)

    painter = QPainter(canvas)
    try:
        for s in screens:
            geo = s.geometry()
            shot: QPixmap = s.grabWindow(0)
            if shot.isNull():
                log.warning("屏幕抓取返回空位图：%s", geo)
                continue
            target = QRect(
                round((geo.x() - union.x()) * scale),
                round((geo.y() - union.y()) * scale),
                round(geo.width() * scale),
                round(geo.height() * scale),
            )
            if shot.width() != target.width() or shot.height() != target.height():
                shot = shot.scaled(
                    target.width(), target.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation
                )
            painter.drawImage(target, shot.toImage())
    finally:
        painter.end()
    return canvas, scale, union


def crop_physical(image: QImage, rect: QRect) -> QImage:
    """按物理像素裁剪，自动夹在图像范围内。"""
    bounded = rect.intersected(QRect(0, 0, image.width(), image.height()))
    if bounded.width() <= 0 or bounded.height() <= 0:
        raise CaptureError("选择区域为空。")
    return image.copy(bounded)


def to_png_bytes(image: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    if not image.save(buf, "PNG"):
        raise CaptureError("截图编码为 PNG 失败。")
    return bytes(buf.data())


def encode_for_model(image: QImage, max_width: int = 1600, quality: int = 88) -> tuple[str, str]:
    """把截图压成适合上传的 JPEG，返回 (base64, mime)。

    原图（PNG）会单独存档用于历史回看，这里只负责给模型减小体积。
    """
    target = image
    if max_width > 0 and image.width() > max_width:
        target = image.scaledToWidth(max_width, Qt.SmoothTransformation)
    if target.format() != QImage.Format_RGB32:
        target = target.convertToFormat(QImage.Format_RGB32)
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    if not target.save(buf, "JPEG", max(40, min(95, int(quality)))):
        raise CaptureError("截图编码为 JPEG 失败。")
    data = bytes(buf.data())
    if not data:
        raise CaptureError("截图编码结果为空。")
    return base64.b64encode(data).decode("ascii"), "image/jpeg"
