# modules/ — 新功能模块目录规范（v2.0.0）

## 为什么要有这个目录

需求4：`FaceRecognitionSystem.py`（项目根目录）是**最终更新版和唯一编译入口**，
所以它必须始终保持「可编译、可运行、逻辑自洽」。

需求5：**脚手架与新增功能模块都要放进子目录**，避免主程序继续膨胀成难以维护的单文件。

因此约定：

- **主程序** `FaceRecognitionSystem.py`：只保留启动流程、类定义与调度逻辑；
  新功能优先写成独立模块放在本目录下，再由主程序 `import`。
- **禁止**在根目录继续新增 `.py` 业务文件、`.bat` 构建脚本、临时脚本。

## 目录约定

```
modules/
├── core/     核心业务：人脸库读写、特征向量检索、模型管理、采集与识别管线
├── ui/       界面组件：对话框、面板、自定义控件（PyQt5）
└── utils/    通用工具：配置/日志/路径/图像处理等无状态工具
```

## 接入方式

主程序根目录运行，`modules` 作为普通包被导入：

```python
from modules.utils.config_manager import ConfigManager
from modules.core.face_database import FaceDatabase
```

- 每个子目录放一个 `__init__.py`（保持可导入、可被 PyInstaller 收集）。
- 模块内部**不要**在 import 阶段创建 QWidget / 连数据库，把副作用放到 `init()` 里。
- 新增模块后，需要在 `build\FaceRecognitionSystem.spec` 的 `hiddenimports`
  里补上模块名（若使用了动态导入），并同步更新 `软件升级迭代记录.md`。

## 迁移节奏

采用「新功能新目录、老代码渐进搬迁」策略：

1. 本版本（v2.0.0）只建立目录与规范，不改动既有类的物理位置，保证 0 回归风险。
2. 后续每个版本搬迁 1~2 个自洽的类（优先 `utils` → `core` → `ui`），
   每次搬迁都必须：备份到 `version\`、跑通启动冒烟测试、更新迭代记录。
