# -*- coding: utf-8 -*-

# 全局调试打印控制
DEBUG_PRINT = False

def debug_print(*args, **kwargs):
    """调试打印函数（v2.0.0：加编码兜底，避免 gbk 重定向下抛异常）"""
    if DEBUG_PRINT:
        try:
            print(*args, **kwargs)
        except Exception:
            safe_print(*args, **kwargs)

import sys
import os

# ============================================================================
#  控制台编码加固（v2.0.0）
#  ---------------------------------------------------------------------------
#  当 stdout 被重定向到文件/管道时（例如 build\2_debug.bat 里的 > temp\debug.txt），
#  Python 会退回系统 locale 编码（中文 Windows 为 gbk），此时任何含 emoji 的 print
#  （"✅" "⚠️" "❌" 等）都会抛 UnicodeEncodeError，把"打一条日志"升级成
#  "启动失败 / 保存设置失败 / 退出时 PyQt 直接 abort"。
#  这里把标准流统一切到 UTF-8 并启用 replace，保证日志永远不会中断业务逻辑。
# ============================================================================
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def safe_print(*args, **kwargs):
    """永不因编码/流异常而抛出的 print（v2.0.0）

    v2.0.0 之前部分日志用裸 print 且带 emoji，在 gbk 重定向下会让
    ConfigManager.load_config 这类"允许失败"的路径直接抛异常。
    """
    try:
        print(*args, **kwargs)
    except Exception:
        try:
            print(*(str(a).encode("ascii", "replace").decode("ascii") for a in args), **kwargs)
        except Exception:
            pass

try:
    import insightface
    from insightface.app import FaceAnalysis
except ImportError as e:
    print(f"导入 insightface 出错: {e}")
    # 尝试修复（v2.0.0：打包后的程序不允许自动 pip 安装，否则会卡住/污染环境）
    import sys
    if getattr(sys, 'frozen', False):
        print("❌ 打包环境中缺少 insightface，请检查打包配置（--collect-all insightface）")
    else:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "insightface", "--no-deps"])
        import insightface

import cv2

import sqlite3
import win32gui
import win32ui
import win32con
import time
import requests
import zipfile
import tarfile
import io
import pinyin
import re
import random

import threading
import functools
import json
import traceback
import shutil
import numpy as np
import win32api
from ctypes import POINTER, byref, c_void_p, cast
import psutil
import win32process
from PyQt5.QtCore import QThread
from datetime import datetime
from queue import Queue

import ctypes
from ctypes import wintypes

try:
    import pywincffi.graphicscapture as gc
except ImportError:
    gc = None
    pass
import comtypes
# 检查并安装 comtypes 模块
try:
    import comtypes
except ImportError:
    import sys
    if getattr(sys, 'frozen', False):
        print("❌ 打包环境中缺少 comtypes，请检查打包配置")
    else:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "comtypes"])
        import comtypes
    
from comtypes import GUID

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QLabel, QPushButton, 
                           QVBoxLayout, QHBoxLayout, QWidget, QFileDialog,
                           QInputDialog, QMessageBox, QComboBox, QGroupBox,
                           QProgressDialog, QTableWidget, QTableWidgetItem, 
                           QHeaderView, QDialog, QDialogButtonBox, QLineEdit,
                           QSlider, QTextEdit, QListWidget, QCheckBox, QFormLayout,
                           QProgressBar, QSizePolicy, QSpinBox, QScrollArea, QSplitter,
                           QGridLayout, QRadioButton,QButtonGroup,QFrame )
from PyQt5.QtGui import QImage, QPixmap, QFont, QIcon, QTextCursor, QPainter, QPen, QFontDatabase
from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal, QRect, QObject, QSize, QThreadPool, QRunnable, QByteArray
from PyQt5.QtGui import QColor
import requests
import zipfile
import io
from fake_useragent import UserAgent
import warnings
from urllib.parse import urlparse
import socket
import socks
import json
import csv
from PyQt5.QtGui import QImage, QPixmap, QFont, QIcon, QTextCursor, QPainter, QPen, QFontDatabase
from appdirs import user_config_dir

warnings.filterwarnings("ignore")

# ============================================================================
#  版本信息（唯一来源：改版本号只改这里，窗口标题自动同步）
# ============================================================================
VERSION = "2.1.2"
APP_NAME = "人脸识别管理系统"
APP_TITLE = f"{APP_NAME} v{VERSION}"

# 项目根目录（所有运行期数据都以它为准，避免 CWD 不同导致配置/数据库错位）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================================
#  .env 加载（需求8：API Key / 数据库密码等敏感信息不写进代码）
#  不依赖 python-dotenv，自行解析；若已装 python-dotenv 也无需改代码。
# ============================================================================
ENV_FILE = os.path.join(BASE_DIR, ".env")
ENV = {}
# 出现这些键名一律视为敏感字段，不允许明文写进 config.json
SECRET_FIELD_NAMES = {"password", "passwd", "pwd", "api_key", "apikey",
                      "api_secret", "secret", "token", "access_key"}


def _parse_env_file(path):
    """极简 .env 解析：KEY=VALUE，# 注释，支持引号与 export 前缀

    v2.0.0：读取时用 errors="replace"，并兼容"记事本另存为 ANSI(GBK)"的情况——
    原实现用严格 utf-8 解析，遇到 GBK 文件会整份丢弃（密钥全部失效）。
    """
    data = {}
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            content = f.read()
        # 若出现替换字符，说明大概率不是 UTF-8，退回 GBK 再试一次
        if "\ufffd" in content:
            try:
                with open(path, "r", encoding="gbk", errors="replace") as f:
                    content = f.read()
            except Exception:
                pass
        for raw in content.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.lower().startswith("export "):
                line = line[7:].strip()
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if key:
                data[key] = value
    except FileNotFoundError:
        pass
    except Exception as e:
        safe_print(f"[ENV] 解析 {path} 失败: {e}")
    return data


def load_env(path=None):
    """加载 .env 到 os.environ（不覆盖已存在的真实环境变量），并返回字典"""
    global ENV_FILE, ENV
    if path:
        ENV_FILE = path
    ENV = _parse_env_file(ENV_FILE)
    for k, v in ENV.items():
        os.environ.setdefault(k, v)
    return ENV


def env_get(key, default=None):
    """读取环境变量（.env 优先，其次系统环境变量）；空串视为未设置"""
    value = ENV.get(key)
    if not value:
        value = os.environ.get(key)
    if not value:
        return default
    return value


def _write_env_var(key, value):
    """把敏感项写回 .env（保持其它行不变），实现"密钥不落 config.json/代码"

    返回 True/False。调用方（ConfigManager._strip_secrets）**只有在本函数返回 True 时**
    才允许把 config.json 中的该字段清空，否则会在 .env 不可写时静默丢密钥。
    """
    try:
        lines = []
        if os.path.exists(ENV_FILE):
            with open(ENV_FILE, "r", encoding="utf-8-sig", errors="replace") as f:
                lines = f.read().splitlines()
        pattern = re.compile(r"^\s*(export\s+)?" + re.escape(key) + r"\s*=")
        out, replaced = [], False
        for line in lines:
            if pattern.match(line):
                out.append(f"{key}={value}")
                replaced = True
            else:
                out.append(line)
        if not replaced:
            if out and out[-1].strip():
                out.append("")
            out.append(f"{key}={value}")
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        ENV[key] = value
        os.environ[key] = value
        return True
    except Exception as e:
        safe_print(f"[ENV] 写入 {key} 失败: {e}")
        return False


load_env()
debug_print(f"已加载 .env: {ENV_FILE} (共 {len(ENV)} 项)")

# 强制模型路径到当前目录 下的models文件夹 .\models\buffalo_*
models_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
debug_print(f"54模型根目录: {models_root}")
os.makedirs(models_root, exist_ok=True)
# 设置环境变量时直接使用绝对路径，不额外添加models
os.environ['INSIGHTFACE_MODELS_ROOT'] = os.path.dirname(os.path.abspath(__file__))
debug_print(f"56修正后的模型下载路径: {models_root}")
download_path = models_root
debug_print(f"59最终模型下载路径:: {download_path}")

# 延迟导入确保环境变量生效
try:
    from insightface.app import FaceAnalysis
except ImportError:
    if getattr(sys, 'frozen', False):
        raise
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "insightface"])
    from insightface.app import FaceAnalysis

# 模型配置
MODELS = {
    "buffalo_l": {
        "url": "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip",
        "files": ["det_10g.onnx", "genderage.onnx", "w600k_r50.onnx", "1k3d68.onnx", "2d106det.onnx"]
    },
    "buffalo_s": {
        "url": "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip",
        "files": ["det_500m.onnx", "genderage.onnx", "w600k_mbf.onnx", "1k3d68.onnx", "2d106det.onnx"]
    },
    "buffalo_sc": {
        "url": "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_sc.zip",
        "files": ["det_500m.onnx", "w600k_mbf.onnx", "genderage.onnx","1k3d68.onnx", "2d106det.onnx"]
    },
    "antelopev2": {
        "url": "https://github.com/deepinsight/insightface/releases/download/v0.7/antelopev2.zip",
        "files": ["1k3d68.onnx", "2d106det.onnx", "genderage.onnx", "glintr100.onnx", "scrfd_10g_bnkps.onnx"]
    },
    "scrfd_person_2.5g": {
        "url": "https://github.com/deepinsight/insightface/releases/download/v0.7/scrfd_person_2.5g.onnx",
        "files": ["scrfd_person_2.5g.onnx"],
        "is_single_file": True
    }
}

def _safe_int(value, default, lo=None, hi=None):
    """把配置里的值安全转成 int（v2.0.0）

    配置文件可能被手工改坏（None / "abc" / 越界）。原实现直接 int()，
    一个坏值就会让 restore_ui_state 整段回填中断，后面的设置全部丢失。
    """
    try:
        if value is None or value == '':
            return default
        result = int(float(value))
    except (TypeError, ValueError):
        return default
    if lo is not None:
        result = max(lo, result)
    if hi is not None:
        result = min(hi, result)
    return result


def _safe_float(value, default, lo=None, hi=None):
    """把配置里的值安全转成 float（v2.0.0），规则同 _safe_int"""
    try:
        if value is None or value == '':
            return default
        result = float(value)
    except (TypeError, ValueError):
        return default
    if lo is not None:
        result = max(lo, result)
    if hi is not None:
        result = min(hi, result)
    return result


def _safe_bool(value, default=False):
    """把配置里的值安全转成 bool（字符串 'false'/'0' 视为 False）"""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on', '是', '开')
    try:
        return bool(value)
    except Exception:
        return default


def _safe_size(value, default=(640, 640)):
    """把 "640x640" 之类的字符串安全转成 (w, h)"""
    try:
        parts = str(value).lower().replace('*', 'x').split('x')
        if len(parts) != 2:
            return default
        w, h = int(parts[0]), int(parts[1])
        if w < 16 or h < 16:
            return default
        return (w, h)
    except (TypeError, ValueError):
        return default


class ConfigManager:
    """配置管理器（需求6：所有设置实时自动保存 + 持久保存）

    设计要点：
      1. 单一数据源 DEFAULTS：新增设置项只需在这里加一行；
      2. set()/update() 立即落盘（原子写：先写 .tmp 再 os.replace），窗口关闭时再兜底保存；
      3. 敏感字段（password/api_key/token/...）自动剥离到 .env，不写进 config.json（需求8）；
      4. 加载时保留配置文件里出现、但 DEFAULTS 中没有的"历史键"，避免升级丢设置；
      5. 配置文件损坏时自动备份为 .corrupt，不静默丢弃用户设置。
    """

    DEFAULTS = {
        'window_geometry': None,
        'model_name': 'buffalo_l',
        'det_thresh': 70,
        'det_interval': 500,
        'det_size': '640x640',
        'low_performance_mode': False,
        'proxy_settings': None,
        'last_window': None,
        'auto_save_unknown': False,
        'detect_interval': 5,
        'roi_threshold': 0.1,
        'min_roi_area': 500,
        'enable_preprocess': True,
        'max_display': 10,
        'enable_color': True,
        'show_detect_box': True,
        'performance_mode': 'auto',  # 'auto' | 'manual'
        'debug_mode': False,
        # ---- v2.1.0 加速与性能相关（需求6：全部实时保存）----
        'accel_backend': 'auto',     # 'auto'|'cuda'|'dml'|'openvino'|'cpu'
        'cpu_threads': 0,            # 0 = 自动（物理核心数）
        'use_worker_thread': True,   # 检测是否放到独立线程（纯 CPU 防卡顿）
        'detect_input_max_side': 1280,  # 检测输入最长边上限（降采样阈值）
    }

    def __init__(self, config_file=None):
        # 如果没有指定配置文件路径，使用主程序所在目录
        if config_file is None:
            self.config_file = os.path.join(BASE_DIR, 'config.json')
        else:
            self.config_file = config_file
        debug_print(f"配置文件路径: {os.path.abspath(self.config_file)}")
        # 从默认值开始，保证任何一项都有值，不会出现 KeyError
        self.config = dict(self.DEFAULTS)

    # ------------------------------------------------------------------
    # 敏感字段处理
    # ------------------------------------------------------------------
    @staticmethod
    def _is_secret_key(key):
        return str(key).lower() in SECRET_FIELD_NAMES

    def _strip_secrets(self, data):
        """递归地把敏感字段搬到 .env，返回可安全写盘的副本

        v2.0.0 加固：只有 `_write_env_var` 真正写成功，才把 config.json 中的该字段清空。
        否则（.env 只读 / 磁盘满 / 权限不足）密钥会在两个地方同时消失。
        """
        if not isinstance(data, dict):
            return data
        clean = {}
        for key, value in data.items():
            if isinstance(value, dict):
                clean[key] = self._strip_secrets(value)
                for sub_key, sub_value in value.items():
                    if self._is_secret_key(sub_key) and sub_value:
                        env_key = 'PROXY_PASSWORD' if str(sub_key).lower() == 'password' else str(sub_key).upper()
                        if not _write_env_var(env_key, sub_value):
                            # 写 .env 失败：保留原值，宁可 config.json 里有密文也不要丢密钥
                            clean[key][sub_key] = sub_value
                            safe_print(f"[ENV] {env_key} 写入失败，已在 config.json 中保留原值")
            elif self._is_secret_key(key):
                if value and not _write_env_var(str(key).upper(), value):
                    clean[key] = value
                    safe_print(f"[ENV] {key} 写入失败，已在 config.json 中保留原值")
                else:
                    clean[key] = ''
            else:
                clean[key] = value
        return clean

    def _restore_secrets(self):
        """从 .env 回填被剥离的敏感字段（例如代理密码）"""
        proxy = self.config.get('proxy_settings')
        if isinstance(proxy, dict) and not proxy.get('password'):
            proxy['password'] = env_get('PROXY_PASSWORD', '') or ''
        for key in list(self.config.keys()):
            if self._is_secret_key(key) and not self.config.get(key):
                self.config[key] = env_get(str(key).upper(), '') or ''

    # ------------------------------------------------------------------
    # 读写
    # ------------------------------------------------------------------
    def load_config(self):
        """加载配置文件（保留默认值 + 历史键 + .env 密钥回填）"""
        try:
            if os.path.exists(self.config_file):
                debug_print(f"从 {self.config_file} 加载配置")
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                if isinstance(loaded_config, dict):
                    for key in self.DEFAULTS:
                        if key in loaded_config:
                            self.config[key] = loaded_config[key]
                    # 兼容历史键：文件里有、DEFAULTS 里没有的，也保留下来，避免丢设置
                    for key, value in loaded_config.items():
                        if key not in self.config:
                            self.config[key] = value
                    self._restore_secrets()
                    debug_print(f"配置加载成功: {self.config}")
                    return True
                safe_print("[配置] 配置文件格式异常（不是 JSON 对象），使用默认配置")
            else:
                debug_print("配置文件不存在，使用默认配置并创建")
                self.save_config()
                return False
        except Exception as e:
            # 注意：这里的日志必须是安全的（safe_print），
            # 否则"配置文件损坏"会因为日志编码问题变成"程序启动崩溃"。
            safe_print(f"[配置] 加载配置文件失败: {str(e)}")
            try:
                corrupt = self.config_file + '.corrupt'
                shutil.copy2(self.config_file, corrupt)
                safe_print(f"[配置] 已把损坏的配置备份到: {corrupt}")
            except Exception:
                pass
            return False
        return False

    def save_config(self):
        """保存当前配置到文件（原子写，避免写一半崩溃导致设置丢失）"""
        try:
            payload = self._strip_secrets(self.config)
            tmp_path = self.config_file + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, self.config_file)
            debug_print("配置保存成功")
            return True
        except Exception as e:
            safe_print(f"[配置] 保存配置文件失败: {str(e)}")
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return False

    # ------------------------------------------------------------------
    # 访问接口
    # ------------------------------------------------------------------
    def get(self, key, default=None):
        """获取配置项"""
        return self.config.get(key, default)

    def set(self, key, value):
        """设置配置项并立即落盘（实时自动保存）；值未变化时不重复写盘"""
        if self.config.get(key) == value:
            return value
        debug_print(f"设置配置: {key} = {value}")
        self.config[key] = value
        self.save_config()
        return value

    def update(self, **kwargs):
        """批量设置配置项，只落盘一次"""
        changed = False
        for key, value in kwargs.items():
            if self.config.get(key) != value:
                self.config[key] = value
                changed = True
        if changed:
            self.save_config()
        return changed

    def as_dict(self):
        """返回配置副本（用于文档/诊断输出）"""
        return dict(self.config)


class MemoryMonitor(QThread):
    update_signal = pyqtSignal(float, float)
    
    def __init__(self):
        super().__init__()
        self.running = True
        
    def run(self):
        while self.running:
            mem = psutil.virtual_memory()
            self.update_signal.emit(mem.used / (1024**3), mem.percent)
            time.sleep(2)
            
    def stop(self):
        self.running = False

class ProxySettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("代理设置")
        self.setFixedSize(400, 250)
        
        layout = QFormLayout()
        
        self.proxy_type = QComboBox()
        self.proxy_type.addItems(["HTTP", "HTTPS", "SOCKS5"])
        self.proxy_host = QLineEdit("127.0.0.1")
        self.proxy_port = QLineEdit("20808")
        self.proxy_user = QLineEdit()
        self.proxy_pass = QLineEdit()
        self.proxy_pass.setEchoMode(QLineEdit.Password)
        
        layout.addRow("代理类型:", self.proxy_type)
        layout.addRow("代理地址:", self.proxy_host)
        layout.addRow("代理端口:", self.proxy_port)
        layout.addRow("用户名(可选):", self.proxy_user)
        layout.addRow("密码(可选):", self.proxy_pass)
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        
        layout.addRow(btn_box)
        self.setLayout(layout)
    
    def get_proxy(self):
        proxy_type = self.proxy_type.currentText().lower()
        host = self.proxy_host.text()
        port = self.proxy_port.text()
        user = self.proxy_user.text()
        password = self.proxy_pass.text()
        
        if proxy_type == "socks5":
            proxy_url = f"socks5://{host}:{port}"
        else:
            proxy_url = f"{proxy_type}://{host}:{port}"
        
        auth = f"{user}:{password}@" if user and password else ""
        return {
            'type': proxy_type,
            'url': proxy_url,
            'host': host,
            'port': int(port) if port.isdigit() else 20808,
            'user': user,
            'password': password
        }

