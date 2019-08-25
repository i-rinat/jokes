# -*- coding: utf8 -*-

# Convert tracklists from Youtube to CUE sheets

import sys
import re
from datetime import datetime
from PySide.QtCore import *
from PySide.QtGui import *

class Sample(QWidget):
    def __init__(self):
        super(Sample, self).__init__()
        self.init_ui()

    def init_ui(self):
        edit = QTextEdit()
        edit.setAcceptRichText(False)
        btn = QPushButton()
        btn.setText("Convert")
        btn.clicked.connect(self.do_convert)

        grid = QGridLayout()
        grid.setSpacing(10)

        grid.addWidget(edit, 1, 0, 4, 0)
        grid.addWidget(btn, 5, 0)

        self.setLayout(grid)

        self.setGeometry(800, 600, 800, 600)
        self.setWindowTitle(u"ゴーゴーＣＵＥ ＳＨＥＥＴ！")
        self.show()

        self._edit = edit

    def do_convert(self):
        result = u"FILE audio.mp3 MP3\n"

        s = self._edit.toPlainText()
        lines = [x.strip() for x in s.split('\n')]
        idx = 0
        for line in lines:
            ts = re.search('\\d{1,2}:\\d{2}:\\d{2}', line)
            if ts:
                raw_timestamp = ts.group(0)
                timestamp = datetime.strptime(raw_timestamp, '%H:%M:%S')
            else:
                ts = re.search('\\d{1,2}:\\d{2}', line)
                if ts:
                    raw_timestamp = ts.group(0)
                    timestamp = datetime.strptime(raw_timestamp, '%M:%S')
                else:
                    continue

            parts = [x.strip(u" /／.．.。・") for x in line.split(raw_timestamp)]
            track_name = sorted(parts, key=lambda x: len(x))[-1]

            idx += 1
            result += u"  TRACK {:02d} AUDIO\n".format(idx)
            result += (u"    TITLE \"{}\"\n".
                       format(track_name.replace(u'"', u"''")))
            result += (u"    INDEX 01 {:02d}:{:02d}:00\n".
                       format(timestamp.hour * 60 + timestamp.minute,
                              timestamp.second))
        self._edit.setText(result)

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    s = Sample()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
