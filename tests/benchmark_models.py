# -*- coding: utf-8 -*-
"""对比 buffalo_l 与 buffalo_sc 在本机的实际检测耗时（纯 CPU 场景的关键决策依据）"""
import os
import statistics
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import cv2
import numpy as np
import FaceRecognitionSystem as M
from insightface.app import FaceAnalysis

img = np.full((1080, 1920, 3), 45, dtype=np.uint8)
cv2.rectangle(img, (300, 200), (520, 520), (210, 190, 180), -1)
cv2.circle(img, (400, 330), 40, (90, 80, 70), -1)

M.install_ort_session_options(M.make_ort_session_options(0))
result = {}
for name in ('buffalo_l', 'buffalo_sc'):
    print(f"\n=== {name} ===")
    t0 = time.perf_counter()
    fa = FaceAnalysis(name=name, root=ROOT, providers=['CPUExecutionProvider'])
    fa.prepare(ctx_id=0, det_thresh=0.5, det_size=(480, 480))
    print(f"  加载 {time.perf_counter() - t0:.1f}s")
    try:
        sess = next(m.session for k, m in fa.models.items() if hasattr(m, 'session'))
        print("  providers:", sess.get_providers())
    except Exception:
        pass
    fa.get(img)
    ts = []
    for _ in range(3):
        t = time.perf_counter()
        faces = fa.get(img)
        ts.append((time.perf_counter() - t) * 1000)
    result[name] = statistics.mean(ts)
    print(f"  get(1920x1080) 平均 {result[name]:.0f}ms  (检出 {len(faces)} 张脸)")
    del fa

if 'buffalo_l' in result and 'buffalo_sc' in result and result['buffalo_sc'] > 0:
    print(f"\n结论：buffalo_sc 比 buffalo_l 快 {result['buffalo_l'] / result['buffalo_sc']:.1f} 倍"
          f"（{result['buffalo_l']:.0f}ms → {result['buffalo_sc']:.0f}ms）")
sys.stdout.flush()
os._exit(0)
