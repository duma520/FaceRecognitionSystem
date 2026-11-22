# tests/ — 回归测试目录（v2.0.0 起）

本目录存放**可重复运行的自检/回归脚本**，保证每次升级都不丢功能、不丢设置。
所有脚本都可以在任意工作目录下运行，脚本内部会自动切到项目根目录。

> 约定：脚本产生的临时文件（备份、临时数据库、日志）一律写入 **`temp\`** 子目录，
> 不在项目根目录留垃圾文件。

## 脚本清单

| 脚本 | 作用 | 命令 |
| --- | --- | --- |
| `test_settings_persistence.py` | 离屏回归测试（70 条断言）：设置实时保存、启动回填、关闭兜底、`.env` 密钥分离、损坏配置安全失败、gbk 重定向下日志不崩、`delayed_init` 链路 | `venv\Scripts\python.exe -u tests\test_settings_persistence.py` |
| `test_e2e_startup.py` | 端到端：真实加载 ONNX 模型，验证"配置的检测阈值/尺寸确实作用于 `det_model`"（非循环论证），事件循环与退出保存 | `venv\Scripts\python.exe -u tests\test_e2e_startup.py` |
| `test_capture_pipeline.py` | **窗口捕获回归（24 条断言，需要真实桌面会话）**：中文标题枚举、hwnd 绑定、真实抓屏（尺寸/非全黑/颜色判定）、8 级策略链、**打瞎窗口类抓屏后仍能靠屏幕裁剪兜底**、诊断、标题变化后继续抓屏 | `venv\Scripts\python.exe -u tests\test_capture_pipeline.py` |
| `test_acceleration.py` | **加速与检测线程回归（46 条断言，需要真实桌面会话）**：GPU/provider 探测、后端自动选择与回退、ONNX 会话选项（线程数/顺序执行）、OpenCV 线程收敛、**检测线程回传结果 / 丢帧不排队 / 界面事件处理 <50ms**、新设置项持久化 | `venv\Scripts\python.exe -u tests\test_acceleration.py` |
| `static_check.py` | 静态自检：语法、**类内重复方法**（历史上多个设置失效的根因）、设置项覆盖度、硬编码密钥扫描 | `venv\Scripts\python.exe tests\static_check.py` |
| `diagnose_capture.py` | **人工排查工具**（非自动测试）：造一个测试窗口，逐个抓屏策略打印 `shape / max / 是否可用`，用于现场定位"抓不到画面" | `venv\Scripts\python.exe -u tests\diagnose_capture.py` |
| `benchmark_performance.py` | **人工性能基准**：加速能力报告 + 各检测尺寸单帧耗时 + 优化建议 | `venv\Scripts\python.exe -u tests\benchmark_performance.py` |
| `benchmark_models.py` | **人工性能基准**：对比 `buffalo_l` / `buffalo_sc` 在本机的实际单帧耗时，决定是否换轻量模型 | `venv\Scripts\python.exe -u tests\benchmark_models.py` |

> `test_capture_pipeline.py` 与 `test_acceleration.py` 必须使用真实 windows 平台插件：
> **不要**设置 `QT_QPA_PLATFORM=offscreen`（离屏平台没有真实窗口，抓屏无从测试）。

## 使用要求

1. 先做备份：脚本会自动把 `config.json` / `.env` 备份到 `temp\` 并在结束时还原。
   **若脚本崩溃（非 0 退出），务必检查 `config.json` 是否被还原**；
   项目根目录 `version\config - <版本> 升级前基线备份.json` 是权威基线。
2. 运行前建议先备份主程序到 `version\`（见 `软件升级迭代记录.md` 的固定流程）。
3. 每次改动设置相关逻辑 / `ConfigManager` / `delayed_init` / `closeEvent`，
   必须重跑 `test_settings_persistence.py` + `static_check.py`。

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 全部通过 |
| `1` | 存在失败断言 / 静态检查发现问题 |
| `3` | 脚本自身异常（含 Python 异常、初始化失败） |
