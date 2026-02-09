import os
import sys

import chardet
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QVBoxLayout, QWidget, QPushButton, QLineEdit, \
    QTextEdit, QLabel


class KeywordSearchApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Keyword Search")

        # 设置主窗口布局
        layout = QVBoxLayout()

        # 选择文件夹按钮
        self.folder_button = QPushButton("选择文件夹")
        self.folder_button.clicked.connect(self.choose_folder)
        layout.addWidget(self.folder_button)

        # 输入关键字
        self.keyword_input = QLineEdit(self)
        self.keyword_input.setPlaceholderText("输入关键字")
        layout.addWidget(self.keyword_input)

        # 搜索按钮
        self.search_button = QPushButton("搜索")
        self.search_button.clicked.connect(self.search_files)
        layout.addWidget(self.search_button)

        # 结果展示框
        self.result_box = QTextEdit(self)
        self.result_box.setReadOnly(True)
        layout.addWidget(self.result_box)

        # 查询总数标签
        self.result_count_label = QLabel("查询到的总数: 0")
        layout.addWidget(self.result_count_label)

        # 设置主窗口中心小部件
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def choose_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        self.selected_folder = folder_path

    def search_files(self):
        keyword = self.keyword_input.text()
        self.result_box.clear()
        result_count = 0  # 初始化结果计数器

        if not hasattr(self, 'selected_folder') or not keyword:
            self.result_box.setText("请先选择文件夹并输入关键字")
            return

        for root, dirs, files in os.walk(self.selected_folder):
            for file in files:
                file_path = os.path.join(root, file)
                # 读取部分文件内容以检测编码
                with open(file_path, 'rb') as f:
                    raw_data = f.read(10000)  # 读取文件的一部分
                    result = chardet.detect(raw_data)
                    encoding = result['encoding']
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        for line_number, line in enumerate(f, start=1):
                            if keyword in line:
                                result = f"{file_path} (line {line_number}): {line.strip()}\n"
                                self.result_box.append(result)
                                result_count += 1  # 增加结果计数
                except Exception as e:
                    self.result_box.append(f"无法读取文件: {file_path}\n错误: {e}")

        # 更新结果总数
        self.result_count_label.setText(f"查询到的总数: {result_count}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = KeywordSearchApp()
    window.show()
    sys.exit(app.exec())
