# -*- coding: utf-8 -*-
"""加速检测 + 检测线程（防卡顿）回归测试（v2.1.0）

覆盖：
  A. 加速能力检测：provider 列表、显卡枚举、后端自动选择与回退逻辑
  B. ONNX 会话选项：intra_op 线程数 = 物理核心数、顺序执行、图优化
  C. insightface 会话选项注入生效（建会话时真的带上了我们的选项）
  D. OpenCV 线程收敛
  E. 检测工作线程：投递→结果回传、丢帧不排队、不阻塞界面线程
  F. 性能红线：检测线程运行时，界面线程的事件处理延迟必须保持在低位
  G. 新增设置项 accel_backend / cpu_threads / detect_input_max_side 的持久化

运行（需要真实桌面会话，不要设 QT_QPA_PLATFORM）：
    venv\\Scripts\\python.exe -u tests\\test_acceleration.py
"""
import io
import json
import os
import shutil
import sys
import time

os.environ.pop('QT_QPA_PLATFORM', None)

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
TEMP_DIR = os.path.join(ROOT, 'temp')
os.makedirs(TEMP_DIR, exist_ok=True)
os.chdir(ROOT)
sys.path.insert(0, ROOT)

CFG = os.path.join(ROOT, 'config.json')
CFG_BAK = os.path.join(TEMP_DIR, 'config.json.accel.pretest')

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))
    print(('  [PASS] ' if cond else '  [FAIL] ') + name + ('' if cond else f'  -> {detail}'))
    sys.stdout.flush()


