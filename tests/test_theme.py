import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def test_apply_theme_sets_stylesheet():
    from assistant.ui.theme import DARK_QSS, apply_theme
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    assert "QMainWindow" in app.styleSheet()
    assert "#12B7F5" in DARK_QSS
    assert "#1e1e22" in DARK_QSS
