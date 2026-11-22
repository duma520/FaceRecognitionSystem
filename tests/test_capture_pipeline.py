# -*- coding: utf-8 -*-
"""窗口捕获回归测试（v2.0.1）

针对用户反馈"选择进程/窗口后未能获得图像"，逐条验证：

  A. 窗口枚举使用宽字符 API —— 中文标题不再是乱码（历史 BUG 的根因）
  B. 按标题解析 HWND（FindWindowW）
  C. 真实抓屏：能拿到正确窗口、正确尺寸、非全黑的画面
  D. 捕获策略链生效，并记录实际使用的方式
  E. **最终兜底**：把窗口类抓屏（PrintWindow/BitBlt）全部打瞎后，
     仍能通过"整屏截图 + 裁剪"拿到画面
  F. 诊断功能可用（逐个策略给出结果）
  G. 不传 hwnd、只给标题也能抓（标题匹配增强）
  H. 窗口标题动态变化后，靠 hwnd 缓存仍能继续抓

运行（需要真实桌面会话，不能设 QT_QPA_PLATFORM=offscreen）：
    venv\\Scripts\\python.exe -u tests\\test_capture_pipeline.py
"""
import io
import json
import os
import shutil
import sys
import time

os.environ.pop('QT_QPA_PLATFORM', None)     # 必须用真实 windows 平台插件

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
TEMP_DIR = os.path.join(ROOT, 'temp')
os.makedirs(TEMP_DIR, exist_ok=True)
os.chdir(ROOT)
sys.path.insert(0, ROOT)

CFG = os.path.join(ROOT, 'config.json')
CFG_BAK = os.path.join(TEMP_DIR, 'config.json.capture.pretest')
WINDOW_TITLE = '捕获测试_中文标题_ABC'

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))
    print(('  [PASS] ' if cond else '  [FAIL] ') + name + ('' if cond else f'  -> {detail}'))
    sys.stdout.flush()