class DatasetDownloader(QThread):
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str)
    
    def __init__(self, dataset_info, proxy_settings=None):
        super().__init__()
        self.dataset_info = dataset_info
        self.proxy_settings = proxy_settings or {}
        self.ua = UserAgent()
        self.stop_flag = False
    
    def run(self):
        try:
            self.setup_proxy()
            
            dataset_name, url, save_path = self.dataset_info
            os.makedirs(save_path, exist_ok=True)
            
            # 检查是否已下载
            if os.path.exists(os.path.join(save_path, f"{dataset_name}_COMPLETED")):
                self.progress_signal.emit(100, f"{dataset_name} 已存在，跳过下载")
                self.finished_signal.emit(True, f"{dataset_name} 已存在")
                return
            
            self.progress_signal.emit(0, f"开始下载 {dataset_name}...")
            
            # 大文件分块下载
            headers = {"User-Agent": self.ua.random}
            response = requests.get(url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            chunk_size = 8192
            data = b''
            
            with open(os.path.join(save_path, f"{dataset_name}_temp"), 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if self.stop_flag:
                        self.progress_signal.emit(0, "下载已取消")
                        return
                    
                    downloaded += len(chunk)
                    f.write(chunk)
                    data += chunk
                    
                    progress = int(downloaded / total_size * 100) if total_size > 0 else 0
                    self.progress_signal.emit(progress, f"下载中... {progress}%")
            
            # 解压文件
            self.progress_signal.emit(100, "正在解压...")
            self.extract_dataset(data, save_path, dataset_name)
            
            # 标记完成
            with open(os.path.join(save_path, f"{dataset_name}_COMPLETED"), 'w') as f:
                f.write("download_completed")
            
            self.finished_signal.emit(True, f"{dataset_name} 下载完成")
        except Exception as e:
            self.finished_signal.emit(False, f"下载失败: {str(e)}")
    
    def setup_proxy(self):
        if not self.proxy_settings:
            return
            
        proxy_type = self.proxy_settings.get('type', 'http')
        host = self.proxy_settings.get('host', '127.0.0.1')
        port = self.proxy_settings.get('port', 20808)
        user = self.proxy_settings.get('user', '')
        password = self.proxy_settings.get('password', '')
        
        if proxy_type == 'socks5':
            socks.set_default_proxy(socks.SOCKS5, host, port, 
                                  username=user if user else None, 
                                  password=password if password else None)
            socket.socket = socks.socksocket
        else:
            os.environ['HTTP_PROXY'] = f"http://{host}:{port}"
            os.environ['HTTPS_PROXY'] = f"http://{host}:{port}"
            
            if user and password:
                os.environ['HTTP_PROXY'] = f"http://{user}:{password}@{host}:{port}"
                os.environ['HTTPS_PROXY'] = f"http://{user}:{password}@{host}:{port}"
    
    def extract_dataset(self, data, save_path, dataset_name):
        try:
            if dataset_name == "LFW":
                with tarfile.open(fileobj=io.BytesIO(data)) as tar:
                    tar.extractall(path=save_path)
            elif dataset_name == "CelebA":
                with zipfile.ZipFile(io.BytesIO(data)) as zip_ref:
                    zip_ref.extractall(save_path)
            elif dataset_name == "VGGFace2":
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
                    tar.extractall(path=save_path)
            elif dataset_name == "FaceScrub":
                with zipfile.ZipFile(io.BytesIO(data)) as zip_ref:
                    zip_ref.extractall(save_path)
            elif dataset_name == "CASIA-WebFace":
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
                    tar.extractall(path=save_path)
            else:
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as zip_ref:
                        zip_ref.extractall(save_path)
                except zipfile.BadZipFile:
                    try:
                        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
                            tar.extractall(path=save_path)
                    except tarfile.TarError:
                        raise ValueError(f"无法解压数据集 {dataset_name}: 不支持的压缩格式")
        except Exception as e:
            raise Exception(f"解压数据集时出错: {str(e)}")
    
    def stop(self):
        self.stop_flag = True

class DatasetManager(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("公开人脸数据库管理")
        self.setFixedSize(700, 500)

        self.config = parent.config if parent and hasattr(parent, 'config') else ConfigManager()
        
        self.proxy_settings = None
        self.current_downloader = None
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        self.window_combo = QComboBox()
        layout.addWidget(self.window_combo)
    
        self.dataset_table = QTableWidget()
        # v2.0.0 修复：URL 存在第 6 列（索引 5）并被隐藏。原来这里只建 5 列，
        # 导致 load_dataset_info 里的 setItem(row, 5, url) 被 Qt 直接丢弃，
        # start_download 拿到 None -> "模型市场"永远下载失败。
        self.dataset_table.setColumnCount(6)
        self.dataset_table.setHorizontalHeaderLabels(["名称", "描述", "大小", "下载", "导入", "URL"])
        self.dataset_table.horizontalHeader().setStretchLastSection(True)
        
        self.progress_bar = QProgressBar()
        self.progress_label = QLabel("准备下载...")
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        
        btn_proxy = QPushButton("设置代理")
        btn_proxy.clicked.connect(self.set_proxy)
        
        layout.addWidget(self.dataset_table)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.log_output)
        layout.addWidget(btn_proxy)
        
        self.setLayout(layout)
        self.load_dataset_info()

    def import_dataset(self, row):
        try:
            dataset_name = self.dataset_table.item(row, 0).text()
            dataset_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datasets", dataset_name)
            
            if not os.path.exists(dataset_path):
                QMessageBox.warning(self, "错误", f"数据集 {dataset_name} 未下载或路径不存在！")
                debug_print(f"390数据集 {dataset_name} 未下载或路径不存在！")
                return
        
            # 调用主窗口的导入方法
            parent = self.parent()
            if hasattr(parent, 'import_dataset_images'):
                parent.import_dataset_images(dataset_name, dataset_path)
            else:
                QMessageBox.critical(self, "错误", "主窗口导入功能未实现！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入数据集时出错: {str(e)}")

    def import_all_datasets(self):
        try:
            parent = self.parent()
            if not hasattr(parent, 'import_dataset_images'):
                QMessageBox.critical(self, "错误", "主窗口导入功能未实现！")
                return
        
            for row in range(self.dataset_table.rowCount()):
                dataset_name = self.dataset_table.item(row, 0).text()
                dataset_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datasets", dataset_name)
                if os.path.exists(dataset_path):
                    parent.import_dataset_images(dataset_name, dataset_path)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"批量导入数据集时出错: {str(e)}")

    def load_dataset_info(self):
        try:
            datasets = [
                ("antelopev2", "insightface", "344MB", 
                 "https://github.com/deepinsight/insightface/releases/download/v0.7/antelopev2.zip"),
                ("buffalo_l", "insightface", "275MB", 
                 "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"),
                ("buffalo_s", "insightface", "122MB", 
                 "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip"),
                ("buffalo_sc", "insightface", "14.3MB", 
                 "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_sc.zip"),
                ("scrfd_person_2.5g", "insightface", "3.54MB", 
                 "https://github.com/deepinsight/insightface/releases/download/v0.7/scrfd_person_2.5g.onnx")
            ]
            
            self.dataset_table.setRowCount(len(datasets))
            # v2.0.0 修复：必须保留第 6 列存放 URL（隐藏列），否则 setItem(row,5,...) 会被丢弃
            self.dataset_table.setColumnCount(6)
            
            for row, (name, desc, size, url) in enumerate(datasets):
                self.dataset_table.setItem(row, 0, QTableWidgetItem(name))
                self.dataset_table.setItem(row, 1, QTableWidgetItem(desc))
                self.dataset_table.setItem(row, 2, QTableWidgetItem(size))
            
                btn_download = QPushButton("下载")
                btn_download.clicked.connect(lambda _, r=row: self.start_download(r))
                self.dataset_table.setCellWidget(row, 3, btn_download)
                
                btn_import = QPushButton("导入")
                btn_import.clicked.connect(lambda _, r=row: self.import_dataset(r))
                self.dataset_table.setCellWidget(row, 4, btn_import)

                # 存储 URL 到隐藏列（第 6 列，索引 5）
                url_item = QTableWidgetItem(url)
                self.dataset_table.setItem(row, 5, url_item)

            # 隐藏URL列
            self.dataset_table.setColumnHidden(5, True)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载数据集信息时出错: {str(e)}")

    def start_download(self, row):
        """下载所选模型/数据集

        v2.0.0 修复：原文件里本方法被定义两次，后一个版本用 column 4 取 URL，
        而 URL 实际存放在隐藏的 column 5，导致"无效的下载URL"永远下载失败。
        现已删除影子定义，统一使用 column 5。
        """
        try:
            if self.current_downloader and self.current_downloader.isRunning():
                QMessageBox.warning(self, "警告", "当前有下载任务正在进行")
                return
            
            dataset_name = self.dataset_table.item(row, 0).text()
            dataset_url = self.dataset_table.item(row, 5).text()  # 从隐藏列获取URL
            
            if not dataset_url:
                QMessageBox.critical(self, "错误", "无效的下载URL")
                return
            
            save_path = os.path.join(BASE_DIR, "datasets", dataset_name)
            dataset_info = (dataset_name, dataset_url, save_path)
            
            self.current_downloader = DatasetDownloader(dataset_info, self.proxy_settings)
            self.current_downloader.progress_signal.connect(self.update_progress)
            self.current_downloader.finished_signal.connect(self.download_finished)
            self.current_downloader.start()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"开始下载时出错: {str(e)}")

    def set_proxy(self):
        """转发给主窗口设置代理

        v2.0.0 修复：本类没有 self.proxy_status（那是主窗口的控件），
        原实现会在主窗口设置成功之后再抛 AttributeError，
        用户看到"设置成功"的弹窗紧跟着"设置代理时出错"。现改为通过父窗口更新标签。
        """
        try:
            parent = self.parent()
            parent.set_proxy()
            if getattr(parent, 'proxy_settings', None) and hasattr(parent, 'proxy_status'):
                proxy_type = parent.proxy_settings['type']
                host = parent.proxy_settings['host']
                port = parent.proxy_settings['port']
                parent.proxy_status.setText(f"代理: {proxy_type.upper()} {host}:{port}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"设置代理时出错: {str(e)}")
    
    def update_progress(self, progress, message):
        try:
            self.progress_bar.setValue(progress)
            self.progress_label.setText(message)
            self.log_output.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
        except Exception as e:
            debug_print(f"522更新进度时出错: {str(e)}")
    
    def download_finished(self, success, message):
        try:
            self.log_output.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
            if success:
                QMessageBox.information(self, "完成", message)
            else:
                QMessageBox.critical(self, "错误", message)
        except Exception as e:
            debug_print(f"532下载完成处理时出错: {str(e)}")
    
    def closeEvent(self, event):
        """关闭窗口时保存当前状态

        v2.0.0 修复：本类并没有 self.config（原来这里会抛 AttributeError 被静默吞掉），
        且窗口几何属于主窗口，不应由数据集对话框写入。改为通过父窗口的 config 操作。
        """
        try:
            parent_cfg = getattr(self.parent(), 'config', None)
            if parent_cfg is not None:
                parent_cfg.save_config()
            if getattr(self, 'current_downloader', None) and self.current_downloader.isRunning():
                self.current_downloader.stop()
                self.current_downloader.wait()
        except Exception as e:
            debug_print(f"关闭数据集对话框时出错: {str(e)}")
        finally:
            event.accept()

    def showEvent(self, event):
        """显示窗口时恢复状态"""
        super().showEvent(event)
        try:
            parent_cfg = getattr(self.parent(), 'config', None)
            if parent_cfg is None or not hasattr(self, 'window_combo'):
                return
            last_window = parent_cfg.get('last_window')
            titles = [self.window_combo.itemText(i) for i in range(self.window_combo.count())]
            if last_window and last_window in titles:
                self.window_combo.setCurrentText(last_window)
        except Exception as e:
            debug_print(f"恢复数据集对话框状态时出错: {str(e)}")

class FaceDatabase:
    def __init__(self, db_path=None):
        # v2.0.0：数据库路径优先取 .env 的 FACE_DB_PATH（需求8），
        # 否则固定用"主程序所在目录/face_database.db"，不再依赖当前工作目录。
        if db_path is None:
            db_path = env_get('FACE_DB_PATH') or os.path.join(BASE_DIR, 'face_database.db')
        self.db_path = db_path
        self.conn = None
        self._cursor = None  # 使用私有变量存储游标
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._cursor = self.conn.cursor()
            self._init_db()
            self._upgrade_database()
            self._prepare_statements()
            print("[DEBUG] 数据库初始化成功")
        except Exception as e:
            print(f"[ERROR] 初始化数据库失败: {str(e)}")
            if self.conn:
                self.conn.close()
            raise Exception(f"初始化数据库失败: {str(e)}")

    def log_message(self, message):
        """统一日志出口

        v2.0.0 修复：本类多处调用 self.log_message()，但原类里没有该方法，
        一旦走到这些分支（如 embedding 非法、相似度计算异常）就会抛
        AttributeError，把"查询失败"变成"程序崩溃"。这里补上安全实现。
        """
        try:
            debug_print(f"[DB] {message}")
        except Exception:
            pass

    @property
    def cursor(self):
        """安全的游标获取方法"""
        if self._cursor is None:
            if self.conn is None:
                self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._cursor = self.conn.cursor()
        return self._cursor

        
    def _init_db(self):
        try:
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS faces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    embedding BLOB,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    image_path TEXT,
                    last_access_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    confidence REAL DEFAULT 0.9,
                    metadata TEXT
                )
            ''')
            
            # 创建索引
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_name ON faces(name)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_create_time ON faces(create_time)')
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"创建表失败: {str(e)}")

    def get_face_storage_path(self, name):
        """获取人脸图片存储路径"""
        # 姓名拼音转换和规范化
        py_name = pinyin.get(name, format="strip", delimiter="_")
        safe_name = re.sub(r'[^\w]', '', py_name)
        
        # 创建对应人名的子目录
        faces_dir = os.path.join("faces", safe_name)
        os.makedirs(faces_dir, exist_ok=True)
        return faces_dir

    def _prepare_statements(self):
        """准备常用SQL语句"""
        self.prepared_statements = {
            'add_face': "INSERT INTO faces (name, embedding, image_path) VALUES (?, ?, ?)",
            'get_all_faces': "SELECT id, name, image_path, create_time FROM faces ORDER BY create_time DESC",
            'search_face': "SELECT name, embedding FROM faces",
            'update_face': "UPDATE faces SET name=?, image_path=? WHERE id=?",
            'delete_face': "DELETE FROM faces WHERE id=?",
            'get_face_by_id': "SELECT * FROM faces WHERE id=?"
        }

    def search_faces_by_name(self, keyword):
        """按姓名搜索人脸"""
        try:
            self.cursor.execute(
                "SELECT id, name, image_path, create_time FROM faces WHERE name LIKE ? ORDER BY name",
                (f"%{keyword}%",))
            return self.cursor.fetchall()
        except Exception as e:
            print(f"614搜索人脸失败: {str(e)}")
            return []
    def get_faces_sorted(self, sort_by="name", ascending=True):
        """获取排序后的人脸数据"""
        try:
            order = "ASC" if ascending else "DESC"
            valid_columns = ["id", "name", "create_time", "last_access_time"]
            if sort_by not in valid_columns:
                sort_by = "name"
            
            self.cursor.execute(
                f"SELECT id, name, image_path, create_time FROM faces ORDER BY {sort_by} {order}")
            return self.cursor.fetchall()
        except Exception as e:
            print(f"628获取排序人脸失败: {str(e)}")
            return []

    def batch_add_faces(self, faces_data):
        """批量添加人脸数据"""
        try:
            with self.conn:
                for name, embedding, image_path in faces_data:
                    self.cursor.execute(
                        self.prepared_statements['add_face'],
                        (name, embedding.tobytes() if embedding is not None else None, image_path)
                    )
            return True
        except Exception as e:
            self.conn.rollback()
            print(f"643批量添加人脸失败: {str(e)}")
            raise Exception(f"批量添加人脸失败: {str(e)}")
             
    def get_all_faces_raw(self):
        """获取所有人脸数据的原始格式(不包含格式化处理)"""
        try:
            self.cursor.execute(self.prepared_statements['get_all_faces'])
            return self.cursor.fetchall()
        except Exception as e:
            print(f"652获取所有人脸数据失败: {str(e)}")
            raise Exception(f"获取所有人脸数据失败: {str(e)}")

    def get_face_by_id(self, face_id):
        """根据ID获取人脸数据"""
        try:
            self.cursor.execute(
                self.prepared_statements['get_face_by_id'],
                (face_id,)
            )
            result = self.cursor.fetchone()
            if not result:
                return None
            return result
        except Exception as e:
            self.conn.rollback()
            print(f"668根据ID查询人脸失败: {str(e)}")
            raise Exception(f"根据ID查询人脸失败: {str(e)}")
            
    def _upgrade_database(self):
        """升级数据库结构（增强版，包含完整错误处理和字段检查）"""
        try:
            # 1. 获取当前表结构
            self.cursor.execute("PRAGMA table_info(faces)")
            columns = {col[1]: col for col in self.cursor.fetchall()}
            
            # 2. 检查并添加缺失字段
            changes_made = False
            
            # 2.1 检查confidence字段
            if 'confidence' not in columns:
                try:
                    self.cursor.execute("ALTER TABLE faces ADD COLUMN confidence REAL DEFAULT 0.9")
                    print("[DEBUG] 数据库升级: 已添加confidence字段")
                    changes_made = True
                except Exception as e:
                    print(f"[ERROR] 添加confidence字段失败: {str(e)}")
                    raise
            
            # 2.2 检查metadata字段
            if 'metadata' not in columns:
                try:
                    self.cursor.execute("ALTER TABLE faces ADD COLUMN metadata TEXT")
                    print("[DEBUG] 数据库升级: 已添加metadata字段")
                    changes_made = True
                except Exception as e:
                    print(f"[ERROR] 添加metadata字段失败: {str(e)}")
                    raise
            
            # 2.3 检查image_path字段
            if 'image_path' not in columns:
                try:
                    self.cursor.execute("ALTER TABLE faces ADD COLUMN image_path TEXT")
                    print("[DEBUG] 数据库升级: 已添加image_path字段")
                    changes_made = True
                except Exception as e:
                    print(f"[ERROR] 添加image_path字段失败: {str(e)}")
                    raise
            
            # 2.4 检查last_access_time字段
            if 'last_access_time' not in columns:
                try:
                    # 先添加不带默认值的列
                    self.cursor.execute("ALTER TABLE faces ADD COLUMN last_access_time DATETIME")
                    # 然后更新现有记录的值为当前时间
                    self.cursor.execute("UPDATE faces SET last_access_time = datetime('now')")
                    print("[DEBUG] 数据库升级: 已添加last_access_time字段")
                    changes_made = True
                except Exception as e:
                    print(f"[ERROR] 添加last_access_time字段失败: {str(e)}")
                    raise
            
            # 3. 创建必要索引
            try:
                self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_name ON faces(name)")
                self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_create_time ON faces(create_time)")
                # v2.0.0：CREATE INDEX IF NOT EXISTS 是幂等的，索引通常已在 _init_db 建好，
                # 因此这里不再把 changes_made 置真（原实现导致每次启动都 commit + 打印）。
                safe_print("[DB] 索引检查完成")
            except Exception as e:
                safe_print(f"[DB] 创建索引失败: {str(e)}")
                # 索引创建失败不影响主要功能，不抛出异常
            
            # 4. 提交变更
            if changes_made:
                self.conn.commit()
                safe_print("[DB] 数据库升级完成")
            else:
                safe_print("[DB] 数据库结构已是最新，无需升级")
                
        except Exception as e:
            self.conn.rollback()
            error_msg = f"升级数据库失败: {str(e)}"
            safe_print(f"[DB] {error_msg}")
            raise Exception(error_msg)



    def update_face(self, face_id, name=None, image_path=None):
        """更新人脸信息"""
        try:
            with self.conn:
                if name is not None or image_path is not None:
                    self.cursor.execute(
                        self.prepared_statements['get_face_by_id'],
                        (face_id,)
                    )
                    current_data = self.cursor.fetchone()
                    if not current_data:
                        raise Exception("人脸记录不存在")
                
                    new_name = name if name is not None else current_data[1]
                    new_image_path = image_path if image_path is not None else current_data[4]
                
                    self.cursor.execute(
                        self.prepared_statements['update_face'],
                        (new_name, new_image_path, face_id)
                    )
            return True
        except Exception as e:
            self.conn.rollback()
            print(f"719更新人脸信息失败: {str(e)}")
            raise Exception(f"更新人脸信息失败: {str(e)}")
            
    def add_face(self, name, embedding, image_path=None, confidence=0.0):
        try:
            target_dir = self.get_face_storage_path(name)
            if image_path:  # 如果有图片路径
                # 如果是新图片，移动到对应目录
                if not os.path.exists(image_path):
                    raise FileNotFoundError(f"图片文件不存在: {image_path}")
                    
                # 生成新文件名
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-4]
                new_filename = f"{confidence:.0f}%_{timestamp}.jpg"
                new_path = os.path.join(target_dir, new_filename)
                
                # 移动文件
                shutil.move(image_path, new_path)
                image_path = new_path
            
            # 保存到数据库
            with self.conn:
                self.cursor.execute(
                    "INSERT INTO faces (name, embedding, image_path, confidence) VALUES (?, ?, ?, ?)",
                    (name, embedding.tobytes() if embedding is not None else None, 
                    image_path, float(confidence))
                )
            return True
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"添加人脸失败: {str(e)}")
            
    def get_all_faces(self):
        """获取用于UI显示的人脸数据(包含格式化处理)"""
        try:
            self.cursor.execute(self.prepared_statements['get_all_faces'])
            faces = self.cursor.fetchall()
            return [(f[0], f[1], f[2] if f[2] else '无图片', f[3]) for f in faces]
        except Exception as e:
            print(f"745获取所有人脸数据失败: {str(e)}")
            raise Exception(f"获取人脸数据失败: {str(e)}")

    def delete_face(self, face_id):
        """删除人脸记录"""
        try:
            with self.conn:
                self.cursor.execute("SELECT image_path FROM faces WHERE id=?", (face_id,))
                result = self.cursor.fetchone()
                if result and result[0] and os.path.exists(result[0]):
                    try:
                       os.remove(result[0])
                    except Exception as e:
                       raise Exception(f"删除图片文件失败: {str(e)}")
            
                self.cursor.execute(self.prepared_statements['delete_face'], (face_id,))
            return True
        except Exception as e:
            self.conn.rollback()
            print(f"764删除人脸记录失败: {str(e)}")
            raise Exception(f"删除人脸记录失败: {str(e)}")

    def search_face(self, embedding, threshold=0.6):
        try:
            # 1. 输入验证 - 检查embedding是否有效
            if embedding is None or not isinstance(embedding, np.ndarray):
                self.log_message("❌ 错误: 无效的特征向量输入")
                return {'name': None, 'similarity': 0, 'confidence': 0}
                
            # 2. 空值检查 - 确保数据库连接正常
            if not self.cursor:
                self.log_message("❌ 错误: 数据库游标未初始化")
                return {'name': None, 'similarity': 0, 'confidence': 0}

            self.cursor.execute("SELECT name, embedding, confidence FROM faces")
            best_match = None
            max_similarity = threshold
            
            for name, db_emb, confidence in self.cursor.fetchall():
                # 3. 空值检查 - 跳过无效的数据库记录
                if db_emb is None:
                    continue
                    
                try:
                    db_embedding = np.frombuffer(db_emb, dtype=np.float32)
                    
                    # 4. 边界条件检查 - 确保特征向量维度匹配
                    if embedding.shape != db_embedding.shape:
                        continue
                        
                    # 计算相似度
                    norm_emb = np.linalg.norm(embedding)
                    norm_db = np.linalg.norm(db_embedding)
                    
                    # 5. 边界条件检查 - 避免除以零
                    if norm_emb == 0 or norm_db == 0:
                        continue
                        
                    similarity = np.dot(embedding, db_embedding) / (norm_emb * norm_db)
                    
                    if similarity > max_similarity:
                        max_similarity = similarity
                        best_match = {
                            'name': name,
                            'similarity': similarity,
                            'confidence': confidence if confidence is not None else 0.9
                        }
                except Exception as e:
                    self.log_message(f"❌ 计算相似度时出错: {str(e)}")
                    continue
                    
            if best_match:
                try:
                    # 更新最后访问时间
                    self.cursor.execute(
                        "UPDATE faces SET last_access_time=CURRENT_TIMESTAMP WHERE name=?",
                        (best_match['name'],)
                    )
                    self.conn.commit()
                    return best_match
                except Exception as e:
                    self.log_message(f"❌ 更新访问时间失败: {str(e)}")
                    return best_match
                    
            return {'name': None, 'similarity': 0, 'confidence': 0}
        except Exception as e:
            self.log_message(f"❌ 搜索人脸失败: {str(e)}")
            return {'name': None, 'similarity': 0, 'confidence': 0}


    def cleanup_unknown_faces(self, days=30):
        """清理长时间未访问的未知人脸"""
        try:
            with self.conn:
                # 查找并删除超过指定天数未访问的未知人脸
                self.cursor.execute("""
                    SELECT id, image_path FROM faces 
                    WHERE name LIKE '未知_%' 
                    AND last_access_time < datetime('now', ?)
                """, (f"-{days} days",))
            
                results = self.cursor.fetchall()
                deleted_count = 0
            
                for face_id, img_path in results:
                    try:
                        if img_path and os.path.exists(img_path):
                            os.remove(img_path)
                        self.cursor.execute(self.prepared_statements['delete_face'], (face_id,))
                        deleted_count += 1
                    except Exception as e:
                        print(f"817删除未知人脸失败: {str(e)}")
                        continue
            
                return deleted_count
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"清理未知人脸失败: {str(e)}")
        
    def export_to_json(self, file_path):
        """导出完整数据库到JSON文件（包含所有关键字段）"""
        try:
            self.cursor.execute('''
                SELECT 
                    id, name, 
                    HEX(embedding) as embedding_hex, 
                    datetime(create_time, 'localtime') as create_time,
                    image_path,
                    datetime(last_access_time, 'localtime') as last_access_time,
                    confidence,
                    metadata
                FROM faces
            ''')
            
            results = []
            for row in self.cursor.fetchall():
                embedding = None
                if row[2]:
                    embedding = np.frombuffer(bytes.fromhex(row[2]), dtype=np.float32).tolist()
                
                results.append({
                    "id": row[0],
                    "name": row[1],
                    "embedding": embedding,
                    "create_time": row[3],
                    "image_path": row[4],
                    "last_access_time": row[5],
                    "confidence": row[6],
                    "metadata": json.loads(row[7]) if row[7] else None
                })
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "version": "2.0",
                    "export_time": datetime.now().isoformat(),
                    "count": len(results),
                    "data": results
                }, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"867导出JSON失败: {str(e)}")
            return False

    def validate_json(self, file_path):
        """验证导出的JSON数据是否完整"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not all(k in data for k in {"version", "export_time", "count", "data"}):
                return False, "缺少必要字段"
            
            if data["count"] != len(data["data"]):
                return False, "数据计数不匹配"
            
            for item in data["data"]:
                if not all(field in item for field in ["id", "name", "embedding", "create_time"]):
                    return False, f"记录 {item.get('id', 'unknown')} 缺少字段"
                
                if item["embedding"] and len(item["embedding"]) != 512:
                    return False, f"记录 {item['id']} 的特征向量长度异常"
            
            return True, "验证通过"
        except Exception as e:
            return False, f"验证过程中出错: {str(e)}"

def _with_db_lock(func):
    """给 FaceDatabase 的公开方法加一把可重入锁（v2.1.0）

    背景：检测线程会调用 `search_face()`，而界面线程可能同时在做增删改。
    sqlite3 连接是 `check_same_thread=False` 共享的，同一游标并发使用会报
    "Recursive use of cursors not allowed" 甚至数据损坏，因此统一加锁。
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        lock = getattr(self, '_db_lock', None)
        if lock is None:
            lock = threading.RLock()
            try:
                self._db_lock = lock
            except Exception:
                pass
        with lock:
            return func(self, *args, **kwargs)
    return wrapper


# 需要串行化的公开方法（读写数据库、使用同一个游标）
for _method_name in ('search_face', 'add_face', 'update_face', 'delete_face',
                     'get_face_by_id', 'get_all_faces', 'get_all_faces_raw',
                     'get_faces_sorted', 'search_faces_by_name', 'batch_add_faces',
                     'cleanup_unknown_faces', 'export_to_json'):
    if hasattr(FaceDatabase, _method_name):
        setattr(FaceDatabase, _method_name, _with_db_lock(getattr(FaceDatabase, _method_name)))


class FaceRecognitionWorker(QRunnable):
    def __init__(self, frame, face_app, face_db, callback):
        super().__init__()
        self.frame = frame
        self.face_app = face_app
        self.face_db = face_db
        self.callback = callback
        self.setAutoDelete(True)

    def run(self):
        try:
            # 添加输入验证
            if self.frame is None:
                self.log_message("错误: 无效的输入帧")
                self.callback([])
                return
                
            faces = self.face_app.get(self.frame)
            results = []
            
            for face in faces:
                # 添加空值检查
                if not hasattr(face, 'embedding') or face.embedding is None:
                    continue
                    
                result = self.face_db.search_face(face.embedding)  # 返回字典
                name = result['name']
                similarity = result['similarity']
                
                results.append({
                    'face': face,
                    'name': name,
                    'similarity': similarity
                })
            
            self.callback(results)
        except Exception as e:
            self.log_message(f"人脸识别失败: {str(e)}")
            self.callback([])


class ModelDownloader(QThread):
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool)

    def __init__(self, model_name):
        super().__init__()
        self.ua = UserAgent()
        self.model_name = model_name
        self.model_info = MODELS.get(model_name)

    def run(self):
        if not self.model_info:
            self.finished_signal.emit(False)
            self.progress_signal.emit(0, f"未知模型: {self.model_name}")
            return

        model_dir = os.path.join(models_root, self.model_name)
        debug_print(f"940修正后的模型下载路径: {model_dir}")
        os.makedirs(model_dir, exist_ok=True)
        debug_print(f"942修正后的模型下载路径: {model_dir}")
        required_files = [os.path.join(model_dir, f) for f in self.model_info["files"]]
        debug_print(f"944修正后的模型下载路径: {required_files}")
        
        
        if all(os.path.exists(f) and os.path.getsize(f) > 10*1024 for f in required_files):
            debug_print(f"948文件路径: {f} 存在: {os.path.exists(f)}")
            self.progress_signal.emit(100, "模型文件已存在")
            self.finished_signal.emit(True)
            return

        os.makedirs(model_dir, exist_ok=True)
        debug_print(f"953修正后的模型下载路径: {model_dir}")
        headers = {"User-Agent": self.ua.random}
        self.progress_signal.emit(0, "正在下载模型...")

        try:
            response = requests.get(self.model_info["url"], headers=headers, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            zip_data = b''

            for data in response.iter_content(chunk_size=4096):
                downloaded += len(data)
                zip_data += data
                progress = int(downloaded / total_size * 100) if total_size > 0 else 0
                self.progress_signal.emit(progress, f"下载中... {progress}%")

            self.progress_signal.emit(100, "正在解压模型...")
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_ref:
                zip_ref.extractall(model_dir)

            self.finished_signal.emit(True)
            self.progress_signal.emit(100, "模型下载完成")
        except Exception as e:
            self.finished_signal.emit(False)
            self.progress_signal.emit(0, f"下载失败: {str(e)}")
            debug_print(f"976下载失败: {str(e)}")

class ScreenCaptureDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("屏幕框选")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowState(Qt.WindowFullScreen)
        self.setFocusPolicy(Qt.StrongFocus)
        self.activateWindow()
        self.raise_()
        self.setStyleSheet("background-color: rgba(0, 0, 0, 50);")
        
        self.start_point = None
        self.end_point = None
        self.is_selecting = False
        self.selected_rect = None
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(QPen(Qt.red, 2, Qt.SolidLine))
        
        # 绘制半透明背景
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        
        # 绘制选择区域
        if self.start_point and self.end_point:
            rect = QRect(self.start_point, self.end_point)
            painter.fillRect(rect, QColor(255, 255, 255, 0))
            painter.drawRect(rect)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_point = event.pos()
            self.end_point = event.pos()
            self.is_selecting = True
            self.update()
    
    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.end_point = event.pos()
            self.update()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_selecting:
            self.end_point = event.pos()
            self.is_selecting = False
            
            # 确保矩形有效
            x1, y1 = min(self.start_point.x(), self.end_point.x()), min(self.start_point.y(), self.end_point.y())
            x2, y2 = max(self.start_point.x(), self.end_point.x()), max(self.start_point.y(), self.end_point.y())
            
            if abs(x2 - x1) > 10 and abs(y2 - y1) > 10:  # 最小尺寸限制
                self.selected_rect = (x1, y1, x2 - x1, y2 - y1)
                self.accept()
            else:
                self.reject()
            self.releaseMouse()
    
    def get_selected_region(self):
        return self.selected_rect

# ============================================================================
#  窗口捕获基础设施（v2.0.1）
#  ---------------------------------------------------------------------------
#  背景（用户反馈）：选择窗口/进程后拿不到画面。根因有四类，本模块逐一覆盖：
#    1. 窗口标题是中文时，历史实现走 ANSI 接口，标题变成乱码，
#       FindWindow 用乱码标题找不到窗口 —— 现在全部改用宽字符(W) API；
#    2. 只用 BitBlt 抓窗口 DC，遇到硬件加速/DirectComposition 窗口
#       （Chrome/Edge/Electron/UWP/播放器）只会返回全黑图 —— 现在先试 PrintWindow；
#    3. 完全没有校验"抓到的是不是黑图"，黑图被当成成功 —— 现在逐策略校验；
#    4. 非 Edge 窗口没有任何兜底方案 —— 现在是一条 8 级策略链，最后一律回落到
#       "整屏截图 + 裁剪"（DPI 一致），保证只要窗口在屏幕上可见就一定能拿到画面。
# ============================================================================

# PrintWindow 标志位
PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002   # Win8.1+：可抓 DirectComposition 内容

# CAPTUREBLT：把分层窗口（layered window）一并抓进来
CAPTUREBLT = 0x40000000

# GDI GetDeviceCaps 索引：物理桌面分辨率（用于 DPI 换算）
DESKTOPHORZRES = 118
DESKTOPVERTRES = 117
# GetSystemMetrics 索引：虚拟桌面逻辑分辨率
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# 捕获策略链（顺序即优先级）
CAPTURE_METHODS = (
    'printwindow_full',     # ① PrintWindow + PW_RENDERFULLCONTENT（首选，可抓加速窗口）
    'printwindow',          # ② PrintWindow 普通模式
    'bitblt_window',        # ③ 窗口 DC 直接 BitBlt（传统窗口）
    'bitblt_captureblt',    # ④ 窗口 DC BitBlt + CAPTUREBLT（带分层窗口）
    'qt_screen_crop',       # ⑤ Qt 整屏截图 + 裁剪（DPI 与 GetWindowRect 一致，多显示器）
    'gdi_screen_crop',      # ⑥ GDI 屏幕 DC BitBlt + 裁剪（按 DPI 缩放）
    'pil_screen_crop',      # ⑦ PIL ImageGrab + 裁剪（按 DPI 缩放，all_screens）
    'graphics_capture',     # ⑧ Windows.Graphics.Capture（pywincffi，若环境提供）
)

CAPTURE_METHOD_DESC = {
    'printwindow_full': 'PrintWindow(全内容)',
    'printwindow': 'PrintWindow(普通)',
    'bitblt_window': '窗口DC BitBlt',
    'bitblt_captureblt': '窗口DC BitBlt+CAPTUREBLT',
    'qt_screen_crop': 'Qt整屏截图裁剪',
    'gdi_screen_crop': 'GDI屏幕裁剪',
    'pil_screen_crop': 'PIL屏幕裁剪',
    'graphics_capture': 'Windows.Graphics.Capture',
}


def _hwnd(value):
    """把任意整数/句柄安全包装成 HWND（64 位下必须包，否则会被截断成 32 位）"""
    return wintypes.HWND(int(value)) if value else wintypes.HWND(0)


def get_window_title_unicode(hwnd):
    """用宽字符 API 读取窗口标题（解决中文乱码）"""
    try:
        user32 = ctypes.windll.user32
        length = user32.GetWindowTextLengthW(_hwnd(hwnd))
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(_hwnd(hwnd), buf, length + 1)
        return buf.value
    except Exception as e:
        debug_print(f"[捕获] 读取窗口标题失败: {e}")
        return ""


def enum_windows_unicode():
    """枚举可见的顶层窗口

    返回 [(title, hwnd, pid), ...]，按 Z 序（前台窗口在前）。
    全部使用宽字符 API，中文标题不会再乱码。
    """
    results = []
    try:
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def _callback(hwnd_, _lparam):
            try:
                if not hwnd_ or not user32.IsWindowVisible(_hwnd(hwnd_)):
                    return True
                # 跳过没有标题的"幽灵"窗口
                length = user32.GetWindowTextLengthW(_hwnd(hwnd_))
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(_hwnd(hwnd_), buf, length + 1)
                title = buf.value.strip()
                if not title:
                    return True
                pid = wintypes.DWORD(0)
                user32.GetWindowThreadProcessId(_hwnd(hwnd_), ctypes.byref(pid))
                results.append((title, int(hwnd_), int(pid.value)))
            except Exception as e:
                debug_print(f"[捕获] 枚举窗口回调异常: {e}")
            return True

        callback = WNDENUMPROC(_callback)   # 必须持有引用，否则回调会被 GC
        user32.EnumWindows(callback, 0)
    except Exception as e:
        safe_print(f"[捕获] 枚举窗口失败: {e}")
    return results


def find_window_unicode(title):
    """按标题精确查找窗口（宽字符 API，解决中文乱码找不到窗口的问题）"""
    if not title:
        return 0
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = wintypes.HWND
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        handle = user32.FindWindowW(None, title)
        return int(handle) if handle else 0
    except Exception as e:
        debug_print(f"[捕获] FindWindowW 失败: {e}")
        return 0


def qimage_to_bgr(qimg):
    """QImage -> OpenCV BGR（正确处理行对齐 padding）"""
    try:
        if qimg is None or qimg.isNull():
            return None
        qimg = qimg.convertToFormat(QImage.Format_RGB888)
        w, h = qimg.width(), qimg.height()
        if w <= 0 or h <= 0:
            return None
        ptr = qimg.constBits()
        if ptr is None:
            return None
        ptr.setsize(qimg.byteCount())
        stride = qimg.bytesPerLine()
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, stride)[:, :w * 3].reshape(h, w, 3)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception as e:
        debug_print(f"[捕获] QImage 转换失败: {e}")
        return None


def frame_is_usable(img, require_content=False):
    """判断抓到的帧是否可用

    require_content=True 时拒绝"几乎全黑"的帧 —— 这正是 BitBlt/PrintWindow 抓
    硬件加速窗口失败时的典型产物（返回成功但整张图是黑的）。
    """
    if img is None:
        return False
    if not isinstance(img, np.ndarray) or img.size == 0:
        return False
    if img.ndim != 3 or img.shape[2] != 3:
        return False
    if img.shape[0] < 2 or img.shape[1] < 2:
        return False
    if require_content:
        try:
            if int(img.max()) <= 8:
                return False      # 全黑
        except Exception:
            pass
    return True


# ============================================================================
#  硬件加速检测与 ONNX Runtime 调优（v2.1.0）
#  ---------------------------------------------------------------------------
#  目标：
#    1. 启动时自动检测本机可用的加速后端（CUDA / DirectML / OpenVINO / 纯 CPU），
#       能用 GPU 就用 GPU；也给用户一个可选的下拉框（config: accel_backend）；
#    2. 纯 CPU 时把"卡顿"从根上解决：ONNX Runtime 线程数/执行模式调优、
#       OpenCV 线程收敛（避免两套线程池互相抢核）、检测移到独立工作线程、
#       重复检测与重复查库全部去掉、大图降采样后再检测。
# ============================================================================
ACCEL_BACKENDS = ('auto', 'cuda', 'dml', 'openvino', 'cpu')
ACCEL_LABELS = {
    'auto': '自动',
    'cuda': 'CUDA (NVIDIA)',
    'dml': 'DirectML (WinGPU)',
    'openvino': 'OpenVINO (Intel)',
    'cpu': 'CPU',
}
# 后端 -> onnxruntime provider 名
BACKEND_TO_ORT_PROVIDER = {
    'cuda': 'CUDAExecutionProvider',
    'dml': 'DmlExecutionProvider',
    'openvino': 'OpenVINOExecutionProvider',
}


class _DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD),
                ('DeviceName', wintypes.WCHAR * 32),
                ('DeviceString', wintypes.WCHAR * 128),
                ('StateFlags', wintypes.DWORD),
                ('DeviceID', wintypes.WCHAR * 128),
                ('DeviceKey', wintypes.WCHAR * 128)]


def list_gpu_adapters():
    """枚举显卡名称（纯 ctypes，不依赖 wmic / nvidia-smi，也不需要网络）"""
    adapters = []
    try:
        user32 = ctypes.windll.user32
        dd = _DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(_DISPLAY_DEVICEW)
        i = 0
        while user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
            name = (dd.DeviceString or '').strip()
            if name and name not in adapters:
                adapters.append(name)
            i += 1
            if i > 32:
                break
    except Exception as e:
        debug_print(f"[加速] 枚举显卡失败: {e}")
    return adapters


def get_ort_info():
    """读取 onnxruntime 版本 / 设备 / 可用 provider 列表"""
    info = {'version': '', 'device': '', 'providers': [], 'error': ''}
    try:
        import onnxruntime as ort
        info['version'] = getattr(ort, '__version__', '')
        try:
            info['device'] = ort.get_device()
        except Exception:
            info['device'] = '未知'
        info['providers'] = list(ort.get_available_providers())
    except Exception as e:
        info['error'] = str(e)
    return info


def choose_accel_backend(preferred, available_providers):
    """决定实际使用的加速后端

    preferred = 'auto' 时按 CUDA > DirectML > OpenVINO > CPU 优先级自动挑；
    用户显式指定但本机不支持时，回退到 auto 的结果并给出提示。
    """
    available = set(available_providers or [])
    order = ('cuda', 'dml', 'openvino')
    auto_pick = 'cpu'
    for backend in order:
        if BACKEND_TO_ORT_PROVIDER[backend] in available:
            auto_pick = backend
            break

    preferred = (preferred or 'auto').lower()
    if preferred == 'auto':
        return auto_pick, ''
    if preferred == 'cpu':
        return 'cpu', ''
    if preferred not in BACKEND_TO_ORT_PROVIDER:
        return auto_pick, f"未知的加速后端 {preferred!r}，已按自动策略处理"
    provider = BACKEND_TO_ORT_PROVIDER[preferred]
    if provider in available:
        return preferred, ''
    hint = ACCEL_LABELS.get(preferred, preferred)
    if preferred == 'cuda':
        hint += '（需安装 onnxruntime-gpu 且显卡驱动支持 CUDA）'
    elif preferred == 'dml':
        hint += '（需安装 onnxruntime-directml）'
    elif preferred == 'openvino':
        hint += '（需安装 onnxruntime-openvino / openvino）'
    return auto_pick, f"本机不支持 {hint}，已回退为 {ACCEL_LABELS.get(auto_pick, auto_pick)}"


def build_ort_providers(backend):
    """构造 provider 列表；CPU 永远放在最后作为兜底"""
    providers = []
    if backend in BACKEND_TO_ORT_PROVIDER:
        providers.append(BACKEND_TO_ORT_PROVIDER[backend])
    providers.append('CPUExecutionProvider')
    return providers


def resolve_cpu_threads(cpu_threads):
    """把配置里的线程数换算成实际值（0/负数 = 自动 = 物理核心数，至少 1）"""
    try:
        value = int(cpu_threads)
    except (TypeError, ValueError):
        value = 0
    if value > 0:
        return value
    try:
        physical = psutil.cpu_count(logical=False) or 0
    except Exception:
        physical = 0
    if physical <= 0:
        physical = max(1, (os.cpu_count() or 2) // 2)
    return max(1, int(physical))


def make_ort_session_options(cpu_threads):
    """构造 ONNX Runtime 会话选项（纯 CPU 卡顿的核心调优点）

    * intra_op_num_threads：单个算子内部的并行线程数，默认=物理核数；
      显式设置可避免 ORT 按逻辑核数起线程导致超订；
    * inter_op_num_threads = 1：算子间不并行（人脸检测是串行小图推理，
      并行只会增加调度开销和延迟抖动）；
    * execution_mode = SEQUENTIAL：顺序执行，降低 CPU 抖动（对交互式 UI 更友好）；
    * graph_optimization_level = ALL：尽量做算子融合。
    """
    try:
        import onnxruntime as ort
        options = ort.SessionOptions()
        threads = resolve_cpu_threads(cpu_threads)
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        try:
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        except Exception:
            pass
        try:
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        except Exception:
            pass
        try:
            options.enable_mem_pattern = True
        except Exception:
            pass
        debug_print(f"[加速] ONNX 会话选项: intra_op={threads}, inter_op=1, 顺序执行")
        return options
    except Exception as e:
        safe_print(f"[加速] 构造 ONNX 会话选项失败（将使用默认值）: {e}")
        return None


def install_ort_session_options(session_options):
    """把会话选项注入 insightface 的模型加载流程

    insightface 的 `model_zoo.get_model()` 只透传 providers/provider_options，
    **不提供 sess_options 参数**，而线程数等关键调优必须在建会话时给。
    这里对 `PickableInferenceSession.__init__` 做一次幂等包装，
    在调用方没传 sess_options 时补上我们的选项。
    """
    if session_options is None:
        return False
    try:
        import insightface.model_zoo.model_zoo as _mz
        if getattr(_mz, '_dsh_session_options_patched', False):
            return True
        original_init = _mz.PickableInferenceSession.__init__

        def _patched_init(self, model_path, **kwargs):
            kwargs.setdefault('sess_options', session_options)
            return original_init(self, model_path, **kwargs)

        _mz.PickableInferenceSession.__init__ = _patched_init
        _mz._dsh_session_options_patched = True
        debug_print("[加速] 已注入 ONNX 会话选项（线程数/执行模式）")
        return True
    except Exception as e:
        safe_print(f"[加速] 注入 ONNX 会话选项失败（不影响功能）: {e}")
        return False


def optimize_cv2_threads(cpu_threads):
    """收敛 OpenCV 线程数

    OpenCV 默认会按逻辑核数起线程，而 ONNX Runtime 也在用同一批核做推理，
    两个线程池互相抢占会导致"帧率抖动、界面一卡一卡"。这里把 OpenCV 限制为 1~2 线程，
    把 CPU 让给 ONNX Runtime。
    """
    try:
        threads = resolve_cpu_threads(cpu_threads)
        cv_threads = 1 if threads <= 2 else 2
        cv2.setNumThreads(cv_threads)
        debug_print(f"[加速] OpenCV 线程数设为 {cv_threads}（原默认按核数）")
        return cv_threads
    except Exception as e:
        debug_print(f"[加速] 设置 OpenCV 线程数失败: {e}")
        return None


LEGACY_CPU_KEYWORDS = ('phenom', 'athlon', 'sempron', 'core(tm)2', 'core 2', 'pentium',
                       'celeron', 'atom', 'e2-', 'a4-', 'a6-', 'a8-', 'duo', 'fx-')


def is_legacy_cpu(cpu_name=None):
    """粗略判断是否为"老旧 CPU"（无 AVX2、算力弱）

    只用于给建议，不参与功能判断；关键词覆盖 2005~2013 年的常见型号。
    """
    name = (cpu_name if cpu_name is not None else get_cpu_name()) or ''
    low = name.lower()
    return any(k in low for k in LEGACY_CPU_KEYWORDS)


def get_cpu_name():
    """读取 CPU 型号名（Windows 注册表，无需第三方库）"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        try:
            value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return str(value).strip()
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass
    try:
        return platform.processor() or platform.machine() or '未知'
    except Exception:
        return '未知'


# 轻量模型优先级（CPU 推理吃力时建议切换）
LIGHT_MODELS = ('buffalo_sc', 'buffalo_s')


def recommend_light_model(current_model, detect_ms):
    """根据当前模型与实测检测耗时，给出"是否该换轻量模型"的建议

    返回 (是否需要建议, 建议的模型名, 说明文字)
    det_10g（buffalo_l / antelopev2 的检测器）比 det_500m（buffalo_s / buffalo_sc）
    重 5~10 倍，老 CPU 上这是最大的单点差异。
    """
    if detect_ms is None or detect_ms <= 0:
        return False, None, ''
    heavy = current_model in ('buffalo_l', 'antelopev2')
    if detect_ms >= 600 and heavy:
        target = 'buffalo_sc' if _model_available('buffalo_sc') else (
            'buffalo_s' if _model_available('buffalo_s') else None)
        if target:
            return True, target, (
                f"当前模型 {current_model} 的检测器是 det_10g（10G 级算力），"
                f"实测单次检测 {detect_ms:.0f}ms；\n"
                f"换用 {target}（检测器 det_500m + 轻量特征模型）通常能快 5~10 倍。")
    return False, None, ''


def _model_available(name):
    """models\\<name> 下的必需文件是否齐全"""
    try:
        info = MODELS.get(name)
        if not info:
            return False
        model_dir = os.path.join(models_root, name)
        return all(os.path.exists(os.path.join(model_dir, f)) and
                   os.path.getsize(os.path.join(model_dir, f)) > 10 * 1024
                   for f in info['files'])
    except Exception:
        return False


def probe_acceleration(preferred_backend='auto', cpu_threads=0):
    """汇总本机加速能力，返回诊断字典（供 UI/日志/测试使用）"""
    ort_info = get_ort_info()
    providers = ort_info.get('providers') or []
    effective, note = choose_accel_backend(preferred_backend, providers)
    gpus = list_gpu_adapters()
    info = {
        'ort_version': ort_info.get('version', ''),
        'ort_device': ort_info.get('device', ''),
        'ort_error': ort_info.get('error', ''),
        'providers': providers,
        'gpus': gpus,
        'cpu_name': get_cpu_name(),
        'cpu_physical': (psutil.cpu_count(logical=False) or 0),
        'cpu_logical': (os.cpu_count() or 0),
        'preferred': (preferred_backend or 'auto').lower(),
        'effective': effective,
        'effective_label': ACCEL_LABELS.get(effective, effective),
        'note': note,
        'cuda_available': 'CUDAExecutionProvider' in providers,
        'dml_available': 'DmlExecutionProvider' in providers,
        'openvino_available': 'OpenVINOExecutionProvider' in providers,
        'cpu_threads': resolve_cpu_threads(cpu_threads),
    }
    # 给出可操作的升级建议
    hints = []
    legacy_cpu = is_legacy_cpu(info.get('cpu_name'))
    info['legacy_cpu'] = legacy_cpu
    if not info['cuda_available']:
        has_nvidia = any('nvidia' in g.lower() or 'geforce' in g.lower() or 'rtx' in g.lower()
                         for g in gpus)
        if has_nvidia:
            hints.append(
                "检测到 NVIDIA 显卡，但当前 onnxruntime 未启用 CUDA。\n"
                "     可用 GPU 加速：pip install onnxruntime-gpu。\n"
                "     ⚠️ 注意：onnxruntime-gpu 需要较新的显卡（CUDA 计算能力 ≥ 3.5，"
                "GT/GTS 等 Fermi 老卡不支持）；DirectML 需要显卡支持 DirectX 12。\n"
                "     老显卡请优先使用下面的「轻量模型 + CPU 多线程」方案。")
        else:
            hints.append(
                "未检测到 CUDA/GPU 版 onnxruntime，可尝试 pip install onnxruntime-directml"
                "（Windows 通用 GPU 加速，需显卡支持 DX12）")
    if effective == 'cpu':
        hints.append(
            f"当前为纯 CPU 推理：已启用多线程工作线程、ONNX intra_op={info['cpu_threads']} 线程、"
            f"OpenCV 线程收敛、跳过重复检测与重复查库、大图先降采样")
        if legacy_cpu or (info['cpu_physical'] and info['cpu_physical'] <= 4):
            hints.append(
                f"CPU「{info.get('cpu_name')}」属于低算力型号，强烈建议使用轻量模型 "
                f"buffalo_sc / buffalo_s（检测器 det_500m，比 buffalo_l 的 det_10g 快 5~10 倍）")
    info['hints'] = hints
    return info


def format_acceleration_report(info):
    """把诊断字典格式化成日志面板可读的报告"""
    lines = ["=" * 46,
             "🚀 硬件加速检测报告",
             f"   · onnxruntime: {info.get('ort_version') or '未安装'}  "
             f"(device={info.get('ort_device') or '未知'})"]
    if info.get('ort_error'):
        lines.append(f"   · onnxruntime 导入异常: {info['ort_error']}")
    lines.append(f"   · 可用 provider: {', '.join(info.get('providers') or []) or '无'}")
    gpus = info.get('gpus') or []
    lines.append(f"   · 显卡: {', '.join(gpus) if gpus else '未识别到'}")
    lines.append(f"   · CPU: {info.get('cpu_name') or '未知'}"
                 f"（物理 {info.get('cpu_physical')} 核 / 逻辑 {info.get('cpu_logical')} 核）")
    lines.append(f"   · 本机推荐后端: {ACCEL_LABELS.get(info.get('effective'), info.get('effective'))}")
    preferred = info.get('preferred', 'auto')
    if preferred != 'auto':
        lines.append(f"   · 用户指定后端: {ACCEL_LABELS.get(preferred, preferred)}"
                     f" → 实际使用: {info.get('effective_label')}")
    lines.append(f"   · ONNX intra_op 线程数: {info.get('cpu_threads')}")
    for hint in info.get('hints') or []:
        lines.append(f"   💡 {hint}")
    if info.get('note'):
        lines.append(f"   ⚠️ {info['note']}")
    lines.append("=" * 46)
    return "\n".join(lines)


class FaceDetectWorker(QThread):
    """独立的人脸检测线程（v2.1.0）

    为什么需要它：`face_app.get()` 在纯 CPU 上是几十到几百毫秒的阻塞调用。
    历史版本直接在 UI 线程（QTimer 回调）里跑，并且**同一帧检测了两遍**、
    每个脸还要重复查库 2~4 次，于是界面必然一卡一卡。

    本 worker 负责"检测 + 特征检索"这两件重活：
      * 只保留最新一帧（`submit` 覆盖旧任务），检测跟不上时自动丢帧，不排队、不积压；
      * 结果通过信号回到 UI 线程，UI 只做绘制，永不阻塞；
      * 不触碰任何 Qt 控件，保证线程安全。
    """

    result_ready = pyqtSignal(object)     # {'faces': [...], 'elapsed_ms': float, 'dropped': int}
    detect_failed = pyqtSignal(str)

    def __init__(self, face_app_provider, face_db, param_provider, parent=None):
        super().__init__(parent)
        self._get_face_app = face_app_provider
        self._db = face_db
        self._get_params = param_provider
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._pending = None
        self._stop = False
        self._dropped = 0
        self.processed = 0

    # ---------------- 供 UI 线程调用 ----------------
    def submit(self, frame, rois, face_id_start):
        """投递一帧（frame/rois 由 UI 线程构造，worker 只读，不得修改）"""
        with self._lock:
            if self._pending is not None:
                self._dropped += 1          # 上一帧还没处理完：丢帧，保证不积压
            self._pending = (frame, rois, face_id_start)
        self._event.set()
        return self._dropped

    @property
    def busy(self):
        with self._lock:
            return self._pending is not None

    @property
    def dropped(self):
        with self._lock:
            return self._dropped

    def request_stop(self):
        self._stop = True
        self._event.set()

    # ---------------- 线程体 ----------------
    def run(self):
        debug_print("[检测线程] 启动")
        while not self._stop:
            self._event.wait(0.2)
            if self._stop:
                break
            with self._lock:
                job = self._pending
                self._pending = None
                self._event.clear()
            if job is None:
                continue
            frame, rois, face_id_start = job
            try:
                t0 = time.time()
                faces = self._detect(frame, rois, face_id_start)
                elapsed = (time.time() - t0) * 1000.0
                self.processed += 1
                self.result_ready.emit({
                    'faces': faces,
                    'elapsed_ms': elapsed,
                    'dropped': self.dropped,
                    'frame_shape': frame.shape,
                })
            except Exception as e:
                self.detect_failed.emit(f"人脸检测线程异常: {e}")
                debug_print(f"[检测线程] 异常: {traceback.format_exc()}")
        debug_print("[检测线程] 退出")

    def _detect(self, frame, rois, face_id_start):
        """在 worker 线程里完成 ROI 检测 + 特征检索，返回可交给 UI 的结果列表"""
        face_app = self._get_face_app()
        if face_app is None:
            return []
        params = self._get_params() or {}
        preprocess = bool(params.get('enable_preprocess', True))
        low_perf = bool(params.get('low_performance_mode', False))
        max_num = int(params.get('max_detect_faces', 0) or 0)
        throttle = float(params.get('detect_input_max_side', 1280) or 1280)

        height, width = frame.shape[:2]
        results = []
        face_id = face_id_start
        seen_boxes = []

        for roi in (rois or [(0, 0, width, height)]):
            x1, y1, x2, y2 = [int(v) for v in roi]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(width, x2), min(height, y2)
            if x2 - x1 < 16 or y2 - y1 < 16:
                continue
            roi_img = frame[y1:y2, x1:x2]
            if roi_img.size == 0:
                continue

            # 大图先降采样再检测（纯 CPU 下这是最直接的提速手段）
            detect_img, scale = self._prepare_input(roi_img, preprocess, low_perf, throttle)

            try:
                if max_num > 0:
                    faces = face_app.get(detect_img, max_num=max_num)
                else:
                    faces = face_app.get(detect_img)
            except TypeError:
                faces = face_app.get(detect_img)
            except Exception as e:
                debug_print(f"[检测线程] ROI 检测失败: {e}")
                continue

            for face in faces:
                bbox = face.bbox.astype(float)
                if scale != 1.0:
                    bbox = bbox / scale
                bbox = bbox.astype(int)
                bx1 = int(bbox[0]) + x1
                by1 = int(bbox[1]) + y1
                bx2 = int(bbox[2]) + x1
                by2 = int(bbox[3]) + y1
                bx1, by1 = max(0, bx1), max(0, by1)
                bx2, by2 = min(width, bx2), min(height, by2)
                if bx2 - bx1 < 4 or by2 - by1 < 4:
                    continue
                # 同一帧里多个 ROI 可能重叠，去重避免重复框/重复查库
                box = (bx1, by1, bx2, by2)
                if any(self._iou(box, other) > 0.6 for other in seen_boxes):
                    continue
                seen_boxes.append(box)

                match = self._db.search_face(face.embedding) if self._db is not None else {}
                name = (match or {}).get('name')
                similarity = float((match or {}).get('similarity') or 0.0)
                confidence = float((match or {}).get('confidence') or 0.0)

                face_img = frame[by1:by2, bx1:bx2]
                results.append({
                    'face_id': face_id,
                    'bbox': [bx1, by1, bx2, by2],
                    'det_score': float(getattr(face, 'det_score', 0.0)),
                    'embedding': face.embedding,
                    'name': name,
                    'similarity': similarity,
                    'confidence': confidence,
                    'image': face_img.copy() if face_img.size else None,
                })
                face_id += 1
        return results

    @staticmethod
    def _prepare_input(roi_img, enable_preprocess, low_performance_mode, max_side):
        """按需降采样；返回 (图像, 相对原 ROI 的缩放比)"""
        try:
            if not enable_preprocess:
                return roi_img, 1.0
            h, w = roi_img.shape[:2]
            limit = float(max_side or 1280)
            if low_performance_mode:
                limit = min(limit, 960.0)      # 低性能模式再降一档
            if max(h, w) <= limit:
                return roi_img, 1.0
            scale = limit / float(max(h, w))
            resized = cv2.resize(roi_img, (max(1, int(w * scale)), max(1, int(h * scale))),
                                 interpolation=cv2.INTER_AREA)
            return resized, scale
        except Exception as e:
            debug_print(f"[检测线程] 预处理失败，用原图: {e}")
            return roi_img, 1.0

    @staticmethod
    def _iou(a, b):
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
        area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
        union = area_a + area_b - inter
        return inter / float(union) if union > 0 else 0.0


class FaceRecognitionApp(QMainWindow):
    safe_add_widget_signal = pyqtSignal(QWidget)

    def __init__(self):
        super().__init__()

        # ==================================================================
        # 配置（需求6：所有设置实时自动保存 + 持久保存）
        # ------------------------------------------------------------------
        # v2.0.0 重要变更：本方法末尾原来有一大段硬编码赋值，会在 init_ui() 之后
        # 覆盖 user 的配置（model_name→buffalo_sc、det_size→640x640、
        # roi_threshold→0.1、min_roi_area→500、detection_interval→500、
        # enable_preprocess→True、setGeometry(100,100,1200,800)），造成
        # "界面显示 buffalo_l / 实际加载 buffalo_sc" 这类设置失灵且无法持久化的现象。
        # 现在 config.json 是唯一权威来源，不再有任何硬编码覆盖。
        # ==================================================================
        self._restoring_ui = False   # 回填控件期间抑制"写回配置"，防止默认值覆盖用户设置

        config_path = os.path.join(BASE_DIR, 'config.json')
        self.config = ConfigManager(config_path)
        self.config.load_config()

        self.color_check = None
        self.default_font = QFont("Microsoft YaHei", 10)  # 使用与主程序相同的字体
        self.default_stylesheet = "font-size: 12px;"      # 设置固定字体大小

        # ------ 从配置加载参数（权威值，其它地方不得再硬编码覆盖）------
        self.model_name = self.config.get('model_name', 'buffalo_l')
        self.detection_interval = self.config.get('det_interval', 500)
        try:
            self.det_size = tuple(map(int, str(self.config.get('det_size', '640x640')).split('x')))
        except Exception:
            self.det_size = (640, 640)
        self.low_performance_mode = bool(self.config.get('low_performance_mode', False))
        self.detect_interval = self.config.get('detect_interval', 5)
        self.roi_threshold = self.config.get('roi_threshold', 0.1)
        self.min_roi_area = self.config.get('min_roi_area', 500)
        self.enable_preprocess = self.config.get('enable_preprocess', True)
        self.max_display = self.config.get('max_display', 10)

        # 调试开关必须在这里生效（历史版本只在勾选框变化时切换 DEBUG_PRINT，
        # 所以 config 里 debug_mode=true 时启动后其实仍然是关闭的）
        global DEBUG_PRINT
        DEBUG_PRINT = bool(self.config.get('debug_mode', False))

        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(QIcon(os.path.join(BASE_DIR, "icon.ico")))

        # 初始化日志组件
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)

        # 识别结果显示相关
        self.displayed_faces = []  # 用于跟踪已显示的人脸

        # ------ 跟踪 / 缓存相关变量（必须在 init_ui() 之前就绪）------
        # 注意：故意不预置 self.last_frame —— 多处逻辑用 hasattr(self,'last_frame')
        # 判断"是否已有上一帧"，预置为 None 会让 cv2.absdiff 收到 None 而报错。
        self.tracked_faces = []       # 存储跟踪中的人脸信息
        self.tracking_frames = 0      # 跟踪持续帧数计数器
        self.last_gray = None         # 上一帧的灰度图像
        self.last_detection_time = 0
        self.last_detected_name = None
        self.current_faces = []
        self.current_face_id = 0      # 用于生成唯一 face_id
        self.face_cache = {}
        self.font_cache = {}
        self.add_progress = 0
        self.fps = 0
        self.fps_counter = 0
        self.current_window = None
        self.is_detecting = False
        self.proxy_settings = None
        self.face_app = None          # 显式初始化，避免各处在模型加载前访问报 AttributeError
        self.has_openvino = False
        # ---- v2.1.0 加速/性能状态 ----
        self.accel_info = {}          # probe_acceleration() 的结果
        self.detect_worker = None     # FaceDetectWorker（检测线程）
        self.last_detect_ms = 0.0     # 最近一次检测耗时（用于性能显示）
        self.detect_skipped = 0       # 因线程忙而丢掉的帧数

        # 光流法参数配置
        self.lk_params = dict(
            winSize=(15, 15),  # 搜索窗口大小
            maxLevel=2,        # 金字塔层数
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03)
        )

        # 线程池（CPU核心数×2，最少4个，最多8个）
        self.thread_pool = QThreadPool()
        cpu_count = os.cpu_count() or 2
        max_threads = min(max(4, cpu_count * 2), 8)
        self.thread_pool.setMaxThreadCount(max_threads)
        self.log_message(f"🛠️ 初始化线程池: 最大线程数 = {max_threads} (CPU核心数 = {cpu_count})")
        self.safe_add_widget_signal.connect(self._add_widget_handler)

        # 初始化UI（内部会按配置回填所有控件）
        self.init_ui()

        # ------ 窗口位置和大小：只有没有历史记录时才用默认几何 ------
        restored_geometry = False
        geometry_hex = self.config.get('window_geometry')
        if geometry_hex:
            try:
                if isinstance(geometry_hex, str):
                    geometry_bytes = QByteArray.fromHex(geometry_hex.encode())
                    if not geometry_bytes.isEmpty():
                        restored_geometry = self.restoreGeometry(geometry_bytes)
            except Exception as e:
                debug_print(f"恢复窗口几何形状失败: {str(e)}")
        if not restored_geometry:
            self.setGeometry(100, 100, 1200, 800)
        self.setFont(QFont("Microsoft YaHei", 10))

        # 检查OpenVINO支持
        self.has_openvino = False
        debug_print("正在检查OpenVINO支持...")
        try:
            from insightface.model_zoo import get_model
            if hasattr(get_model, 'openvino'):
                self.has_openvino = True
                self.log_message("🛠️ 检测到OpenVINO支持，可使用硬件加速")
        except Exception as e:
            debug_print(f"OpenVINO检查失败: {str(e)}")

        # 恢复UI状态（控件值 ← config.json）
        self.restore_ui_state()

        # 恢复代理设置显示
        proxy_settings = self.config.get('proxy_settings')
        if proxy_settings:
            self.proxy_settings = proxy_settings
            try:
                self.proxy_status.setText(
                    f"代理: {str(proxy_settings['type']).upper()} {proxy_settings['host']}:{proxy_settings['port']}")
            except Exception:
                pass

        # 显示加载状态
        self.result_label.setText("状态: 正在初始化...")
        self.log_message(f"🚀 应用程序启动 v{VERSION}，开始初始化")
        self.log_message(f"📄 配置文件: {self.config.config_file}")

        # 延迟加载模块（模型 / 数据库）
        QTimer.singleShot(100, self.delayed_init)

    def migrate_existing_faces(self):
        """迁移现有图片到子目录（完整修正版）"""
        print("[DEBUG] 开始执行图片迁移流程")
        progress = None
        try:
            # 1. 检查faces目录
            faces_dir = "faces"
            print(f"[DEBUG] 检查目标目录: {faces_dir}")
            if not os.path.exists(faces_dir):
                print(f"[DEBUG] 目录不存在，创建目录: {faces_dir}")
                os.makedirs(faces_dir, exist_ok=True)
            
            # 2. 检查数据库连接
            print("[DEBUG] 检查数据库连接状态")
            if not hasattr(self.face_db, 'conn'):
                raise Exception("人脸数据库连接未正确初始化")
            
            # 3. 获取数据库游标
            try:
                print("[DEBUG] 尝试获取数据库游标")
                cursor = self.face_db.conn.cursor()
                if cursor is None:
                    raise Exception("无法获取数据库游标")
                print("[DEBUG] 成功获取数据库游标")
            except Exception as e:
                raise Exception(f"获取数据库游标失败: {str(e)}")
            
            # 4. 执行查询
            try:
                print("[DEBUG] 执行人脸数据查询")
                cursor.execute("SELECT id, name, image_path FROM faces")
                faces = cursor.fetchall()
                print(f"[DEBUG] 查询到 {len(faces)} 条人脸记录")
            except Exception as e:
                raise Exception(f"查询人脸数据失败: {str(e)}")
            finally:
                cursor.close()  # 确保关闭游标
            
            if not faces:
                print("[DEBUG] 没有需要迁移的人脸数据")
                QMessageBox.information(self, "提示", "没有人脸数据需要迁移")
                return
            
            # 5. 设置进度条
            print("[DEBUG] 初始化进度条")
            progress = QProgressDialog("正在迁移图片...", "取消", 0, len(faces), self)
            progress.setWindowTitle("图片迁移")
            progress.setWindowModality(Qt.WindowModal)
            
            success_count = 0
            error_count = 0
            
            # 6. 处理每条记录
            print("[DEBUG] 开始处理人脸记录")
            for i, (face_id, name, image_path) in enumerate(faces):
                if progress.wasCanceled():
                    print("[DEBUG] 用户取消了迁移操作")
                    break
                    
                progress.setValue(i)
                QApplication.processEvents()
                
                try:
                    print(f"[DEBUG] 处理记录 {i+1}/{len(faces)} - ID: {face_id}, 姓名: {name}")
                    
                    # 检查数据有效性
                    if not all([face_id, name, image_path]):
                        print(f"[DEBUG] 记录 {face_id} 数据不完整，跳过")
                        error_count += 1
                        continue
                    
                    if not isinstance(image_path, str) or not image_path.strip():
                        print(f"[DEBUG] 记录 {face_id} 图片路径无效，跳过")
                        error_count += 1
                        continue
                    
                    # 处理路径
                    src_path = image_path.strip()
                    print(f"[DEBUG] 源文件路径: {src_path}")
                    if not os.path.exists(src_path):
                        print(f"[DEBUG] 文件不存在: {src_path}")
                        error_count += 1
                        continue
                    
                    # 创建目标目录
                    safe_name = re.sub(r'[^\w]', '', 
                                    pinyin.get(name, format="strip", delimiter="_"))
                    target_dir = os.path.join("faces", safe_name)
                    print(f"[DEBUG] 目标目录: {target_dir}")
                    os.makedirs(target_dir, exist_ok=True)
                    
                    # 移动文件
                    filename = f"{safe_name}_{int(time.time())}.jpg"
                    dest_path = os.path.join(target_dir, filename)
                    print(f"[DEBUG] 目标文件路径: {dest_path}")
                    
                    print(f"[DEBUG] 正在移动文件: {src_path} -> {dest_path}")
                    shutil.move(src_path, dest_path)
                    
                    # 更新数据库
                    print(f"[DEBUG] 更新数据库记录 {face_id}")
                    update_cursor = self.face_db.conn.cursor()  # 创建新游标用于更新
                    update_cursor.execute("UPDATE faces SET image_path=? WHERE id=?", 
                                (dest_path, face_id))
                    self.face_db.conn.commit()
                    update_cursor.close()  # 关闭更新游标
                    success_count += 1
                    print(f"[DEBUG] 记录 {face_id} 迁移成功")
                    
                except Exception as e:
                    error_count += 1
                    print(f"[ERROR] 迁移记录 {face_id} 失败: {str(e)}")
                    print(f"[DEBUG] 当前成功数: {success_count}, 失败数: {error_count}")
                    continue
                    
            # 7. 显示结果
            progress.close()
            result_msg = f"迁移完成\n成功: {success_count}\n失败: {error_count}"
            if progress.wasCanceled():
                result_msg += "\n(用户取消)"
            print(f"[DEBUG] 迁移结果: {result_msg}")
            QMessageBox.information(self, "完成", result_msg)
            
        except Exception as e:
            if progress:
                progress.close()
            error_msg = f"迁移失败: {str(e)}"
            print(f"[ERROR] {error_msg}")
            print("[DEBUG] 打印异常堆栈:")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", error_msg)







    def delayed_init(self):
        """延迟初始化重模块（数据库 / 模型 / 监控定时器）

        v2.0.0 修复：
          1. 原来这里第二次调用 init_ui()（控件被重建两遍、信号重复连接、
             用户刚恢复的界面状态被再刷一次），现 init_ui() 自带幂等保护；
          2. 原来这里把 self.proxy_settings 置为 None，会把启动时刚恢复的
             代理设置清空，现改为从配置恢复；
          3. 原来 check_and_download_model() 被调用两次（重复建模型/重复弹下载框），
             现只调用一次；
          4. 刷新窗口列表后按配置恢复"上次使用的窗口"，并把选择变化写回配置。
          5. 新增重入/重复执行保护：delayed_init 内部会 processEvents()，
             可能让 pending 的 singleShot 提前触发，历史上会出现"数据库被连两次、
             内存监控线程被创建两次（前者被 GC 后仍在线程中运行 → 崩溃）"的问题。
        """
        if getattr(self, '_initializing', False) or getattr(self, '_initialized', False):
            debug_print("delayed_init 已执行或正在执行，跳过重复初始化")
            return
        self._initializing = True
        try:
            self.log_message("🚀 正在加载人脸数据库...")
            self.result_label.setText("状态: 正在加载人脸数据库")
            QApplication.processEvents()  # 更新UI

            self.face_db = FaceDatabase()
            self.face_app = None
            self.timer = QTimer()
            self.current_window = None
            self.is_detecting = False
            # 代理设置：从配置恢复，不要清空
            self.proxy_settings = self.config.get('proxy_settings')

            self.log_message("🚀 正在启动内存监控...")
            self.result_label.setText("状态: 正在启动内存监控")
            QApplication.processEvents()  # 更新UI

            self.memory_monitor = MemoryMonitor()
            self.unknown_faces_cleanup_timer = QTimer()

            # 初始化UI（幂等：重复调用不会重建控件）
            self.init_ui()

            # 刷新窗口列表并按配置恢复上次选择，然后只检查一次模型
            self.refresh_windows()
            self.restore_last_window()
            self.check_and_download_model()

            # 启动内存监控
            self.memory_monitor.update_signal.connect(self.update_memory_status)
            self.memory_monitor.start()
            
            # 设置自动清理未知人脸定时器（每天检查一次）
            self.unknown_faces_cleanup_timer.timeout.connect(self.cleanup_unknown_faces)
            self.unknown_faces_cleanup_timer.start(24 * 60 * 60 * 1000)  # 24小时

            # 启动CPU监控
            self.cpu_monitor = QTimer()
            self.cpu_monitor.timeout.connect(self.update_cpu_usage)
            self.cpu_monitor.start(2000)  # 每2秒更新一次

            # 启动FPS监控
            self.fps_counter = 0
            self.fps_timer = QTimer()
            self.fps_timer.timeout.connect(self.update_fps)
            self.fps_timer.start(1000)  # 每秒更新一次

            self.log_message("🚀 初始化完成，准备加载模型...")
            self.result_label.setText("状态: 初始化完成，准备加载模型")
            QApplication.processEvents()  # 更新UI

            # 添加人脸缓存
            self.face_cache = {}
            self.current_face_id = 0  # 用于生成唯一face_id

            # ---- v2.1.0：加速检测报告 + 建立检测工作线程 ----
            self.report_acceleration(verbose=True)
            self._start_detect_worker()

            self._initialized = True
        except Exception as e:
            self.log_message(f"❌ 初始化失败: {str(e)}")
            print(f"❌ [DEBUG] 初始化失败: {str(e)}")
            self.result_label.setText(f"状态: 初始化失败 - {str(e)}")
            QMessageBox.critical(self, "错误", f"初始化失败: {str(e)}")
            print(f"❌ [DEBUG] 初始化失败时的堆栈跟踪:\n{traceback.format_exc()}")
        finally:
            self._initializing = False

    def cv2_add_chinese_text(self, img, text, position, textColor=(255, 255, 255), textSize=30):
        """修复后的中文文本绘制方法"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            import numpy as np
            
            # 加载字体（确保 simhei.ttf 存在）
            font_path = "simhei.ttf"  # 或替换为系统字体如 "msyh.ttc"
            font = ImageFont.truetype(font_path, textSize, encoding="utf-8")
            
            # 转换 OpenCV 图像为 PIL 格式
            img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(img_pil)
            
            # 计算文本尺寸（兼容新版 Pillow）
            bbox = draw.textbbox((0, 0), text, font=font)  # 关键修复：显式传入 text 和 font
            text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
            
            # 绘制半透明背景
            x, y = position
            draw.rectangle(
                (x, y - text_height, x + text_width, y),
                fill=(0, 0, 0, 128)  # 黑色半透明背景
            )
            
            # 绘制文本
            draw.text((x, y - text_height), text, font=font, fill=textColor)
            
            # 转换回 OpenCV 格式
            return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
        except Exception as e:
            print(f"1267添加中文文本失败: {str(e)}")
            return img  # 失败时返回原图

    def init_ui(self):
        """构建主界面

        v2.0.0：加入幂等保护。历史版本在 __init__ 和 delayed_init 中各调用一次本方法，
        控件被创建两遍、信号重复连接（同一槽被触发两次），第二次调用还会把界面状态
        重新按硬编码默认值刷一遍。现在只允许构建一次。

        注意：幂等标记放在**方法末尾**才置位。若放在开头，中途构建失败会留下
        "标记已置位但界面残缺"的状态，后续调用会静默跳过重建（比报错更难查）。
        """
        if getattr(self, '_ui_built', False):
            debug_print("init_ui 已执行过，跳过重复构建")
            return

        main_widget = QWidget()
        main_layout = QHBoxLayout()

        # 使用分割器实现可调整大小的布局
        splitter = QSplitter(Qt.Horizontal)

        # 左侧控制面板（紧凑布局）
        control_panel = QWidget()
        control_layout = QVBoxLayout()
        control_layout.setContentsMargins(5, 5, 5, 5)
        control_layout.setSpacing(3)

        # 代理和模型设置（折叠面板）
        settings_group = QGroupBox("系统设置")
        # v2.1.0：改为两行 —— 第 1 行 代理/调试/模型，第 2 行 加速后端/线程/检测
        settings_layout = QVBoxLayout()
        settings_row1 = QHBoxLayout()
        settings_row1.setContentsMargins(0, 0, 0, 0)
        settings_row2 = QHBoxLayout()
        settings_row2.setContentsMargins(0, 0, 0, 0)
        
        # 代理设置
        proxy_layout = QHBoxLayout()
        proxy_layout.setContentsMargins(0, 0, 0, 0)
        self.proxy_status = QLabel("代理:")
        self.proxy_status.setFixedWidth(40)
        btn_proxy = QPushButton("设置")
        btn_proxy.setFixedWidth(60)
        btn_proxy.clicked.connect(self.set_proxy)
        proxy_layout.addWidget(self.proxy_status)
        proxy_layout.addWidget(btn_proxy)
        settings_row1.addLayout(proxy_layout)

        # 调试模式复选框
        self.debug_check = QCheckBox("调试模式")
        self.debug_check.setChecked(self.config.get('debug_mode', False))
        self.debug_check.stateChanged.connect(self.toggle_debug_mode)
        settings_row1.addWidget(self.debug_check)

        # 模型选择
        model_layout = QHBoxLayout()
        # model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.addWidget(QLabel("模型:"))
        self.model_combo = QComboBox()
        self.model_combo.setFixedWidth(100)
        self.model_combo.addItems(MODELS.keys())
        self.model_combo.setCurrentText(self.model_name)
        self.model_combo.currentTextChanged.connect(self.change_model)
        model_layout.addWidget(self.model_combo)
        settings_row1.addLayout(model_layout)

        # ---- v2.1.0 第 2 行：加速后端 / 线程数 / 检测按钮 ----
        settings_row2.addWidget(QLabel("加速:"))
        self.accel_combo = QComboBox()
        self.accel_combo.setFixedWidth(110)
        for backend in ACCEL_BACKENDS:
            self.accel_combo.addItem(ACCEL_LABELS[backend], backend)
        self.accel_combo.setToolTip(
            "自动：启动时检测 CUDA / DirectML / OpenVINO，能用 GPU 就用 GPU，否则用 CPU\n"
            "选其它项表示强制指定后端（本机不支持时会自动回退并在日志里提示）")
        self.accel_combo.currentIndexChanged.connect(self.on_accel_backend_changed)
        settings_row2.addWidget(self.accel_combo)

        settings_row2.addWidget(QLabel("线程:"))
        self.cpu_threads_spin = QSpinBox()
        self.cpu_threads_spin.setRange(0, 64)
        self.cpu_threads_spin.setValue(0)
        self.cpu_threads_spin.setFixedWidth(60)
        self.cpu_threads_spin.setToolTip("ONNX Runtime 推理线程数；0 = 自动（物理核心数）。\n"
                                         "纯 CPU 机器上建议 = 物理核心数，不要超过逻辑核心数")
        self.cpu_threads_spin.valueChanged.connect(self.on_cpu_threads_changed)
        settings_row2.addWidget(self.cpu_threads_spin)

        self.btn_accel_probe = QPushButton("加速检测")
        self.btn_accel_probe.setFixedWidth(80)
        self.btn_accel_probe.setToolTip("检测本机 GPU/加速能力并输出报告（切换后端后建议重新检测）")
        self.btn_accel_probe.clicked.connect(lambda: self.report_acceleration(verbose=True, show_dialog=True))
        settings_row2.addWidget(self.btn_accel_probe)

        settings_layout.addLayout(settings_row1)
        settings_layout.addLayout(settings_row2)

        settings_group.setLayout(settings_layout)
        control_layout.addWidget(settings_group)

        # 参数调节区域（折叠面板）
        param_group = QGroupBox("检测参数")
        param_layout = QFormLayout()
        #param_layout.setRowWrapPolicy(QFormLayout.DontWrapRows)
        #param_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        #param_layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        #param_layout.setLabelAlignment(Qt.AlignLeft)

        # 性能模式选择
        performance_mode_layout = QHBoxLayout()
        performance_mode_layout.addWidget(QLabel("性能模式:"))
        self.performance_mode_combo = QComboBox()
        self.performance_mode_combo.addItems(["自动", "手动"])
        performance_mode_layout.addWidget(self.performance_mode_combo)
        param_layout.addRow(performance_mode_layout)

        # 检测阈值
        self.thresh_slider = QSlider(Qt.Horizontal)
        self.thresh_slider.setRange(50, 95)
        self.thresh_slider.setValue(70)
        self.thresh_spin = QSpinBox()
        self.thresh_spin.setRange(50, 95)
        self.thresh_spin.setValue(70)
        self.thresh_spin.setFixedWidth(60)

        # 添加同步连接
        self.thresh_slider.valueChanged.connect(self.thresh_spin.setValue)
        self.thresh_spin.valueChanged.connect(self.thresh_slider.setValue)
        self.thresh_slider.valueChanged.connect(self.on_thresh_changed)

        thresh_layout = QHBoxLayout()
        thresh_layout.addWidget(self.thresh_slider)
        thresh_layout.addWidget(self.thresh_spin)
        param_layout.addRow(QLabel("检测阈值:"), thresh_layout)

        # 检测间隔
        self.interval_slider = QSlider(Qt.Horizontal)
        self.interval_slider.setRange(50, 1000)
        self.interval_slider.setValue(500)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(50, 1000)
        self.interval_spin.setValue(500)
        self.interval_spin.setFixedWidth(60)

        # 添加同步连接
        self.interval_slider.valueChanged.connect(self.interval_spin.setValue)
        self.interval_spin.valueChanged.connect(self.interval_slider.setValue)
        self.interval_slider.valueChanged.connect(self.on_interval_changed)

        interval_layout = QHBoxLayout()
        interval_layout.addWidget(self.interval_slider)
        interval_layout.addWidget(self.interval_spin)
        param_layout.addRow(QLabel("检测间隔(ms):"), interval_layout)

        # ====== 优化参数控制 ======
        # 完整检测间隔
        self.detect_interval_spin = QSpinBox()
        self.detect_interval_spin.setRange(1, 30)
        self.detect_interval_spin.setValue(5)
        self.detect_interval_spin.setFixedWidth(60)
        # v2.0.0：恢复连接。原版本把这行注释掉了，导致"完整检测间隔"改了既不生效也不保存。
        self.detect_interval_spin.valueChanged.connect(self.on_detect_interval_changed)
        param_layout.addRow(QLabel("完整检测间隔(帧):"), self.detect_interval_spin)

        # ROI变化阈值
        self.roi_thresh_slider = QSlider(Qt.Horizontal)
        self.roi_thresh_slider.setRange(1, 30)  # 1%-30%
        self.roi_thresh_slider.setValue(10)
        self.roi_thresh_spin = QSpinBox()
        self.roi_thresh_spin.setRange(1, 30)
        self.roi_thresh_spin.setValue(10)
        self.roi_thresh_spin.setFixedWidth(60)

        # 添加同步连接
        self.roi_thresh_slider.valueChanged.connect(self.roi_thresh_spin.setValue)
        self.roi_thresh_spin.valueChanged.connect(self.roi_thresh_slider.setValue)
        self.roi_thresh_slider.valueChanged.connect(self.on_roi_thresh_changed)
        self.roi_thresh_spin.valueChanged.connect(self.on_roi_thresh_changed)
        
        roi_thresh_layout = QHBoxLayout()
        roi_thresh_layout.addWidget(self.roi_thresh_slider)
        roi_thresh_layout.addWidget(self.roi_thresh_spin)
        param_layout.addRow(QLabel("ROI变化阈值(%):"), roi_thresh_layout)

        # 初始化控件
        self.min_roi_spin = QSpinBox()
        self.min_roi_spin.setRange(100, 2000)
        self.min_roi_spin.setValue(500)
        self.min_roi_spin.setFixedWidth(60)
        self.min_roi_spin.valueChanged.connect(self.on_min_roi_changed)

        self.max_display_spin = QSpinBox()
        self.max_display_spin.setRange(1, 9999)
        self.max_display_spin.setValue(10)
        self.max_display_spin.setFixedWidth(60)
        self.max_display_spin.valueChanged.connect(self.on_max_display_changed)

        # 最小ROI面积和显示数量设置在同一行
        roi_display_layout = QHBoxLayout()
        roi_display_layout.addWidget(QLabel("最小ROI面积:"))
        roi_display_layout.addWidget(self.min_roi_spin)
        roi_display_layout.addSpacing(20)  # 添加一些间距
        roi_display_layout.addWidget(QLabel("显示数量:"))
        roi_display_layout.addWidget(self.max_display_spin)
        param_layout.addRow(roi_display_layout)

        # 预处理开关
        # self.preprocess_check = QCheckBox("启用图像预处理")
        # self.preprocess_check.setChecked(True)
        # self.preprocess_check.stateChanged.connect(self.on_preprocess_changed)
        # param_layout.addRow(self.preprocess_check)

        # 检测尺寸
        self.det_size_combo = QComboBox()
        self.det_size_combo.addItems(["80x80", "160x160", "240x240", "320x320", "480x480", "640x640", "800x800", "1024x1024"])
        self.det_size_combo.setCurrentText("640x640")
        self.det_size_combo.currentTextChanged.connect(self.on_det_size_changed)
        self.det_size_combo.currentTextChanged.connect(self.update_det_size)
        param_layout.addRow(QLabel("检测尺寸:"), self.det_size_combo)

        # 性能模式
        # self.low_perf_check = QCheckBox("低性能模式")  # 先定义控件
        # self.low_perf_check.stateChanged.connect(self.on_performance_mode_changed)  # 再连接信号
        # self.low_perf_check.stateChanged.connect(self.toggle_performance_mode)

        # 自动保存未知人脸
        # self.auto_save_check = QCheckBox("自动保存未知人脸")
        # self.auto_save_check.setChecked(self.config.get('auto_save_unknown', False))
        # self.auto_save_check.stateChanged.connect(self.toggle_auto_save)

        # ====== 创建水平布局，统一管理4个复选框 ======
        checkboxes_layout = QHBoxLayout()
        # 创建4个复选框（修改文本更简洁）
        self.low_perf_check = QCheckBox("低性能")
        self.auto_save_check = QCheckBox("存人脸") 
        self.preprocess_check = QCheckBox("图预处理")
        self.detect_box_check = QCheckBox("检测框")
        self.detect_box_check.setChecked(self.config.get('show_detect_box', True))
        self.detect_box_check.stateChanged.connect(self.toggle_detect_box)
        self.color_check = QCheckBox("彩色显示")

        # 统一设置宽度，防止过长
        for cb in [self.low_perf_check, self.auto_save_check, self.preprocess_check, self.color_check]:
            cb.setFixedWidth(90)  # 可根据UI效果调整
        # 添加到水平布局
        checkboxes_layout.addWidget(self.low_perf_check)
        checkboxes_layout.addWidget(self.auto_save_check)
        checkboxes_layout.addWidget(self.preprocess_check)
        checkboxes_layout.addWidget(self.detect_box_check)
        checkboxes_layout.addWidget(self.color_check)

        # 添加到参数布局（前面加一个"选项："标签）
        # param_layout.addRow(QLabel("选项:"), checkboxes_layout)
        param_layout.addRow(checkboxes_layout)

        # 保持原有的信号连接（确保功能不变）
        self.low_perf_check.stateChanged.connect(self.on_performance_mode_changed)
        self.low_perf_check.stateChanged.connect(self.toggle_performance_mode)
        self.auto_save_check.stateChanged.connect(self.toggle_auto_save)
        self.preprocess_check.stateChanged.connect(self.on_preprocess_changed)
        self.color_check.stateChanged.connect(self.toggle_color_display)



        # 自动调整按钮
        self.btn_auto_adjust = QPushButton("自动调整")
        self.btn_auto_adjust.setFixedWidth(100)
        param_layout.addRow(self.btn_auto_adjust)
        
        param_group.setLayout(param_layout)
        control_layout.addWidget(param_group)

        # 窗口选择（紧凑布局）
        window_group = QGroupBox("窗口捕获")
        window_layout = QVBoxLayout()
        self.window_combo = QComboBox()
        self.window_combo.setToolTip("选择要识别的窗口。悬停可查看所属进程；"
                                     "选择后本程序会按 8 种方式依次尝试抓取画面")
        window_layout.addWidget(self.window_combo)

        # 操作按钮组（v2.0.1：2 行 × 2 列，新增【诊断】用于排查"抓不到画面"）
        window_btn_layout1 = QHBoxLayout()
        window_btn_layout2 = QHBoxLayout()
        self.btn_refresh = QPushButton("刷新")
        self.btn_capture = QPushButton("开始")
        self.btn_screen_capture = QPushButton("框选")
        self.btn_capture_diag = QPushButton("诊断")
        self.btn_refresh.setToolTip("重新枚举当前所有可见窗口（宽字符标题，中文不乱码）")
        self.btn_capture.setToolTip("开始/停止对所选窗口的识别")
        self.btn_screen_capture.setToolTip("抓不到窗口画面时，可用框选直接框住屏幕区域识别")
        self.btn_capture_diag.setToolTip("逐个测试 8 种抓屏方式，把结果打到系统日志，用于排查抓不到画面")
        for btn in [self.btn_refresh, self.btn_capture, self.btn_screen_capture, self.btn_capture_diag]:
            btn.setFixedWidth(80)
        window_btn_layout1.addWidget(self.btn_refresh)
        window_btn_layout1.addWidget(self.btn_capture)
        window_btn_layout2.addWidget(self.btn_screen_capture)
        window_btn_layout2.addWidget(self.btn_capture_diag)
        window_layout.addLayout(window_btn_layout1)
        window_layout.addLayout(window_btn_layout2)

        window_group.setLayout(window_layout)
        control_layout.addWidget(window_group)

        # 人脸管理（紧凑布局）
        face_group = QGroupBox("人脸管理")
        face_layout = QVBoxLayout()

        # 第一行按钮
        face_btn_row1 = QHBoxLayout()
        self.btn_add_face = QPushButton("添加")
        self.btn_view_faces = QPushButton("查看")
        for btn in [self.btn_add_face, self.btn_view_faces]:
            btn.setFixedWidth(80)
            face_btn_row1.addWidget(btn)
        face_layout.addLayout(face_btn_row1)

        # 第二行按钮
        face_btn_row2 = QHBoxLayout()
        self.btn_export = QPushButton("导出")
        self.btn_dataset_manager = QPushButton("模型市场")
        self.btn_import_unknown = QPushButton("导入")
        for btn in [self.btn_export, self.btn_dataset_manager, self.btn_import_unknown]:
            btn.setFixedWidth(80)
            face_btn_row2.addWidget(btn)

        # ====== 新增的整理图片按钮 ======
        btn_migrate = QPushButton("整理图片")
        btn_migrate.setFixedWidth(80)
        btn_migrate.clicked.connect(self.migrate_existing_faces)
        face_btn_row2.addWidget(btn_migrate)

        face_layout.addLayout(face_btn_row2)  # 将第二行按钮布局添加到主布局
        face_group.setLayout(face_layout)
        control_layout.addWidget(face_group)

        # ====== 5. 系统信息（并排一行）=====
        info_group = QGroupBox("系统信息")
        info_layout = QHBoxLayout()

        # 创建大号字体
        info_font = QFont("Microsoft YaHei", 12)  # 12号字体
        
        self.memory_label = QLabel("内存: -")
        self.cpu_label = QLabel("CPU: -")
        self.fps_label = QLabel("FPS: -")

        # 应用字体和样式
        for label in [self.memory_label, self.cpu_label, self.fps_label]:
            label.setFont(info_font)
            label.setStyleSheet("""
                font-size: 14px;
                min-width: 80px;  /* 设置最小宽度 */
                max-width: 200px; /* 设置最大宽度 */
                qproperty-alignment: AlignCenter;
            """)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)  # 水平扩展

        info_layout.addWidget(self.memory_label)
        info_layout.addWidget(self.cpu_label) 
        info_layout.addWidget(self.fps_label)

        # 设置布局属性使空间分配更合理
        info_layout.setStretch(0, 2)  # 内存占2份空间
        info_layout.setStretch(1, 1)  # CPU占1份
        info_layout.setStretch(2, 1)  # FPS占1份

        info_group.setLayout(info_layout)
        control_layout.addWidget(info_group)

        # ====== v2.1.0 性能/加速状态（加速后端 + 检测耗时）======
        perf_group = QGroupBox("性能")
        perf_layout = QHBoxLayout()
        self.accel_label = QLabel("加速: -")
        self.detect_ms_label = QLabel("检测: -")
        for label in (self.accel_label, self.detect_ms_label):
            label.setFont(QFont("Microsoft YaHei", 11))
            label.setStyleSheet("font-size: 12px; min-width: 90px;"
                                " qproperty-alignment: AlignCenter;")
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            perf_layout.addWidget(label)
        perf_group.setLayout(perf_layout)
        control_layout.addWidget(perf_group)

        # 日志区域
        log_group = QGroupBox("系统日志")
        log_layout = QVBoxLayout()
        # 确保log_text已初始化
        if not hasattr(self, 'log_text'):
            self.log_text = QTextEdit()
            self.log_text.setReadOnly(True)
        # self.log_text = QTextEdit()
        # self.log_text.setMaximumHeight(120) # 固定高度
        self.log_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout.addWidget(self.log_text, 1)
        log_group.setLayout(log_layout)
        control_layout.addWidget(log_group)

        control_panel.setLayout(control_layout)

        # 右侧显示区域
        display_panel = QWidget()
        display_layout = QVBoxLayout()
        display_layout.setContentsMargins(5, 5, 5, 5)
        #display_layout.setSpacing(5)

        # 图像显示区域
        self.display_label = QLabel()
        self.display_label.setAlignment(Qt.AlignCenter)
        self.display_label.setStyleSheet("border: 1px solid gray; background-color: black;")
        self.display_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.display_label.setScaledContents(False)
        self.current_pixmap = None
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.display_label)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignCenter)

        # 状态信息
        self.result_label = QLabel("状态: 等待操作...")
        self.result_label.setStyleSheet("font-size: 12px;")

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumHeight(10)
        
        display_layout.addWidget(self.scroll_area, stretch=1)
        display_layout.addWidget(self.result_label)
        display_layout.addWidget(self.progress_bar)

        # 识别结果滚动显示区域
        self.recognition_group = QGroupBox("识别记录")
        recognition_layout = QVBoxLayout()
        
        # 修改为垂直布局，包含两个水平布局
        self.recognition_display_layout = QVBoxLayout()
        
        # 添加已知人脸标签和布局
        self.known_label = QLabel("已知人脸:")
        self.recognition_display_layout.addWidget(self.known_label)
        self.known_faces_layout = QHBoxLayout()  # 默认有6px间距
        self.known_faces_layout.setSpacing(0)  # ← 原默认值约6px
        self.known_faces_layout.setContentsMargins(0, 0, 0, 0)  # 移除边距
        self.recognition_display_layout.addLayout(self.known_faces_layout)
        
        # 添加分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        self.recognition_display_layout.addWidget(separator)
        
        # 添加未知人脸标签和布局
        self.unknown_label = QLabel("未知人脸:")
        self.recognition_display_layout.addWidget(self.unknown_label)
        self.unknown_faces_layout = QHBoxLayout()  # 默认有6px间距
        self.unknown_faces_layout.setSpacing(0)
        self.unknown_faces_layout.setContentsMargins(0, 0, 0, 0)
        self.recognition_display_layout.addLayout(self.unknown_faces_layout)

        
        self.recognition_widget = QWidget()
        self.recognition_widget.setLayout(self.recognition_display_layout)
        
        # 识别记录滚动区域
        self.recognition_scroll = QScrollArea()
        self.recognition_scroll.setWidgetResizable(True)
        self.recognition_scroll.setFixedHeight(430) # 增加高度以显示更多人脸
        self.recognition_scroll.setWidget(self.recognition_widget)
        
        # 边距设置（关键行）
        self.recognition_scroll.setContentsMargins(0, 0, 5, 0)

        recognition_layout.addWidget(self.recognition_scroll)
        self.recognition_group.setLayout(recognition_layout)
        display_layout.addWidget(self.recognition_group)

        display_panel.setLayout(display_layout)

        # 添加到分割器
        splitter.addWidget(control_panel)
        splitter.addWidget(display_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        
        main_layout.addWidget(splitter)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        # 组合主布局
        main_layout.addWidget(control_panel, stretch=1)
        main_layout.addWidget(display_panel, stretch=3)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        # 连接信号槽
        self.btn_refresh.clicked.connect(self.refresh_windows)
        # 窗口选择变化 → 立即写入配置（原版本从未连接，导致"上次使用的窗口"永远不保存）
        self.window_combo.currentTextChanged.connect(self.on_window_changed)
        # 连接性能模式切换信号（下拉框：文本变化）
        self.performance_mode_combo.currentTextChanged.connect(self.on_performance_mode_text_changed)
        self.btn_capture.clicked.connect(self.toggle_capture)
        self.btn_screen_capture.clicked.connect(self.screen_capture)
        self.btn_capture_diag.clicked.connect(self.capture_window_diagnose)
        self.btn_add_face.clicked.connect(self.add_new_face)
        self.btn_view_faces.clicked.connect(self.view_face_database)
        self.btn_export.clicked.connect(self.export_data)
        self.btn_dataset_manager.clicked.connect(self.show_dataset_manager)
        self.btn_import_unknown.clicked.connect(self.import_unknown_faces)

        # 说明：界面状态回填统一由 __init__ 末尾的 restore_ui_state() 负责，
        # 这里不再重复调用，避免"回填→触发信号→写配置"的额外写盘与状态抖动。
        self._ui_built = True   # 构建成功才置位（见方法开头的说明）

    def on_max_display_changed(self, value):
        """更新最大显示数量（需求6：实时保存并立即生效）"""
        self.max_display = value          # 历史版本只写配置、不更新内存值，导致改完要重启才生效
        if not getattr(self, '_restoring_ui', False):
            self.config.set('max_display', value)
        self.log_message(f"🛠️ 最大显示数量设置为: {value}")




    def update_recognition_display(self, face_info):
        """
        更新识别结果显示区域（增强版）
        参数:
            face_info: 包含人脸信息的字典，应有以下键:
                - 'face_img': numpy数组格式的人脸图像
                - 'name': 字符串格式的人名（可为None）
                - 'similarity': 浮点数相似度
                - 'is_known': 布尔值表示是否已知
                - 'embedding': numpy数组格式的特征向量
        """
        # 1. 输入验证
        if not isinstance(face_info, dict):
            self.log_message("❌ 错误: face_info参数必须是字典")
            return
        
        required_keys = {'face_img', 'name', 'similarity', 'is_known', 'embedding'}
        if not required_keys.issubset(face_info.keys()):
            missing_keys = required_keys - face_info.keys()
            self.log_message(f"❌ 错误: face_info缺少必要键: {missing_keys}")
            return
        
        # 2. 数据校验
        try:
            # 验证图像数据
            if not isinstance(face_info['face_img'], np.ndarray) or face_info['face_img'].size == 0:
                self.log_message("⚠️ 警告: 无效的人脸图像数据")
                return
            
            # 验证相似度范围
            if not (0 <= face_info['similarity'] <= 1):
                self.log_message(f"⚠️ 警告: 无效的相似度值: {face_info['similarity']}")
                return
            
            # 3. 检查是否已显示过相同人脸（幂等性）
            existing_face = self.find_existing_face(face_info['name'], face_info['similarity'])
            if existing_face:
                # 12. 幂等性 - 已存在相似人脸则不重复添加
                return
            
            # 4. 创建显示控件
            face_widget = self.create_face_widget(face_info)
            if not face_widget:
                return
            
            # 5. 根据是否已知人脸决定添加到哪个布局
            if face_info['is_known']:
                target_layout = self.known_faces_layout
                # max_count = max(self.max_display_spin.value() // 2, 1) # 除法逻辑
                max_count = max(self.max_display_spin.value(), 1)  # 每部分都能显示完整的最大数量
            else:
                target_layout = self.unknown_faces_layout
                # max_count = max(self.max_display_spin.value() // 2, 1) # 除法逻辑
                max_count = max(self.max_display_spin.value(), 1)  # 每部分都能显示完整的最大数量
            
            # 6. 清理超出数量的旧控件（只清理对应布局）
            while target_layout.count() > max_count:
                item = target_layout.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            
            # 7. 添加到显示区域（线程安全）
            self.add_widget_safely(face_widget, target_layout)
            
        except Exception as e:
            self.log_message(f"❌ 更新识别显示时出错: {str(e)}")


    def find_existing_face(self, name, similarity):
        """查找是否已存在相似人脸"""
        try:
            for i in range(self.recognition_display_layout.count()):
                item = self.recognition_display_layout.itemAt(i)
                if item and item.widget():
                    existing_name = item.widget().property('face_name')
                    existing_sim = item.widget().property('face_similarity')

                    # 添加防御性编程检查
                    if existing_name is None or existing_sim is None:
                        continue

                    if (existing_name == name and 
                        abs(float(existing_sim) - float(similarity)) < 0.05):
                        return True
            return False
        except Exception as e:
            self.log_message(f"❌ 查找已有人脸时出错: {str(e)}")
            print(f"[DEBUG] 1819查找已有人脸时出错: {str(e)}")
            return False

    def create_face_widget(self, face_info):
        """创建人脸显示控件"""
        try:
            face_widget = QWidget()
            face_widget.setFixedSize(120, 160)
            face_layout = QVBoxLayout()
            face_layout.setContentsMargins(2, 2, 2, 2)
            face_layout.setSpacing(5)
            
            # 转换图像为QPixmap
            face_img = face_info['face_img']
            if face_img is None or face_img.size == 0:
                return None
                
            try:
                face_img = cv2.cvtColor(face_img, cv2.COLOR_BGR2RGB)
                h, w, ch = face_img.shape
                bytes_per_line = ch * w
                q_img = QImage(face_img.data, w, h, bytes_per_line, QImage.Format_RGB888)
                pixmap = QPixmap.fromImage(q_img).scaled(100, 100, Qt.KeepAspectRatio)
            except Exception as e:
                self.log_message(f"❌ 图像转换失败: {str(e)}")
                return None
                
            img_label = QLabel()
            img_label.setPixmap(pixmap)
            img_label.setAlignment(Qt.AlignCenter)
            img_label.setStyleSheet("border: 1px solid gray;")
            
            # 显示姓名和相似度
            name = str(face_info['name']) if face_info['name'] else "未知"
            color = "green" if face_info['is_known'] else "red"
            name_label = QLabel(f"<font color='{color}'>{name}</font>")
            name_label.setAlignment(Qt.AlignCenter)
            name_label.setProperty('face_name', face_info['name'])
            name_label.setProperty('face_similarity', float(face_info['similarity']))
            
            sim_label = QLabel(f"相似度: {float(face_info['similarity']):.2f}")
            sim_label.setAlignment(Qt.AlignCenter)
            sim_label.setStyleSheet("font-size: 10px;")
            
            # 添加控件
            face_layout.addWidget(img_label)
            face_layout.addWidget(name_label)
            face_layout.addWidget(sim_label)
            face_widget.setLayout(face_layout)
            
            # 设置点击事件
            def on_face_clicked(event, face=face_info):
                self.on_face_display_clicked(face)
            
            img_label.mousePressEvent = on_face_clicked
            name_label.mousePressEvent = on_face_clicked
            
            return face_widget
            
        except Exception as e:
            self.log_message(f"❌ 创建人脸控件失败: {str(e)}")
            return None

    def add_widget_safely(self, widget, target_layout):
        """线程安全地添加控件到指定布局"""
        try:
            # 13. 线程安全 - 使用信号槽机制确保在主线程操作UI
            if QThread.currentThread() != self.thread():
                # 修改信号以传递目标布局
                self.safe_add_widget_signal.emit((widget, target_layout))
            else:
                target_layout.addWidget(widget)
        except Exception as e:
            self.log_message(f"❌ 添加控件失败: {str(e)}")


    def cleanup_excess_widgets(self): # 这个方法不再需要，因为清理逻辑已经整合到 update_recognition_display 中。
        #"""清理超出数量的控件"""
        #try:
        #    max_display = self.max_display_spin.value()
        #    while self.recognition_display_layout.count() > max(max_display, 1):
        #        item = self.recognition_display_layout.takeAt(0)
        #        if item and item.widget():
        #            try:
        #                # 15. 资源清理 - 正确释放控件资源
        #                item.widget().deleteLater()
        #            except Exception as e:
        #                self.log_message(f"清理控件失败: {str(e)}")
        #except Exception as e:
        #    self.log_message(f"清理多余控件时出错: {str(e)}")
        pass

    def _add_widget_handler(self, data):
        """处理线程安全的控件添加"""
        try:
            widget, target_layout = data
            target_layout.addWidget(widget)
        except Exception as e:
            self.log_message(f"❌ 线程安全添加控件失败: {str(e)}")


    def on_face_display_clicked(self, face_info):
        """处理点击识别结果中的人脸事件，支持添加人脸图片"""
        try:
            # 防御性编程：检查输入参数有效性
            if not face_info or not isinstance(face_info, dict):
                self.log_message("❌ 错误: 无效的人脸信息参数")
                return

            # 空值检查：确保必要字段存在
            required_keys = ['name', 'similarity', 'is_known', 'embedding', 'face_img']
            if not all(key in face_info for key in required_keys):
                self.log_message(f"❌ 错误: 人脸信息缺少必要字段，应有: {required_keys}")
                return

            # 边界条件检查：确保相似度在合理范围内
            if not (0 <= face_info['similarity'] <= 1):
                self.log_message(f"⚠️ 警告: 异常相似度值: {face_info['similarity']}")
                face_info['similarity'] = max(0, min(1, face_info['similarity']))  # 钳制到[0,1]范围

            if face_info['is_known']:
                # 已知人脸：显示详细信息
                details = (f"姓名: {face_info['name']}\n"
                        f"相似度: {face_info['similarity']:.2f}\n"
                        f"特征向量长度: {len(face_info['embedding']) if face_info['embedding'] is not None else 0}")
                
                # 创建带图片的详细信息对话框
                detail_dialog = QDialog(self)
                detail_dialog.setWindowTitle("人脸详细信息")
                layout = QVBoxLayout()
                
                # 显示人脸图片
                img_label = QLabel()
                face_img = face_info['face_img']
                if face_img is not None and face_img.size > 0:
                    face_img = cv2.cvtColor(face_img, cv2.COLOR_BGR2RGB)
                    h, w, ch = face_img.shape
                    bytes_per_line = ch * w
                    q_img = QImage(face_img.data, w, h, bytes_per_line, QImage.Format_RGB888)
                    pixmap = QPixmap.fromImage(q_img).scaled(200, 200, Qt.KeepAspectRatio)
                    img_label.setPixmap(pixmap)
                
                # 显示文本信息
                text_label = QLabel(details)
                text_label.setWordWrap(True)
                
                # 添加按钮
                btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
                btn_box.accepted.connect(detail_dialog.accept)
                
                layout.addWidget(img_label, 0, Qt.AlignCenter)
                layout.addWidget(text_label)
                layout.addWidget(btn_box)
                detail_dialog.setLayout(layout)
                
                # 设置对话框大小并显示
                detail_dialog.resize(300, 350)
                detail_dialog.exec_()
            else:
                # 未知人脸：询问是否添加到数据库
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("添加新人脸")
                msg_box.setText(f"是否要将此未知人脸添加到数据库?\n检测置信度: {face_info['similarity']:.2f}")
                
                # 添加预览图片
                if face_info['face_img'] is not None and face_info['face_img'].size > 0:
                    face_img = cv2.cvtColor(face_info['face_img'], cv2.COLOR_BGR2RGB)
                    h, w, ch = face_img.shape
                    bytes_per_line = ch * w
                    q_img = QImage(face_img.data, w, h, bytes_per_line, QImage.Format_RGB888)
                    pixmap = QPixmap.fromImage(q_img).scaled(100, 100, Qt.KeepAspectRatio)
                    
                    # 创建QLabel来显示图片
                    img_label = QLabel()
                    img_label.setPixmap(pixmap)
                    img_label.setAlignment(Qt.AlignCenter)
                    
                    # 将图片添加到消息框
                    msg_box.layout().addWidget(img_label, 0, 0, 1, 2)
                
                msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                msg_box.setDefaultButton(QMessageBox.Yes)
                
                reply = msg_box.exec_()
                
                if reply == QMessageBox.Yes:
                    # 输入姓名对话框，带超时处理
                    name, ok = QInputDialog.getText(
                        self, "添加人脸", 
                        "请输入姓名:", 
                        QLineEdit.Normal, "")
                    
                    # 输入验证
                    if ok and name:
                        if not name.strip():
                            QMessageBox.warning(self, "错误", "姓名不能为空")
                            return
                        
                        if len(name) > 50:  # 边界条件检查
                            QMessageBox.warning(self, "错误", "姓名过长，最多50个字符")
                            return
                        
                        # 创建保存目录
                        faces_dir = "faces"
                        try:
                            os.makedirs(faces_dir, exist_ok=True)
                        except Exception as e:
                            self.log_message(f"❌ 创建目录失败: {str(e)}")
                            QMessageBox.critical(self, "错误", f"无法创建保存目录: {str(e)}")
                            return

                        # 文件名规范化
                        def sanitize_filename(name):
                            py_name = pinyin.get(name, format="strip", delimiter="_")
                            return re.sub(r'[^\w]', '', py_name)

                        safe_name = sanitize_filename(name)
                        confidence = int(face_info['similarity'] * 100)  # 使用相似度作为置信度
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-4]
                        img_path = os.path.join(faces_dir, f"{safe_name}_{confidence}%_{timestamp}.jpg")
                        
                        
                        # 保存图片
                        try:
                            if face_info['face_img'] is not None and face_info['face_img'].size > 0:
                                cv2.imwrite(img_path, face_info['face_img'])
                                self.log_message(f"🌈 保存人脸图片到: {img_path}")
                                print(f"🌈 保存人脸图片到: {img_path}")
                            else:
                                img_path = None
                                self.log_message("⚠️ 警告: 无人脸图片可保存")
                            
                            # 添加到数据库
                            try:
                                self.face_db.add_face(
                                    name, 
                                    face_info['embedding'], 
                                    img_path,
                                    confidence=face_info['similarity'])
                                
                                self.log_message(f"✅ 添加新人脸: {name} (相似度: {face_info['similarity']:.2f})")
                                print(f"✅ 添加新人脸: {name} (相似度: {face_info['similarity']:.2f})")
                                
                                # 更新显示状态
                                face_info['name'] = name
                                face_info['is_known'] = True
                                
                                # 更新UI
                                self.update_recognition_display(face_info)
                                
                            except Exception as db_error:
                                self.log_message(f"❌ 数据库添加失败: {str(db_error)}")
                                # 回滚机制：删除已保存的图片
                                if img_path and os.path.exists(img_path):
                                    try:
                                        os.remove(img_path)
                                        self.log_message(f"⚠️ 已回滚删除图片: {img_path}")
                                    except Exception as rollback_error:
                                        self.log_message(f"❌ 回滚失败: {str(rollback_error)}")
                                
                                QMessageBox.critical(self, "错误", f"添加到数据库失败: {str(db_error)}")
                        
                        except Exception as save_error:
                            self.log_message(f"❌ 保存图片失败: {str(save_error)}")
                            QMessageBox.critical(self, "错误", f"保存人脸图片失败: {str(save_error)}")
        
        except Exception as e:
            self.log_message(f"❌ 处理人脸点击时发生未预期错误: {str(e)}")
            QMessageBox.critical(self, "错误", f"处理人脸点击时发生错误: {str(e)}")

    def update_memory_status(self, used_gb, percent):
        """更新内存状态显示，每1%一种颜色"""
        try:
            total_gb = psutil.virtual_memory().total / (1024**3)
            self.memory_label.setText(f"内存: {used_gb:.1f}/{total_gb:.1f}GB ({percent}%)")
            
            # 定义1%间隔的颜色映射 (从绿色到红色的渐变)
            hue = (100 - percent) * 1.2 / 360  # 将百分比转换为色相 (0-120°)
            color = QColor()
            color.setHsvF(hue, 1.0, 1.0)  # HSV色彩空间，固定饱和度和亮度
            
            self.memory_label.setStyleSheet(
                f"{self.default_stylesheet} color: {color.name()}; font-weight: bold;"
            )
        except Exception as e:
            print(f"更新内存状态失败: {str(e)}")

        
        # 仅在自动模式下调整性能
        if self.config.get('performance_mode') == 'auto':
            self.auto_adjust_performance()

        info = f"ROI阈值:{self.roi_threshold*100}% 检测间隔:{self.detect_interval}帧"
        self.statusBar().showMessage(info)

    # ====== 控制方法 ======
    def on_detect_interval_changed(self, value):
        self.detect_interval = value
        if getattr(self, '_restoring_ui', False):
            return
        self.config.set('detect_interval', value)
        self.log_message(f"🛠️ 完整检测间隔设置为: {value}帧")

    def on_roi_thresh_changed(self, value):
        self.roi_threshold = value / 100  # 转换为小数
        if getattr(self, '_restoring_ui', False):
            return
        self.config.set('roi_threshold', self.roi_threshold)
        self.log_message(f"🛠️ ROI变化阈值设置为: {value}%")

    def on_min_roi_changed(self, value):
        # spin 的合法范围是 100~2000，这里只做兜底保护，不再用弹窗打断用户
        if value < 50 or value > 2000:
            debug_print(f"最小ROI面积超出范围，忽略: {value}")
            return
        self.min_roi_area = value
        if getattr(self, '_restoring_ui', False):
            return
        self.config.set('min_roi_area', value)
        self.log_message(f"🛠️ 最小ROI面积设置为: {value}像素")

    def on_preprocess_changed(self, state):
        self.enable_preprocess = (state == Qt.Checked)
        if getattr(self, '_restoring_ui', False):
            return
        self.config.set('enable_preprocess', self.enable_preprocess)
        status = "启用" if self.enable_preprocess else "禁用"
        self.log_message(f"🛠️ 图像预处理{status}")

    def restore_last_window(self):
        """按配置恢复"上次使用的窗口"（必须等窗口列表刷新之后再调用）

        v2.0.0：_restoring_ui 采用"保存/还原原值"的方式，而不是无条件置 False，
        否则被 restore_ui_state 嵌套调用时会把外层的抑制标志提前清掉（潜在隐患）。
        """
        try:
            last_window = self.config.get('last_window')
            if not last_window or not hasattr(self, 'window_combo'):
                return False
            titles = [self.window_combo.itemText(i) for i in range(self.window_combo.count())]
            if last_window in titles:
                prev_restoring = getattr(self, '_restoring_ui', False)
                self._restoring_ui = True          # 避免恢复过程写回配置
                try:
                    self.window_combo.setCurrentText(last_window)
                finally:
                    self._restoring_ui = prev_restoring
                self.log_message(f"🪟 已恢复上次使用的窗口: {last_window}")
                return True
            debug_print(f"上次使用的窗口不在当前列表中，忽略: {last_window}")
        except Exception as e:
            debug_print(f"恢复上次使用的窗口失败: {str(e)}")
        return False

    def restore_ui_state(self):
        """把 config.json 里的设置回填到界面控件（需求6）

        v2.0.0 要点：
          * 全程置 _restoring_ui=True，抑制"控件变化 → 写回配置"，
            避免用默认值反向覆盖用户已保存的设置（历史版本存在此问题）；
          * 所有控件都用 hasattr 保护，某个控件缺失不会中断整段恢复；
          * **每个数值都经 _safe_int/_safe_float/_safe_bool 钳制**：
            手工改坏 config.json（null/"abc"/越界）只会让该项退回默认值，
            不会再让后续所有设置一起丢失；
          * 恢复完成后，内存属性与界面控件保持一致。
        """
        prev_restoring = getattr(self, '_restoring_ui', False)
        self._restoring_ui = True
        try:
            # ---------- 模型 ----------
            model_name = self.config.get('model_name', self.model_name)
            if model_name not in MODELS:
                safe_print(f"[配置] 模型名 {model_name!r} 无效，回退为默认值 {self.model_name}")
                model_name = self.model_name if self.model_name in MODELS else 'buffalo_l'
                self.model_name = model_name
            else:
                self.model_name = model_name
            if hasattr(self, 'model_combo'):
                self.model_combo.setCurrentText(self.model_name)

            # ---------- 检测阈值 ----------
            det_thresh = _safe_int(self.config.get('det_thresh'), 70, 50, 95)
            if hasattr(self, 'thresh_slider'):
                self.thresh_slider.setValue(det_thresh)
            if hasattr(self, 'thresh_spin'):
                self.thresh_spin.setValue(det_thresh)

            # ---------- 检测间隔(ms) ----------
            self.detection_interval = _safe_int(self.config.get('det_interval'),
                                                self.detection_interval, 50, 5000)
            if hasattr(self, 'interval_slider'):
                self.interval_slider.setValue(self.detection_interval)
            if hasattr(self, 'interval_spin'):
                self.interval_spin.setValue(self.detection_interval)

            # ---------- 检测尺寸 ----------
            self.det_size = _safe_size(self.config.get('det_size'), self.det_size)
            if hasattr(self, 'det_size_combo'):
                self.det_size_combo.setCurrentText(f"{self.det_size[0]}x{self.det_size[1]}")

            # ---------- 完整检测间隔(帧) ----------
            self.detect_interval = _safe_int(self.config.get('detect_interval'),
                                             self.detect_interval, 1, 30)
            if hasattr(self, 'detect_interval_spin'):
                self.detect_interval_spin.setValue(self.detect_interval)

            # ---------- ROI 变化阈值 ----------
            self.roi_threshold = _safe_float(self.config.get('roi_threshold'),
                                             self.roi_threshold, 0.01, 0.30)
            if hasattr(self, 'roi_thresh_slider'):
                self.roi_thresh_slider.setValue(int(round(self.roi_threshold * 100)))
            if hasattr(self, 'roi_thresh_spin'):
                self.roi_thresh_spin.setValue(int(round(self.roi_threshold * 100)))

            # ---------- 最小 ROI 面积 ----------
            self.min_roi_area = _safe_int(self.config.get('min_roi_area'),
                                          self.min_roi_area, 100, 2000)
            if hasattr(self, 'min_roi_spin'):
                self.min_roi_spin.setValue(self.min_roi_area)

            # ---------- 显示数量 ----------
            self.max_display = _safe_int(self.config.get('max_display'), self.max_display, 1, 9999)
            if hasattr(self, 'max_display_spin'):
                self.max_display_spin.setValue(self.max_display)

            # ---------- 各类开关 ----------
            self.enable_preprocess = _safe_bool(self.config.get('enable_preprocess'), True)
            self.low_performance_mode = _safe_bool(self.config.get('low_performance_mode'), False)
            if hasattr(self, 'preprocess_check'):
                self.preprocess_check.setChecked(self.enable_preprocess)
            if hasattr(self, 'auto_save_check'):
                self.auto_save_check.setChecked(_safe_bool(self.config.get('auto_save_unknown'), False))
            if hasattr(self, 'detect_box_check'):
                self.detect_box_check.setChecked(_safe_bool(self.config.get('show_detect_box'), True))
            if hasattr(self, 'color_check'):
                self.color_check.setChecked(_safe_bool(self.config.get('enable_color'), True))
            if hasattr(self, 'debug_check'):
                self.debug_check.setChecked(_safe_bool(self.config.get('debug_mode'), False))
            if hasattr(self, 'low_perf_check'):
                self.low_perf_check.setChecked(self.low_performance_mode)

            # 调试模式：同步全局打印开关
            global DEBUG_PRINT
            DEBUG_PRINT = _safe_bool(self.config.get('debug_mode'), False)

            # ---------- 性能模式 ----------
            performance_mode = self.config.get('performance_mode', 'auto')
            if performance_mode not in ('auto', 'manual'):
                performance_mode = 'auto'
            if hasattr(self, 'performance_mode_combo'):
                self.performance_mode_combo.setCurrentText("自动" if performance_mode == 'auto' else "手动")

            # ---------- v2.1.0 加速后端 / 线程数 ----------
            accel_backend = str(self.config.get('accel_backend', 'auto')).lower()
            if accel_backend not in ACCEL_BACKENDS:
                safe_print(f"[配置] 加速后端 {accel_backend!r} 无效，回退为 auto")
                accel_backend = 'auto'
            if hasattr(self, 'accel_combo'):
                idx = self.accel_combo.findData(accel_backend)
                if idx >= 0:
                    self.accel_combo.setCurrentIndex(idx)
            if hasattr(self, 'cpu_threads_spin'):
                self.cpu_threads_spin.setValue(_safe_int(self.config.get('cpu_threads'), 0, 0, 64))

            # ---------- 代理 ----------
            proxy_settings = self.config.get('proxy_settings')
            if isinstance(proxy_settings, dict):
                self.proxy_settings = proxy_settings
                try:
                    self.proxy_status.setText(
                        f"代理: {str(proxy_settings['type']).upper()} "
                        f"{proxy_settings['host']}:{proxy_settings['port']}")
                except Exception:
                    pass

            # ---------- 上次使用的窗口（窗口列表为空时由 restore_last_window 兜底） ----------
            self.restore_last_window()

            self.log_message(f"🛠️ 已从配置恢复界面设置 (model={self.model_name}, det_size="
                             f"{self.det_size[0]}x{self.det_size[1]}, 阈值={det_thresh}, "
                             f"间隔={self.detection_interval}ms, 性能模式={performance_mode})")
        except Exception as e:
            self.log_message(f"❌ 恢复界面设置失败: {str(e)}")
            safe_print(f"[配置] 恢复界面设置失败: {traceback.format_exc()}")
        finally:
            self._restoring_ui = prev_restoring

    # ====== 设置变更回调：全部实时写盘（需求6） ======
    def on_model_changed(self, model_name):
        self.model_name = model_name
        if not getattr(self, '_restoring_ui', False):
            self.config.set('model_name', model_name)
        self.change_model(model_name)

    def on_thresh_changed(self, value):
        if getattr(self, '_restoring_ui', False):
            return
        self.config.set('det_thresh', value)
        self.update_det_thresh()

    def on_interval_changed(self, value):
        if getattr(self, '_restoring_ui', False):
            return
        self.config.set('det_interval', value)
        self.update_det_interval()

    def on_det_size_changed(self, size_str):
        """检测尺寸变化：写配置 + 立即生效（update_det_size 由信号另行调用）"""
        if getattr(self, '_restoring_ui', False):
            return
        self.config.set('det_size', size_str)
        self.update_det_size(size_str)

    def on_performance_mode_changed(self, state):
        """"低性能"复选框变化（stateChanged → int）

        v2.0.0 修复：本方法在旧代码里被后面的
        on_performance_mode_changed(self, text)（性能模式下拉框）覆盖，
        于是勾选"低性能"实际执行的是下拉框逻辑（int != "自动" → 永远判定为 manual），
        既没有保存 low_performance_mode，也会把性能模式强行改成手动。
        现在两个槽彻底分开：本槽处理复选框，on_performance_mode_text_changed 处理下拉框。
        """
        self.low_performance_mode = (state == Qt.Checked)
        if getattr(self, '_restoring_ui', False):
            # 回填控件阶段：只同步内存值，绝不联动修改其它控件，也不写配置
            return
        self.config.set('low_performance_mode', self.low_performance_mode)
        if self.low_performance_mode:
            self.detect_interval_spin.setValue(8)
            self.roi_thresh_slider.setValue(15)
            self.min_roi_spin.setValue(800)
            self.preprocess_check.setChecked(True)
        self.toggle_performance_mode(state)

    def on_performance_mode_text_changed(self, text):
        """性能模式下拉框变化（自动 / 手动），立即写入配置（需求6）"""
        if getattr(self, '_restoring_ui', False):
            return
        mode = 'auto' if text == "自动" else 'manual'
        self.config.set('performance_mode', mode)
        if mode == 'auto':
            self.log_message("🚑 性能模式: 自动 (根据系统负载自动调整)")
            self.auto_adjust_performance()
        else:
            self.log_message("🐛 性能模式: 手动 (使用当前设置)")

    def on_window_changed(self, window_title):
        """窗口选择变化 → 立即保存（需求6：下次启动沿用上次的窗口）"""
        if getattr(self, '_restoring_ui', False):
            return
        if window_title:
            self.config.set('last_window', window_title)
            if not getattr(self, 'is_detecting', False):
                self.current_window = window_title

    def lock_current_faces(self):
        """锁定当前检测到的人脸数据，防止过期"""
        self.locked_faces = {
            k: {
                "image": v["image"].copy(),          # 复制图像数据
                "embedding": v["embedding"].copy(),  # 复制特征向量
                "bbox": v["bbox"].copy(),           # 复制坐标
                "det_score": v["det_score"]          # 基本类型无需复制
            } 
            for k, v in self.face_cache.items()
        }
        print("1704已锁定当前人脸数据")

    def cleanup_unknown_faces(self):
        """清理未知人脸"""
        try:
            deleted_count = self.face_db.cleanup_unknown_faces(days=30)
            if deleted_count > 0:
                self.log_message(f"🚀 自动清理了 {deleted_count} 个未知人脸记录")
        except Exception as e:
            self.log_message(f"❌ 清理未知人脸失败: {str(e)}")

    def log_sort_action(self, column_index):
        """记录用户点击表头排序的行为"""
        column_name = ["ID", "姓名", "图片路径", "添加时间", "预览"][column_index]
        self.log_message(f"🔍 用户按列排序: {column_name}")


    def display_image_with_ratio(self, frame):
        """按比例显示图像（包含检测框显示控制）"""
        # 1. 输入验证和默认值处理
        if frame is None:
            debug_print("[DEBUG] ❌ 显示图像错误: 输入帧为空")
            return
            
        if not isinstance(frame, np.ndarray) or frame.size == 0:
            debug_print("[DEBUG] ❌ 显示图像错误: 无效的输入帧格式")
            return
        
        if frame is None or frame.size == 0:
            return

        try:
            # 保存原始帧用于刷新
            original_frame = frame.copy()
            
            # 如果不显示检测框，则直接显示原始图像
            if not self.config.get('show_detect_box', True):
                frame = original_frame.copy()
            else:
                frame = original_frame.copy()
                # 如果有检测到的人脸，绘制检测框和识别信息
                if hasattr(self, 'face_cache') and self.face_cache:
                    for face_id, face_data in self.face_cache.items():
                        bbox = face_data['bbox']
                        # v2.1.0：姓名/相似度直接用检测线程缓存的结果，
                        # 不再"每帧、每张脸都去查一次数据库"（这是纯 CPU 卡顿的另一大来源）
                        if 'name' in face_data:
                            name = face_data.get('name')
                            similarity = float(face_data.get('similarity') or 0.0)
                            confidence = float(face_data.get('confidence') or 0.0)
                        else:
                            result = self.face_db.search_face(face_data['embedding'])
                            face_data['name'] = result.get('name')
                            face_data['similarity'] = result.get('similarity') or 0.0
                            face_data['confidence'] = result.get('confidence') or 0.0
                            name = face_data['name']
                            similarity = face_data['similarity']
                            confidence = face_data['confidence']

                        # 绘制检测框
                        if name:  # 已知人脸
                            color = (0, 255, 0)  # 绿色
                            text = f"{name} (相似度: {similarity:.2f}, 置信度: {confidence:.2f})"
                        else:  # 陌生人
                            color = (0, 0, 255)  # 红色
                            text = f"未知人脸 (检测置信度: {face_data.get('det_score', 0.0):.2f})"
                        
                        if self.config.get('show_detect_box', True):
                            cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), color, 2)
                        
                        # 添加识别信息文本
                        if self.config.get('show_detect_box', True):
                            frame = self.cv2_add_chinese_text(
                                frame, 
                                text, 
                                (bbox[0], bbox[1]-30),
                                textColor=(255, 255, 255),
                                textSize=20
                            )

            # 根据配置决定是否使用彩色
            # 只在黑白模式下才考虑转换
            if not self.config.get('enable_color', True):
                if frame.ndim == 3:  # 确保是彩色图像
                    gray_mean = cv2.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))[0]
                    if gray_mean > 40:  # 只在亮度足够时转灰度
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                # 转回BGR格式保持三通道
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            
            # 转换为RGB格式
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            
            # 创建QImage
            q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
            self.current_pixmap = QPixmap.fromImage(q_img)
            
            # 保存处理后的帧
            self.last_frame = frame.copy()
        
            # 计算适合显示区域的尺寸，保持宽高比
            label_size = self.display_label.size()
            scaled_pixmap = self.current_pixmap.scaled(
                label_size, 
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            )
            
            self.display_label.setPixmap(scaled_pixmap)
        except Exception as e:
            self.log_message(f"❌ 显示图像错误: {str(e)}")

    def toggle_performance_mode(self, state):
        """切换高性能/低性能模式（仅在手动模式下有效）

        v2.0.0：回填配置阶段直接跳过，避免"恢复 low_perf_check"时
        顺手把检测尺寸/间隔/阈值改成固定值而覆盖用户设置。
        """
        if getattr(self, '_restoring_ui', False):
            return
        if self.config.get('performance_mode') == 'manual':
            self.low_performance_mode = (state == Qt.Checked)
            if self.low_performance_mode:
                # 低性能模式设置
                self.det_size_combo.setCurrentText("480x480")
                self.interval_slider.setValue(1000)
                self.thresh_slider.setValue(75)
                self.log_message("🐛 手动切换到低性能模式")
            else:
                # 高性能模式设置
                self.det_size_combo.setCurrentText("640x640")
                self.interval_slider.setValue(500)
                self.thresh_slider.setValue(70)
                self.log_message("🚑 手动切换到正常性能模式")


    def import_unknown_faces(self):
        """导入unknown_faces目录中的未知人脸"""
        try:
            unknown_dir = "unknown_faces"
            if not os.path.exists(unknown_dir):
                QMessageBox.warning(self, "警告", f"未找到 {unknown_dir} 目录！")
                return
            
            # 获取所有图片文件
            images = [f for f in os.listdir(unknown_dir) if f.lower().endswith(('.jpg', '.png'))]
            if not images:
                QMessageBox.warning(self, "警告", f"{unknown_dir} 目录中没有图片文件！")
                return
            
            # 批量导入对话框
            dialog = QDialog(self)
            dialog.setWindowTitle("导入未知人脸")
            dialog.setFixedSize(800, 600)  # 增大对话框尺寸
            
            layout = QVBoxLayout()
            label = QLabel(f"找到 {len(images)} 张未知人脸图片:")
            layout.addWidget(label)
            
            # 使用网格布局显示图片缩略图
            scroll = QScrollArea()
            scroll_widget = QWidget()
            grid = QGridLayout()
            
            row, col = 0, 0
            for i, filename in enumerate(images):
                img_path = os.path.join(unknown_dir, filename)
                img = cv2.imread(img_path)
                if img is None:
                    continue
                    
                # 创建缩略图
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                h, w, ch = img.shape
                bytes_per_line = ch * w
                q_img = QImage(img.data, w, h, bytes_per_line, QImage.Format_RGB888)
                pixmap = QPixmap.fromImage(q_img).scaled(150, 150, Qt.KeepAspectRatio)
                
                # 创建带图片的复选框
                group = QGroupBox()
                vbox = QVBoxLayout()
                
                label = QLabel()
                label.setPixmap(pixmap)
                vbox.addWidget(label)
                
                checkbox = QCheckBox(filename)
                checkbox.setChecked(True)
                vbox.addWidget(checkbox)
                
                group.setLayout(vbox)
                grid.addWidget(group, row, col)
                
                col += 1
                if col > 3:  # 每行4个
                    col = 0
                    row += 1
            
            scroll_widget.setLayout(grid)
            scroll.setWidget(scroll_widget)
            layout.addWidget(scroll)
            
            # 添加命名模式选项
            name_group = QGroupBox("命名模式")
            name_layout = QVBoxLayout()
            self.name_prefix = QLineEdit("未知_")
            self.name_number = QSpinBox()
            self.name_number.setValue(1)
            self.name_number.setMinimum(1)
            name_layout.addWidget(QLabel("名称前缀:"))
            name_layout.addWidget(self.name_prefix)
            name_layout.addWidget(QLabel("起始编号:"))
            name_layout.addWidget(self.name_number)
            name_group.setLayout(name_layout)
            layout.addWidget(name_group)
            
            btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btn_box.accepted.connect(dialog.accept)
            btn_box.rejected.connect(dialog.reject)
            layout.addWidget(btn_box)
            
            dialog.setLayout(layout)
            
            if dialog.exec_() == QDialog.Accepted:
                # 获取所有选中的图片
                selected_files = []
                for i in range(grid.count()):
                    widget = grid.itemAt(i).widget()
                    if widget and isinstance(widget, QGroupBox):
                        checkbox = widget.findChild(QCheckBox)
                        if checkbox and checkbox.isChecked():
                            selected_files.append(checkbox.text())
                
                if not selected_files:
                    QMessageBox.warning(self, "警告", "请选择要导入的图片！")
                    return
                
                prefix = self.name_prefix.text()
                start_num = self.name_number.value()
                
                # 开始导入
                progress = QProgressDialog("正在导入未知人脸...", "取消", 0, len(selected_files), self)
                progress.setWindowTitle("导入进度")
                
                for i, filename in enumerate(selected_files):
                    if progress.wasCanceled():
                        break
                    
                    progress.setValue(i)
                    progress.setLabelText(f"正在导入 {i+1}/{len(selected_files)}: {filename}")
                    QApplication.processEvents()
                    
                    # 读取图片并提取人脸特征
                    img_path = os.path.join(unknown_dir, filename)
                    img = cv2.imread(img_path)
                    if img is None:
                        continue
                    
                    faces = self.face_app.get(img)
                    if not faces:
                        continue
                    
                    # 使用命名模式生成名称
                    name = f"{prefix}{start_num + i}"
                    self.face_db.add_face(name, faces[0].embedding, img_path)
                
                progress.close()
                QMessageBox.information(self, "完成", f"成功导入 {len(selected_files)} 张人脸图片！")
        except Exception as e:
            self.log_message(f"❌ 导入未知人脸失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"导入未知人脸失败: {str(e)}")

    def change_model(self, model_name):
        """切换模型（并持久化到配置）

        v2.0.0：这里同时写入 model_name 配置，保证从"模型下拉框"或其它入口
        切换模型后都能被记住；用 getattr 保护模型尚未加载的启动早期阶段。
        """
        try:
            self.model_name = model_name
            if not getattr(self, '_restoring_ui', False):
                self.config.set('model_name', model_name)
            debug_print(f"切换模型为: {model_name}")
            current_app = getattr(self, 'face_app', None)
            if current_app:
                self.face_app = None
                self.check_and_download_model()  # 切换模型时检查是否存在
        except Exception as e:
            self.log_message(f"❌ 切换模型失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"切换模型失败: {str(e)}")

    def thresh_spin_changed(self, value):
        """阈值数值框变化"""
        self.thresh_slider.setValue(value)
        self.update_det_thresh()

    def interval_spin_changed(self, value):
        """间隔数值框变化"""
        self.interval_slider.setValue(value)
        self.update_det_interval()

    def auto_adjust_params(self):
        """自动调整参数"""
        try:

            # 根据系统负载自动设置
            mem = psutil.virtual_memory().percent
            cpu = psutil.cpu_percent()
            
            if mem > 80 or cpu > 80:  # 高负载
                self.detect_interval_spin.setValue(10)
                self.roi_thresh_slider.setValue(15)
                self.min_roi_spin.setValue(800)
                self.preprocess_check.setChecked(True)
                self.log_message("🧡 系统负载高，已自动降低检测强度")
            else:  # 低负载
                self.detect_interval_spin.setValue(5)
                self.roi_thresh_slider.setValue(10)
                self.min_roi_spin.setValue(500)
                self.log_message("💚 系统负载正常，已恢复默认检测强度")

            # 根据窗口大小自动调整参数
            window_title = self.window_combo.currentText()
            if not window_title:
                QMessageBox.warning(self, "警告", "请先选择窗口")
                return

            # v2.0.1：改用宽字符解析 + 下拉项绑定的 hwnd，中文标题不会再找不到窗口
            hwnd = self._resolve_window_handle(
                window_title, self.window_combo.currentData())
            if not hwnd:
                self.log_message(f"⚠️ 自动调整参数：未找到窗口「{window_title}」")
                return None

            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            window_width = right - left
            window_height = bottom - top
            
            # 根据窗口大小自动调整检测间隔
            if window_width * window_height > 1920*1080:  # 大窗口
                self.interval_slider.setValue(1000)
                self.det_size_combo.setCurrentText("800x800")
            elif window_width * window_height > 1280*720:  # 中等窗口
                self.interval_slider.setValue(500)
                self.det_size_combo.setCurrentText("640x640")
            else:  # 小窗口
                self.interval_slider.setValue(200)
                self.det_size_combo.setCurrentText("480x480")
            
            # 自动调整阈值
            self.thresh_slider.setValue(65)
            
            self.log_message("✨ 已自动调整检测参数")
        except Exception as e:
            self.log_message(f"❌ 自动调整参数失败: {str(e)}")

    def update_det_size(self, size_str):
        """更新检测尺寸（v2.0.0：真正作用到已加载的检测模型）"""
        try:
            size = tuple(map(int, size_str.split('x')))
            self.det_size = size
            face_app = getattr(self, 'face_app', None)
            if face_app is not None and tuple(getattr(face_app, 'det_size', size)) != size:
                det_thresh, _ = self.get_model_det_params()
                # insightface 只有 prepare() 才能改变检测模型的输入尺寸
                face_app.prepare(ctx_id=0, det_thresh=det_thresh, det_size=size)
                face_app.det_thresh = det_thresh
                face_app.det_size = size
                if hasattr(face_app, 'det_model'):
                    face_app.det_model.det_thresh = det_thresh
                self.log_message(f"🛠️ 检测尺寸已应用到模型: {size_str}")
            else:
                self.log_message(f"🛠️ 检测尺寸更新为: {size_str}")
        except Exception as e:
            self.log_message(f"❌ 更新检测尺寸失败: {str(e)}")

    def screen_capture(self):
        """屏幕框选捕获"""
        try:
            if not self.face_app:
                QMessageBox.warning(self, "警告", "请先等待模型加载完成")
                return
            
            self.setEnabled(False)
        
            dialog = ScreenCaptureDialog(self)
            dialog.setModal(True)
            
            if dialog.exec_() == QDialog.Accepted:
                rect = dialog.get_selected_region()
                if rect:
                    screen = QApplication.primaryScreen()
                    screenshot = screen.grabWindow(0, *rect)
                    
                    # 转换为OpenCV格式
                    qimg = screenshot.toImage()
                    qimg = qimg.convertToFormat(QImage.Format_RGB888)
                    width = qimg.width()
                    height = qimg.height()
                    
                    ptr = qimg.constBits()
                    if ptr:
                        ptr.setsize(qimg.byteCount())
                        arr = np.frombuffer(ptr, np.uint8).reshape(height, width, 3)
                        frame = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

                        # 进行人脸识别前标记来源
                        frame.original_rect = rect

                        # 进行人脸识别
                        self.process_captured_frame(frame)
                    else:
                        self.log_message("❌ 无法获取屏幕截图数据")
                        QMessageBox.warning(self, "错误", "无法获取屏幕截图数据")
        except Exception as e:
            self.log_message(f"❌ 屏幕框选错误: {str(e)}")
            QMessageBox.critical(self, "错误", f"屏幕框选失败: {str(e)}")
            print(f"屏幕框选失败: {str(e)}")
        finally:
            self.setEnabled(True)
            self.activateWindow()
            self.raise_()
            QApplication.processEvents()

    def process_captured_frame(self, frame):
        """处理捕获的帧进行人脸识别"""
        try:
            # 获取原始截图区域
            original_rect = getattr(frame, 'original_rect', (0, 0, frame.shape[1], frame.shape[0]))
            
            # 扩大检测区域
            border_size = 50
            expanded_frame = cv2.copyMakeBorder(frame, border_size, border_size, 
                                            border_size, border_size, 
                                            cv2.BORDER_REPLICATE)

            faces = self.face_app.get(expanded_frame)
            print(f"[DEBUG] 2036检测到的人脸数量: {len(faces)}")

            if len(faces) == 0:
                self.log_message("🚫 未检测到人脸")
                QMessageBox.information(self, "提示", "未检测到人脸")
                return

            if not faces:
                self.log_message("🚫 未检测到人脸")
                QMessageBox.information(self, "提示", "未检测到人脸")
                return

            # 清空旧缓存
            debug_print(f"[DEBUG] 清理前1: face_cache长度={len(self.face_cache)}")
            self.face_cache.clear()
            debug_print(f"[DEBUG] 清理后1: face_cache长度={len(self.face_cache)}")
                
            for face in faces:
                bbox = face.bbox.astype(int)
                # 调整坐标到原图
                bbox[0] = max(0, bbox[0] - border_size)
                bbox[1] = max(0, bbox[1] - border_size)
                bbox[2] = min(frame.shape[1], bbox[2] - border_size)
                bbox[3] = min(frame.shape[0], bbox[3] - border_size)
                
                # 搜索人脸
                result = self.face_db.search_face(face.embedding)
                name = result['name']
                similarity = result['similarity']
                print(f"[DEBUG] 2059人脸识别结果: {name} (相似度: {similarity:.2f})")
                
                if result['name']:  # 已知人脸
                    color = (0, 255, 0)  # 绿色
                    text = f"{result['name']} (相似度: {result['similarity']:.2f}, 置信度: {result['confidence']:.2f})"
                    status = f"识别到 {result['name']} (相似度: {result['similarity']:.2f}, 置信度: {result['confidence']:.2f})"
                    print(f"[DEBUG] 2065识别到已知人脸: {result['name']} (相似度: {result['similarity']:.2f}, 置信度: {result['confidence']:.2f})")
                else:  # 陌生人
                    color = (0, 0, 255)  # 红色
                    text = f"未知人脸 (检测置信度: {face.det_score:.2f})"
                    status = f"未识别到已知人脸 (检测置信度: {face.det_score:.2f})"
                    print(f"[DEBUG] 2070未识别到已知人脸 (检测置信度: {face.det_score:.2f})")

                # 修改位置3: 检测框(红色) - 添加检测框显示控制
                if self.config.get('show_detect_box', True):
                    cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), color, 2)
                    
                    # 文本颜色也可以统一（可选）
                    text_color = (255, 0, 0)  # 黄色文字

                    frame = self.cv2_add_chinese_text(
                        frame, 
                        text, 
                        (bbox[0], bbox[1]-30),
                        textColor=(255, 255, 255),
                        textSize=24
                    )
                self.result_label.setText(f"状态: {status}")

                # 裁剪人脸区域
                face_img = frame[bbox[1]:bbox[3], bbox[0]:bbox[2]]
                
                if face_img.size > 0:  # 确保有有效图像
                    # 生成唯一face_id并缓存
                    face_id = self.current_face_id
                    self.current_face_id += 1
                    
                    # 在检测到人脸后的缓存部分添加：
                    self.face_cache[face_id] = {
                        "image": face_img.copy(),
                        "embedding": face.embedding,
                        "bbox": bbox.copy(),
                        "det_score": face.det_score  # 新增置信度缓存
                    }

                # 绘制检测框（绿色）
                # 仅在显示检测框时绘制
                if self.config.get('show_detect_box', True):
                    color = (0, 255, 0)  # 绿色
                    cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), color, 2)
                    text_color = (0, 255, 255)  # 黄色文字
                
                # 在数据库中搜索匹配的人脸
                result = self.face_db.search_face(face.embedding)  # 返回字典
                name = result['name']
                similarity = result['similarity']
                print(f"[DEBUG] 2113人脸识别结果: {name} (相似度: {similarity:.2f})")
                
                color = (0, 255, 0) if name else (0, 0, 255)  # 已知人脸绿色，未知红色
                if self.config.get('show_detect_box', True):
                    cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), color, 2)

                if name:  # 已知人脸
                    # 更详细的识别结果展示
                    if result['name']:  # 已知人脸
                        color = (0, 255, 0)  # 绿色
                        text = f"{result['name']} (相似度: {result['similarity']:.2f}, 置信度: {result['confidence']:.2f})"
                        status = f"识别到 {result['name']} (相似度: {result['similarity']:.2f}, 置信度: {result['confidence']:.2f})"
                        print(f"[DEBUG] 2124识别到已知人脸: {result['name']} (相似度: {result['similarity']:.2f}, 置信度: {result['confidence']:.2f})")
                    else:  # 陌生人
                        color = (0, 0, 255)  # 红色
                        text = f"未知人脸 (检测置信度: {face.det_score:.2f})"
                        status = f"未识别到已知人脸 (检测置信度: {face.det_score:.2f})"
                        print(f"[DEBUG] 2129未识别到已知人脸 (检测置信度: {face.det_score:.2f})")
                    if self.config.get('show_detect_box', True):
                        frame = self.cv2_add_chinese_text(frame, text, (bbox[0], bbox[1]-30))
                    self.result_label.setText(f"状态: 识别到 {name} (置信度: {similarity:.2f})")
                else:  # 陌生人
                    text = "未知人脸"
                    if self.config.get('show_detect_box', True):
                        frame = self.cv2_add_chinese_text(frame, text, (bbox[0], bbox[1]-30), (0, 255, 0))
                    self.result_label.setText("状态: 未识别到已知人脸")
                    
                    # 自动保存陌生人照片到unknown_faces目录
                    os.makedirs("unknown_faces", exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-4]
                    face_img = frame[bbox[1]:bbox[3], bbox[0]:bbox[2]]
                    if face_img.size > 0:  # 确保有有效图像
                        cv2.imwrite(f"unknown_faces/unknown_{timestamp}.jpg", face_img)

                # 添加到识别结果显示区域
                face_img = frame[bbox[1]:bbox[3], bbox[0]:bbox[2]]
                if face_img.size > 0:
                    self.update_recognition_display({
                        'face_img': face_img,
                        'name': result['name'],
                        'similarity': result['similarity'],
                        'is_known': result['name'] is not None,
                        'embedding': face.embedding
                    })

            # 显示画面
            self.display_image_with_ratio(frame)

            # 询问是否添加新人脸
            reply = QMessageBox.question(self, '添加人脸', 
                                       '是否要将检测到的人脸添加到数据库?',
                                       QMessageBox.Yes | QMessageBox.No)
            
            if reply == QMessageBox.Yes:
                self.add_detected_faces(faces, frame)

        except Exception as e:
            self.log_message(f"❌ 人脸检测错误: {str(e)}")
    
    def add_detected_faces(self, faces, frame):
        """添加检测到的人脸到数据库"""
        try:
            if len(faces) == 1:
                # 单人脸直接添加
                name, ok = QInputDialog.getText(
                    self, "添加人脸", 
                    "请输入姓名:",
                    QLineEdit.Normal,
                    ""
                )
                if ok and name:
                    self.add_single_face(name, faces[0], frame)
            else:
                # 多人脸选择对话框
                if len(self.face_cache) > 1:
                    dialog = QDialog(self)
                    dialog.setWindowTitle("选择要添加的人脸")
                    dialog.setFixedSize(400, 300)
                    
                    layout = QVBoxLayout()
                    label = QLabel(f"检测到 {len(self.face_cache)} 个人脸，请选择要添加的:")
                    layout.addWidget(label)
                    
                    face_list = QListWidget()
                    for face_id, face_data in self.face_cache.items():
                        item = QListWidgetItem(f"人脸 {face_id+1}")
                        item.setData(Qt.UserRole, face_id)
                        face_list.addItem(item)
                    face_list.setSelectionMode(QListWidget.MultiSelection)
                    layout.addWidget(face_list)
                    
                    add_all_check = QCheckBox("添加所有检测到的人脸")
                    layout.addWidget(add_all_check)
                    
                    btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
                    btn_box.accepted.connect(dialog.accept)
                    btn_box.rejected.connect(dialog.reject)
                    layout.addWidget(btn_box)
                    
                    dialog.setLayout(layout)
                    
                    if dialog.exec_() == QDialog.Accepted:
                        selected_faces = []
                        if add_all_check.isChecked():
                            selected_faces = list(self.face_cache.items())
                        else:
                            selected_items = face_list.selectedItems()
                            selected_faces = [(item.data(Qt.UserRole), 
                                             self.face_cache[item.data(Qt.UserRole)]) 
                                            for item in selected_items]
                        
                        if not selected_faces:
                            QMessageBox.warning(self, "警告", "未选择任何人脸")
                            return
                        
                        self.add_multiple_faces(selected_faces)
                    return

                # 单人脸直接添加
                face_id, face_data = next(iter(self.face_cache.items()))
                name, ok = QInputDialog.getText(
                    self, "添加人脸", 
                    "请输入姓名:",
                    QLineEdit.Normal,
                    ""
                )
                if ok and name:
                    self.add_single_face(name, face_id)
        except Exception as e:
            self.log_message(f"❌ 添加检测到的人脸失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"添加人脸失败: {str(e)}")
            print(f"2230添加检测到的人脸失败: {str(e)}")

    def import_dataset_images(self, dataset_name, dataset_path):
        """导入数据集图片到人脸数据库"""
        try:
            # 根据数据集类型处理不同目录结构
            if dataset_name == "CelebA":
                img_dir = os.path.join(dataset_path, "img_align_celeba")
            elif dataset_name == "LFW":
                img_dir = os.path.join(dataset_path, "lfw")
            else:
                img_dir = dataset_path  # 其他数据集默认根目录
        
            # 获取所有图片文件
            images = []
            for root, _, files in os.walk(img_dir):
                for file in files:
                    if file.lower().endswith(('.jpg', '.png')):
                        images.append(os.path.join(root, file))
        
            if not images:
                QMessageBox.warning(self, "警告", f"数据集 {dataset_name} 中未找到图片！")
                return
        
            # 批量导入
            progress = QProgressDialog(f"正在导入 {dataset_name}...", "取消", 0, len(images), self)
            progress.setWindowTitle("导入进度")
        
            for i, img_path in enumerate(images):
                if progress.wasCanceled():
                    break
            
                progress.setValue(i)
                progress.setLabelText(f"正在导入 {i+1}/{len(images)}: {os.path.basename(img_path)}")
                QApplication.processEvents()  # 保持UI响应
            
                # 读取图片并提取人脸特征
                img = cv2.imread(img_path)
                if img is None:
                    continue
            
                faces = self.face_app.get(img)
                if not faces:
                    continue
            
                # 使用文件名作为人名（可自定义逻辑）
                name = os.path.splitext(os.path.basename(img_path))[0]
                self.face_db.add_face(name, faces[0].embedding, img_path)
        
            progress.close()
            QMessageBox.information(self, "完成", f"成功导入 {len(images)} 张图片！")
    
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入失败: {str(e)}")

    def set_proxy(self):
        try:
            dialog = ProxySettingsDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                self.proxy_settings = dialog.get_proxy()
                self.config.set('proxy_settings', self.proxy_settings)
                
                proxy_type = self.proxy_settings['type']
                host = self.proxy_settings['host']
                port = self.proxy_settings['port']
                self.proxy_status.setText(f"代理: {proxy_type.upper()} {host}:{port}")
                self.log_message(f"✅ 代理设置成功: {proxy_type.upper()} {host}:{port}")
        except Exception as e:
            self.log_message(f"❌ 设置代理失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"设置代理失败: {str(e)}")

    def show_dataset_manager(self):
        try:
            dialog = DatasetManager(self)
            dialog.exec_()
        except Exception as e:
            self.log_message(f"❌ 打开数据集管理器失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"打开数据集管理器失败: {str(e)}")

    def save_face_changes(self, table):
        """保存人脸库的修改（姓名和照片路径）"""
        try:
            for row in range(table.rowCount()):
                face_id = int(table.item(row, 0).text())
                new_name = table.item(row, 1).text()
                new_img_path = table.item(row, 2).text()

                if new_img_path != '无图片' and not os.path.exists(new_img_path):
                    QMessageBox.warning(self, "警告", f"图片路径不存在: {new_img_path}")
                    return

                # 更新数据库
                self.face_db.update_face(face_id, new_name, new_img_path if new_img_path != '无图片' else None)
            
            print(f"[DEBUG] ✅ 人脸库数据更新成功")
            # QMessageBox.information(self, "成功", "修改已保存！") # 弹窗在后面，容易看不到，先注释掉，等需要再改
            self.log_message("✅ 人脸库数据更新成功")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")
            self.log_message(f"❌ 人脸库更新错误: {str(e)}")

    def log_message(self, message):
        """记录日志（增强防御性版本）"""
        try:
            # 确保日志组件存在
            if not hasattr(self, 'log_text'):
                print(f"[临时日志] {message}")  # 回退到控制台输出
                return
                
            timestamp = datetime.now().strftime('%H:%M:%S')
            self.log_text.append(f"[{timestamp}] {message}")
            self.log_text.moveCursor(QTextCursor.End)
        except Exception as e:
            print(f"[DEBUG] 2967记录日志失败: {str(e)}")



    def update_det_thresh(self):
        """更新检测阈值（v2.0.0：真正作用到已加载的检测模型）"""
        try:
            thresh = self.thresh_slider.value() / 100
            self.thresh_spin.setValue(self.thresh_slider.value())
            face_app = getattr(self, 'face_app', None)
            if face_app is not None:
                face_app.det_thresh = thresh
                if hasattr(face_app, 'det_model'):
                    face_app.det_model.det_thresh = thresh
            self.log_message(f"🛠️ 检测阈值更新为: {thresh:.2f}")
        except Exception as e:
            self.log_message(f"❌ 更新检测阈值失败: {str(e)}")

    def update_det_interval(self):
        """更新检测间隔"""
        try:
            self.detection_interval = self.interval_slider.value()
            self.interval_spin.setValue(self.interval_slider.value())
            self.log_message(f"🛠️ 检测间隔更新为: {self.detection_interval}ms")
        except Exception as e:
            self.log_message(f"❌ 更新检测间隔失败: {str(e)}")

    def check_and_download_model(self):
        """校验当前模型文件是否齐全，缺失则弹出下载进度框

        v2.0.0 修复：原代码在"模型名不在 MODELS 中"分支调用了不存在的
        self.download_model()（AttributeError）。现在改成：回退到配置里
        可用的模型 / 默认模型，并复用下面统一的下载流程。
        """
        try:
            model_info = MODELS.get(self.model_name)
            if not model_info:
                # 配置里的模型名无效（例如手工改坏了 config.json）
                fallback = 'buffalo_l' if 'buffalo_l' in MODELS else next(iter(MODELS))
                QMessageBox.warning(
                    self, "模型无效",
                    f"配置中的模型 {self.model_name} 不存在。\n已自动回退到 {fallback}。")
                self.log_message(f"⚠️ 模型 {self.model_name} 无效，回退为 {fallback}")
                self.model_name = fallback
                self.config.set('model_name', fallback)
                if hasattr(self, 'model_combo'):
                    self.model_combo.setCurrentText(fallback)
                model_info = MODELS[fallback]

            model_dir = os.path.join(models_root, self.model_name)
            debug_print(f"模型目录: {model_dir}")
            required_files = [os.path.join(model_dir, f) for f in model_info["files"]]

            if all(os.path.exists(f) and os.path.getsize(f) > 10*1024 for f in required_files):
                self.log_message(f"✅ 模型 {self.model_name} 已存在，无需下载。")
                self.init_face_recognition()
                return

            self.download_dialog = QProgressDialog("正在下载模型...", "取消", 0, 100, self)
            self.download_dialog.setWindowTitle("模型下载")
            self.download_dialog.setWindowModality(Qt.WindowModal)
            self.download_dialog.setMinimumDuration(0)
            self.download_dialog.canceled.connect(self.cancel_download)

            self.downloader = ModelDownloader(self.model_name)
            self.downloader.progress_signal.connect(self.update_download_progress)
            self.downloader.finished_signal.connect(self.download_finished)
            self.downloader.start()
        except Exception as e:
            self.log_message(f"❌ 检查并下载模型失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"初始化模型失败: {str(e)}")

    def update_download_progress(self, progress, message):
        try:
            self.download_dialog.setValue(progress)
            print(f"2395下载进度: {progress}%")
            self.download_dialog.setLabelText(message)
            print(f"2397下载消息: {message}")
            self.log_message(message)
        except Exception as e:
            print(f"2400更新下载进度失败: {str(e)}")

    def download_finished(self, success):
        try:
            self.download_dialog.close()
            if success:
                self.init_face_recognition()
            else:
                QMessageBox.critical(self, "错误", "模型下载失败，请检查网络连接")
        except Exception as e:
            self.log_message(f"❌ 下载完成处理失败: {str(e)}")

    def cancel_download(self):
        try:
            if hasattr(self, 'downloader') and self.downloader.isRunning():
                self.downloader.terminate()
            QMessageBox.warning(self, "警告", "模型下载已取消。")
            print("2417取消下载")
            # sys.exit(1) # 程序将退出
        except Exception as e:
            self.log_message(f"❌ 取消下载失败: {str(e)}")

    def get_model_det_params(self):
        """计算当前应作用于检测模型的 (det_thresh, det_size)

        insightface 的 FaceAnalysis.__init__ 里 det_thresh/det_size 只是透传给
        model_zoo（会被忽略），真正生效的是 prepare(det_thresh=..., det_size=...)。
        历史版本用 prepare(ctx_id=0) 的默认值 (0.5, 640x640)，
        所以"界面上的检测阈值/检测尺寸"其实从未作用到模型上。这里统一计算。
        """
        det_thresh = float(self.config.get('det_thresh', 70)) / 100.0
        det_size = tuple(self.det_size)
        if self.low_performance_mode:
            det_size = (480, 480)
            det_thresh = max(det_thresh, 0.75)
        return det_thresh, det_size

    def init_face_recognition(self):
        try:
            model_path = os.path.join(models_root, self.model_name)
            debug_print(f"模型路径: {model_path}")
            # 检查模型文件是否存在
            required_files = MODELS[self.model_name]["files"]
            debug_print(f"所需文件: {required_files}")
            missing = [f for f in required_files
                       if not os.path.exists(os.path.join(model_path, f))]
            if missing:
                print(f"模型文件不存在: {missing}")
                self.check_and_download_model()  # 如果不存在，提示下载


            # ---------- v2.1.0：加速后端选择 + ONNX Runtime 调优 ----------
            # 1) 检测本机能力并按配置（或自动）选后端：CUDA > DirectML > OpenVINO > CPU
            accel = self.report_acceleration(verbose=True)
            backend = accel.get('effective', 'cpu')
            providers = build_ort_providers(backend)
            # 2) 注入 ONNX 会话选项（线程数/顺序执行/图优化）——必须早于建会话
            cpu_threads = self.config.get('cpu_threads', 0)
            session_options = make_ort_session_options(cpu_threads)
            install_ort_session_options(session_options)
            # 3) 收敛 OpenCV 线程，避免与 ONNX 抢核导致界面抖动
            optimize_cv2_threads(cpu_threads)
            self.log_message(f"🚀 使用加速后端: {ACCEL_LABELS.get(backend, backend)}"
                             f"（providers={providers}，intra_op={resolve_cpu_threads(cpu_threads)}）")

            self.face_app = FaceAnalysis(
                name=self.model_name,
                root=os.environ['INSIGHTFACE_MODELS_ROOT'],
                providers=providers)
            # 记录实际生效的 provider（onnxruntime 可能因缺少依赖回退）
            try:
                actual = []
                for model in getattr(self.face_app, 'models', {}).values():
                    session = getattr(model, 'session', None)
                    if session is not None:
                        actual = list(session.get_providers())
                        break
                if actual:
                    self.accel_info['active_providers'] = actual
                    ok_gpu = any('CPU' not in p for p in actual)
                    self.log_message(f"🧠 模型实际运行在: {', '.join(actual)}"
                                     f"{'（GPU 加速已生效）' if ok_gpu else '（纯 CPU）'}")
            except Exception as e:
                debug_print(f"[加速] 读取实际 provider 失败: {e}")

            # v2.0.0：真正把"配置里的检测阈值/检测尺寸"应用到检测模型
            det_thresh, det_size = self.get_model_det_params()
            self.face_app.prepare(ctx_id=0, det_thresh=det_thresh, det_size=det_size)
            self.face_app.det_thresh = det_thresh
            self.face_app.det_size = det_size
            if hasattr(self.face_app, 'det_model'):
                self.face_app.det_model.det_thresh = det_thresh
            # 注意：不要用 det_size 回写 self.det_size。
            # 低性能模式下模型实际跑 480x480，但用户在界面上配置的尺寸要原样保留，
            # 否则 closeEvent 兜底保存时会把用户设置静默改成 480x480。
            self.log_message(f"🛠️ 检测模型实际参数: 阈值={det_thresh:.2f}, "
                             f"尺寸={det_size[0]}x{det_size[1]}（界面配置 {self.det_size[0]}x{self.det_size[1]}）")

            self.result_label.setText("状态: 模型加载成功，请选择窗口")
            self.btn_capture.setEnabled(True)
            self.btn_screen_capture.setEnabled(True)
            self.log_message("🚀 模型初始化成功")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"模型初始化失败: {str(e)}")
            self.log_message(f"❌ 模型初始化失败: {str(e)}")

    def refresh_windows(self):
        """刷新可捕获窗口列表（v2.0.1：宽字符标题 + 把 hwnd 绑定到每个列表项）

        关键改动：
          * 标题改用 GetWindowTextW，中文不再乱码（原来因乱码导致 FindWindow 找不到窗口）；
          * 每个下拉项通过 setItemData 绑定真实 HWND，选择后**不再依赖标题匹配**，
            标题动态变化（浏览器/播放器）也能继续抓；
          * 悬停提示里带上进程名，方便区分同名窗口。
        """
        try:
            self.window_combo.blockSignals(True)   # 重建列表期间不要写配置
            self.window_combo.clear()
            windows = self.get_window_list()        # [(title, hwnd, pid), ...]
            for title, handle, pid in windows:
                self.window_combo.addItem(title, int(handle))
                idx = self.window_combo.count() - 1
                pname = ""
                try:
                    pname = psutil.Process(pid).name()
                except Exception:
                    pname = f"PID {pid}"
                self.window_combo.setItemData(
                    idx, f"{title}\n进程: {pname}\nHWND: 0x{int(handle):X}", Qt.ToolTipRole)
            self.window_combo.blockSignals(False)
            self.log_message(f"🚀 刷新窗口列表，找到 {len(windows)} 个窗口")
            # 刷新后按配置恢复上次选择（原版本没有这一步，last_window 形同虚设）
            self.restore_last_window()
        except Exception as e:
            try:
                self.window_combo.blockSignals(False)
            except Exception:
                pass
            self.log_message(f"❌ 刷新窗口列表失败: {str(e)}")

    def get_window_list(self):
        """获取可见顶层窗口列表，返回 [(title, hwnd, pid), ...]（宽字符，中文不乱码）"""
        try:
            windows = enum_windows_unicode()
            debug_print(f"[捕获] 枚举到 {len(windows)} 个可见窗口")
            return windows
        except Exception as e:
            self.log_message(f"❌ 获取窗口列表失败: {str(e)}")
            return []

    # ==================================================================
    # 窗口句柄解析 / 分辨率与 DPI / 帧校验
    # ==================================================================
    def _resolve_window_handle(self, window_title, hwnd=None):
        """把"下拉项标题 / 缓存的 hwnd"解析成仍然有效的 HWND

        顺序：显式 hwnd → hwnd 缓存 → 标题精确匹配(宽字符) → 标题包含匹配。
        包含匹配用于标题会变的窗口（浏览器标签、播放器文件名等）。
        """
        if not hasattr(self, '_window_hwnd_cache'):
            self._window_hwnd_cache = {}

        def _valid(h):
            try:
                return bool(h) and bool(ctypes.windll.user32.IsWindow(_hwnd(h)))
            except Exception:
                return False

        # 1) 调用方显式传入（来自 window_combo.currentData()，最可靠）
        if _valid(hwnd):
            if window_title:
                self._window_hwnd_cache[window_title] = int(hwnd)
            return int(hwnd)
        # 2) 上次解析结果（同一标题）
        cached = self._window_hwnd_cache.get(window_title)
        if _valid(cached):
            return int(cached)
        # 3) 精确标题匹配（宽字符）
        found = find_window_unicode(window_title)
        if _valid(found):
            self._window_hwnd_cache[window_title] = int(found)
            return int(found)
        # 4) 包含匹配（标题变了 / 用户手工选过）
        if window_title:
            candidates = enum_windows_unicode()
            key = window_title.strip().lower()
            for title, handle, _pid in candidates:
                low = title.strip().lower()
                if low == key:
                    self._window_hwnd_cache[window_title] = int(handle)
                    return int(handle)
            for title, handle, _pid in candidates:
                low = title.strip().lower()
                if key and (key in low or low in key):
                    self._window_hwnd_cache[window_title] = int(handle)
                    debug_print(f"[捕获] 标题包含匹配: {window_title!r} -> {title!r}")
                    return int(handle)
        return 0

    def _window_rect(self, hwnd):
        """取窗口矩形；最小化的窗口用 GetWindowPlacement 的"还原后尺寸"

        最小化窗口的 GetWindowRect 会给出屏幕外的图标位置和极小尺寸，
        直接拿来抓图必然是黑块，所以这里换成 rcNormalPosition。
        """
        try:
            user32 = ctypes.windll.user32
            minimized = bool(user32.IsIconic(_hwnd(hwnd)))
            if minimized:
                try:
                    placement = win32gui.GetWindowPlacement(hwnd)
                    rect = placement[4]      # rcNormalPosition
                    left, top, right, bottom = rect[0], rect[1], rect[2], rect[3]
                except Exception:
                    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            else:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width, height = right - left, bottom - top
            if width < 10 or height < 10:
                debug_print(f"[捕获] 窗口尺寸无效: {width}x{height}")
                return None
            return (left, top, right, bottom)
        except Exception as e:
            debug_print(f"[捕获] 取窗口矩形失败: {e}")
            return None

    def _screen_dpi_scale(self):
        """主显示器 物理像素/逻辑像素 比例（仅用于诊断日志，不参与坐标换算）"""
        if getattr(self, '_dpi_scale', None):
            return self._dpi_scale
        scale = 1.0
        try:
            screen = QApplication.primaryScreen()
            if screen is not None:
                scale = float(screen.devicePixelRatio())
        except Exception as e:
            debug_print(f"[捕获] 读取 DPI 缩放失败: {e}")
        self._dpi_scale = scale
        debug_print(f"[捕获] 主显示器 DPI 缩放比: {scale}")
        return scale

    def _logical_rect_to_physical(self, rect):
        """把 GetWindowRect 的逻辑坐标换算成"物理虚拟桌面"坐标

        为什么需要：非 DPI 感知进程拿到的是逻辑坐标，而屏幕 DC / PIL 取的是物理像素，
        在 125%/150%/200% 缩放屏上直接拿逻辑坐标去裁会裁歪。
        这里按窗口所在那块 QScreen 的 devicePixelRatio 逐屏换算，多显示器也正确。
        """
        left, top, right, bottom = rect
        try:
            width, height = right - left, bottom - top
            cx, cy = left + width // 2, top + height // 2
            screen = None
            for scr in QApplication.screens():
                g = scr.geometry()
                if g.left() <= cx < g.right() and g.top() <= cy < g.bottom():
                    screen = scr
                    break
            if screen is None:
                return rect
            dpr = float(screen.devicePixelRatio() or 1.0)
            if abs(dpr - 1.0) < 1e-6:
                return rect
            g = screen.geometry()
            ox, oy = g.left() * dpr, g.top() * dpr
            pl = int(round(ox + (left - g.left()) * dpr))
            pt = int(round(oy + (top - g.top()) * dpr))
            pr = pl + int(round(width * dpr))
            pb = pt + int(round(height * dpr))
            debug_print(f"[捕获] 坐标换算(dpr={dpr}): {rect} -> {(pl, pt, pr, pb)}")
            return (pl, pt, pr, pb)
        except Exception as e:
            debug_print(f"[捕获] 坐标换算失败，按原值使用: {e}")
            return rect

    # ==================================================================
    # 单策略抓帧实现
    # ==================================================================
    def _grab_window_gdi(self, hwnd, rect, printwindow_flags=None, use_captureblt=False):
        """GDI 抓窗口：printwindow_flags 非空走 PrintWindow，否则走 BitBlt

        v2.0.1 重要经验：pywin32 的 `CreateCompatibleBitmap` / `CDC.BitBlt` 在**成功时返回
        None**，用 `if not ret: 失败` 判断会把成功调用全部误判为失败（这就是"选完窗口
        拿不到画面"的直接原因之一）。所以这里不再相信返回值，一律**以位图内容为准**，
        由调用方 frame_is_usable() 校验黑图/空图。
        """
        left, top, right, bottom = rect
        width, height = right - left, bottom - top
        hwndDC = mfcDC = saveDC = saveBitMap = None
        try:
            hwndDC = win32gui.GetWindowDC(hwnd)
            if not hwndDC:
                debug_print("[捕获] GetWindowDC 失败")
                return None
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()
            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
            if not saveBitMap.GetHandle():
                debug_print("[捕获] CreateCompatibleBitmap 未返回有效位图")
                return None
            saveDC.SelectObject(saveBitMap)

            if printwindow_flags is not None:
                ret = ctypes.windll.user32.PrintWindow(
                    _hwnd(hwnd), wintypes.HDC(saveDC.GetSafeHdc()),
                    ctypes.c_uint(printwindow_flags))
                debug_print(f"[捕获] PrintWindow(flags={printwindow_flags}) 返回 {ret}（仅记录，以内容为准）")
            else:
                rop = win32con.SRCCOPY | (CAPTUREBLT if use_captureblt else 0)
                ret = saveDC.BitBlt((0, 0), (width, height), mfcDC, (0, 0), rop)
                debug_print(f"[捕获] BitBlt(CAPTUREBLT={use_captureblt}) 返回 {ret!r}（仅记录，以内容为准）")

            info = saveBitMap.GetInfo()
            bits = saveBitMap.GetBitmapBits(True)
            img = np.frombuffer(bits, dtype=np.uint8).reshape((info['bmHeight'], info['bmWidth'], 4))
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        except Exception as e:
            debug_print(f"[捕获] GDI 抓窗口异常: {e}")
            return None
        finally:
            try:
                if saveBitMap is not None:
                    win32gui.DeleteObject(saveBitMap.GetHandle())
            except Exception:
                pass
            try:
                if saveDC is not None:
                    saveDC.DeleteDC()
            except Exception:
                pass
            try:
                if mfcDC is not None:
                    mfcDC.DeleteDC()
            except Exception:
                pass
            try:
                if hwndDC:
                    win32gui.ReleaseDC(hwnd, hwndDC)
            except Exception:
                pass

    def _grab_screen_gdi(self, rect):
        """GDI 屏幕 DC 抓取指定区域（坐标由逻辑坐标换算到物理像素）"""
        left, top, right, bottom = self._logical_rect_to_physical(rect)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            return None
        screenDC = mfcDC = saveDC = saveBitMap = None
        try:
            screenDC = win32gui.GetDC(0)
            mfcDC = win32ui.CreateDCFromHandle(screenDC)
            saveDC = mfcDC.CreateCompatibleDC()
            saveBitMap = win32ui.CreateBitmap()
            # 同 _grab_window_gdi：CreateCompatibleBitmap 成功返回 None，不能用返回值判断成败
            saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
            if not saveBitMap.GetHandle():
                return None
            saveDC.SelectObject(saveBitMap)
            # 同样不相信 BitBlt 的返回值（成功时为 None），以内容为准
            ret = saveDC.BitBlt((0, 0), (width, height), mfcDC, (left, top),
                                win32con.SRCCOPY | CAPTUREBLT)
            debug_print(f"[捕获] 屏幕 BitBlt 返回 {ret!r}（仅记录，以内容为准）")
            info = saveBitMap.GetInfo()
            bits = saveBitMap.GetBitmapBits(True)
            img = np.frombuffer(bits, dtype=np.uint8).reshape((info['bmHeight'], info['bmWidth'], 4))
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        except Exception as e:
            debug_print(f"[捕获] GDI 屏幕裁剪异常: {e}")
            return None
        finally:
            try:
                if saveBitMap is not None:
                    win32gui.DeleteObject(saveBitMap.GetHandle())
            except Exception:
                pass
            for dc in (saveDC, mfcDC):
                try:
                    if dc is not None:
                        dc.DeleteDC()
                except Exception:
                    pass
            try:
                if screenDC:
                    win32gui.ReleaseDC(0, screenDC)
            except Exception:
                pass

    def _grab_screen_qt(self, rect):
        """Qt 整屏截图 + 裁剪

        为什么它能兜底：Qt 的坐标系与"非 DPI 感知进程"的 GetWindowRect 同一套逻辑坐标，
        不会出现 GDI 那种"物理/逻辑像素错位"；而且 Qt 走的是自己的抓屏后端，
        在部分 GDI 抓屏失败（受保护内容、驱动异常）的环境下仍能出图。
        """
        try:
            left, top, right, bottom = rect
            width, height = right - left, bottom - top
            if width <= 0 or height <= 0:
                return None
            cx, cy = left + width // 2, top + height // 2
            screen = None
            for scr in QApplication.screens():
                g = scr.geometry()
                if g.left() <= cx < g.right() and g.top() <= cy < g.bottom():
                    screen = scr
                    break
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen is None:
                return None
            geo = screen.geometry()
            local_x, local_y = left - geo.left(), top - geo.top()
            pixmap = screen.grabWindow(0, int(local_x), int(local_y), int(width), int(height))
            if pixmap is None or pixmap.isNull():
                return None
            return qimage_to_bgr(pixmap.toImage())
        except Exception as e:
            debug_print(f"[捕获] Qt 屏幕裁剪异常: {e}")
            return None

    def _grab_screen_pil(self, rect):
        """PIL ImageGrab 抓取指定区域（all_screens，坐标换算到物理像素）"""
        try:
            from PIL import ImageGrab
            box = self._logical_rect_to_physical(rect)
            if box[2] - box[0] <= 0 or box[3] - box[1] <= 0:
                return None
            try:
                shot = ImageGrab.grab(bbox=box, all_screens=True)
            except TypeError:
                shot = ImageGrab.grab(bbox=box)      # 老版本 Pillow 没有 all_screens
            if shot is None:
                return None
            arr = np.array(shot)
            if arr.ndim == 2:
                arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
            return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        except Exception as e:
            debug_print(f"[捕获] PIL 屏幕裁剪异常: {e}")
            return None

    def _grab_via_graphics_capture(self, hwnd, rect):
        """Windows.Graphics.Capture（若环境提供 pywincffi.graphicscapture）

        该库不同版本 API 不统一，这里做"尽力而为"的最小假设尝试；
        任何异常都被吞掉，交由后续策略兜底。
        """
        if gc is None:
            return None
        try:
            for entry in ('capture_window', 'grab_window', 'screenshot_window', 'capture'):
                fn = getattr(gc, entry, None)
                if callable(fn):
                    frame = fn(int(hwnd))
                    arr = np.asarray(frame)
                    if arr.ndim == 3 and arr.shape[2] == 4:
                        return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
                    if arr.ndim == 3 and arr.shape[2] == 3:
                        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                    if arr.ndim == 2:
                        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
            debug_print("[捕获] pywincffi.graphicscapture 未提供可识别的入口，跳过")
        except Exception as e:
            debug_print(f"[捕获] Windows.Graphics.Capture 失败: {e}")
        return None

    def _capture_by_method(self, method, hwnd, rect):
        """按策略名抓一帧（返回 BGR 或 None）"""
        if method == 'printwindow_full':
            return self._grab_window_gdi(hwnd, rect, printwindow_flags=PW_RENDERFULLCONTENT)
        if method == 'printwindow':
            return self._grab_window_gdi(hwnd, rect, printwindow_flags=0)
        if method == 'bitblt_window':
            return self._grab_window_gdi(hwnd, rect, use_captureblt=False)
        if method == 'bitblt_captureblt':
            return self._grab_window_gdi(hwnd, rect, use_captureblt=True)
        if method == 'qt_screen_crop':
            return self._grab_screen_qt(rect)
        if method == 'gdi_screen_crop':
            return self._grab_screen_gdi(rect)
        if method == 'pil_screen_crop':
            return self._grab_screen_pil(rect)
        if method == 'graphics_capture':
            return self._grab_via_graphics_capture(hwnd, rect)
        return None

    def _capture_hint(self, message, force=False):
        """节流记录捕获失败提示：同一条提示不刷屏，日志面板看得清"""
        if not force and message == getattr(self, '_last_capture_hint', None):
            return
        self._last_capture_hint = message
        self.log_message(message)

    def capture_window(self, window_title=None, hwnd=None):
        """抓取窗口画面（v2.0.1：8 级策略链 + 逐级校验 + 策略记忆）

        参数：
            window_title : 下拉框里的标题（用于解析/缓存句柄、写日志）
            hwnd         : 可选，下拉项绑定的真实句柄（最可靠，来自 currentData()）

        返回：BGR ndarray；全部策略失败返回 None（并给出可操作的提示）。
        """
        try:
            if window_title is None:
                window_title = self.current_window or (
                    self.window_combo.currentText() if hasattr(self, 'window_combo') else '')
            if hwnd is None and hasattr(self, 'window_combo'):
                hwnd = self.window_combo.currentData()

            handle = self._resolve_window_handle(window_title, hwnd)
            if not handle:
                self._capture_hint(
                    f"❌ 未找到窗口「{window_title}」：请点击【刷新】，"
                    f"确认窗口未关闭/未被最小化后重新选择")
                return None

            user32 = ctypes.windll.user32
            minimized = bool(user32.IsIconic(_hwnd(handle)))
            rect = self._window_rect(handle)
            if rect is None:
                self._capture_hint("❌ 窗口尺寸无效（可能已最小化到托盘或正在关闭）")
                return None
            width, height = rect[2] - rect[0], rect[3] - rect[1]

            # 记住上次成功的策略，下次优先用它（避免每帧都去试失败的方法）
            methods = list(CAPTURE_METHODS)
            last_ok = getattr(self, '_capture_strategy', None)
            if last_ok in methods:
                methods.remove(last_ok)
                methods.insert(0, last_ok)

            failures = []
            for method in methods:
                # 最小化窗口在屏幕上没有画面，屏幕裁剪类策略直接跳过
                if minimized and method in ('qt_screen_crop', 'gdi_screen_crop', 'pil_screen_crop'):
                    failures.append(f"{CAPTURE_METHOD_DESC[method]}:窗口已最小化")
                    continue
                img = self._capture_by_method(method, handle, rect)
                if not frame_is_usable(img):
                    failures.append(f"{CAPTURE_METHOD_DESC[method]}:未取到图像")
                    continue
                # 窗口类抓取（PrintWindow/BitBlt）在黑图时视为失败，继续降级
                if method in ('printwindow_full', 'printwindow',
                              'bitblt_window', 'bitblt_captureblt') and \
                        not frame_is_usable(img, require_content=True):
                    failures.append(f"{CAPTURE_METHOD_DESC[method]}:抓到全黑画面")
                    continue

                if last_ok != method:
                    self.log_message(
                        f"🖼️ 捕获方式切换为【{CAPTURE_METHOD_DESC[method]}】"
                        f"（{width}x{height}）")
                self._capture_strategy = method
                self._capture_fail_streak = 0
                self._capture_hint("", force=False)
                return img

            # 全部策略失败
            self._capture_fail_streak = getattr(self, '_capture_fail_streak', 0) + 1
            self._capture_strategy = None
            detail = "；".join(failures[:4])
            tip = ("请先还原（不要最小化）该窗口；若窗口显示「受保护内容」"
                   "（如播放器版权画面 / UAC 弹窗），请改用【框选】功能")
            self._capture_hint(
                f"❌ 无法获取窗口画面（已尝试 {len(failures)} 种方式）。{tip}。明细: {detail}")
            debug_print(f"[捕获] 全部策略失败: {failures}")
            return None
        except Exception as e:
            self.log_message(f"❌ 窗口捕获错误: {e}")
            debug_print(f"[捕获] 异常: {traceback.format_exc()}")
            return None

    def capture_window_diagnose(self):
        """诊断当前选择的窗口：逐个策略试一遍并把结果打到日志面板

        用途：用户报"选完窗口没画面"时，点一下【诊断捕获】就能看到
              到底是找不到窗口、句柄失效、还是每种方式都抓不到。
        """
        title = self.window_combo.currentText() if hasattr(self, 'window_combo') else ''
        hwnd = self.window_combo.currentData() if hasattr(self, 'window_combo') else None
        self.log_message("=" * 46)
        self.log_message(f"🔍 开始诊断窗口捕获: {title!r}")
        handle = self._resolve_window_handle(title, hwnd)
        self.log_message(f"   · 解析到的 HWND: 0x{handle:X}" if handle else "   · 未解析到 HWND")
        if not handle:
            self.log_message("   ✗ 结论：窗口句柄无效，请点【刷新】重新选择")
            return False
        try:
            pid = wintypes.DWORD(0)
            ctypes.windll.user32.GetWindowThreadProcessId(_hwnd(handle), ctypes.byref(pid))
            pname = psutil.Process(pid.value).name()
            self.log_message(f"   · 进程: {pname} (PID {pid.value})")
        except Exception:
            pass
        self.log_message(f"   · 实际标题: {get_window_title_unicode(handle)!r}")
        self.log_message(f"   · 是否最小化: {bool(ctypes.windll.user32.IsIconic(_hwnd(handle)))}")
        rect = self._window_rect(handle)
        self.log_message(f"   · 窗口矩形: {rect}")
        if rect is None:
            self.log_message("   ✗ 结论：窗口尺寸无效")
            return False
        self.log_message(f"   · DPI 缩放: {self._screen_dpi_scale()}")
        ok_method = None
        for method in CAPTURE_METHODS:
            img = self._capture_by_method(method, handle, rect)
            usable = frame_is_usable(img)
            content = frame_is_usable(img, require_content=True)
            shape = None if img is None else img.shape
            self.log_message(
                f"   · {CAPTURE_METHOD_DESC[method]:<26} 取到={usable} 非全黑={content} 尺寸={shape}")
            if usable and content and ok_method is None:
                ok_method = method
        if ok_method:
            self.log_message(f"   ✓ 结论：可用，建议方式 = {CAPTURE_METHOD_DESC[ok_method]}")
        else:
            self.log_message("   ✗ 结论：所有方式都拿不到有效画面（窗口可能显示受保护内容，"
                             "或被最小化/隐藏），建议改用【框选】功能")
        self.log_message("=" * 46)
        return ok_method is not None

    def toggle_auto_save(self, state):
        """切换是否自动保存未知人脸（实时写入配置）"""
        if getattr(self, '_restoring_ui', False):
            return
        self.config.set('auto_save_unknown', state == Qt.Checked)
        self.log_message(f"🛠️ 自动保存未知人脸: {'开启' if state == Qt.Checked else '关闭'}")


    def toggle_capture(self):
        """开始/停止捕获

        v2.0.1：开始前先"试抓一帧"。抓不到就立刻弹窗说明原因并给出可操作建议，
        而不是启动定时器后让用户对着黑屏等（这正是"选择进程后拿不到图像"的体验问题）。
        """
        try:
            if self.is_detecting:
                self.timer.stop()
                try:
                    self.timer.timeout.disconnect()  # 确保断开连接
                except Exception:
                    pass
                self.is_detecting = False
                self.btn_capture.setText("开始")
                self.result_label.setText("状态: 捕获已停止")
                self.log_message("📵 停止窗口捕获")
                return

            if not hasattr(self, 'timer'):
                QMessageBox.warning(self, "请稍候", "模型与数据库仍在初始化，请稍后再试。")
                return

            # 开始新检测前清除缓存
            self.face_cache.clear()
            self.current_faces = []
            self.current_face_id = 0
            self._capture_fail_streak = 0
            self._capture_hint_messages = []

            # v2.1.0：确保检测工作线程在跑（关闭状态启动后也能自动补上）
            self._start_detect_worker()

            window_title = self.window_combo.currentText()
            if not window_title:
                QMessageBox.warning(self, "⚠️ 警告", "请先选择窗口")
                return
            hwnd = self.window_combo.currentData() if hasattr(self, 'window_combo') else None

            # ---------- 关键：先试抓一帧 ----------
            self.result_label.setText("状态: 正在尝试获取画面...")
            QApplication.processEvents()
            frame = self.capture_window(window_title, hwnd)
            if frame is None:
                methods = " / ".join(CAPTURE_METHOD_DESC[m] for m in CAPTURE_METHODS)
                QMessageBox.warning(
                    self, "无法获取画面",
                    f"未能获取窗口画面：\n{window_title}\n\n"
                    f"已依次尝试：{methods}\n\n"
                    "请依次排查：\n"
                    "  1. 点【刷新】重新选择窗口（标题会变时尤其需要）；\n"
                    "  2. 窗口不要处于最小化状态；\n"
                    "  3. 点【诊断】查看每种方式的实际结果；\n"
                    "  4. 若窗口显示受保护内容（播放器/DRM/UAC），请改用【框选】。")
                self.result_label.setText("状态: 无法获取画面，请点【诊断】查看原因")
                return

            self.current_window = window_title
            self.current_hwnd = hwnd
            self.display_image_with_ratio(frame)
            desc = CAPTURE_METHOD_DESC.get(self._capture_strategy, str(self._capture_strategy))
            self.log_message(f"✅ 已获取画面 {frame.shape[1]}x{frame.shape[0]}，捕获方式: {desc}")

            self.timer.timeout.connect(self.update_capture)  # 重新连接
            self.timer.start(100)
            self.is_detecting = True
            self.btn_capture.setText("停止")
            self.log_message("📷 检测已开始，旧数据已清理")
            self.result_label.setText(f"状态: 正在捕获窗口 [{window_title}]（{desc}）")
        except Exception as e:
            self.log_message(f"❌ 切换捕获状态失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"切换捕获状态失败: {str(e)}")
            safe_print(f"[捕获] 切换捕获状态失败: {traceback.format_exc()}")

    def toggle_detect_box(self, state):
        """切换是否显示检测框（实时写入配置 + 立即刷新画面）"""
        show_box = (state == Qt.Checked)
        if getattr(self, '_restoring_ui', False):
            return
        self.config.set('show_detect_box', show_box)
        self.log_message(f"🛠️ 检测框显示状态: {'显示' if show_box else '隐藏'}")
        debug_print(f"配置内 show_detect_box = {self.config.get('show_detect_box')}")

        # 强制刷新当前显示
        if getattr(self, 'last_frame', None) is not None:
            self.display_image_with_ratio(self.last_frame)


    # ==================================================================
    # v2.1.0 硬件加速检测 / 检测工作线程 / 性能统计
    # ==================================================================
    def report_acceleration(self, verbose=False, show_dialog=False):
        """检测并输出本机加速能力报告（需求：检测是否支持 GPU 加速）"""
        try:
            preferred = self.config.get('accel_backend', 'auto')
            cpu_threads = self.config.get('cpu_threads', 0)
            info = probe_acceleration(preferred, cpu_threads)
            self.accel_info = info
            if verbose:
                for line in format_acceleration_report(info).splitlines():
                    self.log_message(line)
            if hasattr(self, 'accel_label'):
                label = info.get('effective_label', '-')
                self.accel_label.setText(f"加速: {label}")
                self.accel_label.setToolTip(
                    f"provider: {', '.join(info.get('providers') or [])}\n"
                    f"线程: {info.get('cpu_threads')}\n"
                    f"显卡: {', '.join(info.get('gpus') or []) or '未识别'}")
            if show_dialog:
                QMessageBox.information(self, "硬件加速检测", format_acceleration_report(info))
            return info
        except Exception as e:
            self.log_message(f"❌ 加速检测失败: {str(e)}")
            return {}

    def on_accel_backend_changed(self, _index=None):
        """切换加速后端：写配置 + 重新加载模型（需求6：实时保存）"""
        if getattr(self, '_restoring_ui', False):
            return
        backend = self.accel_combo.currentData() or 'auto'
        self.config.set('accel_backend', backend)
        info = self.report_acceleration(verbose=True)
        if info.get('note'):
            QMessageBox.warning(self, "加速后端", info['note'])
        # 后端变了就重建模型会话（否则还是在用旧 provider）
        if getattr(self, 'face_app', None):
            self.log_message(f"🔁 加速后端切换为「{ACCEL_LABELS.get(backend, backend)}」，正在重建模型...")
            self.change_model(self.model_name)

    def on_cpu_threads_changed(self, value):
        """线程数变更：写配置 + 立即调整 OpenCV/ONNX 线程（需求6）"""
        if getattr(self, '_restoring_ui', False):
            return
        self.config.set('cpu_threads', int(value))
        optimize_cv2_threads(value)
        actual = resolve_cpu_threads(value)
        self.log_message(f"🛠️ 推理线程数设置为 {value}（实际使用 {actual}）"
                         f"，下次重建模型时生效；OpenCV 线程已同步调整")
        if hasattr(self, 'accel_label'):
            self.accel_label.setText(f"加速: {ACCEL_LABELS.get(self.config.get('accel_backend', 'auto'), '-')}")

    def _start_detect_worker(self):
        """建立检测工作线程（纯 CPU 防卡顿的关键）"""
        try:
            if not self.config.get('use_worker_thread', True):
                self.log_message("ℹ️ 检测工作线程已在配置中关闭（use_worker_thread=false）")
                return None
            if self.detect_worker is not None and self.detect_worker.isRunning():
                return self.detect_worker
            self.detect_worker = FaceDetectWorker(
                face_app_provider=lambda: getattr(self, 'face_app', None),
                face_db=getattr(self, 'face_db', None),
                param_provider=lambda: {
                    'enable_preprocess': self.enable_preprocess,
                    'low_performance_mode': self.low_performance_mode,
                    'max_detect_faces': 0,
                    'detect_input_max_side': self.config.get('detect_input_max_side', 1280),
                },
                parent=self)
            self.detect_worker.result_ready.connect(self._on_detect_result)
            self.detect_worker.detect_failed.connect(self._on_detect_failed)
            self.detect_worker.start()
            self.log_message(f"🧵 检测工作线程已启动（推理线程 {resolve_cpu_threads(self.config.get('cpu_threads', 0))}，"
                             f"界面线程只负责绘制）")
            return self.detect_worker
        except Exception as e:
            self.log_message(f"❌ 启动检测线程失败，将回退到界面线程检测: {str(e)}")
            self.detect_worker = None
            return None

    def _stop_detect_worker(self):
        """停止检测工作线程（退出程序时调用）"""
        worker = getattr(self, 'detect_worker', None)
        if worker is None:
            return
        try:
            worker.request_stop()
            if not worker.wait(2000):
                debug_print("[检测线程] 等待超时，强制终止")
                worker.terminate()
                worker.wait(1000)
        except Exception as e:
            debug_print(f"[检测线程] 停止失败: {e}")
        self.detect_worker = None

    def _compute_rois(self, frame):
        """ROI 差分：只在画面发生足够变化时才检测（纯 CPU 下最省算力的一步）"""
        try:
            full = [(0, 0, frame.shape[1], frame.shape[0])]
            if getattr(self, 'last_frame', None) is None:
                return full
            prev = self.last_frame
            if prev.shape != frame.shape:
                return full
            diff = cv2.absdiff(frame, prev)
            gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            _, mask = cv2.threshold(gray_diff, 25, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            rois = []
            frame_area = float(frame.shape[0] * frame.shape[1])
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area > self.min_roi_area and area > frame_area * self.roi_threshold:
                    x, y, w, h = cv2.boundingRect(cnt)
                    margin = min(w, h) // 2
                    rois.append((max(0, x - margin), max(0, y - margin),
                                 min(frame.shape[1], x + w + margin),
                                 min(frame.shape[0], y + h + margin)))
            return rois
        except Exception as e:
            debug_print(f"[性能] ROI 计算失败，退回全图: {e}")
            return [(0, 0, frame.shape[1], frame.shape[0])]

    def _update_tracking(self, frame):
        """光流跟踪（廉价，保留在界面线程）：更新 tracked_faces 的框位置"""
        try:
            if getattr(self, 'last_gray', None) is None or frame.ndim != 3 or not self.tracked_faces:
                return
            current_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            p0 = np.array([[[f['bbox'][0] + (f['bbox'][2] - f['bbox'][0]) // 2,
                             f['bbox'][1] + (f['bbox'][3] - f['bbox'][1]) // 2]]
                           for f in self.tracked_faces], dtype=np.float32)
            p1, st, _ = cv2.calcOpticalFlowPyrLK(self.last_gray, current_gray, p0, None,
                                                 **self.lk_params)
            updated = []
            for i, (success, new_point) in enumerate(zip(st, p1)):
                if success != 1:
                    continue
                face = self.tracked_faces[i].copy()
                w = face['bbox'][2] - face['bbox'][0]
                h = face['bbox'][3] - face['bbox'][1]
                face['bbox'] = [int(new_point[0][0] - w // 2), int(new_point[0][1] - h // 2),
                                int(new_point[0][0] + w // 2), int(new_point[0][1] + h // 2)]
                updated.append(face)
            self.tracked_faces = updated
            self.tracking_frames += 1
        except Exception as e:
            debug_print(f"[性能] 光流跟踪失败: {e}")

    def _on_detect_result(self, payload):
        """检测线程回传结果（在界面线程执行）：更新缓存、识别记录、状态栏"""
        if not isinstance(payload, dict):
            return
        try:
            faces = payload.get('faces') or []
            self.last_detect_ms = float(payload.get('elapsed_ms') or 0.0)
            self.detect_skipped = int(payload.get('dropped') or 0)

            new_cache = {}
            tracked = []
            for item in faces:
                face_id = item.get('face_id')
                if face_id is None:
                    continue
                new_cache[face_id] = {
                    'image': item.get('image'),
                    'embedding': item.get('embedding'),
                    'bbox': np.array(item.get('bbox'), dtype=int),
                    'det_score': item.get('det_score', 0.0),
                    # v2.1.0：把检索结果一起缓存，绘制时不再重复查库
                    'name': item.get('name'),
                    'similarity': item.get('similarity', 0.0),
                    'confidence': item.get('confidence', 0.0),
                }
                tracked.append({
                    'bbox': np.array(item.get('bbox'), dtype=int),
                    'embedding': item.get('embedding'),
                    'name': item.get('name'),
                    'score': item.get('det_score', 0.0),
                })
                face_img = item.get('image')
                if face_img is not None and getattr(face_img, 'size', 0) > 0:
                    self.update_recognition_display({
                        'face_img': face_img,
                        'name': item.get('name'),
                        'similarity': float(item.get('similarity') or 0.0),
                        'is_known': item.get('name') is not None,
                        'embedding': item.get('embedding'),
                    })
                # 未知人脸自动存盘（与原逻辑一致）
                if item.get('name') is None and self.config.get('auto_save_unknown', False) \
                        and face_img is not None and getattr(face_img, 'size', 0) > 0:
                    try:
                        os.makedirs(os.path.join(BASE_DIR, 'unknown_faces'), exist_ok=True)
                        stamp = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-4]
                        cv2.imwrite(os.path.join(BASE_DIR, 'unknown_faces',
                                                 f"unknown_{stamp}.jpg"), face_img)
                        self.log_message(f"📷 已自动保存未知人脸: unknown_{stamp}.jpg")
                    except Exception as e:
                        debug_print(f"[性能] 保存未知人脸失败: {e}")

            self.face_cache = new_cache
            self.tracked_faces = tracked
            self.current_faces = list(new_cache.values())
            self.tracking_frames = 0

            known = [i for i in faces if i.get('name')]
            if known:
                best = max(known, key=lambda i: float(i.get('similarity') or 0))
                self.result_label.setText(
                    f"状态: 识别到 {best.get('name')}（相似度 {float(best.get('similarity') or 0):.2f}）"
                    f" | {len(faces)} 张脸 / {self.last_detect_ms:.0f}ms")
                new_name = best.get('name')
                if new_name != self.last_detected_name:
                    self.log_message(f"✅ 检测到新名字: {new_name} "
                                     f"(相似度: {float(best.get('similarity') or 0):.2f})")
                    self.last_detected_name = new_name
            elif faces:
                self.result_label.setText(f"状态: 未识别到已知人脸（{len(faces)} 张未知 / "
                                          f"{self.last_detect_ms:.0f}ms）")
            else:
                self.result_label.setText(f"状态: 未检测到人脸（{self.last_detect_ms:.0f}ms）")

            # 用最新的人脸缓存重绘一次（缓存里已有姓名，不需要再查库）
            if getattr(self, 'last_frame', None) is not None:
                self.display_image_with_ratio(self.last_frame)

            # 首次拿到真实检测耗时时，给出一次性的性能建议（纯 CPU 场景的关键体验）
            self._advise_performance_once()
        except Exception as e:
            self.log_message(f"❌ 处理检测结果失败: {str(e)}")
            debug_print(f"[性能] 处理检测结果异常: {traceback.format_exc()}")

    def _advise_performance_once(self):
        """根据实测检测耗时给一次性能建议（每个会话只提示一次）

        纯 CPU 机器上最有价值的两条建议：
          1. 换轻量模型 buffalo_sc/buffalo_s（检测器从 det_10g 换成 det_500m）；
          2. 把检测尺寸/检测间隔调到与算力匹配的值。
        """
        if getattr(self, '_perf_advised', False):
            return
        self._perf_advised = True
        ms = float(getattr(self, 'last_detect_ms', 0.0) or 0.0)
        if ms <= 0:
            return
        threads = resolve_cpu_threads(self.config.get('cpu_threads', 0))
        backend = self.get_active_backend_label()
        if ms < 600:
            self.log_message(f"⚡ 性能正常：单次检测 {ms:.0f}ms（{backend}，{threads} 线程）")
            return

        need, target, why = recommend_light_model(self.model_name, ms)
        interval = int(self.detect_interval)
        suggest_size = 320 if ms >= 1200 else 480
        lines = [
            f"⚠️ 检测偏慢：单次「检测+检索」约 {ms:.0f}ms（后端 {backend}，"
            f"ONNX intra_op={threads} 线程）。",
            "已自动生效的优化：检测在独立线程执行（界面不卡，线程忙时自动丢帧）、"
            "ONNX 线程调优、OpenCV 线程收敛、跳过重复检测与重复查库、大图先降采样。",
        ]
        if need:
            lines.append(f"建议①：切换到轻量模型 {target}。{why}")
        lines.append(f"建议②：检测尺寸设为 {suggest_size}x{suggest_size}，"
                     f"完整检测间隔设为 {max(interval, 8)}~10 帧（当前 {interval} 帧）。")
        lines.append("建议③：勾选「图预处理」可对大于 1280 像素的画面先降采样；"
                     "勾选「低性能」会自动降低检测强度。")
        lines.append("建议④：若显卡支持，装 onnxruntime-gpu / onnxruntime-directml 可获得数倍提升。")
        for line in lines:
            self.log_message(line)

        if not need or target is None:
            return
        try:
            reply = QMessageBox.question(
                self, "检测较慢，是否优化？",
                "\n".join(lines) + f"\n\n现在切换到轻量模型 {target} 吗？\n"
                f"（会立即重新加载模型，之后可在「模型」下拉框随时切回 {self.model_name}）",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                old = self.model_name
                self.config.set('model_name', target)
                if hasattr(self, 'model_combo'):
                    self.model_combo.setCurrentText(target)
                else:
                    self.change_model(target)
                self.log_message(f"✅ 已从 {old} 切换为轻量模型 {target}")
        except Exception as e:
            debug_print(f"[性能] 性能建议弹窗失败: {e}")

    def _on_detect_failed(self, message):
        self.log_message(f"❌ {message}")

    def get_active_backend_label(self):
        """当前实际生效的加速后端（用于状态显示/日志/测试）"""
        info = getattr(self, 'accel_info', None) or {}
        return info.get('effective_label') or ACCEL_LABELS.get(
            self.config.get('accel_backend', 'auto'), '未知')

    def update_capture(self):
        """采集一帧 + 决策是否检测（v2.1.0：界面线程只做廉价工作，重活交给检测线程）

        与历史版本的差别（卡顿的根子）：
          * 历史：同一帧在界面线程里**检测两遍**（ROI 一遍 + 中心区域一遍），
            每个脸还要重复查库 2~4 次，`display_image_with_ratio` 又查一遍；
            界面线程被 ONNX 推理阻塞，必然一卡一卡。
          * 现在：界面线程只做「抓屏 + ROI 差分 + 光流跟踪 + 绘制」这些毫秒级工作，
            「ONNX 推理 + 特征检索」投递给 FaceDetectWorker；线程忙就丢帧，不排队积压。
        """
        if not getattr(self, 'is_detecting', False):
            return
        try:
            current_time = time.time()
            if current_time - self.last_detection_time < self.detection_interval / 1000.0:
                return
            self.last_detection_time = current_time

            frame = self.capture_window(self.current_window, getattr(self, 'current_hwnd', None))
            if frame is None:
                # 偶发抓帧失败不再立刻中断会话，连续失败到阈值才停止
                streak = getattr(self, '_capture_fail_streak', 0)
                self.result_label.setText(
                    f"状态: 暂时无法获取画面 [{self.current_window}]（第 {streak} 次）")
                if streak >= 5:
                    self.timer.stop()
                    self.is_detecting = False
                    self.btn_capture.setText("开始")
                    self.log_message(
                        f"❌ 连续 {streak} 次无法获取窗口画面，已自动停止捕获。"
                        f"可点【诊断】查看每种抓屏方式的结果，或改用【框选】。")
                return

            # ---------- ① ROI 差分（毫秒级）----------
            rois = self._compute_rois(frame)

            # ---------- ② 光流跟踪（毫秒级）----------
            was_tracking = bool(self.tracked_faces)
            self._update_tracking(frame)

            # ---------- ③ 决定是否做完整检测 ----------
            need_detect = ((not was_tracking) or (not self.tracked_faces)
                           or (self.tracking_frames % max(1, int(self.detect_interval)) == 0))
            # 画面没有明显变化、且已经有跟踪结果 → 沿用跟踪框，省一次推理。
            # 注意：没有跟踪结果时必须继续按节奏检测，否则人脸重新出现后永远不会被检测到。
            if not rois and self.tracked_faces:
                need_detect = False

            if need_detect:
                worker = getattr(self, 'detect_worker', None)
                if worker is not None and worker.isRunning():
                    if worker.busy:
                        # 上一帧还没算完：丢帧，绝不排队（这是不卡顿的关键）
                        self.detect_skipped = worker.dropped
                    else:
                        worker.submit(frame, rois, self.current_face_id)
                        self.current_face_id += 256   # 预留区间，避免与上一批 id 冲突
                        self.tracking_frames = 0
                elif self.face_app is not None:
                    # 兜底：工作线程不可用时，退回同步检测（功能优先，可能卡顿）
                    self._detect_sync(frame, rois)

            # ---------- ④ 保存帧 + 绘制（只做一次）----------
            self.last_frame = frame.copy()
            if frame.ndim == 3:
                self.last_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            self.display_image_with_ratio(frame)
        except Exception as e:
            self.log_message(f"❌ 更新捕获画面失败: {str(e)}")
            debug_print(f"[性能] update_capture 异常: {traceback.format_exc()}")

    def _detect_sync(self, frame, rois):
        """同步检测兜底路径（工作线程不可用时使用，直接复用 worker 的检测实现）"""
        try:
            fake_worker = FaceDetectWorker(
                face_app_provider=lambda: getattr(self, 'face_app', None),
                face_db=getattr(self, 'face_db', None),
                param_provider=lambda: {
                    'enable_preprocess': self.enable_preprocess,
                    'low_performance_mode': self.low_performance_mode,
                    'max_detect_faces': 0,
                    'detect_input_max_side': self.config.get('detect_input_max_side', 1280),
                })
            t0 = time.time()
            faces = fake_worker._detect(frame, rois, self.current_face_id)
            elapsed = (time.time() - t0) * 1000.0
            self._on_detect_result({'faces': faces, 'elapsed_ms': elapsed,
                                    'dropped': 0, 'frame_shape': frame.shape})
        except Exception as e:
            self.log_message(f"❌ 同步人脸检测失败: {str(e)}")

    def add_new_face(self):
        try:
            if not self.current_window:
                QMessageBox.warning(self, "警告", "请先选择窗口并开始捕获")
                return
            
            # 锁定当前人脸数据（深拷贝）
            self.locked_faces = {k: v.copy() for k, v in self.face_cache.items()}
            
            if not self.locked_faces:
                QMessageBox.warning(self, "警告", "未检测到人脸")
                return

            # 创建带图片预览的对话框
            dialog = QDialog(self)
            dialog.setWindowTitle("添加新人脸 - 请选择要添加的人脸")
            dialog.resize(900, 700)  # 增大对话框尺寸
            
            layout = QVBoxLayout()
            
            # 添加模式选择
            mode_group = QGroupBox("选择模式")
            mode_layout = QHBoxLayout()
            self.single_mode = QRadioButton("单选模式 (一次添加一个人脸)")
            self.multi_mode = QRadioButton("多选模式 (一次添加多个人脸)")
            self.single_mode.setChecked(True)
            mode_layout.addWidget(self.single_mode)
            mode_layout.addWidget(self.multi_mode)
            mode_group.setLayout(mode_layout)
            layout.addWidget(mode_group)
        
            # 显示锁定的人脸图片
            scroll = QScrollArea()
            scroll_widget = QWidget()
            grid = QGridLayout()
            self.face_radios = []
            self.face_checks = []
            
            # 按检测置信度降序排序
            sorted_faces = sorted(
                self.locked_faces.items(),
                key=lambda x: x[1]["det_score"],
                reverse=True
            )
            
            row, col = 0, 0
            sorted_faces = sorted(
                self.locked_faces.items(),
                key=lambda x: x[1]["det_score"],  # 按检测置信度排序
                reverse=True
            )

            # 修改单选按钮组处理
            self.face_button_group = QButtonGroup()  # 添加按钮组管理单选
            for idx, (face_id, face_data) in enumerate(sorted_faces):
                # 转换OpenCV图像为QPixmap
                img = face_data["image"]
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                h, w, ch = img.shape
                bytes_per_line = ch * w
                q_img = QImage(img.data, w, h, bytes_per_line, QImage.Format_RGB888)
                pixmap = QPixmap.fromImage(q_img).scaled(200, 200, Qt.KeepAspectRatio)
                
                # 创建带图片的单选按钮
                group = QGroupBox()
                vbox = QVBoxLayout()
                
                label = QLabel()
                label.setPixmap(pixmap)
                label.setAlignment(Qt.AlignCenter)
                vbox.addWidget(label)
                
                # 添加边框显示选中状态
                group.setStyleSheet("QGroupBox { border: 2px solid gray; }")
                
                # 单选按钮
                radio = QRadioButton(f"人脸 {idx+1} (置信度: {face_data['det_score']:.2f})")
                radio.setChecked(idx == 0)
                radio.face_id = face_id
                radio.face_data = face_data
                self.face_button_group.addButton(radio, idx)  # 添加到按钮组
                self.face_radios.append(radio)

                # 多选复选框
                check = QCheckBox(f"选择人脸 {idx+1}")
                check.setChecked(False)
                check.face_id = face_id
                check.face_data = face_data
                self.face_checks.append(check)
                
                # 连接调试输出信号
                radio.toggled.connect(lambda checked, idx=idx: print(f"Radio {idx+1} clicked: {checked}"))
                check.stateChanged.connect(lambda state, idx=idx: print(f"Checkbox {idx+1} state: {state}"))
                self.single_mode.toggled.connect(self.update_selection_mode)
                
                # 根据模式显示不同控件
                radio.setVisible(self.single_mode.isChecked())
                check.setVisible(not self.single_mode.isChecked())
                vbox.addWidget(radio)
                vbox.addWidget(check)
                
                group.setLayout(vbox)
                grid.addWidget(group, row, col)
                
                col += 1
                if col > 3: 
                    col = 0
                    row += 1
            
            # 连接模式切换信号
            def update_mode():
                single_mode = self.single_mode.isChecked()
                for radio, check in zip(self.face_radios, self.face_checks):
                    radio.setVisible(single_mode)
                    check.setVisible(not single_mode)
            
            self.single_mode.toggled.connect(update_mode)
            

            scroll_widget.setLayout(grid)
            scroll.setWidget(scroll_widget)
            layout.addWidget(scroll)
            
            # 添加姓名输入框
            name_layout = QHBoxLayout()
            name_layout.addWidget(QLabel("姓名:"))
            self.name_edit = QLineEdit()
            name_layout.addWidget(self.name_edit)
            layout.addLayout(name_layout)
            
            # 添加按钮
            btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btn_box.accepted.connect(dialog.accept)
            btn_box.rejected.connect(dialog.reject)
            layout.addWidget(btn_box)
            
            dialog.setLayout(layout)
            
            if dialog.exec_() == QDialog.Accepted:
                if self.single_mode.isChecked():
                    # 获取选中的face_data
                    selected_face_data = None
                    for radio in self.face_radios:
                        if radio.isChecked():
                            selected_face_data = radio.face_data
                            break
                    
                    if not selected_face_data:
                        QMessageBox.warning(self, "警告", "请选择人脸")
                        return
                    
                    name = self.name_edit.text()
                    if not name:
                        QMessageBox.warning(self, "警告", "请输入姓名")
                        return
                    
                    self.add_single_face(name, selected_face_data)
                else:
                    # 多选模式处理
                    selected_faces = []
                    for check in self.face_checks:
                        if check.isChecked():
                            selected_faces.append((check.face_id, check.face_data))
                    
                    if not selected_faces:
                        QMessageBox.warning(self, "警告", "请选择至少一个人脸")
                        return
                        
                    # 批量添加对话框
                    batch_dialog = QDialog(self)
                    batch_dialog.setWindowTitle("批量添加人脸")
                    batch_layout = QVBoxLayout()
                    
                    batch_layout.addWidget(QLabel(f"已选择 {len(selected_faces)} 个人脸，请输入命名模式:"))
                    
                    prefix_layout = QHBoxLayout()
                    prefix_layout.addWidget(QLabel("前缀:"))
                    prefix_edit = QLineEdit("人员_")
                    prefix_layout.addWidget(prefix_edit)
                    batch_layout.addLayout(prefix_layout)
                    
                    start_num_layout = QHBoxLayout()
                    start_num_layout.addWidget(QLabel("起始编号:"))
                    start_num_edit = QSpinBox()
                    start_num_edit.setRange(1, 9999)
                    start_num_edit.setValue(1)
                    start_num_layout.addWidget(start_num_edit)
                    batch_layout.addLayout(start_num_layout)
                    
                    btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
                    btn_box.accepted.connect(batch_dialog.accept)
                    btn_box.rejected.connect(batch_dialog.reject)
                    batch_layout.addWidget(btn_box)
                    
                    batch_dialog.setLayout(batch_layout)
                    
                    if batch_dialog.exec_() == QDialog.Accepted:
                        prefix = prefix_edit.text().strip()
                        start_num = start_num_edit.value()
                        
                        for i, (face_id, face_data) in enumerate(selected_faces):
                            name = f"{prefix}{start_num + i}"
                            self.add_single_face(name, face_data)
        except Exception as e:
            self.log_message(f"❌ 添加新人脸失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"添加新人脸失败: {str(e)}")



    def add_single_face(self, name, face_data):
        """添加单个人脸到数据库"""
        print(f"[DEBUG] 3083保存人脸数据校验 -> name: {name}, bbox: {face_data['bbox']}, score: {face_data['det_score']}")
        """添加单个人脸到数据库（使用锁定的人脸数据）"""
        try:
            os.makedirs("faces", exist_ok=True)
            
            # 文件名规范化
            def sanitize_filename(name):
                py_name = pinyin.get(name, format="strip", delimiter="_")
                return re.sub(r'[^\w]', '', py_name)
            
            safe_name = sanitize_filename(name)
            confidence = int(face_data["det_score"] * 100)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-4]
            img_path = f"faces/{safe_name}_{confidence}%_{timestamp}.jpg"
            
            # 保存人脸图像
            cv2.imwrite(img_path, face_data["image"])

            # 添加到数据库
            self.face_db.add_face(
                name, 
                face_data["embedding"], 
                img_path,
                confidence=face_data["det_score"]
            )
            
            print(f"[DEBUG] 3109添加人脸数据校验 -> 添加了 {name} 人脸")
            self.log_message(f"✅ 添加人脸: {name} (置信度: {face_data['det_score']:.2f})")
            self.progress_bar.setValue((self.progress_bar.value() + 10) % 100)
        except Exception as e:
            self.log_message(f"❌ 添加单个人脸失败: {str(e)}")
            raise

    def add_multiple_faces(self, faces_data):
        """批量添加人脸到数据库（使用锁定的人脸数据）"""
        try:
            total = len(faces_data)
            progress_dialog = QProgressDialog("添加人脸...", "取消", 0, total, self)
            progress_dialog.setWindowTitle("批量添加人脸")
            progress_dialog.setWindowModality(Qt.WindowModal)
            
            for i, (_, face_data) in enumerate(faces_data):
                progress_dialog.setValue(i)
                progress_dialog.setLabelText(f"正在添加第 {i+1}/{total} 个人脸...")
                QApplication.processEvents()
                
                if progress_dialog.wasCanceled():
                    self.log_message("⚠️ 用户取消了批量添加")
                    return
                
                name, ok = QInputDialog.getText(
                    self, f"添加人脸 {i+1}/{total}", 
                    f"请输入第 {i+1} 个人脸的姓名:",
                    QLineEdit.Normal,
                    ""
                )
                if not ok or not name:
                    continue
                
                self.add_single_face(name, face_data)
        
            progress_dialog.close()
            print(f"[DEBUG] 3145添加人脸数据校验 -> 添加了 {total} 个人脸")
            QMessageBox.information(self, "完成", f"成功添加 {len(faces_data)} 个人脸")
        except Exception as e:
            self.log_message(f"❌ 批量添加人脸失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"批量添加人脸失败: {str(e)}") 

    def view_face_database(self):
        """查看和管理人脸数据库"""
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("人脸库管理")
            dialog.resize(1200, 800)  # 增大对话框尺寸以容纳图片

            layout = QVBoxLayout()
            
            # 使用分割器实现左右布局
            splitter = QSplitter(Qt.Horizontal)
            
            # 左侧表格区域
            table_widget = QWidget()
            table_layout = QVBoxLayout()

            # 添加搜索和排序控件
            search_sort_layout = QHBoxLayout()
            
            # 搜索框
            self.search_edit = QLineEdit()
            self.search_edit.setPlaceholderText("输入姓名搜索...")
            search_sort_layout.addWidget(self.search_edit)
            
            # 排序下拉框
            self.sort_combo = QComboBox()
            self.sort_combo.addItems(["按姓名", "按ID", "按添加时间", "按最后访问"])
            search_sort_layout.addWidget(self.sort_combo)
            
            # 排序方向
            self.sort_direction = QCheckBox("升序")
            self.sort_direction.setChecked(True)
            search_sort_layout.addWidget(self.sort_direction)
            
            # 搜索按钮
            btn_search = QPushButton("搜索/排序")
            search_sort_layout.addWidget(btn_search)
            
            table_layout.addLayout(search_sort_layout)
            
            table = QTableWidget()
            table.setColumnCount(5)  # 增加一列用于显示图片
            table.setHorizontalHeaderLabels(["ID", "姓名", "照片路径", "添加时间", "预览"])
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
            table.setColumnWidth(0, 60)   # ID列
            table.setColumnWidth(1, 150)  # 姓名列
            table.setColumnWidth(2, 300)  # 照片路径列
            table.setColumnWidth(3, 150)  # 时间列
            table.setColumnWidth(4, 200)  # 预览列
            
            table.setSortingEnabled(True)  # 启用排序
            # 自定义表头点击事件
            header = table.horizontalHeader()
            header.setSectionsClickable(True)
            header.sectionClicked.connect(self.log_sort_action)  # 点击时记录日志
            # 设置排序指示器样式
            table.setStyleSheet("""
                QHeaderView::section {
                    background-color: #f0f0f0;
                    padding: 5px;
                    border: 1px solid #d0d0d0;
                }
                QHeaderView::section:checked {
                    background-color: #d0e3ff;
                }
            """)


            try:
                faces = self.face_db.get_all_faces()
                table.setRowCount(len(faces))
            
                for row, (face_id, name, img_path, create_time) in enumerate(faces):
                    table.setItem(row, 0, QTableWidgetItem(str(face_id)))
                    table.setItem(row, 1, QTableWidgetItem(name))
                    table.setItem(row, 2, QTableWidgetItem(img_path))
                    table.setItem(row, 3, QTableWidgetItem(create_time))
                    
                    # 在第五列显示图片预览
                    preview_item = QTableWidgetItem()
                    if img_path != '无图片' and os.path.exists(img_path):
                        # 使用相对路径显示（去掉faces/前缀）
                        display_path = os.path.relpath(img_path, start="faces")
                        table.setItem(row, 2, QTableWidgetItem(display_path))  # 更新路径显示
                        
                        # 加载图片预览
                        try:
                            pixmap = QPixmap(img_path).scaled(180, 180, Qt.KeepAspectRatio)
                            preview_item.setData(Qt.DecorationRole, pixmap)
                        except Exception as e:
                            print(f"加载图片失败: {img_path}, 错误: {str(e)}")
                            preview_item.setText("图片加载失败")
                    
                    table.setItem(row, 4, preview_item)  # 第5列显示预览

                    # 设置单元格可编辑（姓名和照片路径）
                    table.item(row, 1).setFlags(table.item(row, 1).flags() | Qt.ItemIsEditable)
                    table.item(row, 2).setFlags(table.item(row, 2).flags() | Qt.ItemIsEditable)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"数据库查询失败: {str(e)}")
                return
            
            table_layout.addWidget(table)
            table_widget.setLayout(table_layout)
            
            # 右侧大图预览区域
            preview_widget = QWidget()
            preview_layout = QVBoxLayout()
            
            self.preview_label = QLabel()
            self.preview_label.setAlignment(Qt.AlignCenter)
            self.preview_label.setStyleSheet("border: 1px solid gray;")
            self.preview_label.setFixedSize(300, 300)
            self.preview_label.setText("点击左侧行预览图片")
            
            # 当前选中人脸的详细信息
            self.detail_label = QLabel()
            self.detail_label.setWordWrap(True)
            
            preview_layout.addWidget(QLabel("图片预览:"))
            preview_layout.addWidget(self.preview_label, 0, Qt.AlignCenter)
            preview_layout.addWidget(QLabel("详细信息:"))
            preview_layout.addWidget(self.detail_label)
            preview_layout.addStretch()
            preview_widget.setLayout(preview_layout)
            
            # 连接表格选择变化信号
            table.itemSelectionChanged.connect(lambda: self.update_face_preview(table))
            
            # 添加到分割器
            splitter.addWidget(table_widget)
            splitter.addWidget(preview_widget)
            splitter.setSizes([800, 400])  # 设置左右比例
            
            # 按钮区域
            btn_box = QDialogButtonBox()
            btn_save = btn_box.addButton("保存修改", QDialogButtonBox.ActionRole)
            btn_delete = btn_box.addButton("删除选中", QDialogButtonBox.ActionRole)
            btn_export = btn_box.addButton("导出数据", QDialogButtonBox.ActionRole)
            btn_close = btn_box.addButton("关闭", QDialogButtonBox.RejectRole)
            
            btn_save.clicked.connect(lambda: self.save_face_changes(table))
            btn_delete.clicked.connect(lambda: self.delete_selected_face(table))
            btn_export.clicked.connect(self.export_data)
            btn_close.clicked.connect(dialog.close)
            
            layout.addWidget(splitter)
            layout.addWidget(btn_box)

            # 连接信号
            btn_search.clicked.connect(lambda: self.update_face_table(table))
            self.search_edit.returnPressed.connect(lambda: self.update_face_table(table))
            
            # 初始加载数据
            self.update_face_table(table)

            dialog.setLayout(layout)
            dialog.exec_()
        except Exception as e:
            self.log_message(f"❌ 查看人脸库失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"查看人脸库失败: {str(e)}")

    def update_face_table(self, table):
        """更新表格数据(根据搜索和排序条件)"""
        keyword = self.search_edit.text().strip()
        
        if keyword:
            # 执行搜索
            faces = self.face_db.search_faces_by_name(keyword)
        else:
            # 执行排序
            sort_map = {
                "按姓名": "name",
                "按ID": "id", 
                "按添加时间": "create_time",
                "按最后访问": "last_access_time"
            }
            sort_by = sort_map.get(self.sort_combo.currentText(), "name")
            ascending = self.sort_direction.isChecked()
            faces = self.face_db.get_faces_sorted(sort_by, ascending)
        
        table.setRowCount(len(faces))
        
        for row, (face_id, name, img_path, create_time) in enumerate(faces):
            table.setItem(row, 0, QTableWidgetItem(str(face_id)))
            table.setItem(row, 1, QTableWidgetItem(name))
            table.setItem(row, 2, QTableWidgetItem(img_path))
            table.setItem(row, 3, QTableWidgetItem(create_time))
            
            # 更新图片预览
            preview_item = QTableWidgetItem()
            if img_path != '无图片' and os.path.exists(img_path):
                pixmap = QPixmap(img_path).scaled(180, 180, Qt.KeepAspectRatio)
                preview_item.setData(Qt.DecorationRole, pixmap)
            table.setItem(row, 4, preview_item)


    def update_face_preview(self, table):
        """更新右侧预览区域的图片和详细信息"""
        selected = table.currentRow()
        if selected >= 0:
            img_path = table.item(selected, 2).text()
            face_id = table.item(selected, 0).text()
            name = table.item(selected, 1).text()
            create_time = table.item(selected, 3).text()
            
            # 更新详细信息
            details = f"""
            ID: {face_id}
            姓名: {name}
            路径: {img_path}
            添加时间: {create_time}
            """
            self.detail_label.setText(details)
            
            # 更新图片预览
            if img_path != '无图片' and os.path.exists(img_path):
                pixmap = QPixmap(img_path).scaled(
                    self.preview_label.size(), 
                    Qt.KeepAspectRatio, 
                    Qt.SmoothTransformation
                )
                self.preview_label.setPixmap(pixmap)
            else:
                self.preview_label.setText("无有效图片")

    def delete_selected_face(self, table):
        """删除选中的人脸记录"""
        try:
            selected = table.currentRow()
            if selected >= 0:
                face_id = int(table.item(selected, 0).text())
                reply = QMessageBox.question(
                    self, '确认删除', 
                    '确定要删除这条记录吗？对应的图片文件也将被删除',
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    try:
                        self.face_db.delete_face(face_id)
                        table.removeRow(selected)
                        print("[DEBUG] ⚡ 删除成功")
                        # QMessageBox.information(self, "成功", "删除完成！")
                    except Exception as e:
                        QMessageBox.critical(self, "错误", f"删除失败: {str(e)}")
                        raise
        except Exception as e:
            self.log_message(f"❌ 删除选中人脸失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"删除人脸失败: {str(e)}")

    def export_data(self):
        """导出数据到文件"""
        try:
            options = QFileDialog.Options()
            file_name, selected_filter = QFileDialog.getSaveFileName(
                self, "导出数据", "", "JSON文件 (*.json);;CSV文件 (*.csv)", options=options)
        
            if not file_name:
                return
        
            faces = self.face_db.get_all_faces()
        
            if selected_filter == "JSON文件 (*.json)":
                if not file_name.endswith('.json'):
                    file_name += '.json'
            
                if self.face_db.export_to_json(file_name):
                    is_valid, msg = self.face_db.validate_json(file_name)
                    if is_valid:
                        QMessageBox.information(self, "导出成功", 
                            f"数据已完整导出到:\n{file_name}\n验证结果: {msg}")
                    else:
                        QMessageBox.warning(self, "验证警告", 
                            f"导出完成但验证失败:\n{msg}")
                else:
                    QMessageBox.critical(self, "导出失败", "导出JSON过程中发生错误")
        
            elif selected_filter == "CSV文件 (*.csv)":
                if not file_name.endswith('.csv'):
                    file_name += '.csv'
            
                import csv
                with open(file_name, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['ID', '姓名', '图片路径', '创建时间'])
                    writer.writerows(faces)
        
            self.log_message(f"✅ 成功导出数据到: {file_name}")
            QMessageBox.information(self, "成功", f"数据已成功导出到:\n{file_name}")
    
        except Exception as e:
            self.log_message(f"❌ 导出失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")



    def on_face_selection_changed(self, checked, index):
        """处理人脸单选按钮变化"""
        if checked:
            face_data = self.face_radios[index].face_data
            # 更新选中状态样式
            self.face_radios[index].parent().parent().setStyleSheet(
                "QGroupBox { border: 2px solid green; }")
        else:
            # 恢复默认样式
            self.face_radios[index].parent().parent().setStyleSheet(
                "QGroupBox { border: 2px solid gray; }")

    def on_face_check_changed(self, state, index):
        """处理人脸复选框变化"""
        if state == Qt.Checked:
            # 更新选中状态样式
            self.face_checks[index].parent().parent().setStyleSheet(
                "QGroupBox { border: 2px solid blue; }")
        else:
            # 恢复默认样式
            self.face_checks[index].parent().parent().setStyleSheet(
                "QGroupBox { border: 2px solid gray; }")

    def on_face_radio_clicked(self, checked, index):
        """处理人脸单选框点击事件"""
        if checked:
            print(f"[DEBUG] 3450用户选择了第 {index+1} 个人脸")
            face_data = self.face_radios[index].face_data
            print(f"[DEBUG] 3452人脸详细信息 - 检测置信度: {face_data['det_score']:.2f}, 坐标: {face_data['bbox']}")

    # 说明：v2.0.0 删除了这里原有的 def on_performance_mode_changed(self, text)。
    # 它与上面处理复选框的同名方法签名冲突（后定义者覆盖先定义者），
    # 会让"低性能"复选框误走下拉框逻辑。现已拆分重命名为
    # on_performance_mode_text_changed（见 getattr 处理器区域）。

    def auto_adjust_performance(self):
        """自动调整性能参数"""
        if self.config.get('performance_mode') != 'auto':
            return
            
        # 获取系统负载信息
        mem = psutil.virtual_memory().percent
        cpu = psutil.cpu_percent()
        
        # 根据负载决定是否启用低性能模式
        new_low_perf = mem > 80 or cpu > 80
        
        if new_low_perf != self.low_performance_mode:
            self.low_performance_mode = new_low_perf
            self.low_perf_check.setChecked(new_low_perf)
            status = "低性能" if new_low_perf else "正常性能"
            self.log_message(f"⚠️ 自动切换至{status}模式 (内存:{mem}% CPU:{cpu}%)")
            
            # 更新参数
            if new_low_perf:
                self.detect_interval_spin.setValue(8)
                self.roi_thresh_slider.setValue(15)
                self.min_roi_spin.setValue(800)
                self.preprocess_check.setChecked(True)
            else:
                self.detect_interval_spin.setValue(5)
                self.roi_thresh_slider.setValue(10)
                self.min_roi_spin.setValue(500)


    def update_selection_mode(self, is_single):
        """更新选择模式（单选/多选）"""
        for radio in self.face_radios:
            radio.setVisible(is_single)
            radio.setChecked(False)  # 清除单选状态
        
        for check in self.face_checks:
            check.setVisible(not is_single)
            check.setChecked(False)  # 清除多选状态
        
        # 初始选中第一个
        if is_single and self.face_radios:
            self.face_radios[0].setChecked(True)

    def update_cpu_usage(self):
        """更新CPU使用率显示，每1%一种颜色"""
        try:
            cpu_percent = psutil.cpu_percent()
            self.cpu_label.setText(f"CPU: {cpu_percent}%")
            
            # 定义1%间隔的颜色映射 (从绿色到红色的渐变)
            hue = (100 - cpu_percent) * 1.2 / 360  # 将百分比转换为色相 (0-120°)
            color = QColor()
            color.setHsvF(hue, 1.0, 1.0)  # HSV色彩空间，固定饱和度和亮度
            
            self.cpu_label.setStyleSheet(
                f"{self.default_stylesheet} color: {color.name()}; font-weight: bold;"
            )
        except Exception as e:
            print(f"更新CPU使用率失败: {str(e)}")



        def interpolate_color(self, hex1, hex2, ratio):
            """十六进制颜色插值"""
            r1, g1, b1 = int(hex1[1:3], 16), int(hex1[3:5], 16), int(hex1[5:7], 16)
            r2, g2, b2 = int(hex2[1:3], 16), int(hex2[3:5], 16), int(hex2[5:7], 16)
            r = int(r1 + (r2 - r1) * ratio)
            g = int(g1 + (g2 - g1) * ratio)
            b = int(b1 + (b2 - b1) * ratio)
            return f"#{r:02X}{g:02X}{b:02X}"


    def update_fps(self):
        """更新FPS/检测耗时显示（v2.1.0：加上加速后端与检测耗时，便于判断瓶颈）"""
        try:
            fps = self.fps_counter
            worker = getattr(self, 'detect_worker', None)
            busy = bool(worker and worker.busy)
            queue_hint = " ·" if busy else ""
            self.fps_label.setText(f"FPS: {fps}{queue_hint}")
            self.fps_label.setToolTip(
                f"每秒刷新帧数（末尾 · 表示检测线程正忙，本帧已丢给下一轮）\n"
                f"检测线程已处理: {getattr(worker, 'processed', 0)} 帧\n"
                f"因线程忙丢弃: {getattr(worker, 'dropped', 0)} 帧")
            
            # 定义FPS颜色映射 (假设最大FPS为60)
            max_fps = 60
            normalized_fps = min(fps, max_fps) / max_fps  # 归一化到0-1
            hue = normalized_fps * 0.4  # 使用0-0.4的色相范围 (绿色到蓝色)
            color = QColor()
            color.setHsvF(hue, 1.0, 1.0)
            
            self.fps_label.setStyleSheet(
                f"{self.default_stylesheet} color: {color.name()}; font-weight: bold;"
            )

            # 性能面板：检测耗时（超过 120ms 标红，提示可能存在卡顿）
            if hasattr(self, 'detect_ms_label'):
                ms = float(getattr(self, 'last_detect_ms', 0.0))
                dropped = int(getattr(worker, 'dropped', 0) or 0)
                self.detect_ms_label.setText(f"检测: {ms:.0f}ms" if ms else "检测: -")
                tip = (f"最近一次「检测+检索」耗时 {ms:.0f}ms\n"
                       f"累计丢帧 {dropped}\n"
                       f"加速后端: {self.get_active_backend_label()}\n"
                       f"提示：>120ms 说明单核/CPU 推理吃力，"
                       f"可降低检测尺寸、加大检测间隔或改用低性能模式")
                self.detect_ms_label.setToolTip(tip)
                if ms > 120:
                    self.detect_ms_label.setStyleSheet(
                        self.default_stylesheet + " color: #d02020; font-weight: bold;"
                        " qproperty-alignment: AlignCenter;")
                else:
                    self.detect_ms_label.setStyleSheet(
                        self.default_stylesheet + " color: #20a020; font-weight: bold;"
                        " qproperty-alignment: AlignCenter;")
                if hasattr(self, 'accel_label'):
                    self.accel_label.setToolTip(
                        f"实际后端: {self.get_active_backend_label()}\n"
                        f"provider: {', '.join((self.accel_info or {}).get('active_providers') or []) or '未记录'}")
            
            self.fps_counter = 0  # 重置计数器
        except Exception as e:
            print(f"更新FPS失败: {str(e)}")

    def toggle_debug_mode(self, state):
        """切换调试模式（实时保存 + 立即切换全局打印开关）"""
        debug_mode = (state == Qt.Checked)
        # 设置全局打印开关
        global DEBUG_PRINT
        DEBUG_PRINT = debug_mode
        if getattr(self, '_restoring_ui', False):
            return
        self.config.set('debug_mode', debug_mode)
        status = "开启" if debug_mode else "关闭"
        self.log_message(f"🛠️ 调试模式{status}")


    def toggle_color_display(self, state):
        """切换彩色/灰度显示模式（实时保存 + 立即刷新）"""
        enable_color = (state == Qt.Checked)
        if getattr(self, '_restoring_ui', False):
            return
        # 更新配置
        self.config.set('enable_color', enable_color)
        
        # 根据新状态更新UI显示
        status = "彩色" if enable_color else "黑白"
        self.log_message(f"🛠️ 图像显示模式设置为: {status}")
        
        # 强制刷新当前显示（使用新的颜色模式）
        # v2.0.0：删除了这里紧跟的一段"再次转灰度 + 再次 setPixmap"的重复代码，
        # display_image_with_ratio 已经根据 enable_color 重新编码并显示，重复处理会二次降质。
        if getattr(self, 'last_frame', None) is not None:
            self.display_image_with_ratio(self.last_frame)

    def _apply_preprocessing(self, img):
        """应用图像预处理"""

        if img is None or img.size == 0:
            return img

        try:
            # 确保是3通道图像
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                
            # 调整尺寸
            if self.enable_preprocess and (self.low_performance_mode or img.shape[1] > 1280):
                h, w = img.shape[:2]
                scale = 1280 / max(h, w)
                new_h, new_w = int(h * scale), int(w * scale)
                img = cv2.resize(img, (new_w, new_h))
                
                # CLAHE处理
                lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
                l = clahe.apply(l)
                lab = cv2.merge((l, a, b))
                img = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
                
            return img
        except Exception as e:
            self.log_message(f"❌ 预处理失败: {str(e)}")
            return img
        # v2.0.0：此处原有约 40 行"永远执行不到"的重复实现（第一个 return 之后），
        # 属于历史遗留的死代码，已删除，避免后续维护时误改到无效分支。

    def closeEvent(self, event):
        """关闭应用程序时的清理工作

        v2.0.0 关键修复（需求6）：
          旧版本 closeEvent 里完全没有保存配置，也从不保存窗口几何信息
          （唯一的 saveGeometry 写在 DatasetManager.closeEvent 里，而那个类没有
          self.config，实际抛异常被吞掉）。结果：窗口大小/位置、最后的设置全部丢失。
          现在关闭前会把运行期状态统一写回 config.json。
        """
        try:
            # ---------- 1. 停止所有线程和定时器 ----------
            if hasattr(self, 'timer') and self.timer.isActive():
                self.timer.stop()
                
            if hasattr(self, 'downloader') and self.downloader.isRunning():
                self.downloader.terminate()
                
            if hasattr(self, 'memory_monitor') and self.memory_monitor.isRunning():
                self.memory_monitor.stop()
                self.memory_monitor.wait()
                
            if hasattr(self, 'unknown_faces_cleanup_timer') and self.unknown_faces_cleanup_timer.isActive():
                self.unknown_faces_cleanup_timer.stop()

            if hasattr(self, 'cpu_monitor') and self.cpu_monitor.isActive():
                self.cpu_monitor.stop()

            if hasattr(self, 'fps_timer') and self.fps_timer.isActive():
                self.fps_timer.stop()

            # 停止检测工作线程（v2.1.0：必须在释放 face_app 之前停，否则线程会用到空模型）
            self._stop_detect_worker()

            # ---------- 2. 保存设置（实时保存的兜底，确保一个都不丢） ----------
            try:
                updates = {
                    'window_geometry': self.saveGeometry().data().hex(),
                    'model_name': self.model_name,
                    'det_thresh': self.thresh_slider.value() if hasattr(self, 'thresh_slider') else self.config.get('det_thresh'),
                    'det_interval': self.detection_interval,
                    'det_size': f"{self.det_size[0]}x{self.det_size[1]}",
                    'low_performance_mode': bool(self.low_performance_mode),
                    'detect_interval': self.detect_interval,
                    'roi_threshold': self.roi_threshold,
                    'min_roi_area': self.min_roi_area,
                    'enable_preprocess': bool(self.enable_preprocess),
                    'max_display': self.max_display,
                    'enable_color': bool(self.config.get('enable_color', True)),
                    'show_detect_box': bool(self.config.get('show_detect_box', True)),
                    'auto_save_unknown': bool(self.config.get('auto_save_unknown', False)),
                    'performance_mode': self.config.get('performance_mode', 'auto'),
                    'debug_mode': bool(self.config.get('debug_mode', False)),
                }
                if hasattr(self, 'window_combo') and self.window_combo.currentText():
                    updates['last_window'] = self.window_combo.currentText()
                if getattr(self, 'proxy_settings', None):
                    updates['proxy_settings'] = self.proxy_settings
                self.config.update(**updates)
                self.config.save_config()
                debug_print(f"退出前已保存配置: {self.config.config_file}")
            except Exception as e:
                print(f"❌ 退出前保存配置失败: {str(e)}")

            # ---------- 3. 释放资源 ----------
            if hasattr(self, 'face_app'):
                self.face_app = None
                
            if hasattr(self, 'face_db') and getattr(self.face_db, 'conn', None):
                self.face_db.conn.close()
                
            # 清空缓存
            self.face_cache.clear()
            self.font_cache.clear()
            
            self.log_message("🚀 应用程序正常退出，设置已保存")
        except Exception as e:
            self.log_message(f"❌ 关闭应用程序时出错: {str(e)}")
        finally:
            event.accept()

    def resizeEvent(self, event):
        """窗口大小变化时重新调整图像显示"""
        if hasattr(self, 'current_pixmap') and self.current_pixmap:
            label_size = self.display_label.size()
            scaled_pixmap = self.current_pixmap.scaled(
                label_size, 
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            )
            self.display_label.setPixmap(scaled_pixmap)
        super().resizeEvent(event)

    # 说明：v2.0.0 删除了此处重复定义的 def export_data(self)。
    # 它只有"JSON 导出"分支，且定义在文件末尾，会覆盖前面功能完整的同名方法
    # （QFileDialog.Options + JSON/CSV 双格式 + 结果校验），导致 CSV 导出永远不可用。
    # 现在统一使用前面的 export_data（约 5251 行）。


if __name__ == "__main__":
    app = None
    try:
        app = QApplication(sys.argv)
        window = FaceRecognitionApp()
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        print(f"❌ 应用程序启动失败: {str(e)}")
        traceback.print_exc()
        raise