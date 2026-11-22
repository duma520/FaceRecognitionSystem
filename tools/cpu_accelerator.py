"""
高级 CPU 加速计算插件框架 - 完整版
版本: 2.2
作者: 杜玛
"""
import os
import sys

try:
    import cpuinfo
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "py-cpuinfo"])
    import cpuinfo
import time
import inspect
import logging
import platform
import multiprocessing
import threading
import hashlib
import pickle
import json
import warnings
import traceback
import signal
import ctypes
import functools
from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import (Any, Callable, Dict, List, Optional, Tuple, Union, 
                   TypeVar, Generic, Sequence, Iterable, Set, Type)
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from concurrent.futures import (ThreadPoolExecutor, ProcessPoolExecutor, 
                               as_completed, Future)
from collections import defaultdict, deque
from weakref import WeakValueDictionary

import numpy as np
from numba import jit, njit, prange, vectorize, guvectorize, cfunc
import psutil
import logging
from typing import Optional
import cpuinfo
from diskcache import Cache
import zstandard as zstd

# 尝试导入GUI相关库
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog, scrolledtext
    from tkinter.font import Font
    from PIL import Image, ImageTk
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

# 类型变量
T = TypeVar('T')
R = TypeVar('R')
FuncType = Callable[..., Any]

# 日志配置
class ColoredFormatter(logging.Formatter):
    """带颜色的日志格式化器"""
    COLORS = {
        'DEBUG': '\033[36m',    # 青色
        'INFO': '\033[32m',     # 绿色
        'WARNING': '\033[33m',  # 黄色
        'ERROR': '\033[31m',    # 红色
        'CRITICAL': '\033[1;31m', # 红色加粗
        'RESET': '\033[0m'      # 重置颜色
    }

    def format(self, record):
        levelname = record.levelname
        message = super().format(record)
        if levelname in self.COLORS:
            message = f"{self.COLORS[levelname]}{message}{self.COLORS['RESET']}"
        return message

def _project_root() -> str:
    """项目根目录（本文件位于 tools\\ 子目录下）"""
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    # 兼容"本文件被复制到项目根目录"的历史用法
    if os.path.basename(here).lower() == 'tools':
        return parent
    return here


def _default_log_path() -> str:
    d = os.path.join(_project_root(), 'logs')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'cpu_accelerator.log')


def _default_cache_dir() -> str:
    d = os.path.join(_project_root(), 'tools', 'cpu_accelerator_cache')
    os.makedirs(d, exist_ok=True)
    return d


def setup_logging(log_file: str = None, level: int = logging.INFO):
    """配置日志系统（v2.0.0：默认写入 <项目根>\logs\cpu_accelerator.log）"""
    if log_file is None:
        log_file = _default_log_path()
    logger = logging.getLogger('CPUAccelerator')
    logger.setLevel(level)
    
    # 文件处理器
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # 控制台处理器
    if sys.stderr and sys.stderr.isatty():
        console_handler = logging.StreamHandler()
        console_formatter = ColoredFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()

# 异常类
class CPUAcceleratorError(Exception):
    """基础异常类"""
    pass

class MemoryLimitExceededError(CPUAcceleratorError):
    """内存超出限制异常"""
    pass

class TimeoutError(CPUAcceleratorError):
    """超时异常"""
    pass

class ConfigurationError(CPUAcceleratorError):
    """配置错误"""
    pass

class AccelerationError(CPUAcceleratorError):
    """加速错误"""
    pass

# 枚举类型
class AccelerationMethod(Enum):
    """加速方法枚举"""
    NUMBA_JIT = auto()
    NUMBA_NJIT = auto()
    NUMBA_PARALLEL = auto()
    MULTIPROCESSING = auto()
    THREADING = auto()
    VECTORIZE = auto()
    GUVECTORIZE = auto()
    CFUNC = auto()
    CYTHON = auto()  # 预留
    PYPY = auto()    # 预留

class TaskPriority(Enum):
    """任务优先级枚举"""
    HIGH = 0
    NORMAL = 1
    LOW = 2

class CachePolicy(Enum):
    """缓存策略枚举"""
    LRU = auto()     # 最近最少使用
    LFU = auto()     # 最不经常使用
    FIFO = auto()    # 先进先出
    TIMED = auto()   # 基于时间

# 配置类
@dataclass
class SystemInfo:
    """系统信息类"""
    cpu_count: int
    cpu_physical_cores: int
    cpu_logical_cores: int
    cpu_usage: float
    cpu_freq: Dict[str, float]
    cpu_name: str
    memory_total: float
    memory_available: float
    memory_used: float
    memory_percent: float
    swap_total: float
    swap_used: float
    swap_percent: float
    platform: str
    python_version: str
    architecture: str

@dataclass
class PluginConfig:
    """插件配置类"""
    # 性能配置
    max_threads: int = field(default_factory=lambda: max(1, multiprocessing.cpu_count() - 1))
    max_processes: int = field(default_factory=lambda: max(1, multiprocessing.cpu_count() - 1))
    memory_limit: float = 0.8  # 最大内存使用比例
    cpu_limit: float = 0.9     # 最大CPU使用比例
    
    # 加速配置
    default_acceleration: AccelerationMethod = AccelerationMethod.NUMBA_NJIT
    auto_parallel: bool = True
    auto_vectorize: bool = True
    prefer_simd: bool = True
    
    # 缓存配置
    cache_enabled: bool = True
    cache_dir: str = field(default_factory=_default_cache_dir)
    cache_size_limit: int = 1024  # MB
    cache_policy: CachePolicy = CachePolicy.LRU
    cache_compress: bool = True
    cache_serializer: str = "pickle"  # pickle or json
    
    # 任务配置
    default_timeout: int = 300  # 默认超时时间(秒)
    task_priority: TaskPriority = TaskPriority.NORMAL
    enable_task_queue: bool = True
    max_queue_size: int = 1000
    
    # 错误处理
    fallback_to_python: bool = True
    suppress_warnings: bool = False
    log_level: int = logging.INFO
    
    # GUI配置
    gui_enabled: bool = GUI_AVAILABLE
    gui_language: str = "zh_CN" if GUI_AVAILABLE else "en"
    gui_theme: str = "clam"
    gui_font: str = "Microsoft YaHei" if platform.system() == "Windows" else "Arial"
    gui_font_size: int = 10
    
    # 高级配置
    enable_profiling: bool = False
    profile_dir: str = "./profiles"
    enable_benchmark: bool = False
    benchmark_iterations: int = 3
    enable_hardware_monitor: bool = True
    monitor_interval: float = 5.0  # 秒
    
    def __post_init__(self):
        """配置后处理"""
        if self.max_threads < 1:
            self.max_threads = 1
        if self.max_threads > (max_cpu := multiprocessing.cpu_count()):
            logger.warning(f"线程数超过CPU核心数({max_cpu}), 将设置为{max_cpu}")
            self.max_threads = max_cpu
            
        if self.max_processes < 1:
            self.max_processes = 1
        if self.max_processes > multiprocessing.cpu_count():
            self.max_processes = multiprocessing.cpu_count()
            
        if not 0 < self.memory_limit <= 1:
            raise ConfigurationError("内存限制必须在0到1之间")
            
        if not 0 < self.cpu_limit <= 1:
            raise ConfigurationError("CPU限制必须在0到1之间")
            
        if self.default_timeout < 0:
            raise ConfigurationError("超时时间必须为正数")
            
        if self.cache_serializer not in ("pickle", "json"):
            raise ConfigurationError("缓存序列化器必须是'pickle'或'json'")
            
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.profile_dir, exist_ok=True)

# 硬件监控器
class HardwareMonitor(threading.Thread):
    """硬件资源监控线程"""
    
    def __init__(self, interval: float = 5.0):
        super().__init__(daemon=True)
        self.interval = interval
        self._stop_event = threading.Event()
        self._stats = {
            'cpu': [],
            'memory': [],
            'timestamps': []
        }
        self._lock = threading.Lock()
        self.start()
    
    def run(self):
        """监控循环"""
        while not self._stop_event.is_set():
            try:
                cpu = psutil.cpu_percent(interval=0.1)
                mem = psutil.virtual_memory().percent
                
                with self._lock:
                    self._stats['cpu'].append(cpu)
                    self._stats['memory'].append(mem)
                    self._stats['timestamps'].append(time.time())
                    
                    # 保持最近100个记录
                    for key in self._stats:
                        if len(self._stats[key]) > 100:
                            self._stats[key] = self._stats[key][-100:]
                
                time.sleep(self.interval)
            except Exception as e:
                logger.error(f"硬件监控错误: {str(e)}")
                time.sleep(1)
    
    def stop(self):
        """停止监控"""
        self._stop_event.set()
    
    def get_stats(self, last_n: int = 10) -> Dict[str, List[float]]:
        """获取最近的监控数据"""
        with self._lock:
            return {
                'cpu': self._stats['cpu'][-last_n:],
                'memory': self._stats['memory'][-last_n:],
                'timestamps': self._stats['timestamps'][-last_n:]
            }
    
    def get_current_usage(self) -> Dict[str, float]:
        """获取当前资源使用情况"""
        with self._lock:
            if not self._stats['cpu']:
                return {'cpu': 0.0, 'memory': 0.0}
            return {
                'cpu': self._stats['cpu'][-1],
                'memory': self._stats['memory'][-1]
            }

# 缓存系统
class AcceleratorCache:
    """高级缓存系统"""
    
    def __init__(self, config: PluginConfig):
        self.config = config
        self._cache = Cache(
            directory=config.cache_dir,
            size_limit=config.cache_size_limit * 1024 * 1024,  # MB to bytes
            disk_min_file_size=0,
            eviction_policy=self._get_eviction_policy(config.cache_policy)
        )
        self._compressor = zstd.ZstdCompressor() if config.cache_compress else None
        self._decompressor = zstd.ZstdDecompressor() if config.cache_compress else None
        
    def _get_eviction_policy(self, policy: CachePolicy) -> str:
        """获取缓存淘汰策略"""
        return {
            CachePolicy.LRU: 'least-recently-used',
            CachePolicy.LFU: 'least-frequently-used',
            CachePolicy.FIFO: 'first-in-first-out',
            CachePolicy.TIMED: 'least-recently-used'  # diskcache不支持纯时间策略
        }[policy]
    
    def _serialize(self, data: Any) -> bytes:
        """序列化数据"""
        if self.config.cache_serializer == "pickle":
            serialized = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
        else:
            serialized = json.dumps(data).encode('utf-8')
        
        if self._compressor:
            return self._compressor.compress(serialized)
        return serialized
    
    def _deserialize(self, data: bytes) -> Any:
        """反序列化数据"""
        if self._decompressor:
            data = self._decompressor.decompress(data)
        
        if self.config.cache_serializer == "pickle":
            return pickle.loads(data)
        return json.loads(data.decode('utf-8'))
    
    def get(self, key: str) -> Any:
        """获取缓存值"""
        try:
            value = self._cache.get(key)
            if value is not None:
                return self._deserialize(value)
            return None
        except Exception as e:
            logger.warning(f"缓存获取失败: {str(e)}")
            return None
    
    def set(self, key: str, value: Any, expire: Optional[int] = None) -> bool:
        """设置缓存值"""
        try:
            serialized = self._serialize(value)
            return self._cache.set(key, serialized, expire=expire)
        except Exception as e:
            logger.warning(f"缓存设置失败: {str(e)}")
            return False
    
    def delete(self, key: str) -> bool:
        """删除缓存值"""
        try:
            return self._cache.delete(key)
        except Exception as e:
            logger.warning(f"缓存删除失败: {str(e)}")
            return False
    
    def clear(self) -> bool:
        """清空缓存"""
        try:
            self._cache.clear()
            return True
        except Exception as e:
            logger.warning(f"缓存清空失败: {str(e)}")
            return False
    
    def stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return {
            'size': self._cache.volume(),
            'count': len(self._cache),
            'hits': self._cache.stats()[0],
            'misses': self._cache.stats()[1],
            'ratio': self._cache.stats()[0] / max(1, self._cache.stats()[0] + self._cache.stats()[1])
        }
    
    def close(self):
        """关闭缓存"""
        self._cache.close()

