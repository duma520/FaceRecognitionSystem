# -*- coding: utf-8 -*-
"""逐个策略抓同一窗口，打印真实结果，定位哪种方式可用/为何失败"""
import os
import sys
import time

os.environ.pop('QT_QPA_PLATFORM', None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import numpy as np
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout
from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtCore import Qt
import FaceRecognitionSystem as M

app = QApplication(sys.argv)
w = QWidget()
w.setWindowTitle('抓屏探针_中文_XYZ')
w.resize(420, 320)
w.move(200, 180)
pal = w.palette()
pal.setColor(QPalette.Window, QColor(210, 25, 25))
w.setAutoFillBackground(True)
w.setPalette(pal)
lay = QVBoxLayout(w)
lab = QLabel("PROBE")
lab.setStyleSheet("color: white; font-size: 26px;")
lab.setAlignment(Qt.AlignCenter)
lay.addWidget(lab)
w.show()
w.raise_()
w.activateWindow()
for _ in range(30):
    app.processEvents()
    time.sleep(0.03)

M.FaceRecognitionApp.delayed_init = lambda self: None
frs = M.FaceRecognitionApp()
title = w.windowTitle()
h = frs._resolve_window_handle(title, None)
rect = frs._window_rect(h)
print('title=', repr(title), 'hwnd=', hex(h), 'rect=', rect)
print('dpi_scale=', frs._screen_dpi_scale())

for m in M.CAPTURE_METHODS:
    try:
        img = frs._capture_by_method(m, h, rect)
    except Exception as e:
        print(f'{m:22s} EXC {e}')
        continue
    if img is None:
        print(f'{m:22s} None')
    else:
        print(f'{m:22s} shape={img.shape} max={int(img.max())} mean={img.mean():.1f} '
              f'usable={M.frame_is_usable(img)} content={M.frame_is_usable(img, require_content=True)}')

# 直接验证 PrintWindow 的返回值
import ctypes
import win32gui
import win32ui
from ctypes import wintypes
left, top, right, bottom = rect
width, height = right - left, bottom - top
hwndDC = win32gui.GetWindowDC(h)
mfcDC = win32ui.CreateDCFromHandle(hwndDC)
saveDC = mfcDC.CreateCompatibleDC()
bmp = win32ui.CreateBitmap()
print('CreateCompatibleBitmap ->', bmp.CreateCompatibleBitmap(mfcDC, width, height))
saveDC.SelectObject(bmp)
ctypes.windll.user32.PrintWindow.restype = wintypes.BOOL
r2 = ctypes.windll.user32.PrintWindow(wintypes.HWND(h), wintypes.HDC(saveDC.GetSafeHdc()), ctypes.c_uint(2))
r0 = ctypes.windll.user32.PrintWindow(wintypes.HWND(h), wintypes.HDC(saveDC.GetSafeHdc()), ctypes.c_uint(0))
print('PrintWindow(2) ->', r2, ' PrintWindow(0) ->', r0)
info = bmp.GetInfo()
print('bitmap info:', {k: info[k] for k in ('bmWidth', 'bmHeight', 'bmBitsPixel', 'bmWidthBytes')})
bits = bmp.GetBitmapBits(True)
arr = np.frombuffer(bits, dtype=np.uint8).reshape((info['bmHeight'], info['bmWidth'], 4))
print('after PrintWindow(0): max=', int(arr.max()), 'mean=', float(arr.mean()))
win32gui.DeleteObject(bmp.GetHandle())
saveDC.DeleteDC()
mfcDC.DeleteDC()
win32gui.ReleaseDC(h, hwndDC)

print('--- capture_window_diagnose 调试 ---')
win_log_before = frs.log_text.toPlainText().count('\n')
ok = frs.capture_window_diagnose()
log_text = frs.log_text.toPlainText()
new_lines = log_text.splitlines()[win_log_before:]
print('ok_diag =', ok)
print('新增日志行数 =', len(new_lines))
for line in new_lines:
    print(line)
sys.stdout.flush()
os._exit(0)
