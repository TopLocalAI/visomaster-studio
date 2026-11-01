"""Compact desktop presentation; no inference or project state lives here."""
from pathlib import Path
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W, QtSvg

# A small, consistent set of 16px outline symbols, drawn locally.
PATHS = {
    'reset': '<path d="M3 6a5 5 0 1 1 0 5M3 2v4h4"/>',
    'plus': '<path d="M8 3v10M3 8h10"/>',
    'folder': '<path d="M2 5V3h4l2 2h6v8H2Z"/>',
    'sliders': '<path d="M3 2v12M8 2v12M13 2v12"/><path d="M1 5h4M6 10h4M11 6h4"/>',
    'queue': '<path d="M6 4h8M6 8h8M6 12h8"/><path d="M2 4h.1M2 8h.1M2 12h.1"/>',
    'export': '<path d="M8 10V2M5 5l3-3 3 3M3 9v5h10V9"/>',
    'close': '<path d="m4 4 8 8M12 4l-8 8"/>',
    'fit': '<path d="M6 2H2v4M10 2h4v4M14 10v4h-4M6 14H2v-4"/>',
    'play': '<path d="m5 3 8 5-8 5Z"/>',
    'previous': '<path d="M3 3v10M12 3 5 8l7 5Z"/>',
    'next': '<path d="M13 3v10M4 3l7 5-7 5Z"/>',
    'sound': '<path d="M2 6h3l4-3v10l-4-3H2ZM12 5c2 2 2 4 0 6"/>',
    'dots': '<circle cx="3" cy="8" r=".6"/><circle cx="8" cy="8" r=".6"/><circle cx="13" cy="8" r=".6"/>',
    'image': '<rect x="2" y="2" width="12" height="12" rx="2"/><circle cx="6" cy="6" r="1"/><path d="m3 12 4-4 3 3 2-2 2 3"/>',
}

def icon(name, color='#c4c6ca'):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"><g fill="none" stroke="{color}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</g></svg>'
    renderer = QtSvg.QSvgRenderer(C.QByteArray(svg.encode()))
    pix = G.QPixmap(32, 32); pix.fill(C.Qt.transparent)
    p = G.QPainter(pix); renderer.render(p); p.end(); pix.setDevicePixelRatio(2)
    return G.QIcon(pix)