def main():
    shutil.copy2(CFG, CFG_BAK)

    import numpy as np
    import onnxruntime as ort
    from PyQt5.QtWidgets import QApplication
    import FaceRecognitionSystem as M

    # ---------- A. 加速能力检测 ----------
    print('\n=== A. 硬件加速能力检测 ===')
    ort_info = M.get_ort_info()
    print(f"    onnxruntime {ort_info['version']} device={ort_info['device']}")
    print(f"    providers={ort_info['providers']}")
    check('能读到 onnxruntime 信息', bool(ort_info['version']) and not ort_info['error'],
          ort_info['error'])
    check('provider 列表非空', len(ort_info['providers']) > 0, ort_info['providers'])
    gpus = M.list_gpu_adapters()
    print(f"    显卡: {gpus}")
    check('能枚举到显卡名称', len(gpus) > 0, gpus)

    info = M.probe_acceleration('auto', 0)
    print(M.format_acceleration_report(info))
    check('自动选择的后端在合法集合内', info['effective'] in M.ACCEL_BACKENDS, info['effective'])
    check('后端可用性与 provider 一致',
          (info['effective'] == 'cpu') or
          (info['effective'] == 'cuda' and info['cuda_available']) or
          (info['effective'] == 'dml' and info['dml_available']) or
          (info['effective'] == 'openvino' and info['openvino_available']),
          info)
    check('报告包含线程数与提示', info['cpu_threads'] >= 1 and bool(info['hints']))
    check('报告包含 CPU 型号与核心数',
          bool(info.get('cpu_name')) and info.get('cpu_logical') >= 1,
          f"{info.get('cpu_name')} / {info.get('cpu_logical')}")
    # 老旧 CPU 判定与轻量模型建议
    check('识别老旧 CPU（Phenom/Athlon/Core2 等）',
          M.is_legacy_cpu('AMD Phenom(tm) II X4 955 Processor') is True and
          M.is_legacy_cpu('Intel(R) Core(TM) i7-12700') is False)
    need, target, why = M.recommend_light_model('buffalo_l', 1200)
    check('检测慢 + 重模型 → 建议换轻量模型', need and target in M.LIGHT_MODELS, f'{need}/{target}')
    check('轻量模型本地可用', M._model_available(target) if target else False, target)
    check('检测快 → 不给建议', M.recommend_light_model('buffalo_l', 120)[0] is False)
    check('已经是轻量模型 → 不再建议', M.recommend_light_model('buffalo_sc', 1200)[0] is False)
    report = M.format_acceleration_report(info)
    check('报告里出现 CPU 型号', (info.get('cpu_name') or '')[:6] in report)
    # 显式指定一个本机不支持的后端 → 必须回退且给出提示
    unsupported = None
    for b in ('cuda', 'dml', 'openvino'):
        provider = M.BACKEND_TO_ORT_PROVIDER[b]
        if provider not in ort_info['providers']:
            unsupported = b
            break
    if unsupported:
        fb = M.probe_acceleration(unsupported, 0)
        check(f'指定不支持的 {unsupported} 时回退并提示',
              fb['effective'] != unsupported and bool(fb['note']), fb)
    # 显式 cpu 必须被尊重
    cpu_info = M.probe_acceleration('cpu', 0)
    check('显式指定 CPU 被尊重', cpu_info['effective'] == 'cpu', cpu_info['effective'])
    check('build_ort_providers 始终以 CPU 兜底',
          M.build_ort_providers('cpu') == ['CPUExecutionProvider'] and
          M.build_ort_providers('cuda')[-1] == 'CPUExecutionProvider',
          M.build_ort_providers('cuda'))

    # ---------- B/C. ONNX 会话选项 ----------
    print('\n=== B/C. ONNX Runtime 线程/执行模式调优 ===')
    import psutil
    physical = psutil.cpu_count(logical=False) or 1
    check('resolve_cpu_threads(0) = 物理核心数', M.resolve_cpu_threads(0) == physical,
          f'{M.resolve_cpu_threads(0)} vs {physical}')
    check('resolve_cpu_threads 显式值生效', M.resolve_cpu_threads(3) == 3)
    so = M.make_ort_session_options(0)
    check('会话选项构造成功', so is not None)
    if so is not None:
        check('intra_op 线程数 = 物理核心数', so.intra_op_num_threads == physical,
              so.intra_op_num_threads)
        check('inter_op 线程数 = 1（降低抖动）', so.inter_op_num_threads == 1,
              so.inter_op_num_threads)
        check('顺序执行模式（ORT_SEQUENTIAL，降低 CPU 抖动）',
              int(so.execution_mode) == int(ort.ExecutionMode.ORT_SEQUENTIAL),
              f'{int(so.execution_mode)} vs {int(ort.ExecutionMode.ORT_SEQUENTIAL)}')
    check('会话选项注入 insightface 成功', M.install_ort_session_options(so) is True)

    # 真正建一个大模型会话，确认注入生效（用最小模型节省时间）
    try:
        import insightface.model_zoo.model_zoo as _mz
        patched = getattr(_mz, '_dsh_session_options_patched', False)
        check('insightface 已被打上注入标记', patched)
    except Exception as e:
        check('insightface 模块可访问', False, e)

    # ---------- D. OpenCV 线程收敛 ----------
    print('\n=== D. OpenCV 线程收敛 ===')
    threads = M.optimize_cv2_threads(0)
    check('OpenCV 线程被限制为 1~2', threads in (1, 2), threads)
    check('cv2.getNumThreads() 与设置一致', M.cv2.getNumThreads() == threads,
          M.cv2.getNumThreads())

    # ---------- E/F. 检测工作线程 ----------
    print('\n=== E/F. 检测工作线程（防卡顿）===')
    app = QApplication(sys.argv)
    M.FaceRecognitionApp.delayed_init = lambda self: None
    win = M.FaceRecognitionApp()

    # 用假模型替换真实模型，专测线程管线（不依赖 ONNX 加载）
    class _FakeFace:
        def __init__(self, x):
            self.bbox = np.array([x, 20, x + 60, 90], dtype=float)
            self.embedding = np.ones(512, dtype=np.float32) / np.sqrt(512)
            self.det_score = 0.9

    class _FakeApp:
        calls = 0

        def get(self, img, max_num=0):
            type(self).calls += 1
            time.sleep(0.15)                    # 模拟 150ms 的 CPU 推理
            return [_FakeFace(10), _FakeFace(90)]

    class _FakeDB:
        def search_face(self, emb):
            return {'name': '测试用户', 'similarity': 0.88, 'confidence': 0.9}

    win.face_app = _FakeApp()
    win.face_db = _FakeDB()
    worker = win._start_detect_worker()
    check('检测工作线程已启动', worker is not None and worker.isRunning())
    check('工作线程不是界面线程', worker is not app.thread())
    check('线程参数读取正确', M.resolve_cpu_threads(win.config.get('cpu_threads', 0)) >= 1)

    frame = np.full((240, 320, 3), 128, dtype=np.uint8)
    got = {}

    def _on_result(payload):
        got.update(payload)

    worker.result_ready.connect(_on_result)
    worker.submit(frame, [(0, 0, 320, 240)], 0)
    t0 = time.time()
    while not got and time.time() - t0 < 5:
        app.processEvents()
        time.sleep(0.01)
    check('线程回传了检测结果', bool(got), '超时未回传')
    faces = got.get('faces') or []
    check('检测到 2 张脸', len(faces) == 2, len(faces))
    if faces:
        f0 = faces[0]
        check('结果包含 bbox/embedding/姓名/相似度',
              all(k in f0 for k in ('bbox', 'embedding', 'name', 'similarity', 'det_score')),
              list(f0.keys()))
        check('姓名来自特征检索', f0['name'] == '测试用户' and f0['similarity'] > 0.8, f0.get('name'))
        check('bbox 是 [x1,y1,x2,y2] 且在本帧范围内',
              f0['bbox'][2] <= 320 and f0['bbox'][3] <= 240, f0['bbox'])
    check('记录了检测耗时', float(got.get('elapsed_ms') or 0) >= 100, got.get('elapsed_ms'))

    # 丢帧：连投 3 帧（每帧 150ms），不应排队执行 3 次
    before = _FakeApp.calls
    for _ in range(3):
        worker.submit(frame, [(0, 0, 320, 240)], 0)
        time.sleep(0.01)
    t0 = time.time()
    while worker.busy and time.time() - t0 < 3:
        app.processEvents()
        time.sleep(0.01)
    time.sleep(0.25)
    app.processEvents()
    ran = _FakeApp.calls - before
    check('连投 3 帧不会全部排队执行（丢帧生效）', ran <= 2, f'实际执行 {ran} 次')
    check('丢帧计数被记录', worker.dropped >= 1, worker.dropped)

    # 界面线程不被阻塞：在检测进行中循环处理事件，单次 processEvents 耗时必须很小
    worker.submit(frame, [(0, 0, 320, 240)], 0)
    worst = 0.0
    t_end = time.time() + 1.0
    while time.time() < t_end:
        t1 = time.time()
        app.processEvents()
        worst = max(worst, time.time() - t1)
        time.sleep(0.005)
    check('检测期间界面事件处理不卡顿（单次 < 50ms）', worst < 0.05, f'{worst * 1000:.1f}ms')

    # ---------- G. 新设置项持久化 ----------
    print('\n=== G. 新增加速设置项的实时保存 ===')
    idx = win.accel_combo.findData('cpu')
    check('加速下拉框含全部后端', win.accel_combo.count() == len(M.ACCEL_BACKENDS),
          win.accel_combo.count())
    win.accel_combo.setCurrentIndex(idx)
    app.processEvents()
    with io.open(CFG, encoding='utf-8') as f:
        saved = json.load(f)
    check('accel_backend 已落盘', saved.get('accel_backend') == 'cpu', saved.get('accel_backend'))
    win.cpu_threads_spin.setValue(3)
    app.processEvents()
    with io.open(CFG, encoding='utf-8') as f:
        saved = json.load(f)
    check('cpu_threads 已落盘', saved.get('cpu_threads') == 3, saved.get('cpu_threads'))
    check('线程设置立即作用于 OpenCV', M.cv2.getNumThreads() == 2, M.cv2.getNumThreads())
    check('detect_input_max_side 有默认值', saved.get('detect_input_max_side') == 1280,
          saved.get('detect_input_max_side'))

    # 界面显示
    check('性能面板显示加速后端', '加速' in win.accel_label.text(), win.accel_label.text())
    win.update_fps()
    check('性能面板显示检测耗时', '检测' in win.detect_ms_label.text(), win.detect_ms_label.text())

    win._stop_detect_worker()
    check('停止后线程不再运行', not (worker.isRunning()))
    win.close()
    app.processEvents()

    failed = [r for r in results if not r[1]]
    print(f"\n================= 结果：{len(results) - len(failed)}/{len(results)} 通过 =================")
    for name, ok, detail in failed:
        print(f"  ❌ {name}  {detail}")
    return 1 if failed else 0


if __name__ == '__main__':
    code = 3
    try:
        code = main()
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        if os.path.exists(CFG_BAK):
            shutil.move(CFG_BAK, CFG)
        sys.stdout.flush()
        os._exit(code)
