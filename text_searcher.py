import os
import sys
import re
import json
from collections import deque
from pathlib import Path

import chardet
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QApplication, QMainWindow, QFileDialog, QVBoxLayout,
                               QHBoxLayout, QWidget, QPushButton, QLineEdit,
                               QPlainTextEdit, QLabel, QCheckBox, QSpinBox, QComboBox)


# 关键字历史文件路径
HISTORY_FILE = Path.home() / ".text_searcher_history.json"
MAX_HISTORY = 20


class KeywordHistory:
    """管理关键字搜索历史"""

    @staticmethod
    def load():
        """加载历史记录"""
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("keywords", []), data.get("ignore_keywords", [])
            except Exception:
                return [], []
        return [], []

    @staticmethod
    def save(keywords, ignore_keywords):
        """保存历史记录"""
        try:
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "keywords": keywords,
                    "ignore_keywords": ignore_keywords
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def add_keyword(keyword):
        """添加关键字到历史记录"""
        if not keyword or not keyword.strip():
            return None
        keywords, ignore_keywords = KeywordHistory.load()
        # 移除已存在的相同关键字
        if keyword in keywords:
            keywords.remove(keyword)
        # 添加到开头
        keywords.insert(0, keyword)
        # 限制历史记录数量
        keywords = keywords[:MAX_HISTORY]
        KeywordHistory.save(keywords, ignore_keywords)
        return keywords

    @staticmethod
    def add_ignore_keyword(keyword):
        """添加忽略关键字到历史记录"""
        if not keyword or not keyword.strip():
            return None
        keywords, ignore_keywords = KeywordHistory.load()
        # 移除已存在的相同关键字
        if keyword in ignore_keywords:
            ignore_keywords.remove(keyword)
        # 添加到开头
        ignore_keywords.insert(0, keyword)
        # 限制历史记录数量
        ignore_keywords = ignore_keywords[:MAX_HISTORY]
        KeywordHistory.save(keywords, ignore_keywords)
        return ignore_keywords


class LogicalExpressionParser:
    """解析逻辑搜索表达式，支持 and, or, &, |, not 运算符"""

    def __init__(self, expression):
        self.expression = expression.strip()
        self.pos = 0

    def parse(self):
        """解析表达式并返回一个匹配函数"""
        try:
            # 预处理：将 and/or/&/|/not 替换为内部标记
            expr = self._preprocess(self.expression)
            # 返回一个lambda函数用于匹配
            return lambda text: self._evaluate(expr, text)
        except Exception as e:
            # 如果解析失败，返回一个总是返回False的函数
            return lambda text: False

    def _preprocess(self, expr):
        """预处理表达式，规范化运算符"""
        # 将 and 替换为 &
        expr = re.sub(r'\band\b', ' & ', expr)
        # 将 or 替换为 |
        expr = re.sub(r'\bor\b', ' | ', expr)
        # 处理 not("x") 格式
        expr = re.sub(r'\bnot\s*\(', '!', expr)
        return expr

    def _evaluate(self, expr, text):
        """评估表达式是否匹配文本"""
        try:
            # 使用安全的评估方式
            # 将字符串字面量提取出来，然后用Python表达式评估
            # 这里使用一个简化的解析器

            # 首先提取所有引号包裹的字符串
            import ast
            # 转换表达式为Python可执行的表达式
            # 将 "string" 转换为 '"string"' in text
            py_expr = self._convert_to_python(expr)
            # 创建安全的执行环境
            safe_dict = {'text': text}
            return eval(py_expr, {"__builtins__": {}}, safe_dict)
        except:
            return False

    def _convert_to_python(self, expr):
        """将逻辑表达式转换为Python表达式"""
        # 处理!("xxx") 格式
        expr = re.sub(r'!\s*\(\s*"([^"]*)"\s*\)', r'("\1" not in text)', expr)
        expr = re.sub(r"!\s*\(\s*'([^']*)'\s*\)", r"('\1' not in text)", expr)

        # 处理!("xxx") 格式（可能没有引号保护的情况）
        expr = re.sub(r'!\s*\(([^)]+)\)', r'not (\1)', expr)

        # 处理 "string" -> '"string" in text'
        expr = re.sub(r'"([^"]*)"', r'("\1" in text)', expr)
        expr = re.sub(r"'([^']*)'", r"('\1' in text)", expr)

        return expr


