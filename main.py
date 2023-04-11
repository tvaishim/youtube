import sys
import yt_dlp
from dataclasses import dataclass
from datetime import timedelta
from math import ceil
import pathlib
import subprocess

import youtubeform

from PyQt5 import QtWidgets, QtCore, QtGui


@dataclass
class LinkInfo:
    ok: bool
    info: dict
    id: str
    title: str
    duration: int
    abr: float
    filesize: int
    time: timedelta
    url: str

    def __init__(self, dict_info=None):
        if isinstance(dict_info, dict):
            info = dict_info["info"]
            self.ok = True
            self.info = info
            self.id = info["id"]
            self.title = info["title"]
            self.duration = info["duration"]
            self.time = timedelta(seconds=self.duration)
            self.url = dict_info["url"]

            l = sorted([x for x in info["formats"] if "audio" in x["format"]], key=lambda k: k['abr'], reverse=True)

            if l:
                self.abr = int(l[0]["abr"])
                self.filesize = l[0]["filesize"]

        else:
            self.ok = False


class ThreadGetInfo(QtCore.QThread):
    signal_start = QtCore.pyqtSignal(str)
    signal_finish = QtCore.pyqtSignal(dict)

    def __init__(self, parent):
        super(ThreadGetInfo, self).__init__()
        self.app = parent

    def run(self):
        self.signal_start.emit("Запрос информации о видео ...")

        url = self.app.main_window.ui.lineEdit.text().strip()

        ydl_opts = {"simulate": True}
        ydl = yt_dlp.YoutubeDL(ydl_opts)

        with ydl:
            try:
                result = ydl.extract_info(url)

                self.signal_finish.emit({"res": True, "info": result, "url": url})
            except Exception as e:
                self.signal_finish.emit({"res": False, "info": {}, "error": str(e), "url": url})


class ThreadDownloadVideo(QtCore.QThread):
    signal_progress = QtCore.pyqtSignal(int)
    signal_info = QtCore.pyqtSignal(str)
    signal_start = QtCore.pyqtSignal(str)
    signal_finish = QtCore.pyqtSignal(str)

    def __init__(self, parent):
        super(ThreadDownloadVideo, self).__init__()
        self.app = parent

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            self.signal_progress.emit(int(d['downloaded_bytes'] / d['total_bytes_estimate'] * 100))
        elif d['status'] == 'finished':
            self.signal_info.emit(f"Загружено, конвертируем...")
            self.signal_progress.emit(100)
        elif d['status'] == 'error':
            self.signal_info.emit(f"Ошибка загрузки!")

    def run(self):
        self.signal_start.emit(f"Загрузка...")

        url = self.app.link_info.url

        # Путь выгрузки
        result_filename = self.app.main_window.ui.lineEdit_2.text()
        path = pathlib.PurePath(result_filename)
        filename = str(pathlib.PurePath(path.parent, f"{path.stem}.%(ext)s"))

        post_proc = {
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3'
        }
        if self.app.main_window.ui.checkBox_2.isChecked():
            post_proc["preferredquality"] = self.app.main_window.ui.comboBox.currentText()

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': filename,
            'postprocessors': [post_proc],
            'progress_hooks': [self.progress_hook],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                result = ydl.download([url])
            except Exception as e:
                self.signal_info.emit(str(e))
                return

        # Разбивка на сегменты
        if self.app.main_window.ui.checkBox.isChecked():
            seg_size = int(self.app.main_window.ui.lineEdit_3.text()) * 60
            if seg_size:
                seg_count = ceil(self.app.link_info.duration / seg_size)
                if seg_count > 1:
                    self.signal_info.emit(f"Разбивка на {seg_count} частей...")

                    path = pathlib.PurePath(result_filename)
                    filename = str(path.with_stem(f"{path.stem}_%03d"))

                    cmd = f'ffmpeg.exe -i "{result_filename}" -f segment -segment_time {seg_size} -c copy "{filename}"'
                    try:
                        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
                        stdout, stderr = p.communicate()
                        if p.returncode != 0:
                            stderr = stderr.decode('utf-8', 'replace')
                            msgs = stderr.strip().split('\n')
                            msg = msgs[-1]
                            raise Exception(msg)
                    except Exception as e:
                        self.signal_info.emit(str(e))
                        return

                    try:
                        pathlib.Path(result_filename).unlink()
                    except Exception as e:
                        self.signal_info.emit(str(e))
                        return

        self.signal_finish.emit(f"Готово.")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, parent):
        super(MainWindow, self).__init__()
        self.app = parent
        self.ui = youtubeform.Ui_MainWindow()
        self.ui.setupUi(self)

        self.ui.checkBox.setChecked(True)
        self.setFixedSize(self.width(), self.height())
        self.ui.lineEdit_3.setValidator(QtGui.QIntValidator(0, 1000))
        self.ui.lineEdit_3.setText("5")

        self.ui.checkBox_2.setChecked(True)
        self.ui.comboBox.addItems(["32", "96", "128", "160", "192", "256", "320"])
        self.ui.comboBox.setCurrentIndex(3)

        self.ui_lineEdit_modified = False
        self.ui.lineEdit.editingFinished.connect(self.text_address_edit)
        self.ui.lineEdit.textChanged.connect(self.text_address_changed)

        self.ui.pushButton.setEnabled(False)
        self.ui.pushButton.clicked.connect(self.btn_start_click)

        self.ui.pushButton_2.clicked.connect(self.btn2_start_click)


    def text_address_changed(self, t):
        self.ui_lineEdit_modified = True

    def text_address_edit(self):
        if self.ui_lineEdit_modified:
            if not self.app.thread_get_info.isRunning():
                self.app.thread_get_info.start()
                self.ui_lineEdit_modified = False

    def btn_start_click(self):
        if self.app.link_info.ok:
            if not self.app.thread_download_video.isRunning():
                self.app.thread_download_video.start()

    def btn2_start_click(self):
        fn = QtWidgets.QFileDialog.getSaveFileName(self, "Выбор имени сохранения", self.ui.lineEdit_2.text(), "mp3 audio file (*.mp3)")[0]
        if fn:
            self.ui.lineEdit_2.setText(fn)


