"""Generate the Studio vector mark at all required macOS icon sizes."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import subprocess
import sys
import tempfile
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter, QColor, QPen, QPainterPath
from PySide6.QtCore import Qt, QRectF
app=QApplication([])
with tempfile.TemporaryDirectory() as tmp:
    icons=Path(tmp)/'Studio.iconset'; icons.mkdir()
    for size in [16,32,128,256,512]:
        for scale in [1,2]:
            n=size*scale
            im=QImage(n,n,QImage.Format_ARGB32); im.fill(Qt.transparent)
            p=QPainter(im); p.setRenderHint(QPainter.Antialiasing); p.scale(n/1024,n/1024)
            p.setPen(Qt.NoPen); p.setBrush(QColor('#182622')); p.drawRoundedRect(QRectF(62,62,900,900),200,200)
            pen=QPen(QColor('#9ee6c7'),105,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin); p.setPen(pen)
            path=QPainterPath(); path.moveTo(285,325); path.lineTo(507,710); path.lineTo(740,325); p.drawPath(path)
            p.setPen(Qt.NoPen); p.setBrush(QColor('#edf5f0')); p.drawEllipse(QRectF(675,615,100,100)); p.end()
            im.save(str(icons/f'icon_{size}x{size}{"@2x" if scale==2 else ""}.png'))
    subprocess.run(['iconutil','-c','icns',str(icons),'-o',sys.argv[1]],check=True)