# 任务队列系统
class TaskQueue:
    """优先级任务队列系统"""
    
    def __init__(self, max_size: int = 1000):
        self._queues = {
            TaskPriority.HIGH: deque(maxlen=max_size),
            TaskPriority.NORMAL: deque(maxlen=max_size),
            TaskPriority.LOW: deque(maxlen=max_size)
        }
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._running = True
    
    def put(self, task: 'Task', priority: TaskPriority = TaskPriority.NORMAL) -> bool:
        """添加任务到队列"""
        with self._lock:
            if len(self._queues[priority]) >= self._queues[priority].maxlen:
                return False
            self._queues[priority].append(task)
            self._condition.notify()
            return True
    
    def get(self) -> Optional['Task']:
        """从队列获取任务"""
        with self._condition:
            while self._running:
                for priority in [TaskPriority.HIGH, TaskPriority.NORMAL, TaskPriority.LOW]:
                    if self._queues[priority]:
                        return self._queues[priority].popleft()
                self._condition.wait()
            return None
    
    def size(self) -> Dict[TaskPriority, int]:
        """获取队列大小"""
        with self._lock:
            return {
                priority: len(queue)
                for priority, queue in self._queues.items()
            }
    
    def stop(self):
        """停止队列"""
        with self._condition:
            self._running = False
            self._condition.notify_all()

# 任务类
@dataclass
class Task:
    """计算任务类"""
    func: Callable
    args: Tuple[Any, ...]
    kwargs: Dict[str, Any]
    priority: TaskPriority = TaskPriority.NORMAL
    timeout: Optional[int] = None
    callback: Optional[Callable[[Any], None]] = None
    error_callback: Optional[Callable[[Exception], None]] = None
    future: Optional[Future] = None
    created_at: float = field(default_factory=time.time)
    task_id: str = field(default_factory=lambda: hashlib.md5(
        f"{time.time()}{os.urandom(4).hex()}".encode()
    ).hexdigest())

    def execute(self) -> Any:
        """执行任务"""
        try:
            result = self.func(*self.args, **self.kwargs)
            if self.callback:
                self.callback(result)
            return result
        except Exception as e:
            if self.error_callback:
                self.error_callback(e)
            raise

