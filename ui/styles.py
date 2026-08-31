MAIN_STYLE = """
QMainWindow {
    background-color: #1e1e1e;
}

QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}

QGroupBox {
    border: 1px solid #3a3a3a;
    border-radius: 6px;
    margin-top: 12px;
    font-weight: bold;
    color: #00adb5;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
}

QPushButton {
    background-color: #2b2b2b;
    border: 1px solid #3a3a3a;
    border-radius: 4px;
    padding: 6px 14px;
    color: #ffffff;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #3a3a3a;
    border-color: #00adb5;
}

QPushButton:pressed {
    background-color: #00adb5;
    color: #1e1e1e;
}

QPushButton:disabled {
    background-color: #181818;
    color: #555555;
    border-color: #2a2a2a;
}

QPushButton#btn_start {
    background-color: #1b5e20;
    border-color: #2e7d32;
}

QPushButton#btn_start:hover {
    background-color: #2e7d32;
}

QPushButton#btn_stop {
    background-color: #b71c1c;
    border-color: #c62828;
}

QPushButton#btn_stop:hover {
    background-color: #c62828;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #2b2b2b;
    border: 1px solid #3a3a3a;
    border-radius: 4px;
    padding: 4px 8px;
    color: #ffffff;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #00adb5;
}

QTabWidget::pane {
    border: 1px solid #3a3a3a;
    background-color: #1e1e1e;
}

QTabBar::tab {
    background-color: #252525;
    border: 1px solid #3a3a3a;
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}

QTabBar::tab:selected {
    background-color: #1e1e1e;
    border-bottom-color: #00adb5;
    color: #00adb5;
    font-weight: bold;
}

QTableWidget {
    background-color: #252525;
    gridline-color: #3a3a3a;
    border: 1px solid #3a3a3a;
}

QHeaderView::section {
    background-color: #2b2b2b;
    color: #00adb5;
    padding: 4px;
    border: 1px solid #3a3a3a;
    font-weight: bold;
}

QStatusBar {
    background-color: #181818;
    color: #aaaaaa;
}
"""