# FaceRecognitionSystem （见源码内 VERSION 常量）

> **一句话**：FaceRecognitionSystem —— 人脸数据库编辑器。
>
> **适合谁**：想直接用现成工具、不想自己写代码的 Windows 用户。
>
> **解决什么问题**：把「人脸数据库编辑器」这件事做成开箱即用的程序 —— 下载解压、装上依赖、双击就能跑。

---

## 目录

- [1. 这是什么](#1-这是什么)
- [2. 零基础入门（5 分钟跑起来）](#2-零基础入门5-分钟跑起来)
- [3. 功能与界面](#3-功能与界面)
- [4. 命令行参数](#4-命令行参数)
- [5. 配置文件与数据](#5-配置文件与数据)
- [6. 工作原理（技术参考）](#6-工作原理技术参考)
- [7. 排错手册](#7-排错手册)
- [8. 常见问题 FAQ](#8-常见问题-faq)
- [9. 目录结构](#9-目录结构)
- [10. 开发与构建](#10-开发与构建)
- [11. 已知限制与安全说明](#11-已知限制与安全说明)
- [12. 许可](#12-许可)

## 1. 这是什么

| 项目 | 说明 |
| --- | --- |
| 程序名 | `FaceRecognitionSystem` |
| 当前版本 | （见源码内 VERSION 常量） |
| 主程序 | `FaceRecognitionSystem.py` |
| 界面技术 | PyQt5（Qt5 社区绑定） |
| 语言 / 运行平台 | Python 3.10 / Windows |
| 源码规模 | 根目录及子模块共 27 个 .py 文件 |
| 仓库 | https://github.com/duma520/FaceRecognitionSystem |

## 2. 零基础入门（5 分钟跑起来）

### 第 1 步：装 Python

1. 打开 <https://www.python.org/downloads/windows/>，下载 Python 3.10 或更新版本。
2. 安装时**务必勾选** `Add python.exe to PATH`（安装向导第一页最下方）。
3. 装完按 `Win + R` 输入 `cmd`，敲 `python --version`，能看到版本号就成功了。

### 第 2 步：拿到源码

- **下载压缩包**：在本仓库 Releases 页下载 `FaceRecognitionSystem-*.zip`，解压到任意目录。
- **git 克隆**：`git clone https://github.com/duma520/FaceRecognitionSystem.git`

### 第 3 步：装依赖

在源码目录打开命令行，执行：

```
pip install Pillow PyQt5 appdirs comtypes cpuinfo diskcache fake_useragent insightface numba numpy onnxruntime opencv-python pinyin psutil pywin32 pywincffi requests socks zstandard
```

> 清单是从源码的实际 import 汇总出来的；若某个包名不准确，以 pip 报错提示的正确包名为准。

### 第 4 步：启动

```bat
python FaceRecognitionSystem.py
```

目录里还带了 `1.bat`，双击等同于上面的命令（前提是 Python 在 PATH 里）。

## 3. 功能与界面

> 本节只列源码里能确认的事实；具体按钮与交互以运行后的界面为准。

| 维度 | 实际情况 |
| --- | --- |
| 界面框架 | PyQt5（Qt5 社区绑定） |
| 是否有 main 入口 | 是，可直接 python 主程序.py 运行 |
| 第三方依赖数 | 19 个 |

### 版本变更（来自项目自带迭代记录）

| 版本 | 说明 |
| --- | --- |
| 8 | 同步"根目录例外：`0.bat` / `1.bat`"及原因 |
| 1 | 直接用系统 Python（`PATH` 里的 `python`）运行主程序 |
| 2 | 本机系统 Python **3.10.11** 与 `venv` 的依赖**完全一致、无缺失**（逐项导入检查：insightface / onnxruntime / cv2 / numpy / PyQt5 / PIL / win32gui / win32process / psutil / requests / pinyin / socks / fake_useragent / appdirs / comtypes / scipy / sklearn / albumentations / easydict / prettytable） |
| 3 | 脚本顶部 `set "USE_VENV=0"` 改成 `1` 即可，无需改动其它逻辑（已干跑验证 `USE_VENV=1` 分支正常走 `call venv\Scripts\activate.bat`） |
| 4 | 取消注释 `set "PYEXE=D:\Program Files\Python310\python.exe"` 即可指定任意解释器（含 `py -3.10` 等启动器写法） |
| 5 | 只执行 `python -c "import sys;…"`（毫秒级，刻意不做 InsightFace/cv2 这类重量级 import，避免每次启动多等几秒）；可拦住 Windows 商店的 `python` 占位程序 |
| 6 | 找不到解释器 → 提示三种解决办法；程序异常退出 → 打印 `pip install -r build\requirements.txt` 与 `USE_VENV` 说明，并 `pause` |
| 7 | 脚本头部 `cd /d "%~dp0"`，从任何工作目录调用都正确 |

## 4. 命令行参数

该程序没有定义命令行参数，直接运行即可（操作都在界面里完成）。

## 5. 配置文件与数据

源码目录里可见的配置/数据文件：

- `config.json`

这些文件在运行时读写；个人数据（路径、账号、历史记录）不会提交到仓库，由 .gitignore 排除，首次运行会自动生成。

## 6. 工作原理（技术参考）

```
用户操作 → PyQt5 → 业务逻辑 → 结果输出
```

- 入口文件 `FaceRecognitionSystem.py`，带 if __name__ == '__main__' 保护。
- 依赖的第三方库：`Pillow`、`PyQt5`、`appdirs`、`comtypes`、`cpuinfo`、`diskcache`、`fake_useragent`、`insightface`、`numba`、`numpy`、`onnxruntime`、`opencv-python`、`pinyin`、`psutil`、`pywin32`、`pywincffi`、`requests`、`socks`、`zstandard`。
- 全部业务逻辑在仓库内可见，没有编译产物、没有联网下发代码。

## 7. 排错手册

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| python 不是内部或外部命令 | 安装时没勾 PATH | 重装 Python 并勾选 Add python.exe to PATH，或改用 py 命令 |
| ModuleNotFoundError: No module named xxx | 依赖没装 | 按第 3 步 pip install 对应包 |
| 双击 .bat 一闪而过 | 出错后窗口立即关闭 | 用 cmd 进入目录再执行命令，看清报错 |
| 界面显示乱码 | 控制台编码不是 UTF-8 | 先执行 chcp 65001，或用 python -X utf8 主程序.py |
| 杀毒软件拦截 | 未签名脚本被误判 | 加入信任/白名单；本项目只提供源码，可自行审阅 |

## 8. 常见问题 FAQ

**Q1：需要装 Visual Studio 之类的编译工具吗？**
A：不需要。这里只提供 Python 源码，pip 装的是预编译轮子。

**Q2：能在 macOS / Linux 上跑吗？**
A：本项目按 Windows 环境开发与验证；其他系统未测试，可能需要改路径与系统 API 调用。

**Q3：为什么 Releases 里只有源码 zip，没有 exe？**
A：只分发源码，避免二进制被误判；需要 exe 请按第 10 节自行打包。

**Q4：改了代码怎么运行？**
A：直接 python 主程序.py，改动立即生效，无需编译。

**Q5：数据存在哪？会不会被上传？**
A：只存在本机（程序目录或用户目录）。本程序不含上传逻辑。

**Q6：怎么反馈问题？**
A：到 https://github.com/duma520/FaceRecognitionSystem/issues 提 Issue，附上报错原文与复现步骤。

## 9. 目录结构

```
backups/
datasets/
docs/
faces/
logs/
models/
modules/
profiles/
release/
temp/
tests/
tools/
unknown_faces/
venv/
.env
.env.example
0.bat
1.bat
FaceRecognitionSystem.py
Face_Database_Editor.py
README.md
config.json
face_database.db
icon.ico
msyh.ttf
simhei.ttf
软件升级迭代记录.md
backups\face_database - 1.0.0 迁移前备份.db
backups\face_database_backup_20250411_065638.db
backups\face_database_backup_20250413_060354.db
backups\face_database_backup_20250413_172719.db
backups\face_database_backup_20250413_174017.db
backups\face_database_backup_20250413_174035.db
backups\face_database_backup_20250416_000547.db
backups\face_database_backup_20250416_001610.db
backups\face_database_backup_20250416_001616.db
backups\face_database_backup_20250418_022407.db
docs\README.md
docs\临时修改记录.txt
docs\优化方案.txt
docs\龙虾.jpg
faces\7_7_a_ao/
faces\D_J_zhou_zhou/
faces\F_r_e_y_a_lai_lai/
faces\L_i_shi_qi_ya/
```

## 10. 开发与构建

- 直接运行（开发态）：`python FaceRecognitionSystem.py`
- 语法自检：`python -m py_compile FaceRecognitionSystem.py`
- 打包 exe（可选）：装 pyinstaller 后执行 `pyinstaller -F -w FaceRecognitionSystem.py`

## 11. 已知限制与安全说明

- 只提供源码，不提供预编译二进制。
- 仓库不含任何凭据；.env / *.pem / *.key / 日志与运行期数据均在 .gitignore 中排除。
- 若程序需要联网，请在源码中确认目标地址后再运行。

## 12. 许可

AGPL-3.0，详见仓库根目录 LICENSE。
