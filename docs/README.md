# docs/ — 文档与图片归档目录

| 文件 | 说明 |
| --- | --- |
| `优化方案.txt` | 早期（1.x 时代）记录的功能优化想法，已归档保留 |
| `临时修改记录.txt` | 早期临时记录文件（内容为空），保留占位 |
| `龙虾.jpg` | 早期说明/演示图片，从项目根目录移入（v2.0.0 目录整理） |

> 项目主文档（**软件升级迭代记录.md**）按需求固定放在**项目根目录**，不放进本目录。

## 相关文档

- 根目录 `软件升级迭代记录.md`：版本历史、架构说明、运行逻辑记忆、设置持久化矩阵、已知问题清单、变更记录。
- `build/README.md`：构建/打包脚手架说明。
- `modules/README.md`：新增功能模块的目录规范。
- `tests/README.md`：回归测试说明。
- `logs/README.md`、`temp/README.md`、`release/README.md`：日志 / 临时文件 / 归档产物说明。

## 目录整理原则（v2.0.0 起）

项目根目录**只保留**：

1. 主程序 `FaceRecognitionSystem.py`（唯一编译入口，需求4）；
2. **两个调试/编译入口脚本（v2.1.1，用户要求放根目录方便双击）**：
   `0.bat`（编译主程序）、`1.bat`（激活 venv 运行/调试主程序）；
   两者内部用 `cd /d "%~dp0"` 定位自身目录，从任意工作目录调用都可用；
3. 文档：`软件升级迭代记录.md`；
4. 运行期必需且路径被代码写死的文件：`config.json`、`.env` / `.env.example`、`icon.ico`、`simhei.ttf`、`msyh.ttf`、`face_database.db`；
5. 运行期数据目录：`faces\`、`unknown_faces\`、`models\`、`datasets\`、`profiles\`、`backups\`。

其余一切都必须放进对应子目录：脚手架 → `build\`（`0.bat`/`1.bat` 是唯一例外），测试 → `tests\`，
临时文件 → `temp\`，日志 → `logs\`，独立工具 → `tools\`，
历史版本 → `version\`，已编译成品 → `release\`，新功能模块 → `modules\`。
