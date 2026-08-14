from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QInputDialog, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QVBoxLayout, QWidget,
)

from assistant.core.sessions import Session


class SessionListWidget(QWidget):
    session_selected = Signal(str)
    session_create_requested = Signal()
    session_rename_requested = Signal(str, str)   # (session_id, new_title)
    session_delete_requested = Signal(str)
    search_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索会话…")
        self.search_box.textChanged.connect(self.search_changed.emit)
        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(
            lambda cur, prev: cur and self.session_selected.emit(
                cur.data(Qt.UserRole)))
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._menu)
        self.new_button = QPushButton("＋ 新会话")
        self.new_button.clicked.connect(self.session_create_requested.emit)
        layout = QVBoxLayout(self)
        layout.addWidget(self.search_box)
        layout.addWidget(self.list_widget)
        layout.addWidget(self.new_button)

    def reload(self, sessions: list[Session]) -> None:
        # 重填期间屏蔽信号：Qt 会把 currentItem 恢复到原行号，
        # 而行序变了，会误触发会话切换（回复完退回上个对话的根因）。
        current_id = None
        cur = self.list_widget.currentItem()
        if cur is not None:
            current_id = cur.data(Qt.UserRole)
        self.list_widget.blockSignals(True)
        try:
            self.list_widget.clear()
            for s in sessions:
                item = QListWidgetItem(s.title)
                item.setData(Qt.UserRole, s.id)
                self.list_widget.addItem(item)
                if s.id == current_id:
                    self.list_widget.setCurrentItem(item)
        finally:
            self.list_widget.blockSignals(False)

    def select_session(self, session_id: str) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == session_id:
                self.list_widget.setCurrentItem(item)
                break

    def _menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if item is None:
            return
        sid = item.data(Qt.UserRole)
        menu = QMenu(self)
        rename = menu.addAction("重命名")
        delete = menu.addAction("删除")
        action = menu.exec(self.list_widget.mapToGlobal(pos))
        if action == rename:
            title, ok = QInputDialog.getText(self, "重命名", "新标题：",
                                             text=item.text())
            if ok and title.strip():
                self.session_rename_requested.emit(sid, title.strip())
        elif action == delete:
            self.session_delete_requested.emit(sid)