class ElidedLabel(W.QLabel):
    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.full_text = text
        self.setMinimumWidth(0)
        self.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text):
        self.full_text = str(text)
        self.setToolTip(self.full_text)
        super().setText(self.fontMetrics().elidedText(self.full_text, C.Qt.ElideMiddle, max(10, self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setText(self.full_text)


def tool(text, symbol, callback=None, *, primary=False):
    b = W.QPushButton(text)
    b.setObjectName('exportAction' if primary else 'toolAction')
    b.setIcon(icon(symbol, '#192c26' if primary else '#c4c6ca'))
    b.setIconSize(C.QSize(16,16))
    b.setFixedHeight(30)
    b.setCursor(C.Qt.PointingHandCursor)
    if callback: b.clicked.connect(callback)
    return b


def small_button(symbol, tip, callback=None):
    b = tool('', symbol, callback)
    b.setFixedSize(26, 26); b.setToolTip(tip); b.setAccessibleName(tip)
    return b

STYLE = '''
QMainWindow, QWidget { background: #242528; color: #dcdee1; font-size: 13px; }
QLabel { background: transparent; border: 0; }
QLabel#muted, QLabel#sectionCount { color: #858a91; font-size: 11px; }
QLabel#sectionTitle { color: #b4b8bf; font-size: 12px; font-weight: 500; }
QLabel#documentTitle { color: #e1e3e6; font-weight: 500; }
QWidget#studioToolbar { background: #2b2c30; border-bottom: 1px solid #37393d; }
QFrame#assetsPanel { background: #242528; border-right: 1px solid #37393d; }
QWidget#canvasPanel, QFrame#canvasHost { background: #17181a; }
QWidget#canvasHeader, QWidget#transport { background: #202124; }
QWidget#statusStrip { background: #202124; border-top: 1px solid #323439; }
QFrame#sectionRule { background: #37393d; max-height: 1px; border: 0; }
QPushButton, QToolButton { background: #33353a; border: 1px solid #41444a; border-radius: 5px; padding: 5px 9px; min-height: 0; color: #dcdee1; }
QPushButton:hover, QToolButton:hover { background: #41444b; border-color: #555961; }
QPushButton:pressed { background: #292c30; }
QPushButton:focus, QToolButton:focus { border-color: #8ab9ab; }
QPushButton:disabled, QToolButton:disabled { color: #666b73; background: #292b2f; border-color: #33363b; }
QPushButton:checked { background: #334840; border-color: #77a996; color: #c7e4d8; }
QPushButton#toolAction { background: transparent; border: 1px solid transparent; padding: 4px 8px; }
QPushButton#toolAction:hover { background: #3b3d42; }
QPushButton#toolAction:focus { border: 1px solid #8ab9ab; }
QPushButton#exportAction { background: #91c8b4; color: #192c26; border: 0; padding: 4px 14px; font-weight: 600; }
QPushButton#exportAction:hover { background: #aad9c8; }
QPushButton#exportAction:disabled { background: #3b5149; color: #80958d; }
QPushButton#faceCard { padding: 3px; border-radius: 5px; border: 1px solid #45484d; background: #2c2e32; }
QPushButton#faceCard:checked { border: 2px solid #91c8b4; background: #334840; }
QPushButton#mediaRow { text-align: left; padding: 0; border-radius: 5px; border: 1px solid transparent; background: transparent; }
QPushButton#mediaRow:checked { background: #383c40; border: 1px solid #525b5a; }
QPushButton#mediaRow:hover { background: #33363a; }
QPushButton#mediaRow QLabel { background: transparent; border: 0; font-size: 12px; }
QCheckBox { spacing: 6px; background: transparent; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #5b6068; border-radius: 3px; background: #292c31; }
QCheckBox::indicator:checked { background: #91c8b4; border: 3px solid #91c8b4; image: none; }
QCheckBox::indicator:disabled { border-color: #3e4146; background: #34373b; }
QListWidget { background: transparent; border: 0; outline: 0; border-radius: 0; }
QListWidget::item { padding: 0; border: 0; background: transparent; }
QListWidget::item:selected { background: #39443f; }
QGraphicsView { background: #17181a; border: 0; border-radius: 0; }
QLineEdit, QSpinBox, QDoubleSpinBox { color: #d9dce1; background: #202226; border: 1px solid #43474e; border-radius: 4px; padding: 4px 6px; min-height: 0; }
QLineEdit:focus { border-color: #8ab9ab; }
QComboBox { background: #303338; border: 1px solid #494d54; padding: 5px 8px; border-radius: 4px; min-height: 0; }
QComboBox::drop-down { border: 0; width: 20px; }
QComboBox QAbstractItemView, QMenu { background: #2d3035; border: 1px solid #484c53; padding: 5px; selection-background-color: #414c47; }
QMenu::item { padding: 6px 20px; border-radius: 3px; }
QMenu::item:selected { background: #414c47; }
QMenu::separator { height: 1px; background: #45484d; margin: 4px; }
QScrollArea, QTabWidget::pane { border: 0; background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #51555c; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 0; }
QScrollBar::handle:horizontal { background: #51555c; border-radius: 4px; min-width: 24px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QSlider::groove:horizontal { height: 3px; background: #454a51; border-radius: 1px; }
QSlider::sub-page:horizontal { background: #91c8b4; }
QSlider::handle:horizontal { background: #dce6e1; width: 10px; margin: -4px 0; border-radius: 5px; }
QProgressBar { background: #363a40; border: 0; border-radius: 2px; max-height: 4px; }
QProgressBar::chunk { background: #91c8b4; border-radius: 2px; }
QFrame#settingsDrawer { background: #242528; border-left: 1px solid #37393d; }
QGroupBox { border: 1px solid #41444a; border-radius: 4px; margin-top: 12px; padding: 12px 6px 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 7px; }
QToolTip { color: #e1e3e6; background: #34373c; border: 1px solid #50545c; padding: 5px; }
'''