# 加速器核心类
class CPUAccelerator:
    """CPU加速计算核心类"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, config: Optional[PluginConfig] = None):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config: Optional[PluginConfig] = None):
        """初始化CPU加速器（完整安全版本）"""
        try:
            # 1. 基础配置初始化
            self._initialized = False
            self._instance_lock = threading.Lock()
            self._function_cache = WeakValueDictionary()
            self._function_metadata = {}
            
            # 2. 配置加载（带默认值回退）
            self.config = config or PluginConfig()
            if not hasattr(self.config, 'log_level'):
                self.config.log_level = logging.INFO
            
            # 3. 日志系统初始化（确保始终有效）
            self.logger = logging.getLogger('CPUAccelerator')
            self.logger.setLevel(self.config.log_level)
            
            # 控制台日志处理器（如果不存在则添加）
            if not self.logger.handlers:
                console_handler = logging.StreamHandler()
                console_handler.setFormatter(logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                ))
                self.logger.addHandler(console_handler)
            
            self.logger.info("开始初始化CPU加速器...")

            # 4. 环境设置
            self._setup_environment()
            
            # 5. 组件初始化（带资源检查）
            self._check_system_resources()
            
            # 6. 核心组件初始化
            self._cache = AcceleratorCache(self.config) if self.config.cache_enabled else None
            self._task_queue = TaskQueue(self.config.max_queue_size) if self.config.enable_task_queue else None
            self._monitor = HardwareMonitor(self.config.monitor_interval) if self.config.enable_hardware_monitor else None
            
            # 7. 执行器池初始化
            self._thread_pool = ThreadPoolExecutor(
                max_workers=self.config.max_threads,
                thread_name_prefix='CPUAcceleratorThread'
            )
            self._process_pool = ProcessPoolExecutor(
                max_workers=self.config.max_processes
            )
            
            # 8. 工作线程初始化
            self._worker_threads = []
            self._start_workers()
            
            # 9. GUI初始化（如果启用）
            self.gui = None
            if self.config.gui_enabled and GUI_AVAILABLE:
                try:
                    self._init_gui()
                    self.logger.info("GUI界面初始化完成")
                except Exception as e:
                    self.logger.error(f"GUI初始化失败: {str(e)}")
                    self.gui = None

            self._initialized = True
            self.logger.info("CPU加速器初始化完成")
            
        except Exception as e:
            # 紧急错误处理
            error_msg = f"初始化失败: {str(e)}\n{traceback.format_exc()}"
            if hasattr(self, 'logger'):
                self.logger.critical(error_msg)
            else:
                print(f"[CRITICAL] {error_msg}")
            
            # 尝试清理已创建的资源
            try:
                if hasattr(self, '_thread_pool'):
                    self._thread_pool.shutdown(wait=False)
                if hasattr(self, '_process_pool'):
                    self._process_pool.shutdown(wait=False)
            except:
                pass
                
            raise CPUAcceleratorError(f"无法初始化CPU加速器: {str(e)}")

    
    def _validate_config(self):
        """验证配置有效性"""
        if self.config.suppress_warnings:
            warnings.filterwarnings("ignore")
        
        if self.config.log_level != logging.INFO:
            logger.setLevel(self.config.log_level)
    
    def _setup_environment(self):
        """设置运行环境"""
        # 设置numba
        from numba import config
        config.THREADING_LAYER = 'threadsafe'
        config.NUMBA_NUM_THREADS = self.config.max_threads
        
        # 设置进程启动方法
        if platform.system() == 'Darwin':
            multiprocessing.set_start_method('spawn', force=True)
        
        # 创建必要目录
        os.makedirs(self.config.cache_dir, exist_ok=True)
        os.makedirs(self.config.profile_dir, exist_ok=True)
    
    def _check_system_resources(self):
        """验证系统资源是否满足要求"""
        try:
            mem = psutil.virtual_memory()
            cpu_count = os.cpu_count() or 1
            
            # 内存检查（至少需要500MB可用）
            if mem.available < 500 * 1024 * 1024:  # 500MB
                self.logger.warning(f"可用内存不足 (当前: {mem.available//(1024*1024)}MB)")
            
            # CPU核心检查
            if cpu_count < 2:
                self.logger.warning("CPU核心数较少，并行加速效果可能受限")
                
            # 操作系统检查
            if platform.system() not in ['Windows', 'Linux', 'Darwin']:
                self.logger.warning(f"未经测试的操作系统: {platform.system()}")
                
        except Exception as e:
            self.logger.error(f"系统资源检查失败: {str(e)}")


    def _init_gui(self):
        """初始化GUI界面"""
        try:
            self.gui = CPUAcceleratorGUI(self)
            logger.info("GUI界面初始化完成")
        except Exception as e:
            logger.error(f"GUI初始化失败: {str(e)}")
            self.gui = None
    
    def _start_workers(self):
        """启动工作线程"""
        if not self.config.enable_task_queue:
            return
        
        def worker():
            while True:
                task = self._task_queue.get()
                if task is None:  # 停止信号
                    break
                
                try:
                    task.future.set_result(task.execute())
                except Exception as e:
                    task.future.set_exception(e)
        
        for i in range(self.config.max_threads):
            t = threading.Thread(target=worker, name=f"TaskWorker-{i}", daemon=True)
            t.start()
            self._worker_threads.append(t)
    
    def _get_function_id(self, func: Callable) -> str:
        """获取函数唯一标识"""
        try:
            # 尝试获取源代码
            source = inspect.getsource(func)
        except (OSError, TypeError):
            # 对于内置函数或某些特殊函数，使用其他标识
            source = f"{func.__module__}.{func.__qualname__}"
        
        return hashlib.md5(source.encode('utf-8')).hexdigest()
    
    def _create_acceleration_wrapper(self, func: Callable, method: AccelerationMethod, **kwargs) -> Callable:
        """创建加速包装器"""
        func_id = self._get_function_id(func)
        
        if func_id in self._function_cache:
            return self._function_cache[func_id]
        
        # 根据加速方法创建加速函数
        accelerated_func = None
        
        try:
            if method == AccelerationMethod.NUMBA_JIT:
                accelerated_func = jit(**kwargs)(func)
            elif method == AccelerationMethod.NUMBA_NJIT:
                accelerated_func = njit(**kwargs)(func)
            elif method == AccelerationMethod.NUMBA_PARALLEL:
                kwargs['parallel'] = True
                accelerated_func = njit(**kwargs)(func)
            elif method == AccelerationMethod.VECTORIZE:
                accelerated_func = vectorize(**kwargs)(func)
            elif method == AccelerationMethod.GUVECTORIZE:
                accelerated_func = guvectorize(**kwargs)(func)
            elif method == AccelerationMethod.CFUNC:
                accelerated_func = cfunc(**kwargs)(func)
            else:
                accelerated_func = func
        except Exception as e:
            if self.config.fallback_to_python:
                logger.warning(f"加速失败({method.name}), 使用原始Python函数: {str(e)}")
                accelerated_func = func
            else:
                raise AccelerationError(f"加速失败: {str(e)}") from e
        
        # 缓存函数
        if accelerated_func and self._function_cache is not None:
            self._function_cache[func_id] = accelerated_func
            self._function_metadata[func_id] = {
                'original_func': func,
                'accelerated_func': accelerated_func,
                'method': method,
                'timestamp': time.time(),
                'call_count': 0
            }
        
        return accelerated_func
    
    def _check_resources(self, estimated_memory: float = 0) -> bool:
        """检查系统资源是否足够"""
        if not self.config.enable_hardware_monitor:
            return True
        
        current_usage = self._monitor.get_current_usage() if self._monitor else {'cpu': 0, 'memory': 0}
        
        # 检查CPU使用率
        if current_usage['cpu'] > self.config.cpu_limit * 100:
            logger.warning(f"CPU使用率过高: {current_usage['cpu']}% > {self.config.cpu_limit * 100}%")
            return False
        
        # 检查内存
        mem = psutil.virtual_memory()
        available_memory = mem.available / (1024 ** 3)  # GB
        if available_memory - estimated_memory < (1 - self.config.memory_limit) * (mem.total / (1024 ** 3)):
            logger.warning(f"内存不足: 可用{available_memory:.2f}GB, 需要{estimated_memory:.2f}GB")
            return False
        
        return True
    
    def accelerate(
        self,
        func: Optional[Callable] = None,
        method: Optional[AccelerationMethod] = None,
        parallel: Optional[bool] = None,
        vectorize: Optional[bool] = None,
        **kwargs
    ) -> Callable:
        """
        加速函数执行
        
        参数:
            func: 要加速的函数(如果为None, 则作为装饰器使用)
            method: 指定加速方法
            parallel: 是否启用并行计算(覆盖自动设置)
            vectorize: 是否启用向量化(覆盖自动设置)
            kwargs: 传递给加速器的额外参数
            
        返回:
            加速后的函数或装饰器
        """
        if func is None:
            return lambda f: self.accelerate(f, method, parallel, vectorize, **kwargs)
        
        # 确定加速方法
        if method is None:
            method = self.config.default_acceleration
        
        # 自动并行/向量化决策
        if parallel is None:
            parallel = self.config.auto_parallel
        if vectorize is None:
            vectorize = self.config.auto_vectorize
        
        # 更新kwargs
        if parallel and 'parallel' not in kwargs:
            kwargs['parallel'] = True
        if vectorize and 'target' not in kwargs and self.config.prefer_simd:
            kwargs['target'] = 'parallel'
        
        # 创建加速函数
        return self._create_acceleration_wrapper(func, method, **kwargs)
    
    def submit_task(
        self,
        func: Callable,
        args: Optional[Tuple] = None,
        kwargs: Optional[Dict] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: Optional[int] = None,
        callback: Optional[Callable[[Any], None]] = None,
        error_callback: Optional[Callable[[Exception], None]] = None
    ) -> Future:
        """
        提交任务到队列
        
        参数:
            func: 要执行的函数
            args: 函数位置参数
            kwargs: 函数关键字参数
            priority: 任务优先级
            timeout: 超时时间(秒)
            callback: 成功回调
            error_callback: 错误回调
            
        返回:
            Future对象，可用于获取结果
        """
        if not self.config.enable_task_queue:
            raise ConfigurationError("任务队列未启用")
        
        args = args or ()
        kwargs = kwargs or {}
        timeout = timeout or self.config.default_timeout
        
        future = Future()
        task = Task(
            func=func,
            args=args,
            kwargs=kwargs,
            priority=priority,
            timeout=timeout,
            callback=callback,
            error_callback=error_callback,
            future=future
        )
        
        if not self._task_queue.put(task, priority):
            raise CPUAcceleratorError("任务队列已满")
        
        return future
    
    def parallel_map(
        self,
        func: Callable,
        iterable: Iterable,
        chunksize: Optional[int] = None,
        timeout: Optional[int] = None,
        executor: str = "process"  # "process" or "thread"
    ) -> List[Any]:
        """
        并行映射函数到可迭代对象
        
        参数:
            func: 要映射的函数
            iterable: 输入数据
            chunksize: 每个任务处理的数据块大小
            timeout: 超时时间(秒)
            executor: 使用进程池还是线程池
            
        返回:
            处理结果列表
        """
        if chunksize is None:
            chunksize = max(1, len(iterable) // (self.config.max_processes * 4))
        
        executor_pool = self._process_pool if executor == "process" else self._thread_pool
        timeout = timeout or self.config.default_timeout
        
        try:
            results = list(executor_pool.map(func, iterable, chunksize=chunksize, timeout=timeout))
        except multiprocessing.TimeoutError:
            raise TimeoutError(f"并行映射操作超时({timeout}秒)")
        
        return results
    
    def batch_process(
        self,
        func: Callable,
        data_batches: Sequence[Sequence[Any]],
        timeout: Optional[int] = None,
        executor: str = "process"
    ) -> List[Any]:
        """
        批量处理数据
        
        参数:
            func: 处理函数
            data_batches: 数据批次列表
            timeout: 超时时间(秒)
            executor: 使用进程池还是线程池
            
        返回:
            处理结果列表
        """
        timeout = timeout or self.config.default_timeout
        executor_pool = self._process_pool if executor == "process" else self._thread_pool
        
        futures = []
        for batch in data_batches:
            futures.append(executor_pool.submit(func, batch))
        
        results = []
        try:
            for future in as_completed(futures, timeout=timeout):
                results.append(future.result())
        except multiprocessing.TimeoutError:
            raise TimeoutError(f"批量处理操作超时({timeout}秒)")
        
        return results
    
    def profile(
        self,
        func: Callable,
        *args,
        warmup: int = 1,
        iterations: int = 5,
        **kwargs
    ) -> Dict[str, Any]:
        """
        分析函数性能
        
        参数:
            func: 要分析的函数
            args: 函数位置参数
            warmup: 预热次数
            iterations: 正式运行次数
            kwargs: 函数关键字参数
            
        返回:
            性能分析结果字典
        """
        if not self.config.enable_profiling:
            raise ConfigurationError("性能分析功能未启用")
        
        # 预热
        for _ in range(warmup):
            func(*args, **kwargs)
        
        # 正式运行
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            end = time.perf_counter()
            times.append(end - start)
        
        # 保存分析结果
        profile_data = {
            'function': func.__name__,
            'module': func.__module__,
            'args': args,
            'kwargs': kwargs,
            'times': times,
            'avg_time': sum(times) / len(times),
            'min_time': min(times),
            'max_time': max(times),
            'timestamp': datetime.now().isoformat(),
            'system_info': self.get_system_info().__dict__
        }
        
        profile_file = os.path.join(
            self.config.profile_dir,
            f"profile_{func.__name__}_{int(time.time())}.json"
        )
        
        with open(profile_file, 'w', encoding='utf-8') as f:
            json.dump(profile_data, f, indent=2)
        
        return profile_data
    
    def benchmark(
        self,
        func: Callable,
        *args,
        compare_funcs: Optional[List[Callable]] = None,
        iterations: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        基准测试函数性能
        
        参数:
            func: 要测试的函数
            args: 函数位置参数
            compare_funcs: 要对比的其他函数
            iterations: 测试迭代次数
            kwargs: 函数关键字参数
            
        返回:
            基准测试结果字典
        """
        if not self.config.enable_benchmark:
            raise ConfigurationError("基准测试功能未启用")
        
        iterations = iterations or self.config.benchmark_iterations
        compare_funcs = compare_funcs or []
        
        # 包含原始函数和所有加速版本
        all_funcs = [func]
        for cf in compare_funcs:
            all_funcs.append(cf)
        
        results = {}
        for f in all_funcs:
            # 预热
            for _ in range(max(1, iterations // 2)):
                f(*args, **kwargs)
            
            # 正式测试
            times = []
            for _ in range(iterations):
                start = time.perf_counter()
                result = f(*args, **kwargs)
                end = time.perf_counter()
                times.append(end - start)
            
            results[f.__name__] = {
                'times': times,
                'avg_time': sum(times) / len(times),
                'min_time': min(times),
                'max_time': max(times),
                'result': result
            }
        
        # 保存基准测试结果
        benchmark_file = os.path.join(
            self.config.profile_dir,
            f"benchmark_{func.__name__}_{int(time.time())}.json"
        )
        
        with open(benchmark_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        
        return results
    
    @staticmethod
    def get_system_info() -> SystemInfo:
        """获取详细的系统信息"""
        cpu_info = cpuinfo.get_cpu_info()
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        return SystemInfo(
            cpu_count=multiprocessing.cpu_count(),
            cpu_physical_cores=psutil.cpu_count(logical=False),
            cpu_logical_cores=psutil.cpu_count(logical=True),
            cpu_usage=psutil.cpu_percent(),
            cpu_freq={
                'current': psutil.cpu_freq().current,
                'min': psutil.cpu_freq().min,
                'max': psutil.cpu_freq().max
            },
            cpu_name=cpu_info.get('brand_raw', 'Unknown'),
            memory_total=mem.total / (1024 ** 3),
            memory_available=mem.available / (1024 ** 3),
            memory_used=mem.used / (1024 ** 3),
            memory_percent=mem.percent,
            swap_total=swap.total / (1024 ** 3),
            swap_used=swap.used / (1024 ** 3),
            swap_percent=swap.percent,
            platform=platform.platform(),
            python_version=platform.python_version(),
            architecture=platform.machine()
        )
    
    def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        """获取缓存统计信息"""
        if self._cache:
            return self._cache.stats()
        return None
    
    def clear_cache(self) -> bool:
        """清空缓存"""
        if self._cache:
            return self._cache.clear()
        return False
    
    def get_function_metadata(self) -> Dict[str, Dict[str, Any]]:
        """获取所有加速函数的元数据"""
        return self._function_metadata.copy()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
    
    def shutdown(self):
        """关闭加速器并释放资源"""
        if self._initialized:
            logger.info("正在关闭CPU加速器...")

            try:
                # 停止任务队列
                if self._task_queue:
                    self._task_queue.stop()
                
                # 关闭线程池和进程池
                self._thread_pool.shutdown(wait=True)
                self._process_pool.shutdown(wait=True)
                
                # 停止监控
                if self._monitor:
                    self._monitor.stop()
                
                # 关闭缓存
                if self._cache:
                    self._cache.close()
                
                # 关闭GUI（仅在GUI存在且未被清理时）
                if self.gui and not getattr(self.gui, '_cleaned_up', True):
                    self.gui.cleanup()
            except Exception as e:
                logger.error(f"关闭过程中发生异常: {str(e)}")
            
            self._initialized = False
            logger.info("CPU加速器已关闭")

# GUI界面
class CPUAcceleratorGUI:
    """CPU加速器GUI界面"""
    
    def __init__(self, accelerator: CPUAccelerator):
        self.accelerator = accelerator
        self.root = tk.Tk()
        self.root.title("CPU加速计算插件" if accelerator.config.gui_language == "zh_CN" else "CPU Accelerator Plugin")
        
        self._setup_styles()
        self._setup_ui()
        self._setup_menu()
        self._setup_statusbar()
        self._center_window()
        self._schedule_updates()
        
        # 绑定关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.cleanup)
    
    def _setup_styles(self):
        """设置GUI样式"""
        style = ttk.Style(self.root)
        
        # 使用指定主题
        try:
            style.theme_use(self.accelerator.config.gui_theme)
        except tk.TclError:
            style.theme_use('clam')
        
        # 配置字体
        default_font = (self.accelerator.config.gui_font, self.accelerator.config.gui_font_size)
        style.configure('.', font=default_font)
        
        # 自定义样式
        style.configure('Title.TLabel', font=(default_font[0], default_font[1] + 2, 'bold'))
        style.configure('Highlight.TFrame', background='#f0f0f0')
        style.configure('Red.TLabel', foreground='red')
        style.configure('Green.TLabel', foreground='green')
    
    def _center_window(self):
        """居中窗口"""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        self.root.geometry(f"{max(800, width)}x{max(600, height)}+{x}+{y}")
    
    def _setup_menu(self):
        """设置菜单栏"""
        menubar = tk.Menu(self.root)
        
        # 文件菜单
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label="退出" if self.accelerator.config.gui_language == "zh_CN" else "Exit",
            command=self.cleanup
        )
        menubar.add_cascade(
            label="文件" if self.accelerator.config.gui_language == "zh_CN" else "File",
            menu=file_menu
        )
        
        # 视图菜单
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_checkbutton(
            label="显示系统信息",
            variable=tk.BooleanVar(value=True)
        )
        menubar.add_cascade(
            label="视图" if self.accelerator.config.gui_language == "zh_CN" else "View",
            menu=view_menu
        )
        
        # 帮助菜单
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(
            label="关于" if self.accelerator.config.gui_language == "zh_CN" else "About",
            command=self._show_about
        )
        menubar.add_cascade(
            label="帮助" if self.accelerator.config.gui_language == "zh_CN" else "Help",
            menu=help_menu
        )
        
        self.root.config(menu=menubar)
    
    def _setup_ui(self):
        """设置主界面"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建笔记本(选项卡)
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        # 添加选项卡
        self._add_dashboard_tab(notebook)
        self._add_config_tab(notebook)
        self._add_functions_tab(notebook)
        self._add_tasks_tab(notebook)
        self._add_cache_tab(notebook)
        self._add_profiling_tab(notebook)
    
    def _add_dashboard_tab(self, notebook):
        """添加仪表盘选项卡"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="仪表盘" if self.accelerator.config.gui_language == "zh_CN" else "Dashboard")
        
        # 系统信息框架
        sys_frame = ttk.LabelFrame(tab, text="系统信息", padding="5")
        sys_frame.pack(fill=tk.X, pady=5)
        
        # 实时资源使用图表
        self._setup_resource_charts(sys_frame)
        
        # 快速操作按钮
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(
            btn_frame,
            text="刷新",
            command=self._refresh_all
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            btn_frame,
            text="加速测试函数",
            command=self._run_test
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            btn_frame,
            text="系统信息",
            command=self._show_system_info
        ).pack(side=tk.RIGHT, padx=5)
    
    def _setup_resource_charts(self, parent):
        """设置资源使用图表"""
        # CPU使用率
        cpu_frame = ttk.Frame(parent)
        cpu_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(
            cpu_frame,
            text="CPU使用率:",
            style='Title.TLabel'
        ).pack(anchor=tk.W)
        
        self.cpu_canvas = tk.Canvas(cpu_frame, height=150, bg='white')
        self.cpu_canvas.pack(fill=tk.X)
        
        # 内存使用率
        mem_frame = ttk.Frame(parent)
        mem_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(
            mem_frame,
            text="内存使用率:",
            style='Title.TLabel'
        ).pack(anchor=tk.W)
        
        self.mem_canvas = tk.Canvas(mem_frame, height=150, bg='white')
        self.mem_canvas.pack(fill=tk.X)
        
        # 初始绘制
        self._draw_resource_charts()
    
    def _draw_resource_charts(self):
        """绘制资源使用图表"""
        if not hasattr(self, 'cpu_canvas'):
            return
        
        # 获取最近10个数据点
        stats = self.accelerator._monitor.get_stats(10) if self.accelerator._monitor else {
            'cpu': [0] * 10,
            'memory': [0] * 10,
            'timestamps': [time.time() - i for i in range(10)]
        }
        
        # 绘制CPU图表
        self.cpu_canvas.delete('all')
        width = self.cpu_canvas.winfo_width()
        height = self.cpu_canvas.winfo_height()
        
        # 网格线
        for i in range(0, 101, 20):
            y = height - (i / 100 * height)
            self.cpu_canvas.create_line(0, y, width, y, fill='#e0e0e0')
            self.cpu_canvas.create_text(5, y - 10, text=f"{i}%", anchor=tk.W)
        
        # 数据线
        points = []
        for i, (cpu, ts) in enumerate(zip(stats['cpu'], stats['timestamps'])):
            x = (i / (len(stats['cpu']) - 1)) * width if len(stats['cpu']) > 1 else width
            y = height - (cpu / 100 * height)
            points.extend([x, y])
        
        if len(points) > 2:
            self.cpu_canvas.create_line(*points, fill='blue', width=2)
        
        # 绘制内存图表
        self.mem_canvas.delete('all')
        width = self.mem_canvas.winfo_width()
        height = self.mem_canvas.winfo_height()
        
        # 网格线
        for i in range(0, 101, 20):
            y = height - (i / 100 * height)
            self.mem_canvas.create_line(0, y, width, y, fill='#e0e0e0')
            self.mem_canvas.create_text(5, y - 10, text=f"{i}%", anchor=tk.W)
        
        # 数据线
        points = []
        for i, (mem, ts) in enumerate(zip(stats['memory'], stats['timestamps'])):
            x = (i / (len(stats['memory']) - 1)) * width if len(stats['memory']) > 1 else width
            y = height - (mem / 100 * height)
            points.extend([x, y])
        
        if len(points) > 2:
            self.mem_canvas.create_line(*points, fill='green', width=2)
    
    def _add_config_tab(self, notebook):
        """添加配置选项卡"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="配置" if self.accelerator.config.gui_language == "zh_CN" else "Configuration")
        
        # 滚动区域
        canvas = tk.Canvas(tab)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 性能配置
        perf_frame = ttk.LabelFrame(scrollable_frame, text="性能配置", padding="5")
        perf_frame.pack(fill=tk.X, pady=5, padx=5)
        
        # 线程数
        ttk.Label(perf_frame, text="最大线程数:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.threads_var = tk.IntVar(value=self.accelerator.config.max_threads)
        ttk.Spinbox(
            perf_frame,
            from_=1,
            to=multiprocessing.cpu_count(),
            textvariable=self.threads_var
        ).grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        
        # 进程数
        ttk.Label(perf_frame, text="最大进程数:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.processes_var = tk.IntVar(value=self.accelerator.config.max_processes)
        ttk.Spinbox(
            perf_frame,
            from_=1,
            to=multiprocessing.cpu_count(),
            textvariable=self.processes_var
        ).grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        
        # 内存限制
        ttk.Label(perf_frame, text="内存限制比例:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.mem_limit_var = tk.DoubleVar(value=self.accelerator.config.memory_limit)
        ttk.Spinbox(
            perf_frame,
            from_=0.1,
            to=1.0,
            increment=0.1,
            textvariable=self.mem_limit_var
        ).grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        
        # CPU限制
        ttk.Label(perf_frame, text="CPU限制比例:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.cpu_limit_var = tk.DoubleVar(value=self.accelerator.config.cpu_limit)
        ttk.Spinbox(
            perf_frame,
            from_=0.1,
            to=1.0,
            increment=0.1,
            textvariable=self.cpu_limit_var
        ).grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)
        
        # 加速配置
        accel_frame = ttk.LabelFrame(scrollable_frame, text="加速配置", padding="5")
        accel_frame.pack(fill=tk.X, pady=5, padx=5)
        
        # 默认加速方法
        ttk.Label(accel_frame, text="默认加速方法:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.accel_method_var = tk.StringVar(value=self.accelerator.config.default_acceleration.name)
        ttk.Combobox(
            accel_frame,
            textvariable=self.accel_method_var,
            values=[m.name for m in AccelerationMethod],
            state="readonly"
        ).grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        
        # 自动并行
        self.auto_parallel_var = tk.BooleanVar(value=self.accelerator.config.auto_parallel)
        ttk.Checkbutton(
            accel_frame,
            text="自动并行",
            variable=self.auto_parallel_var
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        # 自动向量化
        self.auto_vectorize_var = tk.BooleanVar(value=self.accelerator.config.auto_vectorize)
        ttk.Checkbutton(
            accel_frame,
            text="自动向量化",
            variable=self.auto_vectorize_var
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        # 偏好SIMD
        self.prefer_simd_var = tk.BooleanVar(value=self.accelerator.config.prefer_simd)
        ttk.Checkbutton(
            accel_frame,
            text="偏好SIMD指令",
            variable=self.prefer_simd_var
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        # 缓存配置
        cache_frame = ttk.LabelFrame(scrollable_frame, text="缓存配置", padding="5")
        cache_frame.pack(fill=tk.X, pady=5, padx=5)
        
        # 启用缓存
        self.cache_enabled_var = tk.BooleanVar(value=self.accelerator.config.cache_enabled)
        ttk.Checkbutton(
            cache_frame,
            text="启用缓存",
            variable=self.cache_enabled_var,
            command=self._toggle_cache_settings
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        # 缓存目录
        ttk.Label(cache_frame, text="缓存目录:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.cache_dir_var = tk.StringVar(value=self.accelerator.config.cache_dir)
        ttk.Entry(cache_frame, textvariable=self.cache_dir_var).grid(row=1, column=1, sticky=tk.EW, padx=5, pady=2)
        ttk.Button(
            cache_frame,
            text="浏览...",
            command=self._browse_cache_dir
        ).grid(row=1, column=2, sticky=tk.E, padx=5, pady=2)
        
        # 缓存大小限制
        ttk.Label(cache_frame, text="缓存大小限制(MB):").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.cache_size_var = tk.IntVar(value=self.accelerator.config.cache_size_limit)
        ttk.Spinbox(
            cache_frame,
            from_=1,
            to=10240,
            increment=100,
            textvariable=self.cache_size_var
        ).grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        
        # 缓存策略
        ttk.Label(cache_frame, text="缓存策略:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.cache_policy_var = tk.StringVar(value=self.accelerator.config.cache_policy.name)
        ttk.Combobox(
            cache_frame,
            textvariable=self.cache_policy_var,
            values=[p.name for p in CachePolicy],
            state="readonly"
        ).grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)
        
        # 缓存压缩
        self.cache_compress_var = tk.BooleanVar(value=self.accelerator.config.cache_compress)
        ttk.Checkbutton(
            cache_frame,
            text="启用压缩",
            variable=self.cache_compress_var
        ).grid(row=4, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        # 缓存序列化器
        ttk.Label(cache_frame, text="序列化器:").grid(row=5, column=0, sticky=tk.W, padx=5, pady=2)
        self.cache_serializer_var = tk.StringVar(value=self.accelerator.config.cache_serializer)
        ttk.Combobox(
            cache_frame,
            textvariable=self.cache_serializer_var,
            values=["pickle", "json"],
            state="readonly"
        ).grid(row=5, column=1, sticky=tk.W, padx=5, pady=2)
        
        # 任务配置
        task_frame = ttk.LabelFrame(scrollable_frame, text="任务配置", padding="5")
        task_frame.pack(fill=tk.X, pady=5, padx=5)
        
        # 启用任务队列
        self.task_queue_var = tk.BooleanVar(value=self.accelerator.config.enable_task_queue)
        ttk.Checkbutton(
            task_frame,
            text="启用任务队列",
            variable=self.task_queue_var,
            command=self._toggle_task_settings
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        # 默认超时
        ttk.Label(task_frame, text="默认超时(秒):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.timeout_var = tk.IntVar(value=self.accelerator.config.default_timeout)
        ttk.Spinbox(
            task_frame,
            from_=1,
            to=3600,
            increment=30,
            textvariable=self.timeout_var
        ).grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        
        # 最大队列大小
        ttk.Label(task_frame, text="最大队列大小:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.queue_size_var = tk.IntVar(value=self.accelerator.config.max_queue_size)
        ttk.Spinbox(
            task_frame,
            from_=1,
            to=100000,
            increment=100,
            textvariable=self.queue_size_var
        ).grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        
        # 错误处理
        error_frame = ttk.LabelFrame(scrollable_frame, text="错误处理", padding="5")
        error_frame.pack(fill=tk.X, pady=5, padx=5)
        
        # 回退到Python
        self.fallback_var = tk.BooleanVar(value=self.accelerator.config.fallback_to_python)
        ttk.Checkbutton(
            error_frame,
            text="加速失败时回退到Python",
            variable=self.fallback_var
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        # 抑制警告
        self.suppress_warnings_var = tk.BooleanVar(value=self.accelerator.config.suppress_warnings)
        ttk.Checkbutton(
            error_frame,
            text="抑制警告信息",
            variable=self.suppress_warnings_var
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        # 日志级别
        ttk.Label(error_frame, text="日志级别:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.log_level_var = tk.StringVar(value=logging.getLevelName(self.accelerator.config.log_level))
        ttk.Combobox(
            error_frame,
            textvariable=self.log_level_var,
            values=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            state="readonly"
        ).grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        
        # 高级配置
        advanced_frame = ttk.LabelFrame(scrollable_frame, text="高级配置", padding="5")
        advanced_frame.pack(fill=tk.X, pady=5, padx=5)
        
        # 启用性能分析
        self.profiling_var = tk.BooleanVar(value=self.accelerator.config.enable_profiling)
        ttk.Checkbutton(
            advanced_frame,
            text="启用性能分析",
            variable=self.profiling_var
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        # 性能分析目录
        ttk.Label(advanced_frame, text="分析目录:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.profile_dir_var = tk.StringVar(value=self.accelerator.config.profile_dir)
        ttk.Entry(advanced_frame, textvariable=self.profile_dir_var).grid(row=1, column=1, sticky=tk.EW, padx=5, pady=2)
        ttk.Button(
            advanced_frame,
            text="浏览...",
            command=self._browse_profile_dir
        ).grid(row=1, column=2, sticky=tk.E, padx=5, pady=2)
        
        # 启用基准测试
        self.benchmark_var = tk.BooleanVar(value=self.accelerator.config.enable_benchmark)
        ttk.Checkbutton(
            advanced_frame,
            text="启用基准测试",
            variable=self.benchmark_var
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        # 基准测试迭代次数
        ttk.Label(advanced_frame, text="测试迭代次数:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.benchmark_iter_var = tk.IntVar(value=self.accelerator.config.benchmark_iterations)
        ttk.Spinbox(
            advanced_frame,
            from_=1,
            to=100,
            increment=1,
            textvariable=self.benchmark_iter_var
        ).grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)
        
        # 启用硬件监控
        self.monitor_var = tk.BooleanVar(value=self.accelerator.config.enable_hardware_monitor)
        ttk.Checkbutton(
            advanced_frame,
            text="启用硬件监控",
            variable=self.monitor_var
        ).grid(row=4, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        # 监控间隔
        ttk.Label(advanced_frame, text="监控间隔(秒):").grid(row=5, column=0, sticky=tk.W, padx=5, pady=2)
        self.monitor_interval_var = tk.DoubleVar(value=self.accelerator.config.monitor_interval)
        ttk.Spinbox(
            advanced_frame,
            from_=0.1,
            to=60,
            increment=0.5,
            textvariable=self.monitor_interval_var
        ).grid(row=5, column=1, sticky=tk.W, padx=5, pady=2)
        
        # GUI配置
        gui_frame = ttk.LabelFrame(scrollable_frame, text="GUI配置", padding="5")
        gui_frame.pack(fill=tk.X, pady=5, padx=5)
        
        # 语言
        ttk.Label(gui_frame, text="语言:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.gui_lang_var = tk.StringVar(value=self.accelerator.config.gui_language)
        ttk.Combobox(
            gui_frame,
            textvariable=self.gui_lang_var,
            values=["zh_CN", "en"],
            state="readonly"
        ).grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        
        # 主题
        ttk.Label(gui_frame, text="主题:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.gui_theme_var = tk.StringVar(value=self.accelerator.config.gui_theme)
        ttk.Combobox(
            gui_frame,
            textvariable=self.gui_theme_var,
            values=["clam", "alt", "default", "classic"],
            state="readonly"
        ).grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        
        # 字体
        ttk.Label(gui_frame, text="字体:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.gui_font_var = tk.StringVar(value=self.accelerator.config.gui_font)
        ttk.Entry(gui_frame, textvariable=self.gui_font_var).grid(row=2, column=1, sticky=tk.EW, padx=5, pady=2)
        
        # 字体大小
        ttk.Label(gui_frame, text="字体大小:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.gui_font_size_var = tk.IntVar(value=self.accelerator.config.gui_font_size)
        ttk.Spinbox(
            gui_frame,
            from_=8,
            to=24,
            increment=1,
            textvariable=self.gui_font_size_var
        ).grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)
        
        # 应用按钮
        btn_frame = ttk.Frame(scrollable_frame)
        btn_frame.pack(fill=tk.X, pady=10)
        
        ttk.Button(
            btn_frame,
            text="应用配置",
            command=self._apply_config,
            style='Accent.TButton'
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            btn_frame,
            text="重置",
            command=self._reset_config
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            btn_frame,
            text="保存配置",
            command=self._save_config
        ).pack(side=tk.RIGHT, padx=5)
        
        ttk.Button(
            btn_frame,
            text="加载配置",
            command=self._load_config
        ).pack(side=tk.RIGHT, padx=5)
    
    def _toggle_cache_settings(self):
        """切换缓存设置状态"""
        state = 'normal' if self.cache_enabled_var.get() else 'disabled'
        
        widgets = [
            self.cache_dir_var, self.cache_size_var, self.cache_policy_var,
            self.cache_compress_var, self.cache_serializer_var
        ]
        
        for widget in widgets:
            if hasattr(widget, '_tk'):
                widget._tk.configure(state=state)
    
    def _toggle_task_settings(self):
        """切换任务设置状态"""
        state = 'normal' if self.task_queue_var.get() else 'disabled'
        
        widgets = [
            self.timeout_var, self.queue_size_var
        ]
        
        for widget in widgets:
            if hasattr(widget, '_tk'):
                widget._tk.configure(state=state)
    
    def _browse_cache_dir(self):
        """浏览缓存目录"""
        dir_path = filedialog.askdirectory(
            initialdir=self.cache_dir_var.get(),
            title="选择缓存目录"
        )
        if dir_path:
            self.cache_dir_var.set(dir_path)
    
    def _browse_profile_dir(self):
        """浏览分析目录"""
        dir_path = filedialog.askdirectory(
            initialdir=self.profile_dir_var.get(),
            title="选择分析目录"
        )
        if dir_path:
            self.profile_dir_var.set(dir_path)
    
    def _apply_config(self):
        """应用配置更改"""
        try:
            # 性能配置
            self.accelerator.config.max_threads = self.threads_var.get()
            self.accelerator.config.max_processes = self.processes_var.get()
            self.accelerator.config.memory_limit = self.mem_limit_var.get()
            self.accelerator.config.cpu_limit = self.cpu_limit_var.get()
            
            # 加速配置
            self.accelerator.config.default_acceleration = AccelerationMethod[self.accel_method_var.get()]
            self.accelerator.config.auto_parallel = self.auto_parallel_var.get()
            self.accelerator.config.auto_vectorize = self.auto_vectorize_var.get()
            self.accelerator.config.prefer_simd = self.prefer_simd_var.get()
            
            # 缓存配置
            self.accelerator.config.cache_enabled = self.cache_enabled_var.get()
            self.accelerator.config.cache_dir = self.cache_dir_var.get()
            self.accelerator.config.cache_size_limit = self.cache_size_var.get()
            self.accelerator.config.cache_policy = CachePolicy[self.cache_policy_var.get()]
            self.accelerator.config.cache_compress = self.cache_compress_var.get()
            self.accelerator.config.cache_serializer = self.cache_serializer_var.get()
            
            # 任务配置
            self.accelerator.config.enable_task_queue = self.task_queue_var.get()
            self.accelerator.config.default_timeout = self.timeout_var.get()
            self.accelerator.config.max_queue_size = self.queue_size_var.get()
            
            # 错误处理
            self.accelerator.config.fallback_to_python = self.fallback_var.get()
            self.accelerator.config.suppress_warnings = self.suppress_warnings_var.get()
            self.accelerator.config.log_level = logging.getLevelName(self.log_level_var.get())
            
            # 高级配置
            self.accelerator.config.enable_profiling = self.profiling_var.get()
            self.accelerator.config.profile_dir = self.profile_dir_var.get()
            self.accelerator.config.enable_benchmark = self.benchmark_var.get()
            self.accelerator.config.benchmark_iterations = self.benchmark_iter_var.get()
            self.accelerator.config.enable_hardware_monitor = self.monitor_var.get()
            self.accelerator.config.monitor_interval = self.monitor_interval_var.get()
            
            # GUI配置
            self.accelerator.config.gui_language = self.gui_lang_var.get()
            self.accelerator.config.gui_theme = self.gui_theme_var.get()
            self.accelerator.config.gui_font = self.gui_font_var.get()
            self.accelerator.config.gui_font_size = self.gui_font_size_var.get()
            
            # 更新日志级别
            logger.setLevel(self.accelerator.config.log_level)
            
            # 更新numba线程数
            from numba import config
            config.NUMBA_NUM_THREADS = self.accelerator.config.max_threads
            
            # 更新监控
            if self.accelerator._monitor:
                self.accelerator._monitor.interval = self.accelerator.config.monitor_interval
            
            messagebox.showinfo(
                "成功" if self.accelerator.config.gui_language == "zh_CN" else "Success",
                "配置已成功应用" if self.accelerator.config.gui_language == "zh_CN" else "Configuration applied successfully"
            )
            
            logger.info("配置已更新")
        except Exception as e:
            messagebox.showerror(
                "错误" if self.accelerator.config.gui_language == "zh_CN" else "Error",
                f"配置应用失败: {str(e)}" if self.accelerator.config.gui_language == "zh_CN" else f"Failed to apply config: {str(e)}"
            )
            logger.error(f"配置应用失败: {str(e)}")
    
    def _reset_config(self):
        """重置为默认配置"""
        default_config = PluginConfig()
        
        # 性能配置
        self.threads_var.set(default_config.max_threads)
        self.processes_var.set(default_config.max_processes)
        self.mem_limit_var.set(default_config.memory_limit)
        self.cpu_limit_var.set(default_config.cpu_limit)
        
        # 加速配置
        self.accel_method_var.set(default_config.default_acceleration.name)
        self.auto_parallel_var.set(default_config.auto_parallel)
        self.auto_vectorize_var.set(default_config.auto_vectorize)
        self.prefer_simd_var.set(default_config.prefer_simd)
        
        # 缓存配置
        self.cache_enabled_var.set(default_config.cache_enabled)
        self.cache_dir_var.set(default_config.cache_dir)
        self.cache_size_var.set(default_config.cache_size_limit)
        self.cache_policy_var.set(default_config.cache_policy.name)
        self.cache_compress_var.set(default_config.cache_compress)
        self.cache_serializer_var.set(default_config.cache_serializer)
        
        # 任务配置
        self.task_queue_var.set(default_config.enable_task_queue)
        self.timeout_var.set(default_config.default_timeout)
        self.queue_size_var.set(default_config.max_queue_size)
        
        # 错误处理
        self.fallback_var.set(default_config.fallback_to_python)
        self.suppress_warnings_var.set(default_config.suppress_warnings)
        self.log_level_var.set(logging.getLevelName(default_config.log_level))
        
        # 高级配置
        self.profiling_var.set(default_config.enable_profiling)
        self.profile_dir_var.set(default_config.profile_dir)
        self.benchmark_var.set(default_config.enable_benchmark)
        self.benchmark_iter_var.set(default_config.benchmark_iterations)
        self.monitor_var.set(default_config.enable_hardware_monitor)
        self.monitor_interval_var.set(default_config.monitor_interval)
        
        # GUI配置
        self.gui_lang_var.set(default_config.gui_language)
        self.gui_theme_var.set(default_config.gui_theme)
        self.gui_font_var.set(default_config.gui_font)
        self.gui_font_size_var.set(default_config.gui_font_size)
        
        messagebox.showinfo(
            "成功" if self.accelerator.config.gui_language == "zh_CN" else "Success",
            "配置已重置为默认值" if self.accelerator.config.gui_language == "zh_CN" else "Configuration reset to defaults"
        )
    
    def _save_config(self):
        """保存配置到文件"""
        config_file = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json")],
            title="保存配置"
        )
        
        if not config_file:
            return
        
        try:
            config_dict = {
                # 性能配置
                'max_threads': self.threads_var.get(),
                'max_processes': self.processes_var.get(),
                'memory_limit': self.mem_limit_var.get(),
                'cpu_limit': self.cpu_limit_var.get(),
                
                # 加速配置
                'default_acceleration': self.accel_method_var.get(),
                'auto_parallel': self.auto_parallel_var.get(),
                'auto_vectorize': self.auto_vectorize_var.get(),
                'prefer_simd': self.prefer_simd_var.get(),
                
                # 缓存配置
                'cache_enabled': self.cache_enabled_var.get(),
                'cache_dir': self.cache_dir_var.get(),
                'cache_size_limit': self.cache_size_var.get(),
                'cache_policy': self.cache_policy_var.get(),
                'cache_compress': self.cache_compress_var.get(),
                'cache_serializer': self.cache_serializer_var.get(),
                
                # 任务配置
                'enable_task_queue': self.task_queue_var.get(),
                'default_timeout': self.timeout_var.get(),
                'max_queue_size': self.queue_size_var.get(),
                
                # 错误处理
                'fallback_to_python': self.fallback_var.get(),
                'suppress_warnings': self.suppress_warnings_var.get(),
                'log_level': self.log_level_var.get(),
                
                # 高级配置
                'enable_profiling': self.profiling_var.get(),
                'profile_dir': self.profile_dir_var.get(),
                'enable_benchmark': self.benchmark_var.get(),
                'benchmark_iterations': self.benchmark_iter_var.get(),
                'enable_hardware_monitor': self.monitor_var.get(),
                'monitor_interval': self.monitor_interval_var.get(),
                
                # GUI配置
                'gui_language': self.gui_lang_var.get(),
                'gui_theme': self.gui_theme_var.get(),
                'gui_font': self.gui_font_var.get(),
                'gui_font_size': self.gui_font_size_var.get()
            }
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, indent=2)
            
            messagebox.showinfo(
                "成功" if self.accelerator.config.gui_language == "zh_CN" else "Success",
                f"配置已保存到 {config_file}" if self.accelerator.config.gui_language == "zh_CN" else f"Configuration saved to {config_file}"
            )
        except Exception as e:
            messagebox.showerror(
                "错误" if self.accelerator.config.gui_language == "zh_CN" else "Error",
                f"保存配置失败: {str(e)}" if self.accelerator.config.gui_language == "zh_CN" else f"Failed to save config: {str(e)}"
            )
    
    def _load_config(self):
        """从文件加载配置"""
        config_file = filedialog.askopenfilename(
            filetypes=[("JSON Files", "*.json")],
            title="加载配置"
        )
        
        if not config_file:
            return
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config_dict = json.load(f)
            
            # 性能配置
            self.threads_var.set(config_dict.get('max_threads', self.accelerator.config.max_threads))
            self.processes_var.set(config_dict.get('max_processes', self.accelerator.config.max_processes))
            self.mem_limit_var.set(config_dict.get('memory_limit', self.accelerator.config.memory_limit))
            self.cpu_limit_var.set(config_dict.get('cpu_limit', self.accelerator.config.cpu_limit))
            
            # 加速配置
            self.accel_method_var.set(config_dict.get('default_acceleration', self.accelerator.config.default_acceleration.name))
            self.auto_parallel_var.set(config_dict.get('auto_parallel', self.accelerator.config.auto_parallel))
            self.auto_vectorize_var.set(config_dict.get('auto_vectorize', self.accelerator.config.auto_vectorize))
            self.prefer_simd_var.set(config_dict.get('prefer_simd', self.accelerator.config.prefer_simd))
            
            # 缓存配置
            self.cache_enabled_var.set(config_dict.get('cache_enabled', self.accelerator.config.cache_enabled))
            self.cache_dir_var.set(config_dict.get('cache_dir', self.accelerator.config.cache_dir))
            self.cache_size_var.set(config_dict.get('cache_size_limit', self.accelerator.config.cache_size_limit))
            self.cache_policy_var.set(config_dict.get('cache_policy', self.accelerator.config.cache_policy.name))
            self.cache_compress_var.set(config_dict.get('cache_compress', self.accelerator.config.cache_compress))
            self.cache_serializer_var.set(config_dict.get('cache_serializer', self.accelerator.config.cache_serializer))
            
            # 任务配置
            self.task_queue_var.set(config_dict.get('enable_task_queue', self.accelerator.config.enable_task_queue))
            self.timeout_var.set(config_dict.get('default_timeout', self.accelerator.config.default_timeout))
            self.queue_size_var.set(config_dict.get('max_queue_size', self.accelerator.config.max_queue_size))
            
            # 错误处理
            self.fallback_var.set(config_dict.get('fallback_to_python', self.accelerator.config.fallback_to_python))
            self.suppress_warnings_var.set(config_dict.get('suppress_warnings', self.accelerator.config.suppress_warnings))
            self.log_level_var.set(config_dict.get('log_level', logging.getLevelName(self.accelerator.config.log_level)))
            
            # 高级配置
            self.profiling_var.set(config_dict.get('enable_profiling', self.accelerator.config.enable_profiling))
            self.profile_dir_var.set(config_dict.get('profile_dir', self.accelerator.config.profile_dir))
            self.benchmark_var.set(config_dict.get('enable_benchmark', self.accelerator.config.enable_benchmark))
            self.benchmark_iter_var.set(config_dict.get('benchmark_iterations', self.accelerator.config.benchmark_iterations))
            self.monitor_var.set(config_dict.get('enable_hardware_monitor', self.accelerator.config.enable_hardware_monitor))
            self.monitor_interval_var.set(config_dict.get('monitor_interval', self.accelerator.config.monitor_interval))
            
            # GUI配置
            self.gui_lang_var.set(config_dict.get('gui_language', self.accelerator.config.gui_language))
            self.gui_theme_var.set(config_dict.get('gui_theme', self.accelerator.config.gui_theme))
            self.gui_font_var.set(config_dict.get('gui_font', self.accelerator.config.gui_font))
            self.gui_font_size_var.set(config_dict.get('gui_font_size', self.accelerator.config.gui_font_size))
            
            messagebox.showinfo(
                "成功" if self.accelerator.config.gui_language == "zh_CN" else "Success",
                f"配置已从 {config_file} 加载" if self.accelerator.config.gui_language == "zh_CN" else f"Configuration loaded from {config_file}"
            )
        except Exception as e:
            messagebox.showerror(
                "错误" if self.accelerator.config.gui_language == "zh_CN" else "Error",
                f"加载配置失败: {str(e)}" if self.accelerator.config.gui_language == "zh_CN" else f"Failed to load config: {str(e)}"
            )
    
    def _add_functions_tab(self, notebook):
        """添加函数选项卡"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="函数" if self.accelerator.config.gui_language == "zh_CN" else "Functions")
        
        # 工具栏
        toolbar = ttk.Frame(tab)
        toolbar.pack(fill=tk.X, pady=5)
        
        ttk.Button(
            toolbar,
            text="刷新",
            command=self._refresh_functions
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            toolbar,
            text="加速新函数",
            command=self._accelerate_new_function
        ).pack(side=tk.LEFT, padx=5)
        
        # 函数列表
        columns = ("id", "name", "module", "method", "calls", "last_used")
        self.functions_tree = ttk.Treeview(
            tab,
            columns=columns,
            show="headings",
            selectmode="browse"
        )
        
        # 设置列
        self.functions_tree.heading("id", text="ID")
        self.functions_tree.heading("name", text="函数名")
        self.functions_tree.heading("module", text="模块")
        self.functions_tree.heading("method", text="加速方法")
        self.functions_tree.heading("calls", text="调用次数")
        self.functions_tree.heading("last_used", text="最后使用")
        
        # 设置列宽
        self.functions_tree.column("id", width=50, anchor=tk.CENTER)
        self.functions_tree.column("name", width=150, anchor=tk.W)
        self.functions_tree.column("module", width=150, anchor=tk.W)
        self.functions_tree.column("method", width=100, anchor=tk.W)
        self.functions_tree.column("calls", width=80, anchor=tk.CENTER)
        self.functions_tree.column("last_used", width=120, anchor=tk.CENTER)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.functions_tree.yview)
        self.functions_tree.configure(yscrollcommand=scrollbar.set)
        
        self.functions_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 右键菜单
        self.function_menu = tk.Menu(self.functions_tree, tearoff=0)
        self.function_menu.add_command(
            label="查看详情",
            command=self._show_function_details
        )
        self.function_menu.add_command(
            label="重新加速",
            command=self._reaccelerate_function
        )
        self.function_menu.add_command(
            label="清除缓存",
            command=self._clear_function_cache
        )
        
        self.functions_tree.bind("<Button-3>", self._show_function_menu)
        
        # 初始加载数据
        self._refresh_functions()
    
    def _refresh_functions(self):
        """刷新函数列表"""
        self.functions_tree.delete(*self.functions_tree.get_children())
        
        for func_id, metadata in self.accelerator.get_function_metadata().items():
            self.functions_tree.insert("", "end", values=(
                func_id[:8] + "...",
                metadata['original_func'].__name__,
                metadata['original_func'].__module__,
                metadata['method'].name,
                metadata.get('call_count', 0),
                time.strftime("%Y-%m-%d %H:%M", time.localtime(metadata.get('timestamp', 0)))
            ))
    
    def _show_function_menu(self, event):
        """显示函数右键菜单"""
        item = self.functions_tree.identify_row(event.y)
        if item:
            self.functions_tree.selection_set(item)
            self.function_menu.post(event.x_root, event.y_root)
    
    def _show_function_details(self):
        """显示函数详情"""
        selected = self.functions_tree.selection()
        if not selected:
            return
        
        item = self.functions_tree.item(selected[0])
        func_id_short = item['values'][0]
        
        # 查找完整ID
        full_id = None
        for fid in self.accelerator._function_metadata.keys():
            if fid.startswith(func_id_short[:8]):
                full_id = fid
                break
        
        if not full_id:
            return
        
        metadata = self.accelerator._function_metadata[full_id]
        
        # 创建详情窗口
        detail_win = tk.Toplevel(self.root)
        detail_win.title(f"函数详情 - {metadata['original_func'].__name__}")
        
        # 基本信息
        info_frame = ttk.LabelFrame(detail_win, text="基本信息", padding="5")
        info_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(info_frame, text=f"函数名: {metadata['original_func'].__name__}").pack(anchor=tk.W)
        ttk.Label(info_frame, text=f"模块: {metadata['original_func'].__module__}").pack(anchor=tk.W)
        ttk.Label(info_frame, text=f"加速方法: {metadata['method'].name}").pack(anchor=tk.W)
        ttk.Label(info_frame, text=f"调用次数: {metadata.get('call_count', 0)}").pack(anchor=tk.W)
        ttk.Label(info_frame, text=f"最后使用: {time.ctime(metadata.get('timestamp', 0))}").pack(anchor=tk.W)
        
        # 源代码
        code_frame = ttk.LabelFrame(detail_win, text="源代码", padding="5")
        code_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        code_text = scrolledtext.ScrolledText(code_frame, wrap=tk.WORD, width=80, height=20)
        code_text.pack(fill=tk.BOTH, expand=True)
        
        try:
            source = inspect.getsource(metadata['original_func'])
            code_text.insert(tk.END, source)
            code_text.config(state=tk.DISABLED)
        except Exception as e:
            code_text.insert(tk.END, f"无法获取源代码: {str(e)}")
            code_text.config(state=tk.DISABLED)
    
    def _reaccelerate_function(self):
        """重新加速函数"""
        selected = self.functions_tree.selection()
        if not selected:
            return
        
        item = self.functions_tree.item(selected[0])
        func_id_short = item['values'][0]
        
        # 查找完整ID
        full_id = None
        for fid in self.accelerator._function_metadata.keys():
            if fid.startswith(func_id_short[:8]):
                full_id = fid
                break
        
        if not full_id:
            return
        
        metadata = self.accelerator._function_metadata[full_id]
        
        # 使用新方法重新加速
        new_method = AccelerationMethod[
            simpledialog.askstring(
                "选择加速方法",
                "输入新的加速方法:",
                initialvalue=metadata['method'].name,
                parent=self.root
            )
        ]
        
        try:
            new_func = self.accelerator._create_acceleration_wrapper(
                metadata['original_func'],
                new_method
            )
            
            # 更新元数据
            self.accelerator._function_metadata[full_id]['method'] = new_method
            self.accelerator._function_metadata[full_id]['accelerated_func'] = new_func
            self.accelerator._function_metadata[full_id]['timestamp'] = time.time()
            
            messagebox.showinfo(
                "成功" if self.accelerator.config.gui_language == "zh_CN" else "Success",
                "函数已重新加速" if self.accelerator.config.gui_language == "zh_CN" else "Function re-accelerated"
            )
            
            self._refresh_functions()
        except Exception as e:
            messagebox.showerror(
                "错误" if self.accelerator.config.gui_language == "zh_CN" else "Error",
                f"重新加速失败: {str(e)}" if self.accelerator.config.gui_language == "zh_CN" else f"Failed to re-accelerate: {str(e)}"
            )
    
    def _clear_function_cache(self):
        """清除函数缓存"""
        selected = self.functions_tree.selection()
        if not selected:
            return
        
        item = self.functions_tree.item(selected[0])
        func_id_short = item['values'][0]
        
        # 查找完整ID
        full_id = None
        for fid in self.accelerator._function_metadata.keys():
            if fid.startswith(func_id_short[:8]):
                full_id = fid
                break
        
        if not full_id:
            return
        
        # 从缓存中删除
        if full_id in self.accelerator._function_cache:
            del self.accelerator._function_cache[full_id]
        
        # 从元数据中删除
        if full_id in self.accelerator._function_metadata:
            del self.accelerator._function_metadata[full_id]
        
        messagebox.showinfo(
            "成功" if self.accelerator.config.gui_language == "zh_CN" else "Success",
            "函数缓存已清除" if self.accelerator.config.gui_language == "zh_CN" else "Function cache cleared"
        )
        
        self._refresh_functions()
    
    def _accelerate_new_function(self):
        """加速新函数"""
        # 创建对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("加速新函数" if self.accelerator.config.gui_language == "zh_CN" else "Accelerate New Function")
        
        # 函数代码输入
        ttk.Label(dialog, text="输入函数代码:").pack(anchor=tk.W, padx=5, pady=5)
        
        code_text = scrolledtext.ScrolledText(dialog, wrap=tk.WORD, width=80, height=15)
        code_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 加速方法选择
        method_frame = ttk.Frame(dialog)
        method_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(method_frame, text="加速方法:").pack(side=tk.LEFT)
        
        method_var = tk.StringVar(value=self.accelerator.config.default_acceleration.name)
        method_menu = ttk.Combobox(
            method_frame,
            textvariable=method_var,
            values=[m.name for m in AccelerationMethod],
            state="readonly"
        )
        method_menu.pack(side=tk.LEFT, padx=5)
        
        # 参数选项
        options_frame = ttk.LabelFrame(dialog, text="选项", padding="5")
        options_frame.pack(fill=tk.X, padx=5, pady=5)
        
        parallel_var = tk.BooleanVar(value=self.accelerator.config.auto_parallel)
        ttk.Checkbutton(
            options_frame,
            text="并行",
            variable=parallel_var
        ).pack(side=tk.LEFT, padx=5)
        
        vectorize_var = tk.BooleanVar(value=self.accelerator.config.auto_vectorize)
        ttk.Checkbutton(
            options_frame,
            text="向量化",
            variable=vectorize_var
        ).pack(side=tk.LEFT, padx=5)
        
        # 按钮
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        def on_ok():
            """确定按钮回调"""
            try:
                # 获取函数代码
                code = code_text.get("1.0", tk.END).strip()
                if not code:
                    raise ValueError("函数代码不能为空")
                
                # 创建函数
                namespace = {}
                exec(code, namespace)
                
                # 查找函数对象
                func = None
                for obj in namespace.values():
                    if inspect.isfunction(obj):
                        func = obj
                        break
                
                if not func:
                    raise ValueError("未找到有效的函数定义")
                
                # 加速函数
                method = AccelerationMethod[method_var.get()]
                self.accelerator.accelerate(
                    func,
                    method=method,
                    parallel=parallel_var.get(),
                    vectorize=vectorize_var.get()
                )
                
                messagebox.showinfo(
                    "成功" if self.accelerator.config.gui_language == "zh_CN" else "Success",
                    "函数已成功加速" if self.accelerator.config.gui_language == "zh_CN" else "Function accelerated successfully"
                )
                
                self._refresh_functions()
                dialog.destroy()
            except Exception as e:
                messagebox.showerror(
                    "错误" if self.accelerator.config.gui_language == "zh_CN" else "Error",
                    f"加速失败: {str(e)}" if self.accelerator.config.gui_language == "zh_CN" else f"Failed to accelerate: {str(e)}"
                )
        
        ttk.Button(
            btn_frame,
            text="确定",
            command=on_ok
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            btn_frame,
            text="取消",
            command=dialog.destroy
        ).pack(side=tk.RIGHT, padx=5)
    
    def _add_tasks_tab(self, notebook):
        """添加任务选项卡"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="任务" if self.accelerator.config.gui_language == "zh_CN" else "Tasks")
        
        # 工具栏
        toolbar = ttk.Frame(tab)
        toolbar.pack(fill=tk.X, pady=5)
        
        ttk.Button(
            toolbar,
            text="刷新",
            command=self._refresh_tasks
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            toolbar,
            text="提交新任务",
            command=self._submit_new_task
        ).pack(side=tk.LEFT, padx=5)
        
        # 任务列表
        columns = ("id", "function", "priority", "status", "created", "elapsed")
        self.tasks_tree = ttk.Treeview(
            tab,
            columns=columns,
            show="headings",
            selectmode="browse"
        )
        
        # 设置列
        self.tasks_tree.heading("id", text="ID")
        self.tasks_tree.heading("function", text="函数")
        self.tasks_tree.heading("priority", text="优先级")
        self.tasks_tree.heading("status", text="状态")
        self.tasks_tree.heading("created", text="创建时间")
        self.tasks_tree.heading("elapsed", text="耗时")
        
        # 设置列宽
        self.tasks_tree.column("id", width=50, anchor=tk.CENTER)
        self.tasks_tree.column("function", width=150, anchor=tk.W)
        self.tasks_tree.column("priority", width=80, anchor=tk.W)
        self.tasks_tree.column("status", width=100, anchor=tk.W)
        self.tasks_tree.column("created", width=120, anchor=tk.CENTER)
        self.tasks_tree.column("elapsed", width=80, anchor=tk.CENTER)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.tasks_tree.yview)
        self.tasks_tree.configure(yscrollcommand=scrollbar.set)
        
        self.tasks_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 右键菜单
        self.task_menu = tk.Menu(self.tasks_tree, tearoff=0)
        self.task_menu.add_command(
            label="查看详情",
            command=self._show_task_details
        )
        self.task_menu.add_command(
            label="取消任务",
            command=self._cancel_task
        )
        
        self.tasks_tree.bind("<Button-3>", self._show_task_menu)
        
        # 初始加载数据
        self._refresh_tasks()
    
    def _refresh_tasks(self):
        """刷新任务列表"""
        # TODO: 实现任务列表刷新逻辑
        pass
    
    def _show_task_menu(self, event):
        """显示任务右键菜单"""
        item = self.tasks_tree.identify_row(event.y)
        if item:
            self.tasks_tree.selection_set(item)
            self.task_menu.post(event.x_root, event.y_root)
    
    def _show_task_details(self):
        """显示任务详情"""
        # TODO: 实现任务详情显示逻辑
        pass
    
    def _cancel_task(self):
        """取消任务"""
        # TODO: 实现任务取消逻辑
        pass
    
    def _submit_new_task(self):
        """提交新任务"""
        # TODO: 实现新任务提交逻辑
        pass
    
    def _add_cache_tab(self, notebook):
        """添加缓存选项卡"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="缓存" if self.accelerator.config.gui_language == "zh_CN" else "Cache")
        
        # 工具栏
        toolbar = ttk.Frame(tab)
        toolbar.pack(fill=tk.X, pady=5)
        
        ttk.Button(
            toolbar,
            text="刷新",
            command=self._refresh_cache
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            toolbar,
            text="清空缓存",
            command=self._clear_cache
        ).pack(side=tk.LEFT, padx=5)
        
        # 缓存统计
        stats_frame = ttk.LabelFrame(tab, text="缓存统计", padding="5")
        stats_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.cache_stats_label = ttk.Label(stats_frame, text="加载中...")
        self.cache_stats_label.pack(anchor=tk.W)
        
        # 缓存项目列表
        columns = ("key", "size", "access", "created")
        self.cache_tree = ttk.Treeview(
            tab,
            columns=columns,
            show="headings",
            selectmode="browse"
        )
        
        # 设置列
        self.cache_tree.heading("key", text="键")
        self.cache_tree.heading("size", text="大小")
        self.cache_tree.heading("access", text="最后访问")
        self.cache_tree.heading("created", text="创建时间")
        
        # 设置列宽
        self.cache_tree.column("key", width=200, anchor=tk.W)
        self.cache_tree.column("size", width=100, anchor=tk.CENTER)
        self.cache_tree.column("access", width=150, anchor=tk.CENTER)
        self.cache_tree.column("created", width=150, anchor=tk.CENTER)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.cache_tree.yview)
        self.cache_tree.configure(yscrollcommand=scrollbar.set)
        
        self.cache_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 右键菜单
        self.cache_menu = tk.Menu(self.cache_tree, tearoff=0)
        self.cache_menu.add_command(
            label="查看详情",
            command=self._show_cache_item_details
        )
        self.cache_menu.add_command(
            label="删除",
            command=self._delete_cache_item
        )
        
        self.cache_tree.bind("<Button-3>", self._show_cache_menu)
        
        # 初始加载数据
        self._refresh_cache()
    
    def _refresh_cache(self):
        """刷新缓存信息"""
        if not self.accelerator._cache:
            self.cache_stats_label.config(text="缓存未启用")
            return
        
        stats = self.accelerator._cache.stats()
        self.cache_stats_label.config(text=(
            f"总大小: {stats['size'] / (1024 * 1024):.2f} MB | "
            f"项目数: {stats['count']} | "
            f"命中率: {stats['ratio'] * 100:.1f}%"
        ))
        
        # TODO: 加载缓存项目列表
    
    def _show_cache_menu(self, event):
        """显示缓存右键菜单"""
        item = self.cache_tree.identify_row(event.y)
        if item:
            self.cache_tree.selection_set(item)
            self.cache_menu.post(event.x_root, event.y_root)
    
    def _show_cache_item_details(self):
        """显示缓存项目详情"""
        # TODO: 实现缓存项目详情显示
        pass
    
    def _delete_cache_item(self):
        """删除缓存项目"""
        # TODO: 实现缓存项目删除
        pass
    
    def _clear_cache(self):
        """清空缓存"""
        if messagebox.askyesno(
            "确认" if self.accelerator.config.gui_language == "zh_CN" else "Confirm",
            "确定要清空缓存吗?" if self.accelerator.config.gui_language == "zh_CN" else "Are you sure to clear the cache?"
        ):
            if self.accelerator.clear_cache():
                messagebox.showinfo(
                    "成功" if self.accelerator.config.gui_language == "zh_CN" else "Success",
                    "缓存已清空" if self.accelerator.config.gui_language == "zh_CN" else "Cache cleared"
                )
                self._refresh_cache()
            else:
                messagebox.showerror(
                    "错误" if self.accelerator.config.gui_language == "zh_CN" else "Error",
                    "清空缓存失败" if self.accelerator.config.gui_language == "zh_CN" else "Failed to clear cache"
                )
    
    def _add_profiling_tab(self, notebook):
        """添加性能分析选项卡"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="性能分析" if self.accelerator.config.gui_language == "zh_CN" else "Profiling")
        
        # 工具栏
        toolbar = ttk.Frame(tab)
        toolbar.pack(fill=tk.X, pady=5)
        
        ttk.Button(
            toolbar,
            text="刷新",
            command=self._refresh_profiles
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            toolbar,
            text="分析函数",
            command=self._profile_function
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            toolbar,
            text="基准测试",
            command=self._benchmark_function
        ).pack(side=tk.LEFT, padx=5)
        
        # 分析结果列表
        columns = ("name", "avg_time", "min_time", "max_time", "timestamp")
        self.profile_tree = ttk.Treeview(
            tab,
            columns=columns,
            show="headings",
            selectmode="browse"
        )
        
        # 设置列
        self.profile_tree.heading("name", text="函数名")
        self.profile_tree.heading("avg_time", text="平均时间(s)")
        self.profile_tree.heading("min_time", text="最小时间(s)")
        self.profile_tree.heading("max_time", text="最大时间(s)")
        self.profile_tree.heading("timestamp", text="时间戳")
        
        # 设置列宽
        self.profile_tree.column("name", width=150, anchor=tk.W)
        self.profile_tree.column("avg_time", width=100, anchor=tk.CENTER)
        self.profile_tree.column("min_time", width=100, anchor=tk.CENTER)
        self.profile_tree.column("max_time", width=100, anchor=tk.CENTER)
        self.profile_tree.column("timestamp", width=150, anchor=tk.CENTER)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.profile_tree.yview)
        self.profile_tree.configure(yscrollcommand=scrollbar.set)
        
        self.profile_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 右键菜单
        self.profile_menu = tk.Menu(self.profile_tree, tearoff=0)
        self.profile_menu.add_command(
            label="查看详情",
            command=self._show_profile_details
        )
        self.profile_menu.add_command(
            label="删除",
            command=self._delete_profile
        )
        
        self.profile_tree.bind("<Button-3>", self._show_profile_menu)
        
        # 初始加载数据
        self._refresh_profiles()
    
    def _refresh_profiles(self):
        """刷新性能分析列表"""
        # TODO: 实现性能分析列表刷新逻辑
        pass
    
    def _show_profile_menu(self, event):
        """显示性能分析右键菜单"""
        item = self.profile_tree.identify_row(event.y)
        if item:
            self.profile_tree.selection_set(item)
            self.profile_menu.post(event.x_root, event.y_root)
    
    def _show_profile_details(self):
        """显示性能分析详情"""
        # TODO: 实现性能分析详情显示逻辑
        pass
    
    def _delete_profile(self):
        """删除性能分析结果"""
        # TODO: 实现性能分析结果删除逻辑
        pass
    
    def _profile_function(self):
        """分析函数性能"""
        # TODO: 实现函数性能分析逻辑
        pass
    
    def _benchmark_function(self):
        """基准测试函数"""
        # TODO: 实现函数基准测试逻辑
        pass
    
    def _setup_statusbar(self):
        """设置状态栏"""
        self.status_var = tk.StringVar()
        self.status_var.set("就绪" if self.accelerator.config.gui_language == "zh_CN" else "Ready")
        
        self.status_bar = ttk.Label(
            self.root,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor=tk.W
        )
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
    
    def _schedule_updates(self):
        """定时更新UI"""
        self._update_resource_charts()
        self.root.after(1000, self._schedule_updates)
    
    def _update_resource_charts(self):
        """更新资源图表"""
        self._draw_resource_charts()
    
    def _refresh_all(self):
        """刷新所有数据"""
        self._refresh_functions()
        self._refresh_tasks()
        self._refresh_cache()
        self._refresh_profiles()
        self._update_resource_charts()
    
    def _run_test(self):
        """运行测试函数"""
        # TODO: 实现测试函数运行逻辑
        pass
    
    def _show_system_info(self):
        """显示系统信息"""
        info = self.accelerator.get_system_info()
        
        info_win = tk.Toplevel(self.root)
        info_win.title("系统信息" if self.accelerator.config.gui_language == "zh_CN" else "System Information")
        
        text = scrolledtext.ScrolledText(info_win, wrap=tk.WORD, width=80, height=25)
        text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        info_text = (
            f"CPU名称: {info.cpu_name}\n"
            f"物理核心数: {info.cpu_physical_cores}\n"
            f"逻辑核心数: {info.cpu_logical_cores}\n"
            f"当前CPU频率: {info.cpu_freq['current']:.2f} MHz\n"
            f"最小CPU频率: {info.cpu_freq['min']:.2f} MHz\n"
            f"最大CPU频率: {info.cpu_freq['max']:.2f} MHz\n"
            f"当前CPU使用率: {info.cpu_usage:.1f}%\n\n"
            f"总内存: {info.memory_total:.2f} GB\n"
            f"可用内存: {info.memory_available:.2f} GB\n"
            f"已用内存: {info.memory_used:.2f} GB\n"
            f"内存使用率: {info.memory_percent:.1f}%\n\n"
            f"总交换空间: {info.swap_total:.2f} GB\n"
            f"已用交换空间: {info.swap_used:.2f} GB\n"
            f"交换空间使用率: {info.swap_percent:.1f}%\n\n"
            f"操作系统: {info.platform}\n"
            f"系统架构: {info.architecture}\n"
            f"Python版本: {info.python_version}\n"
        )
        
        text.insert(tk.END, info_text)
        text.config(state=tk.DISABLED)
    
    def _show_about(self):
        """显示关于对话框"""
        about_win = tk.Toplevel(self.root)
        about_win.title("关于" if self.accelerator.config.gui_language == "zh_CN" else "About")
        
        about_frame = ttk.Frame(about_win, padding="10")
        about_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(
            about_frame,
            text="CPU加速计算插件",
            font=(self.accelerator.config.gui_font, 14, 'bold')
        ).pack(pady=5)
        
        ttk.Label(
            about_frame,
            text="版本: 2.0"
        ).pack(pady=2)
        
        ttk.Label(
            about_frame,
            text="作者: 杜玛"
        ).pack(pady=2)
        
        ttk.Label(
            about_frame,
            text="这是一个高性能的CPU加速计算框架，\n支持多种加速方法和任务管理。",
            justify=tk.CENTER
        ).pack(pady=10)
        
        ttk.Button(
            about_frame,
            text="确定",
            command=about_win.destroy
        ).pack(pady=5)
    
    def run(self):
        """运行GUI主循环"""
        self.root.mainloop()
    
    def cleanup(self):
        """清理资源"""
        if not hasattr(self, '_cleaned_up'):
            self._cleaned_up = True
            if hasattr(self, 'root'):
                try:
                    if self.root.winfo_exists():
                        self.root.quit()
                        self.root.destroy()
                except Exception as e:
                    logger.warning(f"清理GUI资源时发生异常: {str(e)}")
            logger.info("GUI资源已清理")


# 便捷装饰器
def accelerate(**kwargs):
    """
    加速装饰器
    
    示例:
        @accelerate(method=AccelerationMethod.NUMBA_NJIT, parallel=True)
        def my_func(x):
            return x * 2
    """
    def decorator(func):
        accelerator = CPUAccelerator()
        return accelerator.accelerate(func, **kwargs)
    return decorator

# 模块初始化
def init(config: Optional[PluginConfig] = None) -> CPUAccelerator:
    """初始化CPU加速器"""
    return CPUAccelerator(config)

# 测试代码
if __name__ == "__main__":
    # 初始化加速器
    accelerator = init()
    
    try:
        # 如果有GUI则显示
        if accelerator.gui:
            accelerator.gui.run()
        else:
            # 无GUI时的测试代码
            @accelerate(method=AccelerationMethod.NUMBA_NJIT)
            def calculate_sum(n: int) -> int:
                total = 0
                for i in range(n):
                    total += i
                return total
            
            result = calculate_sum(10_000_000)
            print(f"计算结果: {result}")
    finally:
        accelerator.shutdown()