class SearchThread(QThread):
    search_progress = Signal(str, int)  # 发送结果和当前计数
    search_finished = Signal(int, bool)  # 搜索完成，发送总计数和是否被取消
    search_error = Signal(str)  # 发送错误信息

    def __init__(self, target, keyword, file_filter, use_logical_search=False,
                 context_lines=0, ignore_keyword="", use_ignore_logical=False, is_folder=True):
        super().__init__()
        self.target = target
        self.is_folder = is_folder
        self.keyword = keyword
        self.file_filter = file_filter
        self.use_logical_search = use_logical_search
        self.context_lines = context_lines
        self.ignore_keyword = ignore_keyword
        self.use_ignore_logical = use_ignore_logical
        self._is_running = True

        # 准备匹配函数
        if use_logical_search:
            self.matcher = LogicalExpressionParser(keyword).parse()
        else:
            self.matcher = lambda text: keyword in text

        # 准备忽略匹配函数
        if ignore_keyword and ignore_keyword.strip():
            if use_ignore_logical:
                self.ignore_matcher = LogicalExpressionParser(ignore_keyword).parse()
            else:
                self.ignore_matcher = lambda text: ignore_keyword in text
        else:
            self.ignore_matcher = None

    def _should_ignore(self, line):
        """检查是否应该忽略该行"""
        if self.ignore_matcher is None:
            return False
        return self.ignore_matcher(line)

    def run(self):
        result_count = 0

        if self.is_folder:
            # 文件夹模式：遍历目录
            for root, dirs, files in os.walk(self.target):
                if not self._is_running:
                    self.search_finished.emit(result_count, True)
                    return
                for file in files:
                    if not self._is_running:
                        self.search_finished.emit(result_count, True)
                        return
                    # 文件过滤
                    if self.file_filter and self.file_filter.strip() and self.file_filter.strip() not in file:
                        continue
                    file_path = os.path.join(root, file)
                    result_count = self._search_file(file_path, result_count)
        else:
            # 单文件模式：直接搜索指定文件
            result_count = self._search_file(self.target, result_count)

        self.search_finished.emit(result_count, False)

    def _search_file(self, file_path, result_count):
        """搜索单个文件"""
        # 尝试多种编码方式打开文件
        encodings = []
        try:
            # 读取部分文件内容以检测编码
            with open(file_path, 'rb') as f:
                raw_data = f.read(10000)
                result = chardet.detect(raw_data)
                if result['encoding']:
                    encodings.append(result['encoding'])
        except Exception:
            pass

        # 添加常用编码作为备选
        encodings.extend(['utf-8', 'gbk', 'gb2312', 'gb18030'])
        # 去重，保留顺序
        seen = set()
        unique_encodings = []
        for enc in encodings:
            if enc and enc not in seen:
                seen.add(enc)
                unique_encodings.append(enc)

        # 尝试每种编码
        for encoding in unique_encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    if self.context_lines > 0:
                        # 使用上下文窗口模式
                        return self._search_with_context(f, file_path, result_count)
                    else:
                        # 普通模式
                        return self._search_normal(f, file_path, result_count)
            except (UnicodeDecodeError, LookupError):
                continue
            except Exception as e:
                self.search_error.emit(f"无法读取文件: {file_path}\n错误: {e}")
                return result_count

        # 所有编码都失败，尝试带错误忽略的方式
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                if self.context_lines > 0:
                    return self._search_with_context(f, file_path, result_count)
                else:
                    return self._search_normal(f, file_path, result_count)
        except Exception as e:
            self.search_error.emit(f"无法读取文件: {file_path}\n错误: {e}")
            return result_count

    def _search_normal(self, f, file_path, result_count):
        """普通搜索模式"""
        for line_number, line in enumerate(f, start=1):
            if not self._is_running:
                return result_count
            # 检查是否应该忽略该行
            if self._should_ignore(line):
                continue
            if self.matcher(line):
                result = f"{file_path} (line {line_number}): {line.strip()}\n"
                self.search_progress.emit(result, result_count + 1)
                result_count += 1
        return result_count

    def _search_with_context(self, f, file_path, result_count):
        """带上下文的搜索模式"""
        # 使用 deque 缓存之前的非忽略行
        context_buffer = deque(maxlen=self.context_lines)

        for line_number, line in enumerate(f, start=1):
            if not self._is_running:
                return result_count

            # 检查是否应该忽略该行
            if self._should_ignore(line):
                # 忽略的行不计入上下文
                continue

            context_buffer.append((line_number, line))

            if self.matcher(line):
                # 构建带上下文的结果
                result_lines = []
                result_lines.append(f"{'='*80}")
                result_lines.append(f"{file_path} (line {line_number}):")

                # 添加之前的上下文
                for ctx_line_num, ctx_line in context_buffer:
                    if ctx_line_num < line_number:
                        result_lines.append(f"  {ctx_line_num}: {ctx_line.rstrip()}")

                # 标记当前匹配行
                result_lines.append(f"> {line_number}: {line.rstrip()}")

                # 读取并添加后续的上下文行（跳过忽略的行）
                future_lines = []
                collected = 0
                while collected < self.context_lines:
                    try:
                        future_line = next(f)
                        future_line_num = line_number + collected + 1
                        # 检查是否应该忽略该行
                        if self._should_ignore(future_line):
                            continue
                        future_lines.append(f"  {future_line_num}: {future_line.rstrip()}")
                        collected += 1
                    except StopIteration:
                        break

                result_lines.extend(future_lines)
                result_lines.append(f"{'='*80}\n")

                result = "\n".join(result_lines)
                self.search_progress.emit(result, result_count + 1)
                result_count += 1

        return result_count

    def stop(self):
        self._is_running = False


class KeywordSearchApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Keyword Search")
        self.resize(1200, 800)

        self.search_thread = None

        # 批量处理优化：缓冲区和定时器
        self.result_buffer = []  # 缓存待显示的结果
        self.batch_size = 100  # 每100条结果更新一次UI
        self.count_update_interval = 10  # 每10条结果更新一次计数标签
        self.max_display_results = 5000  # 最大显示结果数量，超过后停止显示但继续计数
        self.display_count = 0  # 已显示的结果数量
        self.is_display_limited = False  # 是否已达到显示限制

        # 设置主窗口布局
        layout = QVBoxLayout()

        # 选择文件/文件夹区域（水平布局）
        folder_layout = QHBoxLayout()

        self.file_button = QPushButton("选择单文件")
        self.file_button.setFixedWidth(100)
        self.file_button.clicked.connect(self.choose_file)
        folder_layout.addWidget(self.file_button)

        self.folder_button = QPushButton("选择文件夹")
        self.folder_button.setFixedWidth(100)
        self.folder_button.clicked.connect(self.choose_folder)
        folder_layout.addWidget(self.folder_button)

        self.folder_path_label = QLabel("未选择")
        self.folder_path_label.setStyleSheet("color: gray;")
        folder_layout.addWidget(self.folder_path_label, 1)  # stretch=1 占据剩余空间

        folder_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(folder_layout)

        # 文件过滤
        filter_layout = QHBoxLayout()
        filter_label = QLabel("文件过滤:")
        filter_label.setFixedWidth(70)
        filter_layout.addWidget(filter_label)

        self.file_filter_input = QLineEdit(self)
        self.file_filter_input.setText(".log")
        self.file_filter_input.setPlaceholderText("留空表示不过滤")
        filter_layout.addWidget(self.file_filter_input)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(filter_layout)

        # 输入关键字（使用 QComboBox 支持历史记录）
        keyword_layout = QHBoxLayout()
        keyword_label = QLabel("关键字:")
        keyword_label.setFixedWidth(70)
        keyword_layout.addWidget(keyword_label)

        self.keyword_input = QComboBox(self)
        self.keyword_input.setEditable(True)
        self.keyword_input.setPlaceholderText("输入关键字")
        # 加载历史记录
        self.load_keyword_history()
        keyword_layout.addWidget(self.keyword_input, 1)

        # 关键字正则组合开关
        self.logical_search_checkbox = QCheckBox("正则组合", self)
        self.logical_search_checkbox.setChecked(False)
        self.logical_search_checkbox.setToolTip(
            '启用后支持逻辑运算符: and, or, &, |, not("x")\n'
            '例如: "error" and "warning" 或 "error" | "warning"'
        )
        keyword_layout.addWidget(self.logical_search_checkbox)

        keyword_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(keyword_layout)

        # 忽略关键字（使用 QComboBox 支持历史记录）
        ignore_keyword_layout = QHBoxLayout()
        ignore_keyword_label = QLabel("忽略关键字:")
        ignore_keyword_label.setFixedWidth(70)
        ignore_keyword_layout.addWidget(ignore_keyword_label)

        self.ignore_keyword_input = QComboBox(self)
        self.ignore_keyword_input.setEditable(True)
        self.ignore_keyword_input.setPlaceholderText("留空表示不忽略")
        # 加载忽略关键字历史记录
        self.load_ignore_keyword_history()
        ignore_keyword_layout.addWidget(self.ignore_keyword_input, 1)

        # 忽略关键字正则组合开关
        self.ignore_logical_checkbox = QCheckBox("正则组合", self)
        self.ignore_logical_checkbox.setChecked(False)
        self.ignore_logical_checkbox.setToolTip(
            '启用后忽略关键字支持逻辑运算符: and, or, &, |, not("x")'
        )
        ignore_keyword_layout.addWidget(self.ignore_logical_checkbox)

        ignore_keyword_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(ignore_keyword_layout)

        # 上下文窗口设置
        context_layout = QHBoxLayout()
        context_label = QLabel("上下文行数:")
        context_label.setFixedWidth(70)
        context_layout.addWidget(context_label)

        self.context_spinbox = QSpinBox(self)
        self.context_spinbox.setRange(0, 1000)
        self.context_spinbox.setValue(10)
        self.context_spinbox.setToolTip("设置为0表示不显示上下文，只显示匹配行")
        context_layout.addWidget(self.context_spinbox)
        context_layout.addStretch()
        context_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(context_layout)

        # 搜索按钮
        search_btn_layout = QHBoxLayout()
        self.search_button = QPushButton("搜索")
        self.search_button.setFixedWidth(100)
        self.search_button.clicked.connect(self.on_search_button_clicked)
        search_btn_layout.addWidget(self.search_button)
        search_btn_layout.addStretch()
        search_btn_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(search_btn_layout)

        # 显示选项区域
        options_layout = QHBoxLayout()
        self.wrap_checkbox = QCheckBox("结果自动换行")
        self.wrap_checkbox.setChecked(False)  # 默认不换行
        self.wrap_checkbox.stateChanged.connect(self.toggle_line_wrap)
        options_layout.addWidget(self.wrap_checkbox)
        options_layout.addStretch()
        options_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(options_layout)

        # 状态标签
        self.status_label = QLabel("就绪")
        layout.addWidget(self.status_label)

        # 结果展示框（使用 QPlainTextEdit 以更好地处理大量文本）
        self.result_box = QPlainTextEdit(self)
        self.result_box.setReadOnly(True)
        self.result_box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)  # 默认不换行
        # 设置等宽字体以便更好地显示对齐
        self.result_box.setStyleSheet("QPlainTextEdit { font-family: 'Menlo', 'Monaco', 'Consolas', monospace; }")
        layout.addWidget(self.result_box)

        # 查询总数标签和导出按钮
        count_layout = QHBoxLayout()
        self.result_count_label = QLabel("查询到的总数: 0")
        count_layout.addWidget(self.result_count_label)
        count_layout.addStretch()
        self.export_button = QPushButton("导出结果")
        self.export_button.clicked.connect(self.export_results)
        self.export_button.setEnabled(False)
        count_layout.addWidget(self.export_button)
        count_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(count_layout)

        # 设置主窗口中心小部件
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def load_keyword_history(self):
        """加载关键字历史记录到下拉框"""
        self.keyword_input.clear()
        keywords, _ = KeywordHistory.load()
        for kw in keywords:
            self.keyword_input.addItem(kw)

    def load_ignore_keyword_history(self):
        """加载忽略关键字历史记录到下拉框"""
        self.ignore_keyword_input.clear()
        _, ignore_keywords = KeywordHistory.load()
        for kw in ignore_keywords:
            self.ignore_keyword_input.addItem(kw)

    def add_keyword_to_history(self, keyword):
        """添加关键字到历史记录"""
        keywords = KeywordHistory.add_keyword(keyword)
        if keywords:
            # 重新加载下拉框
            current_text = self.keyword_input.currentText()
            self.keyword_input.clear()
            for kw in keywords:
                self.keyword_input.addItem(kw)
            # 恢复当前输入
            self.keyword_input.setCurrentText(current_text)

    def add_ignore_keyword_to_history(self, keyword):
        """添加忽略关键字到历史记录"""
        ignore_keywords = KeywordHistory.add_ignore_keyword(keyword)
        if ignore_keywords:
            # 重新加载下拉框
            current_text = self.ignore_keyword_input.currentText()
            self.ignore_keyword_input.clear()
            for kw in ignore_keywords:
                self.ignore_keyword_input.addItem(kw)
            # 恢复当前输入
            self.ignore_keyword_input.setCurrentText(current_text)

    def choose_file(self):
        """选择单个文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择文件",
            options=QFileDialog.Option.DontUseNativeDialog
        )
        if file_path:
            self.selected_target = file_path
            self.is_folder = False
            self.folder_path_label.setText(f"文件: {file_path}")
            self.folder_path_label.setStyleSheet("color: black;")

    def choose_folder(self):
        """选择文件夹"""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "选择文件夹",
            options=QFileDialog.Option.DontUseNativeDialog
        )
        if folder_path:
            self.selected_target = folder_path
            self.is_folder = True
            self.folder_path_label.setText(f"文件夹: {folder_path}")
            self.folder_path_label.setStyleSheet("color: black;")

    def toggle_line_wrap(self, state):
        if state == Qt.CheckState.Checked.value:
            self.result_box.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        else:
            self.result_box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    def on_search_button_clicked(self):
        if self.search_thread is None:
            self.start_search()
        else:
            self.cancel_search()

    def start_search(self):
        keyword = self.keyword_input.currentText()
        ignore_keyword = self.ignore_keyword_input.currentText()
        file_filter = self.file_filter_input.text()
        use_logical = self.logical_search_checkbox.isChecked()
        use_ignore_logical = self.ignore_logical_checkbox.isChecked()
        context_lines = self.context_spinbox.value()

        if not hasattr(self, 'selected_target') or not keyword:
            self.result_box.setPlainText("请先选择文件或文件夹并输入关键字")
            return

        # 重置显示计数
        self.display_count = 0
        self.is_display_limited = False

        # 添加关键字到历史记录
        self.add_keyword_to_history(keyword)

        # 添加忽略关键字到历史记录
        if ignore_keyword and ignore_keyword.strip():
            self.add_ignore_keyword_to_history(ignore_keyword)

        # 清空结果和缓冲区
        self.result_box.clear()
        self.result_buffer.clear()
        self.result_count_label.setText("查询到的总数: 0")

        # 更改按钮为取消按钮
        self.search_button.setText("取消")
        self.folder_button.setEnabled(False)

        # 禁用输入
        self.keyword_input.setEnabled(False)
        self.ignore_keyword_input.setEnabled(False)
        self.file_filter_input.setEnabled(False)
        self.logical_search_checkbox.setEnabled(False)
        self.ignore_logical_checkbox.setEnabled(False)
        self.context_spinbox.setEnabled(False)
        self.export_button.setEnabled(False)

        # 创建并启动搜索线程
        self.search_thread = SearchThread(
            self.selected_target, keyword, file_filter, use_logical,
            context_lines, ignore_keyword, use_ignore_logical, self.is_folder
        )
        self.search_thread.search_progress.connect(self.on_search_progress)
        self.search_thread.search_finished.connect(self.on_search_finished)
        self.search_thread.search_error.connect(self.on_search_error)
        self.search_thread.start()

        mode_str = "逻辑搜索" if use_logical else "普通搜索"
        context_str = f", 上下文: {context_lines}行" if context_lines > 0 else ""
        ignore_str = f", 忽略: {ignore_keyword}" if ignore_keyword and ignore_keyword.strip() else ""
        self.status_label.setText(f"搜索中... ({mode_str}{context_str}{ignore_str})")

    def cancel_search(self):
        if self.search_thread:
            self.search_thread.stop()
            self.status_label.setText("正在取消搜索...")
            # 清理缓冲区
            self.result_buffer.clear()

    def on_search_progress(self, result, count):
        # 如果已达到显示限制，只更新计数，不显示结果
        if self.is_display_limited:
            self.result_count_label.setText(f"查询到的总数: {count}（已达到显示限制）")
            return

        # 批量处理：收集结果到缓冲区
        self.result_buffer.append(result)

        # 定期更新计数标签（减少UI更新频率）
        if count % self.count_update_interval == 0:
            self.result_count_label.setText(f"查询到的总数: {count}")

        # 当缓冲区达到批次大小时，批量插入
        if len(self.result_buffer) >= self.batch_size:
            self.batch_insert_results()

    def batch_insert_results(self):
        """批量插入结果到UI，使用直接文本插入提高性能"""
        if not self.result_buffer or self.is_display_limited:
            return

        # 计算可以显示的结果数量
        remaining_capacity = self.max_display_results - self.display_count
        if remaining_capacity <= 0:
            self.is_display_limited = True
            self.result_buffer.clear()
            # 在末尾添加限制提示
            self.result_box.appendPlainText("\n" + "=" * 80)
            self.result_box.appendPlainText(f"已达到显示限制（{self.max_display_results}条），更多结果请使用导出功能")
            self.result_box.appendPlainText("=" * 80)
            return

        # 确定本次要插入的数量
        results_to_insert = min(len(self.result_buffer), remaining_capacity)

        # 构建要插入的文本（一次性构建，减少字符串操作）
        text_parts = []
        for i in range(results_to_insert):
            result = self.result_buffer[i]
            # 添加分割线（在第一条结果之前不添加）
            if self.display_count > 0:
                text_parts.append("─" * 80)
                text_parts.append("\n")
            text_parts.append(result)
            self.display_count += 1

        # 一次性插入所有文本
        self.result_box.insertPlainText("".join(text_parts))

        # 滚动到底部
        scrollbar = self.result_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        # 移除已处理的结果
        self.result_buffer = self.result_buffer[results_to_insert:]

        # 检查是否达到限制
        if self.display_count >= self.max_display_results:
            self.is_display_limited = True
            self.result_buffer.clear()
            # 在末尾添加限制提示
            self.result_box.appendPlainText("\n" + "=" * 80)
            self.result_box.appendPlainText(f"已达到显示限制（{self.max_display_results}条），更多结果请使用导出功能")
            self.result_box.appendPlainText("=" * 80)

    def on_search_finished(self, count, cancelled):
        # 插入剩余缓冲区内容
        self.batch_insert_results()

        self.search_button.setText("搜索")
        self.search_button.setEnabled(True)
        self.folder_button.setEnabled(True)
        self.keyword_input.setEnabled(True)
        self.ignore_keyword_input.setEnabled(True)
        self.file_filter_input.setEnabled(True)
        self.logical_search_checkbox.setEnabled(True)
        self.ignore_logical_checkbox.setEnabled(True)
        self.context_spinbox.setEnabled(True)
        # 如果有结果，启用导出按钮
        self.export_button.setEnabled(count > 0)

        # 更新最终计数
        self.result_count_label.setText(f"查询到的总数: {count}")

        if cancelled:
            self.status_label.setText(f"搜索已取消，共找到 {count} 条结果")
        else:
            self.status_label.setText(f"搜索完成，共找到 {count} 条结果")

        self.search_thread = None

    def on_search_error(self, error):
        self.result_box.appendPlainText(error)

    def export_results(self):
        """导出搜索结果到txt文件"""
        content = self.result_box.toPlainText()
        if not content or content.strip() == "":
            self.status_label.setText("没有可导出的结果")
            return

        # 获取保存文件路径
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出搜索结果",
            "search_results.txt",
            "文本文件 (*.txt);;所有文件 (*)",
            options=QFileDialog.Option.DontUseNativeDialog
        )

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.status_label.setText(f"结果已导出到: {file_path}")
            except Exception as e:
                self.status_label.setText(f"导出失败: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = KeywordSearchApp()
    window.show()
    sys.exit(app.exec())
