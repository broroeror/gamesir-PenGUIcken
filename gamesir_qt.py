"""
GameSir Cyclone 2 - Qt/QML application entry point
==================================================
Starts the existing background reader thread (unchanged) and hosts the QML UI.
The reverse-engineered protocol code is reused as-is; this file only wires the
reader + the QML engine + the bridge together.

Run:  python3 gamesir_qt.py
"""

import os
import sys
import threading

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from gamesir_reader import read_controller, press_select_loop
from gamesir_bridge import GamesirBridge
import gamesir_kwin as kwin
import gamesir_mousegrab as mousegrab

__version__ = '0.2.0-dev'

HERE = os.path.dirname(os.path.abspath(__file__))
QML_DIR = os.path.join(HERE, 'qml')
ASSETS_DIR = os.path.join(HERE, 'assets')


def main():
    # Background side: identical to the Dear PyGui app.
    threading.Thread(target=read_controller, daemon=True).start()
    # Press-to-select: switch the driven controller by pressing a button on it.
    threading.Thread(target=press_select_loop, daemon=True).start()
    if not kwin.available():
        mousegrab.start()   # EVIOCGRAB fallback (non-KDE); KDE uses the KWin plugin

    app = QGuiApplication(sys.argv)
    app.setApplicationName('GameSir Cyclone 2')
    app.setOrganizationName('gamesir-linux')
    icon_path = os.path.join(ASSETS_DIR, 'icon.png')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    engine = QQmlApplicationEngine()
    engine.addImportPath(QML_DIR)                 # makes `import App` resolve
    bridge = GamesirBridge()
    engine.rootContext().setContextProperty('bridge', bridge)
    engine.rootContext().setContextProperty('appVersion', __version__)
    engine.rootContext().setContextProperty(
        'assetsDir', QUrl.fromLocalFile(ASSETS_DIR + os.sep).toString())

    engine.load(QUrl.fromLocalFile(os.path.join(QML_DIR, 'Main.qml')))
    if not engine.rootObjects():
        sys.exit('Failed to load QML.')

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
