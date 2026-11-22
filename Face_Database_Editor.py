# -*- coding: utf-8 -*-
import sys
import os
import sqlite3
import logging
import csv
import json
import shutil
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QTableWidget, QTableWidgetItem, QPushButton, QLabel, 
                            QFileDialog, QMessageBox, QInputDialog, QHeaderView, 
                            QMenu, QAction, QSizePolicy, QSplitter, QLineEdit, 
                            QComboBox, QFormLayout, QGroupBox, QProgressDialog, 
                            QCheckBox, QTabWidget, QScrollArea, QDialog, QDialogButtonBox)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QThread, QSize, QDateTime
from PyQt5.QtGui import QCursor, QPixmap, QImage, QIcon, QPainter, QColor

# ============================================================================
# 目录约定（v2.0.0）：调试日志统一放到 logs\ 子目录，不在程序根目录产生日志文件
# ============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# 配置日志记录
logging.basicConfig(
    filename=os.path.join(LOG_DIR, 'face_database_editor.log'),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
logger = logging.getLogger(__name__)

class ImageProcessorThread(QThread):
    """图片处理线程"""
    process_complete = pyqtSignal(str, str)  # 信号：原路径, 新路径
    
    def __init__(self, image_path, output_dir, process_type, size=None, quality=None):
        super().__init__()
        self.image_path = image_path
        self.output_dir = output_dir
        self.process_type = process_type  # 'resize', 'compress', 'convert'
        self.size = size or (300, 300)
        self.quality = quality or 85
        self.target_format = 'JPEG'  # 默认转换为JPEG
    
    def run(self):
        try:
            if not os.path.exists(self.image_path):
                self.process_complete.emit(self.image_path, "源文件不存在")
                return
            
            # 创建输出目录
            os.makedirs(self.output_dir, exist_ok=True)
            
            # 生成输出文件名
            filename = os.path.basename(self.image_path)
            name, ext = os.path.splitext(filename)
            
            if self.process_type == 'convert':
                new_filename = f"{name}.jpg"
            else:
                new_filename = filename
            
            output_path = os.path.join(self.output_dir, new_filename)
            
            # 处理图片
            image = QImage(self.image_path)
            if image.isNull():
                self.process_complete.emit(self.image_path, "无法加载图片")
                return
            
            if self.process_type == 'resize':
                scaled_image = image.scaled(
                    QSize(*self.size), 
                    Qt.KeepAspectRatio, 
                    Qt.SmoothTransformation
                )
                success = scaled_image.save(output_path, quality=100)
            elif self.process_type == 'compress':
                success = image.save(output_path, quality=self.quality)
            elif self.process_type == 'convert':
                success = image.save(output_path, self.target_format, quality=self.quality)
            else:
                self.process_complete.emit(self.image_path, "未知处理类型")
                return
            
            if success:
                self.process_complete.emit(self.image_path, output_path)
            else:
                self.process_complete.emit(self.image_path, "保存失败")
                
        except Exception as e:
            self.process_complete.emit(self.image_path, f"处理出错: {str(e)}")

class DatabaseBackupThread(QThread):
    """数据库备份线程"""
    backup_complete = pyqtSignal(bool, str)  # 信号：是否成功, 消息
    
    def __init__(self, source_db, backup_dir):
        super().__init__()
        self.source_db = source_db
        self.backup_dir = backup_dir
    
    def run(self):
        try:
            if not os.path.exists(self.source_db):
                self.backup_complete.emit(False, "源数据库不存在")
                return
            
            os.makedirs(self.backup_dir, exist_ok=True)
            
            # 生成带时间戳的备份文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            db_name = os.path.basename(self.source_db)
            backup_name = f"{os.path.splitext(db_name)[0]}_backup_{timestamp}.db"
            backup_path = os.path.join(self.backup_dir, backup_name)
            
            # 复制数据库文件
            shutil.copy2(self.source_db, backup_path)
            
            # 验证备份是否成功
            if os.path.exists(backup_path):
                self.backup_complete.emit(True, f"备份成功: {backup_path}")
            else:
                self.backup_complete.emit(False, "备份文件创建失败")
                
        except Exception as e:
            self.backup_complete.emit(False, f"备份出错: {str(e)}")

class BatchImportThread(QThread):
    """批量导入线程"""
    progress_signal = pyqtSignal(int, int, str)  # 当前, 总数, 当前文件名
    import_complete = pyqtSignal(bool, str)     # 是否成功, 消息
    
    def __init__(self, db_path, import_dir, naming_rule, name_prefix=""):
        super().__init__()
        self.db_path = db_path
        self.import_dir = import_dir
        self.naming_rule = naming_rule  # 'filename', 'serial', 'custom'
        self.name_prefix = name_prefix
        self.cancel_flag = False
    
    def run(self):
        try:
            # 获取所有图片文件
            valid_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.gif')
            image_files = [
                f for f in os.listdir(self.import_dir) 
                if os.path.splitext(f)[1].lower() in valid_extensions
            ]
            
            if not image_files:
                self.import_complete.emit(False, "没有找到有效的图片文件")
                return
            
            total = len(image_files)
            success_count = 0
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            for i, filename in enumerate(image_files):
                if self.cancel_flag:
                    break
                
                self.progress_signal.emit(i+1, total, filename)
                
                try:
                    image_path = os.path.join(self.import_dir, filename)
                    
                    # 根据命名规则确定姓名
                    if self.naming_rule == 'filename':
                        name = os.path.splitext(filename)[0]
                    elif self.naming_rule == 'serial':
                        name = f"{self.name_prefix}{i+1}"
                    else:  # custom
                        name = self.name_prefix
                    
                    # 检查是否已存在相同记录
                    cursor.execute(
                        "SELECT COUNT(*) FROM faces WHERE name=? AND image_path=?",
                        (name, image_path))
                    if cursor.fetchone()[0] > 0:
                        continue
                    
                    # 插入记录
                    cursor.execute(
                        "INSERT INTO faces (name, image_path) VALUES (?, ?)",
                        (name, image_path)
                    )
                    success_count += 1
                    
                except Exception as e:
                    logger.error(f"导入图片 {filename} 出错: {str(e)}")
                    continue
            
            conn.commit()
            conn.close()
            
            if self.cancel_flag:
                self.import_complete.emit(False, f"用户取消，已导入 {success_count}/{total} 条记录")
            else:
                self.import_complete.emit(True, f"成功导入 {success_count}/{total} 条记录")
                
        except Exception as e:
            self.import_complete.emit(False, f"批量导入出错: {str(e)}")

class SortableTableWidget(QTableWidget):
    """可排序的表格控件"""
    headerClicked = pyqtSignal(int)  # 表头点击信号
    rightClicked = pyqtSignal()      # 右键点击信号
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sort_order = Qt.AscendingOrder  # 默认升序
        self._sort_column = 0  # 默认按第一列排序
        self.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.on_right_click)
    
    def on_header_clicked(self, column):
        """表头点击事件处理"""
        try:
            if column == self._sort_column:
                # 同一列点击，切换排序顺序
                self._sort_order = Qt.DescendingOrder if self._sort_order == Qt.AscendingOrder else Qt.AscendingOrder
            else:
                # 不同列点击，默认升序
                self._sort_order = Qt.AscendingOrder
                self._sort_column = column
            
            self.headerClicked.emit(column)
            self.sortItems(column, self._sort_order)
        except Exception as e:
            logger.error(f"表头排序出错: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"排序时发生错误: {str(e)}")
    
    def on_right_click(self, pos):
        """右键点击事件处理"""
        try:
            self.rightClicked.emit()
        except Exception as e:
            logger.error(f"右键菜单出错: {str(e)}", exc_info=True)

class SettingsDialog(QDialog):
    """设置对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setWindowIcon(QIcon(":settings.png"))
        self.resize(500, 400)
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # 创建标签页
        tab_widget = QTabWidget()
        
        # 常规设置标签页
        general_tab = QWidget()
        general_layout = QFormLayout(general_tab)
        
        self.auto_backup_check = QCheckBox("自动备份数据库")
        self.backup_interval = QComboBox()
        self.backup_interval.addItems(["每次修改时", "每天", "每周", "每月"])
        
        self.auto_load_check = QCheckBox("启动时自动加载上次的数据库")
        self.remember_window_size_check = QCheckBox("记住窗口大小和位置")
        
        general_layout.addRow(self.auto_backup_check)
        general_layout.addRow("备份频率:", self.backup_interval)
        general_layout.addRow(self.auto_load_check)
        general_layout.addRow(self.remember_window_size_check)
        
        # 图片设置标签页
        image_tab = QWidget()
        image_layout = QFormLayout(image_tab)
        
        self.preview_size = QComboBox()
        self.preview_size.addItems(["小 (200x200)", "中 (300x300)", "大 (400x400)"])
        
        self.image_quality = QComboBox()
        self.image_quality.addItems(["低 (70%)", "中 (85%)", "高 (100%)"])
        
        self.default_image_dir = QLineEdit()
        self.browse_image_dir_btn = QPushButton("浏览...")
        self.browse_image_dir_btn.clicked.connect(self.browse_image_dir)
        
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(self.default_image_dir)
        dir_layout.addWidget(self.browse_image_dir_btn)
        
        image_layout.addRow("预览图大小:", self.preview_size)
        image_layout.addRow("图片质量:", self.image_quality)
        image_layout.addRow("默认图片目录:", dir_layout)
        
        # 添加标签页
        tab_widget.addTab(general_tab, "常规")
        tab_widget.addTab(image_tab, "图片")
        
        # 按钮框
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        layout.addWidget(tab_widget)
        layout.addWidget(button_box)
        
        self.setLayout(layout)
    
    def browse_image_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择默认图片目录")
        if dir_path:
            self.default_image_dir.setText(dir_path)

class FaceDatabaseEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("人脸数据库编辑器 v1.6.2")
        self.setGeometry(100, 100, 1200, 800)
        
        # 数据库路径
        self.db_path = 'face_database.db'
        self.last_backup_time = None
        
        # 搜索相关变量
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.perform_search)
        
        # 自动备份计时器
        self.auto_backup_timer = QTimer()
        self.auto_backup_timer.timeout.connect(self.auto_backup)
        
        # 初始化UI
        self.init_ui()
        
        # 加载数据库
        self.load_database()
        
        # 检查数据库是否存在，不存在则创建
        self.initialize_database()
    
    def init_ui(self):
        """初始化用户界面"""
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # 顶部固定区域
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(5)
        
        # 数据库路径显示
        self.db_label = QLabel(f"当前数据库: {self.db_path}")
        top_layout.addWidget(self.db_label)
        
        # 搜索区域
        search_group = QGroupBox("搜索")
        search_layout = QFormLayout(search_group)
        
        self.search_field = QComboBox()
        self.search_field.addItems(["ID", "姓名", "图片路径", "创建时间", "最后访问时间"])
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入搜索内容...")
        self.search_input.textChanged.connect(self.on_search_text_changed)
        
        search_layout.addRow("搜索字段:", self.search_field)
        search_layout.addRow("搜索内容:", self.search_input)
        
        top_layout.addWidget(search_group)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        
        self.btn_open = QPushButton("打开数据库")
        self.btn_open.clicked.connect(self.open_database)
        self.btn_open.setToolTip("打开不同的人脸数据库文件")
        
        self.btn_add = QPushButton("添加记录")
        self.btn_add.clicked.connect(self.add_record)
        self.btn_add.setToolTip("添加新的人脸记录")
        
        self.btn_edit = QPushButton("编辑记录")
        self.btn_edit.clicked.connect(self.edit_record)
        self.btn_edit.setToolTip("编辑选中的记录")
        
        self.btn_delete = QPushButton("删除记录")
        self.btn_delete.clicked.connect(self.delete_record)
        self.btn_delete.setToolTip("删除选中的记录")
        
        self.btn_export = QPushButton("导出数据")
        self.btn_export.clicked.connect(self.export_data)
        self.btn_export.setToolTip("将数据导出为CSV或JSON文件")
        
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.load_database)
        self.btn_refresh.setToolTip("重新加载数据库")
        
        self.btn_clear_search = QPushButton("清除搜索")
        self.btn_clear_search.clicked.connect(self.clear_search)
        self.btn_clear_search.setToolTip("清除当前搜索条件")
        
        # 添加更多功能按钮
        self.btn_batch_import = QPushButton("批量导入")
        self.btn_batch_import.clicked.connect(self.batch_import)
        self.btn_batch_import.setToolTip("批量导入图片到数据库")
        
        self.btn_backup = QPushButton("备份")
        self.btn_backup.clicked.connect(self.manual_backup)
        self.btn_backup.setToolTip("备份当前数据库")
        
        self.btn_settings = QPushButton("设置")
        self.btn_settings.clicked.connect(self.show_settings)
        self.btn_settings.setToolTip("程序设置")
        
        btn_layout.addWidget(self.btn_open)
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_edit)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.btn_clear_search)
        btn_layout.addWidget(self.btn_batch_import)
        btn_layout.addWidget(self.btn_backup)
        btn_layout.addWidget(self.btn_settings)
        
        top_layout.addLayout(btn_layout)
        
        # 将顶部区域添加到主布局
        main_layout.addWidget(top_widget)
        
        # 创建分割器用于表格和图片预览
        splitter = QSplitter(Qt.Horizontal)
        
        # 左侧表格
        self.table = SortableTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID", "姓名", "图片路径", "创建时间", "最后访问时间"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # 设置列宽 - 让图片路径列自动拉伸
        self.table.setColumnWidth(0, 60)   # ID列固定宽度
        self.table.setColumnWidth(1, 150)  # 姓名列固定宽度
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)  # 图片路径列自动拉伸
        self.table.setColumnWidth(3, 150)  # 创建时间列固定宽度
        self.table.setColumnWidth(4, 150)  # 最后访问时间列固定宽度
        
        # 右侧区域 - 使用标签页
        right_tab = QTabWidget()
        
        # 图片预览标签页
        preview_tab = QWidget()
        preview_layout = QVBoxLayout(preview_tab)
        preview_layout.setContentsMargins(5, 0, 5, 5)
        
        self.image_label = QLabel("选择记录查看图片")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("""
            border: 1px solid #ccc; 
            background: #f8f8f8;
            min-width: 300px;
            min-height: 300px;
        """)
        
        self.image_info = QLabel()
        self.image_info.setAlignment(Qt.AlignCenter)
        self.image_info.setStyleSheet("font-size: 12px; margin-top: 5px;")
        
        # 图片操作按钮
        image_btn_layout = QHBoxLayout()
        
        self.btn_save_image = QPushButton("保存图片")
        self.btn_save_image.clicked.connect(self.save_image_as)
        self.btn_save_image.setToolTip("将当前图片另存为")
        
        self.btn_process_image = QPushButton("处理图片")
        self.btn_process_image.clicked.connect(self.process_image)
        self.btn_process_image.setToolTip("调整图片大小或质量")
        
        image_btn_layout.addWidget(self.btn_save_image)
        image_btn_layout.addWidget(self.btn_process_image)
        
        preview_layout.addWidget(self.image_label)
        preview_layout.addWidget(self.image_info)
        preview_layout.addLayout(image_btn_layout)
        
        # 统计信息标签页
        stats_tab = QWidget()
        stats_layout = QVBoxLayout(stats_tab)
        
        self.stats_label = QLabel("数据库统计信息")
        self.stats_label.setAlignment(Qt.AlignCenter)
        self.stats_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        
        self.stats_content = QLabel()
        self.stats_content.setAlignment(Qt.AlignLeft)
        self.stats_content.setStyleSheet("font-size: 12px;")
        
        stats_layout.addWidget(self.stats_label)
        stats_layout.addWidget(self.stats_content)
        stats_layout.addStretch()
        
        # 添加标签页
        right_tab.addTab(preview_tab, "图片预览")
        right_tab.addTab(stats_tab, "统计信息")
        
        # 将表格和预览添加到分割器
        splitter.addWidget(self.table)
        splitter.addWidget(right_tab)
        splitter.setStretchFactor(0, 3)  # 表格区域占3份
        splitter.setStretchFactor(1, 1)  # 预览区域占1份
        
        # 将分割器添加到主布局
        main_layout.addWidget(splitter, stretch=1)
        
        # 连接信号
        self.table.headerClicked.connect(self.on_table_header_clicked)
        self.table.rightClicked.connect(self.show_context_menu)
        self.table.doubleClicked.connect(self.edit_record)
        self.table.itemSelectionChanged.connect(self.update_image_preview)
        self.table.itemSelectionChanged.connect(self.update_stats)
        
        # 状态栏
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("就绪")
        
        self.setCentralWidget(main_widget)
        
        # 初始化右键菜单
        self.init_context_menu()
        
        # 加载设置
        self.load_settings()
        
        # 启动自动备份检查
        self.setup_auto_backup()
    
    def initialize_database(self):
        """初始化数据库，如果不存在则创建"""
        if not os.path.exists(self.db_path):
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # 创建表
                cursor.execute('''
                    CREATE TABLE faces (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        image_path TEXT,
                        create_time TEXT DEFAULT (datetime('now', 'localtime')),
                        last_access_time TEXT DEFAULT (datetime('now', 'localtime'))
                    )
                ''')
                
                # 创建索引
                cursor.execute('CREATE INDEX idx_name ON faces (name)')
                cursor.execute('CREATE INDEX idx_image_path ON faces (image_path)')
                
                conn.commit()
                conn.close()
                
                logger.info(f"创建新数据库: {self.db_path}")
                self.status_bar.showMessage(f"已创建新数据库: {self.db_path}")
                
            except Exception as e:
                logger.error(f"初始化数据库出错: {str(e)}", exc_info=True)
                QMessageBox.critical(self, "错误", f"初始化数据库失败: {str(e)}")
    
    def load_settings(self):
        """加载程序设置"""
        try:
            # 这里应该是从配置文件或数据库加载设置
            # 示例代码，实际应用中应该从持久化存储加载
            self.settings = {
                'auto_backup': True,
                'backup_interval': '每次修改时',
                'preview_size': '中 (300x300)',
                'image_quality': '中 (85%)',
                'default_image_dir': os.path.expanduser('~/Pictures')
            }
        except Exception as e:
            logger.error(f"加载设置出错: {str(e)}", exc_info=True)
            self.settings = {}
    
    def save_settings(self):
        """保存程序设置"""
        try:
            # 这里应该是将设置保存到配置文件或数据库
            pass
        except Exception as e:
            logger.error(f"保存设置出错: {str(e)}", exc_info=True)
    
    def setup_auto_backup(self):
        """设置自动备份"""
        if self.settings.get('auto_backup', False):
            interval = self.settings.get('backup_interval', '每次修改时')
            
            if interval == '每次修改时':
                # 通过数据库操作触发备份
                pass
            elif interval == '每天':
                self.auto_backup_timer.start(24 * 60 * 60 * 1000)  # 24小时
            elif interval == '每周':
                self.auto_backup_timer.start(7 * 24 * 60 * 60 * 1000)  # 7天
            elif interval == '每月':
                self.auto_backup_timer.start(30 * 24 * 60 * 60 * 1000)  # 30天
    
    def auto_backup(self):
        """自动备份数据库"""
        try:
            backup_dir = os.path.join(os.path.dirname(self.db_path), 'backups')
            os.makedirs(backup_dir, exist_ok=True)
            
            # 使用线程进行备份
            self.backup_thread = DatabaseBackupThread(self.db_path, backup_dir)
            self.backup_thread.backup_complete.connect(self.on_backup_complete)
            self.backup_thread.start()
            
            self.status_bar.showMessage("正在自动备份数据库...")
            
        except Exception as e:
            logger.error(f"自动备份出错: {str(e)}", exc_info=True)
    
    def manual_backup(self):
        """手动备份数据库"""
        try:
            backup_dir = QFileDialog.getExistingDirectory(
                self, "选择备份目录", 
                os.path.join(os.path.dirname(self.db_path), 'backups'))
            
            if not backup_dir:
                return
                
            # 显示进度对话框
            progress = QProgressDialog("正在备份数据库...", "取消", 0, 0, self)
            progress.setWindowTitle("备份")
            progress.setWindowModality(Qt.WindowModal)
            progress.setCancelButton(None)  # 暂时禁用取消按钮
            progress.show()
            
            # 使用线程进行备份
            self.backup_thread = DatabaseBackupThread(self.db_path, backup_dir)
            self.backup_thread.backup_complete.connect(lambda ok, msg: self.on_backup_complete(ok, msg, progress))
            self.backup_thread.start()
            
        except Exception as e:
            logger.error(f"手动备份出错: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"备份失败: {str(e)}")
    
    def on_backup_complete(self, success, message, progress=None):
        """备份完成处理"""
        if progress:
            progress.close()
            
        if success:
            self.status_bar.showMessage(message)
            logger.info(message)
            self.last_backup_time = datetime.now()
        else:
            QMessageBox.warning(self, "备份失败", message)
            logger.error(message)
    
    def show_settings(self):
        """显示设置对话框"""
        dialog = SettingsDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            # 保存设置
            self.save_settings()
    
    def batch_import(self):
        """批量导入图片"""
        try:
            # 选择图片目录
            import_dir = QFileDialog.getExistingDirectory(
                self, "选择包含图片的目录", 
                self.settings.get('default_image_dir', ''))
            
            if not import_dir:
                return
                
            # 显示导入选项对话框
            dialog = QDialog(self)
            dialog.setWindowTitle("批量导入选项")
            layout = QFormLayout(dialog)
            
            naming_rule = QComboBox()
            naming_rule.addItems(["使用文件名作为姓名", "使用序号作为姓名", "使用自定义姓名"])
            
            name_prefix = QLineEdit()
            name_prefix.setPlaceholderText("输入姓名前缀")
            
            layout.addRow("命名规则:", naming_rule)
            layout.addRow("姓名前缀:", name_prefix)
            
            button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)
            
            layout.addRow(button_box)
            
            if dialog.exec_() != QDialog.Accepted:
                return
                
            # 确定命名规则
            rule_map = {
                0: 'filename',
                1: 'serial',
                2: 'custom'
            }
            selected_rule = rule_map.get(naming_rule.currentIndex(), 'filename')
            
            # 创建进度对话框
            progress = QProgressDialog("正在导入图片...", "取消", 0, 0, self)
            progress.setWindowTitle("批量导入")
            progress.setWindowModality(Qt.WindowModal)
            progress.show()
            
            # 使用线程进行批量导入
            self.import_thread = BatchImportThread(
                self.db_path, 
                import_dir, 
                selected_rule, 
                name_prefix.text())
            
            self.import_thread.progress_signal.connect(
                lambda current, total, name: progress.setLabelText(f"正在导入: {name} ({current}/{total})"))
            
            self.import_thread.import_complete.connect(
                lambda ok, msg: self.on_import_complete(ok, msg, progress))
            
            progress.canceled.connect(self.import_thread.cancel_import)
            
            self.import_thread.start()
            
        except Exception as e:
            logger.error(f"批量导入出错: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"批量导入失败: {str(e)}")
    
    def on_import_complete(self, success, message, progress):
        """导入完成处理"""
        progress.close()
        
        if success:
            QMessageBox.information(self, "完成", message)
            self.load_database()
        else:
            QMessageBox.warning(self, "导入失败", message)
    
    def process_image(self):
        """处理当前图片"""
        try:
            selected_row = self.table.currentRow()
            if selected_row < 0:
                QMessageBox.warning(self, "警告", "请先选择一条记录")
                return
                
            image_path_item = self.table.item(selected_row, 2)
            if not image_path_item or not image_path_item.text() or not os.path.exists(image_path_item.text()):
                QMessageBox.warning(self, "警告", "图片路径无效或图片不存在")
                return
                
            image_path = image_path_item.text()
            
            # 显示处理选项对话框
            dialog = QDialog(self)
            dialog.setWindowTitle("图片处理选项")
            layout = QFormLayout(dialog)
            
            process_type = QComboBox()
            process_type.addItems(["调整大小", "压缩质量", "转换为JPEG"])
            
            size_label = QLabel("新尺寸:")
            width_spin = QSpinBox()
            width_spin.setRange(50, 2000)
            width_spin.setValue(300)
            height_spin = QSpinBox()
            height_spin.setRange(50, 2000)
            height_spin.setValue(300)
            
            size_layout = QHBoxLayout()
            size_layout.addWidget(width_spin)
            size_layout.addWidget(QLabel("x"))
            size_layout.addWidget(height_spin)
            
            quality_slider = QSlider(Qt.Horizontal)
            quality_slider.setRange(10, 100)
            quality_slider.setValue(85)
            quality_value = QLabel("85%")
            
            quality_layout = QHBoxLayout()
            quality_layout.addWidget(quality_slider)
            quality_layout.addWidget(quality_value)
            
            output_dir = QLineEdit(os.path.join(os.path.dirname(image_path), 'processed'))
            browse_btn = QPushButton("浏览...")
            browse_btn.clicked.connect(lambda: self.choose_output_dir(output_dir))
            
            output_layout = QHBoxLayout()
            output_layout.addWidget(output_dir)
            output_layout.addWidget(browse_btn)
            
            # 根据处理类型显示不同控件
            def update_ui(index):
                size_label.setVisible(index == 0)
                width_spin.setVisible(index == 0)
                height_spin.setVisible(index == 0)
                quality_slider.setVisible(index == 1)
                quality_value.setVisible(index == 1)
                
            process_type.currentIndexChanged.connect(update_ui)
            update_ui(0)  # 初始状态
            
            layout.addRow("处理类型:", process_type)
            layout.addRow(size_label, size_layout)
            layout.addRow("质量:", quality_layout)
            layout.addRow("输出目录:", output_layout)
            
            button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)
            
            layout.addRow(button_box)
            
            if dialog.exec_() != QDialog.Accepted:
                return
                
            # 准备处理参数
            process_map = {
                0: 'resize',
                1: 'compress',
                2: 'convert'
            }
            selected_process = process_map.get(process_type.currentIndex(), 'resize')
            
            # 创建进度对话框
            progress = QProgressDialog("正在处理图片...", "取消", 0, 0, self)
            progress.setWindowTitle("图片处理")
            progress.setWindowModality(Qt.WindowModal)
            progress.show()
            
            # 使用线程处理图片
            self.image_thread = ImageProcessorThread(
                image_path,
                output_dir.text(),
                selected_process,
                (width_spin.value(), height_spin.value()),
                quality_slider.value()
            )
            
            self.image_thread.process_complete.connect(
                lambda src, dst: self.on_image_process_complete(src, dst, progress))
            
            self.image_thread.start()
            
        except Exception as e:
            logger.error(f"图片处理出错: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"图片处理失败: {str(e)}")
    
    def choose_output_dir(self, output_dir_widget):
        """选择输出目录"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录", output_dir_widget.text())
        if dir_path:
            output_dir_widget.setText(dir_path)
    
    def on_image_process_complete(self, src_path, dst_path, progress):
        """图片处理完成"""
        progress.close()
        
        if os.path.exists(dst_path):
            reply = QMessageBox.question(
                self, "处理完成", 
                f"图片已处理并保存到:\n{dst_path}\n\n是否更新当前记录使用新图片?",
                QMessageBox.Yes | QMessageBox.No)
                
            if reply == QMessageBox.Yes:
                # 更新当前记录的图片路径
                selected_row = self.table.currentRow()
                if selected_row >= 0:
                    record_id_item = self.table.item(selected_row, 0)
                    if record_id_item:
                        conn = None
                        try:
                            conn = sqlite3.connect(self.db_path)
                            cursor = conn.cursor()
                            
                            cursor.execute(
                                "UPDATE faces SET image_path=? WHERE id=?",
                                (dst_path, record_id_item.text())
                            )
                            conn.commit()
                            
                            self.load_database()
                            self.status_bar.showMessage(f"已更新记录使用新图片: {os.path.basename(dst_path)}")
                            
                        except sqlite3.Error as e:
                            logger.error(f"更新图片路径出错: {str(e)}", exc_info=True)
                            QMessageBox.critical(self, "错误", f"更新记录失败: {str(e)}")
                        finally:
                            if conn:
                                conn.close()
        else:
            QMessageBox.warning(self, "处理失败", f"图片处理失败: {dst_path}")
    
    def save_image_as(self):
        """将当前图片另存为"""
        try:
            selected_row = self.table.currentRow()
            if selected_row < 0:
                QMessageBox.warning(self, "警告", "请先选择一条记录")
                return
                
            image_path_item = self.table.item(selected_row, 2)
            if not image_path_item or not image_path_item.text() or not os.path.exists(image_path_item.text()):
                QMessageBox.warning(self, "警告", "图片路径无效或图片不存在")
                return
                
            image_path = image_path_item.text()
            default_name = os.path.basename(image_path)
            
            save_path, _ = QFileDialog.getSaveFileName(
                self, "保存图片", 
                os.path.join(self.settings.get('default_image_dir', ''), default_name,
                "图片文件 (*.jpg *.png *.bmp)"))
                
            if save_path:
                try:
                    shutil.copy2(image_path, save_path)
                    self.status_bar.showMessage(f"图片已保存到: {save_path}")
                    logger.info(f"图片另存为: {save_path}")
                except Exception as e:
                    logger.error(f"保存图片出错: {str(e)}", exc_info=True)
                    QMessageBox.critical(self, "错误", f"保存图片失败: {str(e)}")
                    
        except Exception as e:
            logger.error(f"另存图片出错: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"另存图片时发生错误: {str(e)}")
    
    def update_stats(self):
        """更新统计信息"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 获取总记录数
            cursor.execute("SELECT COUNT(*) FROM faces")
            total_records = cursor.fetchone()[0]
            
            # 获取有图片的记录数
            cursor.execute("SELECT COUNT(*) FROM faces WHERE image_path IS NOT NULL AND image_path != ''")
            records_with_image = cursor.fetchone()[0]
            
            # 获取最早的创建时间
            cursor.execute("SELECT MIN(create_time) FROM faces")
            min_time = cursor.fetchone()[0]
            
            # 获取最近的访问时间
            cursor.execute("SELECT MAX(last_access_time) FROM faces")
            max_time = cursor.fetchone()[0]
            
            # 获取数据库大小
            db_size = os.path.getsize(self.db_path) / (1024 * 1024)  # MB
            
            stats_text = (
                f"总记录数: {total_records}\n"
                f"有图片的记录: {records_with_image}\n"
                f"无图片的记录: {total_records - records_with_image}\n"
                f"最早创建时间: {min_time}\n"
                f"最近访问时间: {max_time}\n"
                f"数据库大小: {db_size:.2f} MB\n"
            )
            
            if self.last_backup_time:
                stats_text += f"\n上次备份: {self.last_backup_time.strftime('%Y-%m-%d %H:%M:%S')}"
            
            self.stats_content.setText(stats_text)
            
            conn.close()
            
        except Exception as e:
            logger.error(f"更新统计信息出错: {str(e)}", exc_info=True)
            self.stats_content.setText("无法加载统计信息")
    
    def on_search_text_changed(self, text):
        """搜索文本变化时触发延迟搜索"""
        try:
            if text.strip():
                self.search_timer.start(500)  # 500毫秒延迟
            else:
                self.clear_search()
        except Exception as e:
            logger.error(f"搜索文本处理出错: {str(e)}", exc_info=True)
            self.status_bar.showMessage("搜索处理出错")
    
    def perform_search(self):
        """执行搜索操作"""
        try:
            search_text = self.search_input.text().strip()
            if not search_text:
                self.clear_search()
                return
            
            search_column = self.search_field.currentIndex()
            search_column_name = ["id", "name", "image_path", "create_time", "last_access_time"][search_column]
            
            conn = None
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # 根据字段类型构建不同的查询条件
                if search_column in [0]:  # ID字段
                    if search_text.isdigit():
                        cursor.execute(
                            f"SELECT id, name, image_path, create_time, last_access_time FROM faces WHERE {search_column_name}=?",
                            (int(search_text),))
                    else:
                        QMessageBox.warning(self, "警告", "ID必须为数字")
                        return
                elif search_column in [3, 4]:  # 日期字段
                    cursor.execute(
                        f"SELECT id, name, image_path, create_time, last_access_time FROM faces WHERE {search_column_name} LIKE ?",
                        (f"%{search_text}%",))
                else:  # 文本字段
                    cursor.execute(
                        f"SELECT id, name, image_path, create_time, last_access_time FROM faces WHERE {search_column_name} LIKE ?",
                        (f"%{search_text}%",))
                
                records = cursor.fetchall()
                
                # 显示搜索结果
                self.display_search_results(records)
                
                logger.info(f"执行搜索: 字段={search_column_name}, 内容={search_text}, 结果数={len(records)}")
                self.status_bar.showMessage(f"找到 {len(records)} 条匹配记录")
                
            except sqlite3.Error as e:
                logger.error(f"数据库搜索出错: {str(e)}", exc_info=True)
                QMessageBox.critical(self, "错误", f"数据库搜索出错: {str(e)}")
                self.status_bar.showMessage("搜索出错")
            finally:
                if conn:
                    conn.close()
                    
        except Exception as e:
            logger.error(f"执行搜索出错: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"搜索时发生错误: {str(e)}")
            self.status_bar.showMessage("搜索出错")
    
    def display_search_results(self, records):
        """显示搜索结果到表格"""
        try:
            # 先禁用排序，避免在填充数据时触发排序
            self.table.setSortingEnabled(False)
            self.table.setRowCount(len(records))
            
            for row, record in enumerate(records):
                for col, value in enumerate(record):
                    item = QTableWidgetItem(str(value))
                    
                    # 设置ID列和日期列的特殊对齐方式
                    if col == 0:  # ID列
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    elif col in [3, 4]:  # 日期列
                        item.setTextAlignment(Qt.AlignCenter)
                    
                    self.table.setItem(row, col, item)
            
            # 重新启用排序
            self.table.setSortingEnabled(True)
            
            if records:
                self.table.setCurrentCell(0, 0)
            else:
                self.status_bar.showMessage("未找到匹配记录")
                
        except Exception as e:
            logger.error(f"显示搜索结果出错: {str(e)}", exc_info=True)
            raise
    
    def clear_search(self):
        """清除搜索条件并重新加载所有数据"""
        try:
            self.search_input.clear()
            self.load_database()
            self.status_bar.showMessage("已清除搜索条件")
        except Exception as e:
            logger.error(f"清除搜索出错: {str(e)}", exc_info=True)
            self.status_bar.showMessage("清除搜索出错")
    
    def update_image_preview(self):
        """更新图片预览"""
        try:
            selected_row = self.table.currentRow()
            if selected_row < 0:
                self.image_label.setText("未选择记录")
                self.image_info.setText("")
                return
            
            image_path_item = self.table.item(selected_row, 2)
            name_item = self.table.item(selected_row, 1)
            
            if not image_path_item or not name_item:
                self.image_label.setText("数据不完整")
                self.image_info.setText("")
                return
            
            image_path = image_path_item.text()
            name = name_item.text()
            
            if not image_path or image_path == '无图片':
                self.image_label.setText("无有效图片")
                self.image_info.setText(f"姓名: {name}\n图片路径: 无")
                return
            
            if not os.path.exists(image_path):
                self.image_label.setText("图片不存在")
                self.image_info.setText(f"姓名: {name}\n路径: {image_path}\n(文件不存在)")
                return
            
            try:
                pixmap = QPixmap(image_path)
                if pixmap.isNull():
                    raise ValueError("不支持的图片格式")
                    
                scaled_pixmap = pixmap.scaled(
                    self.image_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.image_label.setPixmap(scaled_pixmap)
                
                # 显示图片信息
                file_size = os.path.getsize(image_path) / 1024
                self.image_info.setText(
                    f"姓名: {name}\n"
                    f"尺寸: {pixmap.width()}x{pixmap.height()}\n"
                    f"大小: {file_size:.1f}KB"
                )
                
            except Exception as e:
                logger.error(f"图片加载失败: {str(e)}", exc_info=True)
                self.image_label.setText("图片加载失败")
                self.image_info.setText(f"错误: {str(e)}")
                
        except Exception as e:
            logger.error(f"更新图片预览出错: {str(e)}", exc_info=True)
            self.image_label.setText("预览更新出错")
            self.image_info.setText("")

    def init_context_menu(self):
        """初始化右键菜单"""
        try:
            self.context_menu = QMenu(self)
            
            # 添加菜单项
            self.edit_action = QAction("编辑记录", self)
            self.edit_action.triggered.connect(self.edit_record)
            self.context_menu.addAction(self.edit_action)
            
            self.delete_action = QAction("删除记录", self)
            self.delete_action.triggered.connect(self.delete_record)
            self.context_menu.addAction(self.delete_action)
            
            self.context_menu.addSeparator()
            
            self.copy_action = QAction("复制选中内容", self)
            self.copy_action.triggered.connect(self.copy_selected)
            self.context_menu.addAction(self.copy_action)
            
            self.copy_row_action = QAction("复制整行", self)
            self.copy_row_action.triggered.connect(self.copy_row)
            self.context_menu.addAction(self.copy_row_action)
            
            self.context_menu.addSeparator()
            
            self.view_image_action = QAction("查看图片", self)
            self.view_image_action.triggered.connect(self.view_image)
            self.context_menu.addAction(self.view_image_action)
            
            self.save_image_action = QAction("另存图片", self)
            self.save_image_action.triggered.connect(self.save_image_as)
            self.context_menu.addAction(self.save_image_action)
            
            self.process_image_action = QAction("处理图片", self)
            self.process_image_action.triggered.connect(self.process_image)
            self.context_menu.addAction(self.process_image_action)
            
            self.context_menu.addSeparator()
            
            self.search_selected_action = QAction("搜索选中内容", self)
            self.search_selected_action.triggered.connect(self.search_selected)
            self.context_menu.addAction(self.search_selected_action)
            
            self.export_selected_action = QAction("导出选中记录", self)
            self.export_selected_action.triggered.connect(self.export_selected)
            self.context_menu.addAction(self.export_selected_action)
            
        except Exception as e:
            logger.error(f"初始化右键菜单出错: {str(e)}", exc_info=True)
            raise
    
    def export_selected(self):
        """导出选中记录"""
        try:
            selected_items = self.table.selectedItems()
            if not selected_items:
                QMessageBox.warning(self, "警告", "请先选择要导出的记录")
                return
                
            # 获取选中的所有行
            selected_rows = set(item.row() for item in selected_items)
            
            options = QFileDialog.Options()
            file_name, selected_filter = QFileDialog.getSaveFileName(
                self, "导出选中记录", "", "CSV文件 (*.csv);;JSON文件 (*.json)", options=options)
            
            if not file_name:
                return
            
            if selected_filter == "CSV文件 (*.csv)" and not file_name.endswith('.csv'):
                file_name += '.csv'
            elif selected_filter == "JSON文件 (*.json)" and not file_name.endswith('.json'):
                file_name += '.json'
            
            try:
                # 准备数据
                headers = []
                for col in range(self.table.columnCount()):
                    header_item = self.table.horizontalHeaderItem(col)
                    headers.append(header_item.text() if header_item else f"Column{col+1}")
                
                data = []
                for row in selected_rows:
                    row_data = {}
                    for col in range(self.table.columnCount()):
                        item = self.table.item(row, col)
                        row_data[headers[col]] = item.text() if item else ""
                    data.append(row_data)
                
                # 写入文件
                if selected_filter == "CSV文件 (*.csv)":
                    with open(file_name, 'w', encoding='utf-8', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=headers)
                        writer.writeheader()
                        writer.writerows(data)
                else:  # JSON
                    with open(file_name, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                
                self.status_bar.showMessage(f"已导出 {len(selected_rows)} 条记录到: {file_name}")
                QMessageBox.information(self, "成功", f"已成功导出 {len(selected_rows)} 条记录到:\n{file_name}")
                logger.info(f"导出选中记录到: {file_name}")
            
            except IOError as e:
                logger.error(f"导出选中记录出错: {str(e)}", exc_info=True)
                QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")
                self.status_bar.showMessage("导出选中记录失败")
                
        except Exception as e:
            logger.error(f"导出选中记录出错: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"导出时发生错误: {str(e)}")
            self.status_bar.showMessage("导出选中记录出错")
    
    def search_selected(self):
        """搜索选中内容"""
        try:
            selected_items = self.table.selectedItems()
            if not selected_items:
                return
            
            first_item = selected_items[0]
            column = first_item.column()
            text = first_item.text()
            
            if column >= 0 and text:
                self.search_field.setCurrentIndex(column)
                self.search_input.setText(text)
                self.perform_search()
                
        except Exception as e:
            logger.error(f"搜索选中内容出错: {str(e)}", exc_info=True)
            self.status_bar.showMessage("搜索选中内容出错")
    
    def show_context_menu(self):
        """显示右键菜单"""
        try:
            if self.table.currentRow() >= 0:
                self.context_menu.exec_(QCursor.pos())
        except Exception as e:
            logger.error(f"显示右键菜单出错: {str(e)}", exc_info=True)
    
    def on_table_header_clicked(self, column):
        """表格表头点击事件处理"""
        try:
            self.status_bar.showMessage(f"按 {self.table.horizontalHeaderItem(column).text()} 排序")
        except Exception as e:
            logger.error(f"表头点击事件处理出错: {str(e)}", exc_info=True)
    
    def open_database(self):
        """打开数据库文件"""
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "选择数据库文件", "", "SQLite数据库 (*.db *.sqlite)")
            
            if file_path:
                self.db_path = file_path
                self.db_label.setText(f"当前数据库: {self.db_path}")
                self.load_database()
                self.status_bar.showMessage(f"已加载数据库: {os.path.basename(file_path)}")
                logger.info(f"打开数据库: {file_path}")
                
        except Exception as e:
            logger.error(f"打开数据库出错: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"打开数据库失败: {str(e)}")
            self.status_bar.showMessage("打开数据库失败")
    
    def load_database(self):
        """加载数据库内容到表格"""
        try:
            conn = None
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # 获取所有记录
                cursor.execute("SELECT id, name, image_path, create_time, last_access_time FROM faces")
                records = cursor.fetchall()
                
                # 先禁用排序，避免在填充数据时触发排序
                self.table.setSortingEnabled(False)
                self.table.setRowCount(len(records))
                
                for row, record in enumerate(records):
                    for col, value in enumerate(record):
                        item = QTableWidgetItem(str(value))
                        
                        # 设置ID列和日期列的特殊对齐方式
                        if col == 0:  # ID列
                            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        elif col in [3, 4]:  # 日期列
                            item.setTextAlignment(Qt.AlignCenter)
                        
                        self.table.setItem(row, col, item)
                
                # 重新启用排序
                self.table.setSortingEnabled(True)
                self.status_bar.showMessage(f"已加载 {len(records)} 条记录")
                logger.info(f"加载数据库: 记录数={len(records)}")
                
                if records:
                    self.table.setCurrentCell(0, 0)
                    
            except sqlite3.Error as e:
                logger.error(f"数据库加载出错: {str(e)}", exc_info=True)
                QMessageBox.critical(self, "错误", f"加载数据库失败: {str(e)}")
                self.status_bar.showMessage("加载数据库失败")
            finally:
                if conn:
                    conn.close()
                    
        except Exception as e:
            logger.error(f"加载数据库出错: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"加载数据库时发生错误: {str(e)}")
            self.status_bar.showMessage("加载数据库出错")
    
    def add_record(self):
        """添加新记录"""
        try:
            # 获取姓名
            name, ok = QInputDialog.getText(self, "添加记录", "请输入姓名:")
            if not ok or not name:
                return
            
            # 验证姓名
            if not name.strip():
                QMessageBox.warning(self, "警告", "姓名不能为空")
                return
            
            # 获取图片路径
            image_path, _ = QFileDialog.getOpenFileName(
                self, "选择人脸图片", self.settings.get('default_image_dir', ''), 
                "图片文件 (*.jpg *.png *.jpeg)")
            
            if not image_path:
                return
            
            # 验证图片路径
            if not os.path.exists(image_path):
                QMessageBox.warning(self, "警告", "选择的图片文件不存在")
                return
            
            conn = None
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # 检查是否已存在相同姓名和图片的记录
                cursor.execute(
                    "SELECT COUNT(*) FROM faces WHERE name=? AND image_path=?",
                    (name, image_path))
                count = cursor.fetchone()[0]
                
                if count > 0:
                    QMessageBox.warning(self, "警告", "已存在相同姓名和图片的记录")
                    return
                
                # 插入新记录
                cursor.execute(
                    "INSERT INTO faces (name, image_path) VALUES (?, ?)",
                    (name, image_path)
                )
                conn.commit()
                
                self.status_bar.showMessage(f"已添加记录: {name}")
                logger.info(f"添加记录: 姓名={name}, 图片路径={image_path}")
                self.load_database()
                
                # 触发自动备份
                if self.settings.get('auto_backup', False) and self.settings.get('backup_interval', '') == '每次修改时':
                    self.auto_backup()
                
            except sqlite3.Error as e:
                logger.error(f"添加记录到数据库出错: {str(e)}", exc_info=True)
                QMessageBox.critical(self, "错误", f"添加记录失败: {str(e)}")
                self.status_bar.showMessage("添加记录失败")
            finally:
                if conn:
                    conn.close()
                    
        except Exception as e:
            logger.error(f"添加记录出错: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"添加记录时发生错误: {str(e)}")
            self.status_bar.showMessage("添加记录出错")
    
    def edit_record(self):
        """编辑选中记录"""
        try:
            selected_row = self.table.currentRow()
            if selected_row < 0:
                QMessageBox.warning(self, "警告", "请先选择一条记录")
                return
            
            # 获取当前记录信息
            record_id_item = self.table.item(selected_row, 0)
            current_name_item = self.table.item(selected_row, 1)
            current_image_item = self.table.item(selected_row, 2)
            
            if not record_id_item or not current_name_item or not current_image_item:
                QMessageBox.warning(self, "警告", "记录数据不完整")
                return
            
            record_id = record_id_item.text()
            current_name = current_name_item.text()
            current_image = current_image_item.text()
            
            # 编辑姓名
            new_name, ok = QInputDialog.getText(
                self, "编辑姓名", "请输入新姓名:", 
                text=current_name)
            
            if not ok:
                return
            
            # 验证姓名
            if not new_name.strip():
                QMessageBox.warning(self, "警告", "姓名不能为空")
                return
            
            # 编辑图片路径
            new_image, _ = QFileDialog.getOpenFileName(
                self, "选择新图片", self.settings.get('default_image_dir', ''), 
                "图片文件 (*.jpg *.png *.jpeg)", 
                current_image if current_image and current_image != '无图片' else "")
            
            if not new_image:
                new_image = current_image
            
            # 验证图片路径
            if new_image and new_image != '无图片' and not os.path.exists(new_image):
                QMessageBox.warning(self, "警告", "选择的图片文件不存在")
                return
            
            conn = None
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # 检查是否已存在相同姓名和图片的记录
                cursor.execute(
                    "SELECT COUNT(*) FROM faces WHERE name=? AND image_path=? AND id!=?",
                    (new_name, new_image, record_id))
                count = cursor.fetchone()[0]
                
                if count > 0:
                    QMessageBox.warning(self, "警告", "已存在相同姓名和图片的记录")
                    return
                
                # 更新记录
                cursor.execute(
                    "UPDATE faces SET name=?, image_path=? WHERE id=?",
                    (new_name, new_image, record_id)
                )
                conn.commit()
                
                self.status_bar.showMessage(f"已更新记录: {new_name}")
                logger.info(f"更新记录: ID={record_id}, 新姓名={new_name}, 新图片路径={new_image}")
                self.load_database()
                
                # 触发自动备份
                if self.settings.get('auto_backup', False) and self.settings.get('backup_interval', '') == '每次修改时':
                    self.auto_backup()
                
            except sqlite3.Error as e:
                logger.error(f"更新数据库记录出错: {str(e)}", exc_info=True)
                QMessageBox.critical(self, "错误", f"更新记录失败: {str(e)}")
                self.status_bar.showMessage("更新记录失败")
            finally:
                if conn:
                    conn.close()
                    
        except Exception as e:
            logger.error(f"编辑记录出错: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"编辑记录时发生错误: {str(e)}")
            self.status_bar.showMessage("编辑记录出错")
    
    def delete_record(self):
        """删除选中记录"""
        try:
            selected_row = self.table.currentRow()
            if selected_row < 0:
                QMessageBox.warning(self, "警告", "请先选择一条记录")
                return
            
            # 获取记录信息
            record_id_item = self.table.item(selected_row, 0)
            record_name_item = self.table.item(selected_row, 1)
            
            if not record_id_item or not record_name_item:
                QMessageBox.warning(self, "警告", "记录数据不完整")
                return
            
            record_id = record_id_item.text()
            record_name = record_name_item.text()
            
            # 确认删除
            reply = QMessageBox.question(
                self, "确认删除", 
                f"确定要删除 {record_name} (ID: {record_id}) 吗?\n此操作不可恢复!",
                QMessageBox.Yes | QMessageBox.No)
            
            if reply == QMessageBox.No:
                return
            
            conn = None
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # 删除记录
                cursor.execute("DELETE FROM faces WHERE id=?", (record_id,))
                conn.commit()
                
                self.status_bar.showMessage(f"已删除记录: {record_name}")
                logger.info(f"删除记录: ID={record_id}, 姓名={record_name}")
                self.load_database()
                
                # 触发自动备份
                if self.settings.get('auto_backup', False) and self.settings.get('backup_interval', '') == '每次修改时':
                    self.auto_backup()
                
            except sqlite3.Error as e:
                logger.error(f"从数据库删除记录出错: {str(e)}", exc_info=True)
                QMessageBox.critical(self, "错误", f"删除记录失败: {str(e)}")
                self.status_bar.showMessage("删除记录失败")
            finally:
                if conn:
                    conn.close()
                    
        except Exception as e:
            logger.error(f"删除记录出错: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"删除记录时发生错误: {str(e)}")
            self.status_bar.showMessage("删除记录出错")
    
    def copy_selected(self):
        """复制选中内容到剪贴板"""
        try:
            selected_items = self.table.selectedItems()
            if not selected_items:
                return
            
            text = ""
            current_row = -1
            
            for item in selected_items:
                if not item:
                    continue
                    
                if item.row() != current_row:
                    if current_row != -1:
                        text += "\n"
                    current_row = item.row()
                else:
                    text += "\t"
                
                text += item.text() if item.text() else ""
            
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self.status_bar.showMessage("已复制选中内容到剪贴板")
            logger.info("复制选中内容到剪贴板")
            
        except Exception as e:
            logger.error(f"复制选中内容出错: {str(e)}", exc_info=True)
            self.status_bar.showMessage("复制内容出错")
    
    def copy_row(self):
        """复制整行内容到剪贴板"""
        try:
            selected_row = self.table.currentRow()
            if selected_row < 0:
                return
            
            row_data = []
            for col in range(self.table.columnCount()):
                item = self.table.item(selected_row, col)
                row_data.append(item.text() if item else "")
            
            text = "\t".join(row_data)
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self.status_bar.showMessage("已复制整行内容到剪贴板")
            logger.info(f"复制整行内容: 行号={selected_row}")
            
        except Exception as e:
            logger.error(f"复制整行内容出错: {str(e)}", exc_info=True)
            self.status_bar.showMessage("复制整行内容出错")
    
    def view_image(self):
        """查看选中记录的图片"""
        try:
            selected_row = self.table.currentRow()
            if selected_row < 0:
                return
            
            image_path_item = self.table.item(selected_row, 2)
            if not image_path_item:
                QMessageBox.warning(self, "警告", "图片路径无效")
                return
            
            image_path = image_path_item.text()
            if not image_path or image_path == '无图片' or not os.path.exists(image_path):
                QMessageBox.warning(self, "警告", "图片路径无效或图片不存在")
                return
            
            # 使用系统默认程序打开图片
            try:
                if sys.platform == 'win32':
                    os.startfile(image_path)
                elif sys.platform == 'darwin':
                    os.system(f'open "{image_path}"')
                else:
                    os.system(f'xdg-open "{image_path}"')
                    
                logger.info(f"查看图片: {image_path}")
            except Exception as e:
                logger.error(f"打开图片出错: {str(e)}", exc_info=True)
                QMessageBox.critical(self, "错误", f"无法打开图片: {str(e)}")
                
        except Exception as e:
            logger.error(f"查看图片出错: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"查看图片时发生错误: {str(e)}")
    
    def export_data(self):
        """导出数据到文件"""
        try:
            options = QFileDialog.Options()
            file_name, selected_filter = QFileDialog.getSaveFileName(
                self, "导出数据", "", "CSV文件 (*.csv);;JSON文件 (*.json);;文本文件 (*.txt)", options=options)
            
            if not file_name:
                return
            
            if selected_filter == "CSV文件 (*.csv)" and not file_name.endswith('.csv'):
                file_name += '.csv'
            elif selected_filter == "JSON文件 (*.json)" and not file_name.endswith('.json'):
                file_name += '.json'
            elif selected_filter == "文本文件 (*.txt)" and not file_name.endswith('.txt'):
                file_name += '.txt'
            
            try:
                # 准备数据
                headers = []
                for col in range(self.table.columnCount()):
                    header_item = self.table.horizontalHeaderItem(col)
                    headers.append(header_item.text() if header_item else f"Column{col+1}")
                
                data = []
                for row in range(self.table.rowCount()):
                    row_data = {}
                    for col in range(self.table.columnCount()):
                        item = self.table.item(row, col)
                        row_data[headers[col]] = item.text() if item else ""
                    data.append(row_data)
                
                # 写入文件
                if selected_filter == "CSV文件 (*.csv)":
                    with open(file_name, 'w', encoding='utf-8', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=headers)
                        writer.writeheader()
                        writer.writerows(data)
                elif selected_filter == "JSON文件 (*.json)":
                    with open(file_name, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                else:  # 文本文件
                    with open(file_name, 'w', encoding='utf-8') as f:
                        # 写入表头
                        f.write("\t".join(headers) + "\n")
                        # 写入数据
                        for row in data:
                            f.write("\t".join(str(row[h]) for h in headers) + "\n")
                
                self.status_bar.showMessage(f"数据已导出到: {file_name}")
                QMessageBox.information(self, "成功", f"数据已成功导出到:\n{file_name}")
                logger.info(f"导出数据到: {file_name}")
            
            except IOError as e:
                logger.error(f"导出数据到文件出错: {str(e)}", exc_info=True)
                QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")
                self.status_bar.showMessage("导出数据失败")
                
        except Exception as e:
            logger.error(f"导出数据出错: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"导出时发生错误: {str(e)}")
            self.status_bar.showMessage("导出数据出错")

if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        window = FaceDatabaseEditor()
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        logger.critical(f"应用程序崩溃: {str(e)}", exc_info=True)
        QMessageBox.critical(None, "致命错误", f"应用程序发生致命错误:\n{str(e)}\n请查看日志文件获取更多信息。")