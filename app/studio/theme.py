"""Studio's deliberately quiet desktop theme."""
STYLE = """
QMainWindow, QWidget { background: #141619; color: #edf0f4; font-size: 14px; }
QFrame#rail, QFrame#panel { background: #1f252b; border-radius: 12px; }
QFrame#rail QLabel, QFrame#panel QLabel { background: transparent; }
QLabel#title { font-size: 24px; font-weight: 600; }
QLabel#muted { color: #a0acb9; }
QLabel#notice { color: #e7c28b; }
QPushButton { background: #2b323a; border: 1px solid transparent; border-radius: 7px;
 padding: 11px 16px; min-height: 20px; }
QPushButton:hover { background: #36414b; }
QPushButton:focus { border: 1px solid #75e0c1; }
QPushButton:disabled { background: #24282d; color: #66717c; }
QPushButton#primary { background: #75e0c1; color: #10241f; font-weight: 600; }
QPushButton#primary:hover { background: #9cebd4; }
QPushButton#primary:disabled { background: #344940; color: #8da79d; }
QPushButton:checked { background: #1a4037; color: #75e0c1; }
QPushButton#asset { border: 1px dashed #495661; min-height: 100px; }
QProgressBar { background: #30373f; border: 0; border-radius: 3px; height: 6px; }
QProgressBar::chunk { background: #75e0c1; border-radius: 3px; }
QListWidget, QGraphicsView { background: #191d21; border: 0; border-radius: 8px; }
QSplitter::handle { background: #141619; width: 10px; }
QCheckBox { spacing: 8px; }
QToolTip { background: #30373f; color: #edf0f4; border: 0; padding: 6px; }
"""
STYLE += """
QFrame#rail { background: #191d21; border-radius: 0; }
QFrame#panel { background: #1f252b; border-radius: 10px; }
QFrame#divider { background: #35404a; }
QLabel { background: transparent; }
QLabel#muted { font-size: 12px; color: #8d9ca7; }
QPushButton#segment { padding: 7px 9px; min-height: 18px; background: transparent; }
QPushButton#segment:checked { background: #354039; color: #75e0c1; }
QPushButton#segment:disabled { color: #58626a; }
QToolButton#mediaCard { background: #293038; border: 1px solid #35404a; border-radius: 8px; padding: 8px; }
QToolButton#mediaCard:hover { border-color: #75e0c1; }
QToolButton#mediaCard:disabled { color: #65717b; }
QComboBox { background: #293038; border: 1px solid #35404a; padding: 6px; border-radius: 6px; }
QComboBox::drop-down { border: 0; width: 20px; }
QComboBox QAbstractItemView { background: #293038; selection-background-color: #1a4037; }
QSlider::groove:horizontal { height: 4px; background: #35404a; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #75e0c1; border-radius: 2px; }
QSlider::handle:horizontal { background: #eaf6f1; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }
QSlider:disabled { color: #65717b; }
QGroupBox { border: 1px solid #35404a; border-radius: 7px; margin-top: 18px; padding: 20px 6px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; top: 5px; }
QListWidget::item { padding: 18px; background: #242b31; border-radius: 6px; }
QListWidget::item:selected { background: #1a4037; color: #75e0c1; }
"""

STYLE += """
QFrame#settingsBackdrop { background: rgba(0, 0, 0, 130); }
QFrame#settingsDrawer { background: #1f252b; border: 1px solid #35404a; border-radius: 12px; }
QTabWidget::pane { border: 0; background: #1f252b; }
QTabBar::tab { background: transparent; color: #8d9ca7; padding: 12px 24px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #75e0c1; border-bottom-color: #75e0c1; }
QTabBar::tab:hover { color: #edf0f4; }
"""
