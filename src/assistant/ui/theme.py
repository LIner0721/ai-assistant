"""深色主题：QQ 蓝点缀的全局 QSS。"""
from PySide6.QtWidgets import QApplication

DARK_QSS = """
QMainWindow, QWidget {
    background-color: #1e1e22;
    color: #e8e8ea;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    font-size: 10pt;
}
QMenuBar, QMenu {
    background-color: #1e1e22;
    color: #e8e8ea;
}
QMenu::item:selected {
    background-color: #12B7F5;
    color: #ffffff;
}
QTextEdit, QTextBrowser, QPlainTextEdit {
    background-color: #1e1e22;
    color: #e8e8ea;
    border: 1px solid #3a3a42;
    border-radius: 10px;
    padding: 8px;
    selection-background-color: #12B7F5;
    selection-color: #ffffff;
}
QLineEdit {
    background-color: #26262b;
    color: #e8e8ea;
    border: 1px solid #3a3a42;
    border-radius: 8px;
    padding: 6px 8px;
    selection-background-color: #12B7F5;
}
QListWidget {
    background-color: #1e1e22;
    color: #e8e8ea;
    border: none;
    border-radius: 10px;
    padding: 4px;
}
QListWidget::item {
    padding: 8px 10px;
    border-radius: 8px;
    margin: 2px 0;
}
QListWidget::item:hover {
    background-color: #26262b;
}
QListWidget::item:selected {
    background-color: #12B7F5;
    color: #ffffff;
}
QPushButton {
    background-color: #2a2a30;
    color: #e8e8ea;
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
}
QPushButton:hover {
    background-color: #3a3a42;
}
QPushButton:disabled {
    color: #6a6a73;
    background-color: #26262b;
}
QPushButton#sendButton {
    background-color: #12B7F5;
    color: #ffffff;
    font-weight: bold;
}
QPushButton#sendButton:hover {
    background-color: #3ec6ff;
}
QPushButton#sendButton:disabled {
    background-color: #0e5c78;
    color: #9a9aa3;
}
QStatusBar {
    background-color: #1e1e22;
    color: #9a9aa3;
}
QTabWidget::pane {
    border: 1px solid #3a3a42;
    border-radius: 8px;
}
QTabBar::tab {
    background-color: #26262b;
    color: #9a9aa3;
    padding: 8px 16px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
QTabBar::tab:selected {
    background-color: #12B7F5;
    color: #ffffff;
}
QScrollBar:vertical {
    background-color: #1e1e22;
    width: 10px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background-color: #3a3a42;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background-color: #12B7F5;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QSplitter::handle {
    background-color: #26262b;
    width: 2px;
}
QDialog {
    background-color: #1e1e22;
    color: #e8e8ea;
}
QCheckBox, QLabel {
    color: #e8e8ea;
}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyleSheet(DARK_QSS)