def main():
    shutil.copy2(CFG, CFG_BAK)

    from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout
    from PyQt5.QtGui import QPalette, QColor
    from PyQt5.QtCore import Qt

    import FaceRecognitionSystem as M

    app = QApplication(sys.argv)

    # ---------- 造一个颜色醒目的真实窗口 ----------
    widget = QWidget()
    widget.setWindowTitle(WINDOW_TITLE)
    widget.resize(420, 320)
    widget.move(200, 180)
    pal = widget.palette()
    pal.setColor(QPalette.Window, QColor(210, 25, 25))       # 纯红底，便于判定"抓的是这个窗口"
    widget.setAutoFillBackground(True)
    widget.setPalette(pal)
    lay = QVBoxLayout(widget)
    label = QLabel("CAPTURE-TEST")
    label.setStyleSheet("color: white; font-size: 26px;")
    label.setAlignment(Qt.AlignCenter)
    lay.addWidget(label)
    widget.show()
    widget.raise_()
    widget.activateWindow()
    for _ in range(30):
        app.processEvents()
        time.sleep(0.03)

    # 测试用实例：关掉 delayed_init（不需要加载模型/数据库）
    M.FaceRecognitionApp.delayed_init = lambda self: None
    win = M.FaceRecognitionApp()

    # ---------- A. 中文标题枚举 ----------
    print('\n=== A. 宽字符窗口枚举（中文标题）===')
    windows = M.enum_windows_unicode()
    check('枚举到窗口', len(windows) > 0, len(windows))
    exact = [w for w in windows if w[0] == WINDOW_TITLE]
    check('枚举结果包含本测试窗口且标题完全一致（无乱码）', len(exact) == 1,
          [w[0] for w in windows if '捕获测试' in w[0]] or [w[0] for w in windows[:5]])
    mojibake = [w[0] for w in windows if '锟' in w[0] or '\ufffd' in w[0] or '鎹' in w[0]]
    check('枚举结果中没有乱码标题', not mojibake, mojibake[:3])
    hwnd_from_enum = exact[0][1] if exact else 0
    pid_from_enum = exact[0][2] if exact else 0
    check('枚举返回有效 hwnd/pid', hwnd_from_enum > 0 and pid_from_enum > 0,
          f'hwnd={hwnd_from_enum} pid={pid_from_enum}')

    # ---------- A2. 真实用户流程：刷新 → 选择 ----------
    print('\n=== A2. 下拉框刷新与选择（宽字符标题 + 绑定 hwnd）===')
    win.refresh_windows()
    combo_idx = win.window_combo.findText(WINDOW_TITLE)
    if combo_idx >= 0:
        win.window_combo.setCurrentIndex(combo_idx)
    app.processEvents()
    combo_hwnd = win.window_combo.currentData()
    check('下拉框能找到本测试窗口', combo_idx >= 0, combo_idx)
    check('下拉项绑定了真实 hwnd（不再依赖标题匹配）',
          bool(combo_hwnd) and int(combo_hwnd) == hwnd_from_enum,
          f'{combo_hwnd} vs {hwnd_from_enum}')
    check('下拉项标题未被进程名污染（仍是纯标题）',
          win.window_combo.currentText() == WINDOW_TITLE, win.window_combo.currentText())
    tip = win.window_combo.itemData(combo_idx, Qt.ToolTipRole) if combo_idx >= 0 else None
    check('下拉项悬停提示含进程名/HWND（便于区分同名窗口）',
          bool(tip) and 'HWND' in str(tip), tip)

    # ---------- B. 标题 -> HWND ----------
    print('\n=== B. 按标题解析 HWND ===')
    check('FindWindowW 能找到窗口', M.find_window_unicode(WINDOW_TITLE) > 0)
    resolved = win._resolve_window_handle(WINDOW_TITLE, None)
    check('_resolve_window_handle 解析成功', resolved == hwnd_from_enum,
          f'{resolved} vs {hwnd_from_enum}')
    check('无效标题返回 0（不抛异常）',
          win._resolve_window_handle('绝对不存在的窗口标题_ZZZ', None) == 0)

    # ---------- C. 真实抓屏 ----------
    print('\n=== C. 真实抓屏 ===')
    frame = win.capture_window(WINDOW_TITLE, hwnd_from_enum)
    check('抓到画面', frame is not None)
    if frame is not None:
        h, w = frame.shape[:2]
        check('画面尺寸与窗口一致(±40px)', abs(w - 420) <= 40 and abs(h - 320) <= 40,
              f'{w}x{h}')
        check('画面非全黑', int(frame.max()) > 8, int(frame.max()))
        # 判定颜色：窗口是红底，抓到的图应明显偏红
        b, g, r = (float(frame[..., i].mean()) for i in range(3))
        check('画面确实是该窗口（红色为主）', r > 80 and r > g * 1.3 and r > b * 1.3,
              f'B={b:.1f} G={g:.1f} R={r:.1f}')

    # ---------- D. 策略链 ----------
    print('\n=== D. 捕获策略链 ===')
    used = getattr(win, '_capture_strategy', None)
    check('记录了实际使用的捕获方式', used in M.CAPTURE_METHODS, used)
    print(f'    本次使用: {M.CAPTURE_METHOD_DESC.get(used, used)}')

    # ---------- E. 最终兜底（打瞎所有窗口类抓屏） ----------
    print('\n=== E. 最终兜底：窗口类抓屏全部失败时仍能出图 ===')
    real_gdi = win._grab_window_gdi
    win._grab_window_gdi = lambda *a, **k: None          # PrintWindow / BitBlt 全失败
    win._capture_strategy = None
    try:
        fallback = win.capture_window(WINDOW_TITLE, hwnd_from_enum)
        used_fb = getattr(win, '_capture_strategy', None)
    finally:
        win._grab_window_gdi = real_gdi
    check('兜底后仍抓到画面', fallback is not None)
    check('兜底走的是屏幕裁剪类策略', used_fb in ('qt_screen_crop', 'gdi_screen_crop',
                                                'pil_screen_crop', 'graphics_capture'), used_fb)
    print(f'    兜底使用: {M.CAPTURE_METHOD_DESC.get(used_fb, used_fb)}')
    if fallback is not None:
        b, g, r = (float(fallback[..., i].mean()) for i in range(3))
        check('兜底画面尺寸合理', abs(fallback.shape[1] - 420) <= 40, fallback.shape)
        print(f'    兜底画面颜色: B={b:.1f} G={g:.1f} R={r:.1f}（被其它窗口遮挡时可能非红底）')

    # ---------- F. 诊断 ----------
    print('\n=== F. 捕获诊断 ===')
    ok_diag = win.capture_window_diagnose()
    check('诊断至少找到一种可用方式', ok_diag is True)
    log_text = win.log_text.toPlainText()
    missing = [m for m in M.CAPTURE_METHODS if M.CAPTURE_METHOD_DESC[m] not in log_text]
    check('诊断结果列出了全部 8 种方式', not missing, missing)

    # ---------- G. 只给标题（不传 hwnd） ----------
    print('\n=== G. 只按标题抓取 ===')
    win._capture_strategy = None
    win._window_hwnd_cache = {}
    by_title = win.capture_window(WINDOW_TITLE)
    check('仅凭标题也能抓到画面', by_title is not None)

    # ---------- H. 标题动态变化 + hwnd 缓存 ----------
    print('\n=== H. 标题变化后仍能继续抓取 ===')
    cached_hwnd = hwnd_from_enum
    widget.setWindowTitle(WINDOW_TITLE + ' - 新标题片段')
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)
    # 模拟"下拉列表里还是旧标题、但句柄已被绑定"的真实场景
    win._window_hwnd_cache = {WINDOW_TITLE: cached_hwnd}
    after_rename = win.capture_window(WINDOW_TITLE, None)
    check('标题变化后靠缓存句柄仍能抓到画面', after_rename is not None)
    # 旧的乱码标题也应能被"包含匹配"救回来
    win._window_hwnd_cache = {}
    recovered = win.capture_window('捕获测试_中文标题')      # 标题的前缀
    check('标题不完全一致时靠包含匹配可以找到窗口', recovered is not None)

    widget.close()
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
