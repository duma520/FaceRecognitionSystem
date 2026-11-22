# -*- coding: utf-8 -*-
"""回归测试：设置实时保存 / 持久化 / 敏感信息分离 / 初始化链路（v2.0.0）

运行（在项目根目录或任意目录均可）：
    venv\\Scripts\\python.exe -u tests\\test_settings_persistence.py

特点：
  * 离屏运行（QT_QPA_PLATFORM=offscreen），不弹窗；
  * 自动备份并还原 config.json / .env，备份文件放在 temp\\ 下；
  * 使用 temp\\ 下的临时数据库，不触碰真实 face_database.db；
  * 覆盖 v2.0.0 修复的每一个"设置不生效/不保存"问题点，共 60+ 条断言。
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
TEMP_DIR = os.path.join(ROOT, 'temp')
os.makedirs(TEMP_DIR, exist_ok=True)
os.chdir(ROOT)
sys.path.insert(0, ROOT)

CFG = os.path.join(ROOT, 'config.json')
ENVF = os.path.join(ROOT, '.env')
CFG_BAK = os.path.join(TEMP_DIR, 'config.json.pretest')
ENV_BAK = os.path.join(TEMP_DIR, '.env.pretest')
PRETEST_DB = os.path.join(TEMP_DIR, 'fr_test.db')

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))
    print(('  [PASS] ' if cond else '  [FAIL] ') + name + ('' if cond else f'  -> {detail}'))
    sys.stdout.flush()


def read_cfg():
    with io.open(CFG, encoding='utf-8') as f:
        return json.load(f)


def main():
    # ---------- 0. 备份现场 ----------
    shutil.copy2(CFG, CFG_BAK)
    if os.path.exists(ENVF):
        shutil.copy2(ENVF, ENV_BAK)
    if os.path.exists(PRETEST_DB):
        os.remove(PRETEST_DB)
    os.environ['FACE_DB_PATH'] = PRETEST_DB

    probe = dict(read_cfg())
    probe.update({
        'model_name': 'buffalo_s', 'det_thresh': 82, 'det_interval': 750,
        'det_size': '800x800', 'low_performance_mode': True, 'detect_interval': 9,
        'roi_threshold': 0.22, 'min_roi_area': 900, 'enable_preprocess': False,
        'max_display': 23, 'enable_color': False, 'show_detect_box': False,
        'auto_save_unknown': True, 'performance_mode': 'manual', 'debug_mode': True,
        'window_geometry': None, 'proxy_settings': None, 'last_window': None,
    })
    with io.open(CFG, 'w', encoding='utf-8') as f:
        json.dump(probe, f, ensure_ascii=False, indent=4)

    # ---------- 1. 模块导入与 .env 加载 ----------
    print('\n=== 1. 模块导入与 .env 加载 ===')
    import FaceRecognitionSystem as M
    check('VERSION 形如 x.y.z', re.match(r'^\d+\.\d+\.\d+$', str(getattr(M, 'VERSION', ''))),
          getattr(M, 'VERSION', None))
    check('APP_TITLE 含 VERSION（版本号单一来源）', M.VERSION in M.APP_TITLE, M.APP_TITLE)
    check('.env 已加载', isinstance(M.ENV, dict) and M.ENV_FILE.endswith('.env'), M.ENV_FILE)
    check('env_get 读取 .env', M.env_get('FACE_DB_PATH') == PRETEST_DB, M.env_get('FACE_DB_PATH'))

    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)

    # ---------- 2. 启动：config.json -> 界面（核心回归点） ----------
    print('\n=== 2. 启动把 config.json 回填到界面 ===')
    real_delayed = M.FaceRecognitionApp.delayed_init
    # 关闭自动初始化，避免测试窗口的 singleShot 定时器互相干扰；Phase 6 会显式调用真实实现
    M.FaceRecognitionApp.delayed_init = lambda self: None
    win = M.FaceRecognitionApp()

    check('self.model_name 采纳配置', win.model_name == 'buffalo_s', win.model_name)
    check('模型下拉框采纳配置', win.model_combo.currentText() == 'buffalo_s', win.model_combo.currentText())
    check('self.det_size 采纳配置', win.det_size == (800, 800), str(win.det_size))
    check('检测尺寸下拉框采纳配置', win.det_size_combo.currentText() == '800x800', win.det_size_combo.currentText())
    check('检测阈值采纳配置', win.thresh_spin.value() == 82, win.thresh_spin.value())
    check('检测间隔采纳配置', win.interval_spin.value() == 750, win.interval_spin.value())
    check('self.detection_interval 采纳配置', win.detection_interval == 750, win.detection_interval)
    check('完整检测间隔采纳配置', win.detect_interval_spin.value() == 9, win.detect_interval_spin.value())
    check('ROI阈值采纳配置', win.roi_thresh_spin.value() == 22, win.roi_thresh_spin.value())
    check('最小ROI面积采纳配置', win.min_roi_spin.value() == 900, win.min_roi_spin.value())
    check('显示数量采纳配置(不再被强制为10)', win.max_display == 23 and win.max_display_spin.value() == 23,
          f'max_display={win.max_display} spin={win.max_display_spin.value()}')
    check('图像预处理采纳配置', win.preprocess_check.isChecked() is False)
    check('低性能模式采纳配置', win.low_perf_check.isChecked() is True and win.low_performance_mode is True)
    check('自动存未知人脸采纳配置', win.auto_save_check.isChecked() is True)
    check('检测框采纳配置', win.detect_box_check.isChecked() is False)
    check('彩色显示采纳配置', win.color_check.isChecked() is False)
    check('性能模式采纳配置', win.performance_mode_combo.currentText() == '手动')
    check('调试模式采纳配置', win.debug_check.isChecked() is True)
    check('DEBUG_PRINT 由配置驱动', M.DEBUG_PRINT is True, M.DEBUG_PRINT)
    check('窗口标题含 VERSION', M.VERSION in win.windowTitle(), win.windowTitle())

    guarded = ('model_name', 'det_thresh', 'det_interval', 'det_size', 'low_performance_mode',
               'detect_interval', 'roi_threshold', 'min_roi_area', 'enable_preprocess',
               'max_display', 'enable_color', 'show_detect_box', 'auto_save_unknown',
               'performance_mode', 'debug_mode')
    after_boot = read_cfg()
    drift = {k: (probe[k], after_boot.get(k)) for k in guarded if probe[k] != after_boot.get(k)}
    check('启动过程没有反向覆盖用户配置', not drift, str(drift))

    # ---------- 3a. 参数类控件 -> 实时落盘 ----------
    print('\n=== 3a. 参数类设置即时写入 config.json ===')
    win.performance_mode_combo.setCurrentText('手动')      # 保证处于手动模式
    win.low_perf_check.setChecked(False)                  # 手动模式取消低性能 -> 设计上联动 640/500/70
    win.thresh_spin.setValue(90)
    win.interval_spin.setValue(300)
    win.det_size_combo.setCurrentText('320x320')
    win.detect_interval_spin.setValue(3)
    win.roi_thresh_spin.setValue(18)
    win.min_roi_spin.setValue(700)

    live = read_cfg()
    check('det_thresh 已落盘', live.get('det_thresh') == 90, live.get('det_thresh'))
    check('det_interval 已落盘', live.get('det_interval') == 300, live.get('det_interval'))
    check('det_size 已落盘', live.get('det_size') == '320x320', live.get('det_size'))
    check('detect_interval 已落盘(原连接被注释的项)', live.get('detect_interval') == 3, live.get('detect_interval'))
    check('roi_threshold 已落盘', abs(float(live.get('roi_threshold', 0)) - 0.18) < 1e-6, live.get('roi_threshold'))
    check('min_roi_area 已落盘', live.get('min_roi_area') == 700, live.get('min_roi_area'))
    check('self.det_size 与界面一致', win.det_size == (320, 320), win.det_size)
    check('self.min_roi_area 与界面一致', win.min_roi_area == 700, win.min_roi_area)
    check('self.roi_threshold 与界面一致', abs(win.roi_threshold - 0.18) < 1e-6, win.roi_threshold)
    check('self.detect_interval 与界面一致', win.detect_interval == 3, win.detect_interval)
    check('.tmp 原子写临时文件已清理', not os.path.exists(CFG + '.tmp'))

    # ---------- 3b. 开关类控件 -> 实时落盘 ----------
    print('\n=== 3b. 开关类设置即时写入 config.json ===')
    win.max_display_spin.setValue(7)
    win.preprocess_check.setChecked(True)
    win.auto_save_check.setChecked(False)
    win.detect_box_check.setChecked(True)
    win.color_check.setChecked(True)
    win.debug_check.setChecked(False)
    live = read_cfg()
    check('max_display 已落盘', live.get('max_display') == 7, live.get('max_display'))
    check('max_display 内存值同步(原只写配置)', win.max_display == 7, win.max_display)
    check('enable_preprocess 已落盘', live.get('enable_preprocess') is True)
    check('auto_save_unknown 已落盘', live.get('auto_save_unknown') is False)
    check('show_detect_box 已落盘', live.get('show_detect_box') is True)
    check('enable_color 已落盘', live.get('enable_color') is True)
    check('debug_mode 已落盘', live.get('debug_mode') is False)
    check('DEBUG_PRINT 跟随调试开关', M.DEBUG_PRINT is False, M.DEBUG_PRINT)

    # ---------- 3c. 手动模式"低性能"联动 + 持久化 ----------
    print('\n=== 3c. 手动模式下"低性能"复选框（原被同名方法覆盖）===')
    win.low_perf_check.setChecked(True)
    live = read_cfg()
    check('low_performance_mode=True 已落盘', live.get('low_performance_mode') is True, live.get('low_performance_mode'))
    check('手动模式勾选低性能 -> 联动 480x480', live.get('det_size') == '480x480', live.get('det_size'))
    check('手动模式勾选低性能 -> 联动 1000ms', live.get('det_interval') == 1000, live.get('det_interval'))
    check('手动模式勾选低性能 -> 联动 阈值75', live.get('det_thresh') == 75, live.get('det_thresh'))
    check('复选框状态 -> 内存值同步', win.low_performance_mode is True)

    # ---------- 3d. 性能模式 + 上次使用的窗口 ----------
    print('\n=== 3d. 性能模式与"上次使用的窗口"持久化 ===')
    win.performance_mode_combo.setCurrentText('自动')
    win.window_combo.addItem('__smoke_test_window__')
    win.window_combo.setCurrentText('__smoke_test_window__')
    live = read_cfg()
    check('performance_mode 已落盘', live.get('performance_mode') == 'auto', live.get('performance_mode'))
    check('last_window 已落盘(原从未连接)', live.get('last_window') == '__smoke_test_window__', live.get('last_window'))

    # ---------- 4. 关闭时兜底保存窗口几何 ----------
    print('\n=== 4. 关闭程序保存窗口几何 ===')
    win.setGeometry(150, 160, 1280, 860)
    win.close()
    closed = read_cfg()
    check('window_geometry 已保存', bool(closed.get('window_geometry')), str(closed.get('window_geometry'))[:40])
    check('关闭后 model_name 仍保留', closed.get('model_name') == 'buffalo_s', closed.get('model_name'))

    # ---------- 5. 敏感信息只进 .env ----------
    print('\n=== 5. 敏感信息只进 .env（需求8）===')
    win2 = M.FaceRecognitionApp()
    win2.config.set('proxy_settings', {
        'type': 'socks5', 'url': 'socks5://127.0.0.1:1080',
        'host': '127.0.0.1', 'port': 1080, 'user': 'tester', 'password': 'SMOKE_SECRET',
    })
    disk = read_cfg()
    check('config.json 中代理密码为空串', (disk.get('proxy_settings') or {}).get('password') == '',
          (disk.get('proxy_settings') or {}).get('password'))
    env_text = io.open(ENVF, encoding='utf-8').read()
    check('.env 中写入 PROXY_PASSWORD', 'PROXY_PASSWORD=SMOKE_SECRET' in env_text)
    cm = M.ConfigManager(CFG)
    cm.load_config()
    check('重新加载后密码从 .env 回填', (cm.get('proxy_settings') or {}).get('password') == 'SMOKE_SECRET',
          (cm.get('proxy_settings') or {}).get('password'))
    cm.set('proxy_settings', None)
    win2.close()

    # ---------- 5b. 历史未知键保留 ----------
    print('\n=== 5b. 配置文件中的历史未知键保留 ===')
    raw = read_cfg()
    raw['_legacy_unknown_setting'] = 'keep-me'
    with io.open(CFG, 'w', encoding='utf-8') as f:
        json.dump(raw, f, ensure_ascii=False, indent=4)
    cm2 = M.ConfigManager(CFG)
    cm2.load_config()
    check('加载时保留历史未知键', cm2.get('_legacy_unknown_setting') == 'keep-me',
          cm2.get('_legacy_unknown_setting'))
    cm2.set('det_thresh', 66)
    check('保存后历史未知键仍写回文件', read_cfg().get('_legacy_unknown_setting') == 'keep-me',
          read_cfg().get('_legacy_unknown_setting'))

    # ---------- 5c. 健壮性：损坏配置 + gbk 重定向编码（v2.0.0 审计发现） ----------
    print('\n=== 5c. 健壮性：损坏配置 / gbk 重定向下的日志 ===')
    # (1) 配置文件是非法 JSON 时必须"安全失败"：返回 False、备份 .corrupt、绝不抛异常
    with io.open(CFG, 'w', encoding='utf-8') as f:
        f.write('{ 这不是合法 JSON,,, }')
    cm3 = M.ConfigManager(CFG)
    raised = None
    try:
        result = cm3.load_config()
    except Exception as e:
        raised, result = e, None
    check('损坏配置不抛异常（返回 False）', raised is None and result is False, f'raised={raised!r}')
    check('损坏配置已备份为 .corrupt', os.path.exists(CFG + '.corrupt'))
    if os.path.exists(CFG + '.corrupt'):
        os.remove(CFG + '.corrupt')

    # (2) 模拟 stdout 被重定向为 gbk 编码（build\\2_debug.bat 的场景）：
    #     emoji 日志不得抛 UnicodeEncodeError，也不能中断业务逻辑
    import io as _io
    _buf = _io.BytesIO()
    _gbk_stream = _io.TextIOWrapper(_buf, encoding='gbk', newline='')
    _old_stdout = sys.stdout
    gbk_ok = True
    try:
        sys.stdout = _gbk_stream
        M.safe_print('✅ ⚠️ ❌ emoji 日志测试')
        M.debug_print('debug 关闭时应静默')
        cm4 = M.ConfigManager(CFG)
        cm4.load_config()          # 已损坏的配置文件在 gbk 流下也必须安全失败
        cm4.set('det_thresh', 71)  # 保存路径也不得抛异常
    except Exception as e:
        gbk_ok = False
        _gbk_stream.seek(0)
        _err = repr(e)
    finally:
        sys.stdout = _old_stdout
    if not gbk_ok:
        print(f'    gbk 流下发生异常: {_err}')
    check('gbk 重定向下 emoji 日志不抛异常', gbk_ok)

    # 复原探针配置，进入下一阶段
    with io.open(CFG, 'w', encoding='utf-8') as f:
        json.dump(probe, f, ensure_ascii=False, indent=4)

    # ---------- 6. delayed_init 初始化链路（跳过真实模型下载） ----------
    print('\n=== 6. delayed_init 初始化链路 ===')
    M.FaceRecognitionApp.check_and_download_model = lambda self: self.log_message('模型检查已跳过(测试)')
    win3 = M.FaceRecognitionApp()
    real_delayed(win3)                     # 直接调用真实实现，不 patch delayed_init 本身
    check('face_db 创建成功', getattr(win3, 'face_db', None) is not None)
    check('face_db 使用 .env 指定路径', os.path.abspath(win3.face_db.db_path) == os.path.abspath(PRETEST_DB),
          win3.face_db.db_path)
    check('内存监控已启动', win3.memory_monitor.isRunning())
    check('CPU/FPS 定时器已启动', win3.cpu_monitor.isActive() and win3.fps_timer.isActive())
    check('init_ui 幂等标记', win3._ui_built is True)
    check('delayed_init 只执行一次', win3._initialized is True)
    win3.delayed_init()                    # 重复调用应被拒绝（不会重建数据库/线程）
    check('重复 delayed_init 不重建数据库', win3.face_db.db_path == PRETEST_DB)
    check('FaceDatabase.log_message 已补齐', callable(getattr(win3.face_db, 'log_message', None)))
    r = win3.face_db.search_face(None)
    check('search_face 非法入参不再抛异常', isinstance(r, dict) and r.get('name') is None, str(r))
    win3.close()
    app.processEvents()

    failed = [r for r in results if not r[1]]
    print(f"\n================= 结果：{len(results) - len(failed)}/{len(results)} 通过 =================")
    for name, ok, detail in failed:
        print(f"  ❌ {name}  {detail}")
    return 1 if failed else 0


if __name__ == '__main__':
    code = 1
    try:
        code = main()
    except Exception:
        import traceback
        traceback.print_exc()
        code = 3
    finally:
        try:
            if os.path.exists(CFG_BAK):
                shutil.move(CFG_BAK, CFG)
            if os.path.exists(ENV_BAK):
                shutil.move(ENV_BAK, ENVF)
            for extra in (CFG + '.tmp', CFG + '.corrupt'):
                if os.path.exists(extra):
                    os.remove(extra)
            if os.path.exists(PRETEST_DB):
                os.remove(PRETEST_DB)
        except Exception as e:
            print(f'还原现场失败: {e}')
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
