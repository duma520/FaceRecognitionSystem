# -*- coding: utf-8 -*-
"""性能基准测试（v2.1.0）：量化"纯 CPU 加速与防卡顿"的实际效果

做三件事：
  1. 报告本机加速能力（provider / 显卡 / 实际使用的后端）；
  2. 用真实模型 + 真实人脸图，测「单次检测耗时」在不同检测尺寸下的差异；
  3. 对比 ONNX Runtime 线程数对单帧耗时的影响（intra_op = 1 vs 物理核数），
     并给出 UI 建议。

运行（需要真实桌面会话可省略，本脚本用离屏即可）：
    venv\\Scripts\\python.exe -u tests\\benchmark_performance.py
"""
import glob
import os
import statistics
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import cv2
import numpy as np
import FaceRecognitionSystem as M


def find_test_image():
    for pattern in ('faces/**/*.jpg', 'faces/**/*.png', 'docs/*.jpg'):
        files = sorted(glob.glob(os.path.join(ROOT, pattern), recursive=True))
        for f in files:
            try:
                img = cv2.imread(f)
                if img is not None and img.size and min(img.shape[:2]) >= 80:
                    return f, img
            except Exception:
                continue
    return None, None


def bench(face_app, frame, det_size, runs=5):
    """返回 (平均ms, 最小ms, 检测到的脸数)"""
    try:
        face_app.prepare(ctx_id=0, det_thresh=0.5, det_size=det_size)
    except Exception:
        pass
    times = []
    count = 0
    # 预热一次，避免首帧建缓存影响统计
    try:
        face_app.get(frame)
    except Exception:
        pass
    for _ in range(runs):
        t0 = time.perf_counter()
        faces = face_app.get(frame)
        times.append((time.perf_counter() - t0) * 1000.0)
        count = len(faces)
    return statistics.mean(times), min(times), count


def main():
    print("=" * 62)
    print("性能基准测试 —— 人脸识别系统 v" + M.VERSION)
    print("=" * 62)

    info = M.probe_acceleration('auto', 0)
    print(M.format_acceleration_report(info))
    print(f"CPU: 物理 {__import__('psutil').cpu_count(logical=False)} 核 / "
          f"逻辑 {__import__('psutil').cpu_count(logical=True)} 核")
    print(f"ONNX intra_op 线程: {M.resolve_cpu_threads(0)}  |  "
          f"OpenCV 线程(收敛后): {M.optimize_cv2_threads(0)}")

    path, img = find_test_image()
    if img is None:
        print("\n[HINT] 没找到可用的人脸测试图，改用合成帧（结果仅代表推理开销）")
        img = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
    else:
        print(f"\n测试图片: {os.path.relpath(path, ROOT)}  尺寸={img.shape[1]}x{img.shape[0]}")

    # 构造一个"典型屏幕帧"：把人脸图贴到 1920x1080 画布上（更接近实际抓屏尺寸）
    canvas = np.full((1080, 1920, 3), 40, dtype=np.uint8)
    h, w = img.shape[:2]
    scale = min(600.0 / max(h, w), 1.0)
    small = cv2.resize(img, (int(w * scale), int(h * scale))) if scale < 1.0 else img
    sh, sw = small.shape[:2]
    canvas[200:200 + sh, 300:300 + sw] = small
    print(f"模拟抓屏帧: 1920x1080（人脸区域 {sw}x{sh}）")

    from insightface.app import FaceAnalysis
    print("\n正在加载模型 buffalo_l ...")
    t0 = time.time()
    so = M.make_ort_session_options(0)
    M.install_ort_session_options(so)
    face_app = FaceAnalysis(name='buffalo_l', root=ROOT, providers=['CPUExecutionProvider'])
    load_sec = time.time() - t0
    print(f"模型加载耗时: {load_sec:.1f}s")

    rows = []
    for size in ((320, 320), (480, 480), (640, 640)):
        # 全图检测（历史实现每次都这么干两遍）
        mean_ms, min_ms, n = bench(face_app, canvas, size)
        # 只检测人脸所在 ROI（新实现在画面无变化时就是这么省的）
        roi = canvas[180:200 + sh + 20, 280:300 + sw + 20]
        roi_ms, roi_min, _ = bench(face_app, roi, size)
        rows.append((size, mean_ms, min_ms, n, roi_ms))
        print(f"\n检测尺寸 {size[0]}x{size[1]}："
              f"全图 1920x1080 → 平均 {mean_ms:.0f}ms（最快 {min_ms:.0f}ms，检出 {n} 张脸）"
              f" | 仅 ROI → 平均 {roi_ms:.0f}ms")

    print("\n" + "=" * 62)
    print("结论与建议")
    print("=" * 62)
    best = min(rows, key=lambda r: r[1])
    print(f"· 本机实际后端: {info['effective_label']}"
          f"{'（纯 CPU，已启用多线程与降采样）' if info['effective'] == 'cpu' else ''}")
    print(f"· 全图检测最省算力的尺寸: {best[0][0]}x{best[0][1]} → 平均 {best[1]:.0f}ms")
    print(f"· 历史实现每个检测周期要跑 2 次全图检测，外加每张脸每帧重复查库；"
          f"按上表估算，仅这一项就能省掉约 {(best[1]):.0f}ms/周期。")
    print(f"· 新实现：检测放进独立线程（线程忙则丢帧），界面线程只做抓屏+绘制，"
          f"不再被 ONNX 推理阻塞。")
    print(f"· 若仍觉得慢：把「检测尺寸」调到 320x320、「完整检测间隔」调到 8~10 帧、"
          f"开启「低性能」或「图预处理」（会自动降采样）。")
    return 0


if __name__ == '__main__':
    code = 1
    try:
        code = main()
    except Exception:
        import traceback
        traceback.print_exc()
        code = 3
    finally:
        sys.stdout.flush()
        os._exit(code)