class MainApp(QtWidgets.QApplication):
    def __init__(self, argv):
        super(MainApp, self).__init__(argv)
        self.main_window = MainWindow(self)
        self.main_window.show()
        self.mutex = QtCore.QMutex()
        self.thread_get_info = ThreadGetInfo(self)
        self.thread_get_info.signal_start.connect(self.start_info)
        self.thread_get_info.signal_finish.connect(self.finish_info)
        self.thread_download_video = ThreadDownloadVideo(self)
        self.thread_download_video.signal_progress.connect(self.download_progress)
        self.thread_download_video.signal_info.connect(self.download_info)
        self.thread_download_video.signal_start.connect(self.download_start)
        self.thread_download_video.signal_finish.connect(self.download_finish)
        self.link_info = LinkInfo()

    @staticmethod
    def del_points(txt):
        res = txt
        res = res.replace("#", "")
        res = res.replace(":", "")
        res = res.replace("/", "")
        res = res.replace("\\", "")
        res = res.replace("$", "")
        res = res.replace("!", "")
        res = res.replace("*", "")
        return res

    def start_info(self, info_text):
        self.main_window.ui.textEdit.setStyleSheet("QTextEdit {background-color: #ffffff}")
        self.main_window.ui.textEdit.clear()
        self.main_window.ui.textEdit.setText(info_text)

    def finish_info(self, result_info):
        if result_info["res"]:
            self.link_info = LinkInfo(result_info)
            txt = f"Имя: {self.link_info.title}\nПродолжительность: {str(self.link_info.time)},    Размер: {(self.link_info.filesize/(1024*1024)):.2f} Мб,    Битрейт: {self.link_info.abr} кбит/с"
        else:
            self.link_info = LinkInfo()
            txt = result_info["error"]

        self.main_window.ui.textEdit.clear()
        self.main_window.ui.textEdit.setText(txt)
        self.main_window.ui.lineEdit_2.setText(f"{self.del_points(self.link_info.title)}.mp3")

        self.main_window.ui.pushButton.setEnabled(self.link_info.ok)

    def download_progress(self, proc):
        self.main_window.ui.progressBar.setValue(proc)

    def download_info(self, info_text):
        self.main_window.ui.textEdit.append(info_text)

    def download_start(self, info_text):
        self.main_window.ui.textEdit.append(info_text)
        self.main_window.ui.textEdit.setStyleSheet("QTextEdit {background-color: #ffffff}")

    def download_finish(self, info_text):
        self.main_window.ui.textEdit.append(info_text)
        self.main_window.ui.textEdit.setStyleSheet("QTextEdit {background-color: #80ff80}")


if __name__ == '__main__':
    app = MainApp(sys.argv)
    sys.exit(app.exec())
