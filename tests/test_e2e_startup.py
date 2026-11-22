# -*- coding: utf-8 -*-
"""端到端验证：不做任何 monkeypatch，走真实启动链路

覆盖：真实 ONNX 模型加载 -> 检测参数真正生效 -> 事件循环 -> 关闭保存设置。

运行：
    venv\\Scripts\\python.exe -u tests\\test_e2e_startup.py

注意：需要 models\\ 下已有对应模型文件（默认 buffalo_l），否则会走下载流程。
"""
import io
import json
import os
import shutil
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
TEMP_DIR = os.path.join(ROOT, 'temp')
os.makedirs(TEMP_DIR, exist_ok=True)
os.chdir(ROOT)
sys.path.insert(0, ROOT)

CFG = os.path.join(ROOT, 'config.json')
CFG_BAK = os.path.join(TEMP_DIR, 'config.json.e2e.pretest')
E2E_DB = os.path.join(TEMP_DIR, 'fr_e2e.db')

fail = []


def check(name, cond, detail=''):
    print(('  [PASS] ' if cond else '  [FAIL] ') + name + ('' if cond else f' -> {detail}'))
    sys.stdout.flush()
    if not cond:
        fail.append(name)


def main():
    if os.path.exists(E2E_DB):
        os.remove(E2E_DB)
    os.environ['FACE_DB_PATH'] = E2E_DB
    shutil.copy2(CFG, CFG_BAK)

    cfg = json.load(io.open(CFG, encoding='utf-8'))
    cfg.update({'model_name': 'buffalo_l', 'det_size': '480x480', 'det_thresh': 78,
                'det_interval': 600, 'performance_mode': 'manual', 'low_performance_mode': False,
                'debug_mode': False, 'max_display': 15, 'window_geometry': None})
    json.dump(cfg, io.open(CFG, 'w', encoding='utf-8'), ensure_ascii=False, indent=4)

    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QTimer
    import FaceRecognitionSystem as M

    app = QApplication(sys.argv)
    win = M.FaceRecognitionApp()
    win.show()
    check('窗口标题含 VERSION（版本号单一来源）', M.VERSION in win.windowTitle(), win.windowTitle())

    win.delayed_init()          # 真实初始化，内部会加载 ONNX 模型
    check('模型加载成功(face_app 非空)', win.face_app is not None)
    check('加载的是配置指定的模型', win.model_name == 'buffalo_l', win.model_name)
    check('配置的检测尺寸真正作用于模型',
          tuple(win.face_app.det_size) == (480, 480), tuple(win.face_app.det_size))
    check('配置的检测阈值真正作用于模型',
          abs(float(win.face_app.det_thresh) - 0.78) < 1e-6, win.face_app.det_thresh)
    # 关键：face_app.det_size/det_thresh 是 init_face_recognition 自己赋的值（循环论证），
    # 必须检查真正参与推理的 det_model.input_size / det_model.det_thresh。
    det_model = getattr(win.face_app, 'det_model', None)
    check('检测器输入尺寸真正生效 (det_model.input_size)',
          det_model is not None and tuple(det_model.input_size) == (480, 480),
          None if det_model is None else tuple(det_model.input_size))
    check('检测器阈值真正生效 (det_model.det_thresh)',
          det_model is not None and abs(float(det_model.det_thresh) - 0.78) < 1e-6,
          None if det_model is None else det_model.det_thresh)
    check('数据库已连接', getattr(win.face_db, 'conn', None) is not None)

    win.window_combo.addItem('__e2e__')
    win.window_combo.setCurrentText('__e2e__')
    win.color_check.setChecked(False)
    QTimer.singleShot(1200, app.quit)
    app.exec_()
    check('事件循环正常退出', True)

    win.setGeometry(120, 130, 1200, 800)
    win.close()
    saved = json.load(io.open(CFG, encoding='utf-8'))
    check('关闭后 model_name 保留', saved.get('model_name') == 'buffalo_l', saved.get('model_name'))
    check('关闭后 det_size 保留', saved.get('det_size') == '480x480', saved.get('det_size'))
    check('关闭后 last_window 保留', saved.get('last_window') == '__e2e__', saved.get('last_window'))
    check('关闭后 enable_color 保留', saved.get('enable_color') is False, saved.get('enable_color'))
    check('关闭后 window_geometry 已写入', bool(saved.get('window_geometry')))

    print(f"\n=== 端到端结果：{'全部通过' if not fail else '存在失败: ' + str(fail)} ===")
    return 1 if fail else 0


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
        if os.path.exists(E2E_DB):
            os.remove(E2E_DB)
        sys.stdout.flush()
        os._exit(code)
