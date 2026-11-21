"""Isabelledit · editor de video liviano (PySide6 + FFmpeg)."""
import copy
import json
import os
import shutil
import sys
import tempfile
from dataclasses import asdict

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QPolygonF, QIcon, QShortcut, QKeySequence, QCursor
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSlider,
    QScrollArea, QFileDialog, QMessageBox, QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit,
    QDialog, QFormLayout, QDialogButtonBox, QProgressBar, QMenu)

import engine as E

APP = "Isabelledit"
ROSE, LILAC = "#ff6b9d", "#b79cff"
PAL = ["#ff6b9d", "#b79cff", "#5ec8e5", "#6fd6a4", "#f2b866", "#f28b82"]
PAD = 10

QSS = f"""
* {{ font-family: 'Segoe UI', 'Noto Sans', sans-serif; font-size: 13px; color: #ece8f4; }}
QMainWindow, QDialog {{ background: #17121f; }}
QLabel#logo {{ font-size: 24px; font-weight: 700; }}
QLabel#h2 {{ font-size: 12px; font-weight: 700; color: {LILAC}; padding-top: 10px; }}
QLabel#dim {{ color: #8f87a3; }}
QWidget#panel {{ background: #1f1929; border-radius: 12px; }}
QPushButton {{ background: #2a2236; border: none; border-radius: 8px; padding: 7px 14px; }}
QPushButton:hover {{ background: #352b45; }}
QPushButton:disabled {{ color: #6c6380; }}
QPushButton[kind="accent"] {{ background: {ROSE}; color: #2b0f1b; font-weight: 700; padding: 8px 20px; }}
QPushButton[kind="accent"]:hover {{ background: #ff86ae; }}
QPushButton[kind="accent"]:disabled {{ background: #5b3446; color: #a98a98; }}
QPushButton[kind="ghost"] {{ background: transparent; color: #aaa1bf; }}
QPushButton[kind="ghost"]:hover {{ background: #251d30; }}
QScrollArea {{ border: none; background: transparent; }}
QSlider::groove:horizontal {{ height: 4px; background: #3a3049; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ROSE}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: #fff; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: #2a2236; border: 1px solid #3a3049; border-radius: 6px; padding: 4px 6px; }}
QComboBox QAbstractItemView {{ background: #2a2236; selection-background-color: #5b3f78; }}
QProgressBar {{ background: #2a2236; border: none; border-radius: 4px; max-height: 8px; }}
QProgressBar::chunk {{ background: {ROSE}; border-radius: 4px; }}
QStatusBar, QMenu {{ background: #17121f; color: #aaa1bf; }}
QMenu::item:selected {{ background: #352b45; }}
"""


def fmt(t):
    m = int(t // 60)
    return f"{m:02d}:{t - m * 60:04.1f}"


class Job(QThread):
    progress = Signal(float)
    done = Signal(bool, str)

    def __init__(self, runner):
        super().__init__()
        self.r = runner
        runner.on_progress = self.progress.emit

    def run(self):
        try:
            ok, log = self.r.run()
        except Exception as ex:  # noqa: BLE001
            ok, log = False, str(ex)
        self.done.emit(ok, log)


class ExportDialog(QDialog):
    QUALITY = [("Idéntica · sin pérdida visible, archivo liviano", 16, "medium"),
               ("Alta · más rápida", 19, "veryfast"),
               ("Ligera · archivo pequeño", 24, "faster"),
               ("Copia exacta · sin recodificar (solo unir clips enteros)", None, None)]
    RES = [("Original", 0), ("1080p", 1080), ("720p", 720), ("480p", 480)]

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Exportar video")
        f = QFormLayout(self)
        self.q, self.r = QComboBox(), QComboBox()
        self.q.addItems([x[0] for x in self.QUALITY])
        self.r.addItems([x[0] for x in self.RES])
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow("Calidad", self.q)
        f.addRow("Resolución", self.r)
        f.addRow(bb)

    def values(self):
        _, crf, pre = self.QUALITY[self.q.currentIndex()]
        return crf, pre, self.RES[self.r.currentIndex()][1]


class Timeline(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw, self.pps = mw, 60.0
        self.setMinimumHeight(140)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def x_of(self, t):
        return PAD + t * self.pps

    def fit(self):
        self.setMinimumWidth(int(self.x_of(max(self.mw.total() + 8, 12))))

    def set_zoom(self, v):
        self.pps = float(v)
        self.fit()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        mw, pps = self.mw, self.pps
        p.fillRect(self.rect(), QColor("#17121f"))
        p.setFont(QFont("Segoe UI", 8))
        fm = p.fontMetrics()
        step = 1 if pps >= 50 else 2 if pps >= 25 else 5 if pps >= 12 else 15
        p.setPen(QColor("#8f87a3"))
        for s in range(0, int(self.width() / pps) + 1, step):
            x = int(self.x_of(s))
            p.drawLine(x, 16, x, 24)
            p.drawText(x + 3, 12, f"{s // 60}:{s % 60:02d}")
        acc = 0.0
        for i, c in enumerate(mw.clips):
            r = QRectF(self.x_of(acc) + 1, 30, max(c.length * pps - 2, 3), 62)
            sel = i == mw.sel
            p.setPen(QPen(QColor("white"), 2) if sel else Qt.PenStyle.NoPen)
            p.setBrush(QColor(PAL[i % len(PAL)]).darker(115 if sel else 170))
            p.drawRoundedRect(r, 8, 8)
            p.setPen(QColor("white"))
            name = os.path.basename(c.path) + (f"  ×{c.speed:g}" if c.speed != 1 else "")
            inner = r.adjusted(8, 6, -6, -6)
            p.drawText(inner, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                       fm.elidedText(name, Qt.TextElideMode.ElideRight, max(int(inner.width()), 1)))
            p.drawText(inner, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, f"{c.length:.1f} s")
            acc += c.length
        if acc:
            mr = QRectF(self.x_of(0), 100, acc * pps, 26)
            if mw.music:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#2f6f77"))
                p.drawRoundedRect(mr, 6, 6)
                p.setPen(QColor("white"))
                p.drawText(mr.adjusted(8, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           "♪ " + os.path.basename(mw.music))
            else:
                p.setPen(QPen(QColor("#3a3049"), 1, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(mr, 6, 6)
                p.setPen(QColor("#6c6380"))
                p.drawText(mr, Qt.AlignmentFlag.AlignCenter, "♪ pista de música (botón Música)")
        if mw.clips:
            x = self.x_of(mw.playhead())
            p.setPen(QPen(QColor(ROSE), 2))
            p.drawLine(int(x), 0, int(x), self.height())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ROSE))
            p.drawPolygon(QPolygonF([QPointF(x - 6, 0), QPointF(x + 6, 0), QPointF(x, 9)]))

    def _hit(self, e):
        self.mw.seek_global(max(0.0, (e.position().x() - PAD) / self.pps))

    def mousePressEvent(self, e):
        self._hit(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._hit(e)


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP)
        self.resize(1200, 720)
        self.setAcceptDrops(True)
        self.clips, self.sel, self.music, self.mvol = [], 0, None, 80
        self.undo, self.job, self.busy, self.tmp = [], None, False, None
        self.loaded, self.pending, self.preview_mode, self.loading = None, None, False, False
        self.ctl = {}
        self.video = QVideoWidget()
        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self.on_pos)
        self.player.mediaStatusChanged.connect(self.on_status)
        self._build_ui()
        self.player.playbackStateChanged.connect(lambda *_: self.sync_ui())
        for key, fn in [("Space", self.toggle_play), ("Ctrl+K", self.split), ("Delete", self.delete),
                        ("Ctrl+Z", self.do_undo), ("Ctrl+E", self.export), ("Ctrl+S", self.save_project)]:
            QShortcut(QKeySequence(key), self).activated.connect(fn)
        self.load_inspector()
        self.statusBar().showMessage("Arrastra videos aquí o pulsa «Importar» para empezar.")

    # ------------------------------------------------------------------ UI
    def btn(self, text, fn, kind=""):
        b = QPushButton(text)
        b.clicked.connect(lambda *_: fn())
        if kind:
            b.setProperty("kind", kind)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(14, 10, 14, 6)
        v.setSpacing(10)
        # cabecera
        h = QHBoxLayout()
        logo = QLabel(f"<span style='color:{ROSE}'>Isabell</span><span style='color:{LILAC}'>edit</span>")
        logo.setObjectName("logo")
        h.addWidget(logo)
        h.addStretch()
        h.addWidget(self.btn("Abrir proyecto", self.open_project, "ghost"))
        h.addWidget(self.btn("Guardar", self.save_project, "ghost"))
        h.addSpacing(8)
        h.addWidget(self.btn("+ Importar", self.import_media))
        h.addWidget(self.btn("♪ Música", self.music_menu))
        self.b_export = self.btn("Exportar", self.export, "accent")
        h.addWidget(self.b_export)
        v.addLayout(h)
        # centro: vista previa + inspector
        mid = QHBoxLayout()
        mid.setSpacing(12)
        left = QVBoxLayout()
        self.video.setMinimumSize(420, 236)
        left.addWidget(self.video, 1)
        tr = QHBoxLayout()
        self.b_play = self.btn("Reproducir", self.toggle_play)
        self.b_play.setFixedWidth(110)
        tr.addWidget(self.b_play)
        self.sl = QSlider(Qt.Orientation.Horizontal)
        self.sl.sliderMoved.connect(lambda x: self.seek_global(x / 1000))
        tr.addWidget(self.sl, 1)
        self.lb_time = QLabel("00:00.0 / 00:00.0")
        self.lb_time.setObjectName("dim")
        tr.addWidget(self.lb_time)
        tr.addWidget(self.btn("Probar efectos (4 s)", self.fx_preview))
        left.addLayout(tr)
        mid.addLayout(left, 1)
        mid.addWidget(self._build_inspector())
        v.addLayout(mid, 1)
        # barra de herramientas de la línea de tiempo
        tb = QHBoxLayout()
        for text, fn, tip in [("Dividir", self.split, "Ctrl+K · corta en la posición del cursor"),
                              ("Eliminar", self.delete, "Supr"), ("←", lambda: self.move(-1), "Mover atrás"),
                              ("→", lambda: self.move(1), "Mover adelante"), ("Duplicar", self.duplicate, ""),
                              ("Deshacer", self.do_undo, "Ctrl+Z")]:
            b = self.btn(text, fn)
            b.setToolTip(tip)
            tb.addWidget(b)
        tb.addStretch()
        z = QLabel("Zoom")
        z.setObjectName("dim")
        tb.addWidget(z)
        zs = QSlider(Qt.Orientation.Horizontal)
        zs.setRange(10, 200)
        zs.setValue(60)
        zs.setFixedWidth(140)
        zs.valueChanged.connect(lambda x: self.tl.set_zoom(x))
        tb.addWidget(zs)
        v.addLayout(tb)
        self.tl = Timeline(self)
        self.tl_scroll = QScrollArea()
        self.tl_scroll.setWidget(self.tl)
        self.tl_scroll.setWidgetResizable(True)
        self.tl_scroll.setFixedHeight(160)
        v.addWidget(self.tl_scroll)
        # barra de estado con progreso
        self.pb_box = QWidget()
        pl = QHBoxLayout(self.pb_box)
        pl.setContentsMargins(0, 0, 0, 0)
        self.pb = QProgressBar()
        self.pb.setFixedWidth(220)
        self.pb.setTextVisible(False)
        pl.addWidget(QLabel("Procesando…"))
        pl.addWidget(self.pb)
        pl.addWidget(self.btn("Cancelar", lambda: self.job and self.job.r.cancel()))
        self.statusBar().addPermanentWidget(self.pb_box)
        self.pb_box.hide()

    def _slider(self, lay, label, key, lo, hi, scale=1, suffix=""):
        row = QHBoxLayout()
        name = QLabel(label)
        name.setFixedWidth(84)
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        val = QLabel()
        val.setFixedWidth(48)
        val.setAlignment(Qt.AlignmentFlag.AlignRight)

        def changed(x):
            val.setText(f"{x / scale:g}{suffix}")
            if self.loading:
                return
            if key == "mvol":
                self.mvol = x
            elif self.cur():
                setattr(self.cur(), key, x / scale if scale != 1 else x)
                self.refresh()

        s.valueChanged.connect(changed)
        self.ctl[key] = (s, scale, changed)
        for w in (name, s, val):
            row.addWidget(w)
        lay.addLayout(row)

    def _prop(self, key):
        def f(x):
            if not self.loading and self.cur():
                setattr(self.cur(), key, x)
                self.refresh()
        return f

    def _build_inspector(self):
        scroll = QScrollArea()
        scroll.setFixedWidth(318)
        scroll.setWidgetResizable(True)
        panel = QWidget()
        panel.setObjectName("panel")
        self.insp = panel
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 6, 14, 14)
        lay.setSpacing(6)

        def h2(t):
            lb = QLabel(t)
            lb.setObjectName("h2")
            lay.addWidget(lb)
        h2("Clip seleccionado")
        self.lb_name = QLabel("—")
        self.lb_name.setObjectName("dim")
        lay.addWidget(self.lb_name)
        form = QFormLayout()
        self.sp_in, self.sp_out = QDoubleSpinBox(), QDoubleSpinBox()
        for sp in (self.sp_in, self.sp_out):
            sp.setDecimals(2)
            sp.setSingleStep(0.1)
            sp.setSuffix(" s")
        self.sp_in.valueChanged.connect(lambda _: self._trim("in"))
        self.sp_out.valueChanged.connect(lambda _: self._trim("out"))
        form.addRow("Inicio", self.sp_in)
        form.addRow("Fin", self.sp_out)
        lay.addLayout(form)
        h2("Imagen y sonido")
        for args in [("Brillo", "bright", -100, 100), ("Contraste", "contrast", -100, 100),
                     ("Saturación", "sat", 0, 200, 1, "%"), ("Velocidad", "speed", 25, 400, 100, "×"),
                     ("Volumen", "vol", 0, 200, 1, "%")]:
            self._slider(lay, *args)
        h2("Filtro y fundidos")
        self.cb_look = QComboBox()
        self.cb_look.addItems(["Ninguno"] + list(E.LOOKS))
        self.cb_look.currentTextChanged.connect(self._prop("look"))
        lay.addWidget(self.cb_look)
        ff = QFormLayout()
        self.sp_fi, self.sp_fo = QDoubleSpinBox(), QDoubleSpinBox()
        for sp, key in ((self.sp_fi, "fade_in"), (self.sp_fo, "fade_out")):
            sp.setRange(0, 5)
            sp.setSingleStep(0.1)
            sp.setSuffix(" s")
            sp.valueChanged.connect(self._prop(key))
        ff.addRow("Entrada", self.sp_fi)
        ff.addRow("Salida", self.sp_fo)
        lay.addLayout(ff)
        h2("Texto en pantalla")
        self.ed_text = QLineEdit()
        self.ed_text.setPlaceholderText("Escribe un título…")
        self.ed_text.textChanged.connect(self._prop("text"))
        lay.addWidget(self.ed_text)
        tf = QFormLayout()
        self.cb_pos = QComboBox()
        self.cb_pos.addItems(list(E.TEXT_POS))
        self.cb_pos.currentTextChanged.connect(self._prop("text_pos"))
        self.sp_ts = QSpinBox()
        self.sp_ts.setRange(10, 200)
        self.sp_ts.valueChanged.connect(self._prop("text_size"))
        tf.addRow("Posición", self.cb_pos)
        tf.addRow("Tamaño", self.sp_ts)
        lay.addLayout(tf)
        h2("Proyecto")
        self._slider(lay, "Música", "mvol", 0, 150, 1, "%")
        lay.addStretch()
        scroll.setWidget(panel)
        return scroll

    # ------------------------------------------------------------- estado
    def cur(self):
        return self.clips[self.sel] if 0 <= self.sel < len(self.clips) else None

    def total(self):
        return sum(c.length for c in self.clips)

    def playhead(self):
        c = self.cur()
        if not c:
            return 0.0
        acc = sum(x.length for x in self.clips[:self.sel])
        if self.preview_mode or self.loaded != c.path:
            return acc
        t = self.player.position() / 1000
        return acc + max(0.0, min((t - c.t_in) / c.speed, c.length))

    def load_inspector(self):
        self.loading = True
        c = self.cur()
        if c:
            self.lb_name.setText(os.path.basename(c.path))
            self.sp_in.setRange(0, c.dur)
            self.sp_out.setRange(0.1, c.dur)
            self.sp_in.setValue(c.t_in)
            self.sp_out.setValue(c.t_out)
            for key, (s, scale, ch) in self.ctl.items():
                val = self.mvol if key == "mvol" else getattr(c, key)
                s.setValue(round(val * scale))
                ch(s.value())
            self.cb_look.setCurrentText(c.look)
            self.sp_fi.setValue(c.fade_in)
            self.sp_fo.setValue(c.fade_out)
            self.ed_text.setText(c.text)
            self.cb_pos.setCurrentText(c.text_pos)
            self.sp_ts.setValue(c.text_size)
        else:
            self.lb_name.setText("—")
        self.loading = False
        self.insp.setEnabled(bool(c))

    def refresh(self):
        self.tl.fit()
        self.sl.setRange(0, int(self.total() * 1000))
        c = self.cur()
        if c and not self.preview_mode:
            self.player.setPlaybackRate(c.speed)
            self.audio.setVolume(min(1.0, c.vol / 100))
        self.sync_ui()

    def sync_ui(self):
        ph = self.playhead()
        self.sl.blockSignals(True)
        self.sl.setValue(int(ph * 1000))
        self.sl.blockSignals(False)
        self.lb_time.setText(f"{fmt(ph)} / {fmt(self.total())}")
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.b_play.setText("Pausa" if playing else "Reproducir")
        self.tl.update()
        if playing:
            self.tl_scroll.ensureVisible(int(self.tl.x_of(ph)), 10, 90, 10)

    # ----------------------------------------------------------- reproductor
    def load_clip(self, i, local=None, play=False):
        changed = i != self.sel or self.preview_mode
        self.preview_mode = False
        self.sel = i
        c = self.clips[i]
        local = c.t_in if local is None else local
        self.audio.setVolume(min(1.0, c.vol / 100))
        if self.loaded != c.path:
            self.loaded = c.path
            self.pending = (local, play)
            self.player.setSource(QUrl.fromLocalFile(c.path))
        else:
            self.pending = None
            self.player.setPlaybackRate(c.speed)
            self.player.setPosition(int(local * 1000))
            self.player.play() if play else self.player.pause()
        if changed:
            self.load_inspector()
        self.sync_ui()

    def on_status(self, st):
        ready = (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia)
        if st in ready and self.pending:
            local, play = self.pending
            self.pending = None
            c = self.cur()
            self.player.setPlaybackRate(1.0 if self.preview_mode or not c else c.speed)
            self.player.setPosition(int(local * 1000))
            self.player.play() if play else self.player.pause()

    def on_pos(self, ms):
        if self.preview_mode:
            return
        c = self.cur()
        if not c or self.loaded != c.path:
            return
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if playing and ms / 1000 >= c.t_out - 0.03:
            if self.sel + 1 < len(self.clips):
                self.load_clip(self.sel + 1, play=True)
            else:
                self.player.pause()
            return
        self.sync_ui()

    def toggle_play(self):
        c = self.cur()
        if not c:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        elif not self.preview_mode and self.loaded == c.path and self.player.position() / 1000 < c.t_out - 0.05:
            self.player.play()
        elif self.preview_mode:
            self.player.play()
        else:
            self.load_clip((self.sel + 1) % len(self.clips) if self.loaded == c.path else self.sel, play=True)
        self.sync_ui()

    def seek_global(self, t):
        if not self.clips:
            return
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        acc = 0.0
        for i, c in enumerate(self.clips):
            if t < acc + c.length or i == len(self.clips) - 1:
                self.load_clip(i, c.t_in + min(max(t - acc, 0.0), c.length) * c.speed, play=playing)
                return
            acc += c.length

    # ------------------------------------------------------------- edición
    def snap(self):
        self.undo.append((copy.deepcopy(self.clips), self.sel))
        del self.undo[:-30]

    def after_edit(self):
        self.sel = max(0, min(self.sel, len(self.clips) - 1))
        self.load_inspector()
        self.refresh()
        if self.clips:
            self.load_clip(self.sel)
        else:
            self.player.stop()
            self.loaded = None

    def do_undo(self):
        if self.undo:
            self.clips, self.sel = self.undo.pop()
            self.after_edit()

    def _trim(self, which):
        c = self.cur()
        if self.loading or not c:
            return
        a, b = self.sp_in.value(), self.sp_out.value()
        a, b = (min(a, b - 0.1), b) if which == "in" else (a, max(b, a + 0.1))
        c.t_in, c.t_out = round(max(a, 0), 2), round(b, 2)
        self.loading = True
        self.sp_in.setValue(c.t_in)
        self.sp_out.setValue(c.t_out)
        self.loading = False
        self.refresh()
        self.load_clip(self.sel, c.t_in if which == "in" else max(c.t_in, c.t_out - 0.1))

    def split(self):
        c = self.cur()
        if not c or self.preview_mode or self.loaded != c.path:
            return
        t = self.player.position() / 1000
        if not (c.t_in + 0.15 < t < c.t_out - 0.15):
            self.statusBar().showMessage("Coloca el cursor dentro del clip para dividirlo.", 4000)
            return
        self.snap()
        b = copy.deepcopy(c)
        c.t_out, b.t_in = t, t
        c.fade_out, b.fade_in, b.text = 0.0, 0.0, ""
        self.clips.insert(self.sel + 1, b)
        self.load_inspector()
        self.refresh()

    def delete(self):
        if self.cur():
            self.snap()
            self.clips.pop(self.sel)
            self.after_edit()

    def duplicate(self):
        if self.cur():
            self.snap()
            self.clips.insert(self.sel + 1, copy.deepcopy(self.cur()))
            self.sel += 1
            self.after_edit()

    def move(self, d):
        j = self.sel + d
        if self.cur() and 0 <= j < len(self.clips):
            self.snap()
            self.clips[self.sel], self.clips[j] = self.clips[j], self.clips[self.sel]
            self.sel = j
            self.refresh()

    # --------------------------------------------------------------- medios
    def import_media(self, files=None):
        if not files:
            files, _ = QFileDialog.getOpenFileNames(self, "Importar videos", "", E.VIDEO_FILTER)
        if not files:
            return
        self.snap()
        first, added = len(self.clips), 0
        for f in files:
            try:
                self.clips.append(E.probe(f))
                added += 1
            except Exception as ex:  # noqa: BLE001
                QMessageBox.warning(self, APP, f"No pude abrir {os.path.basename(f)}:\n{ex}")
        if added:
            self.sel = first
            self.after_edit()
            self.statusBar().showMessage(f"{added} clip(s) añadidos a la línea de tiempo.", 4000)

    def music_menu(self):
        m = QMenu(self)
        m.addAction("Elegir archivo de música…", self.pick_music)
        if self.music:
            m.addAction("Quitar música", self.remove_music)
        m.exec(QCursor.pos())

    def pick_music(self):
        f, _ = QFileDialog.getOpenFileName(self, "Elegir música", "", E.AUDIO_FILTER)
        if f:
            self.music = f
            self.refresh()
            self.statusBar().showMessage("La música se mezcla al exportar (no suena en la vista previa).", 6000)

    def remove_music(self):
        self.music = None
        self.refresh()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.import_media([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    def save_project(self):
        p, _ = QFileDialog.getSaveFileName(self, "Guardar proyecto", "proyecto.isabelledit",
                                           "Proyecto Isabelledit (*.isabelledit)")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"clips": [asdict(c) for c in self.clips], "music": self.music,
                           "mvol": self.mvol}, f, ensure_ascii=False, indent=1)
            self.statusBar().showMessage("Proyecto guardado.", 4000)

    def open_project(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir proyecto", "", "Proyecto Isabelledit (*.isabelledit)")
        if not p:
            return
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            clips = [E.Clip(**c) for c in d["clips"]]
        except Exception as ex:  # noqa: BLE001
            QMessageBox.warning(self, APP, f"No pude abrir el proyecto:\n{ex}")
            return
        missing = [os.path.basename(c.path) for c in clips if not os.path.exists(c.path)]
        if missing:
            QMessageBox.warning(self, APP, "Faltan estos archivos:\n" + "\n".join(missing))
        self.snap()
        self.clips = [c for c in clips if os.path.exists(c.path)]
        self.music = d.get("music") if d.get("music") and os.path.exists(d["music"]) else None
        self.mvol, self.sel = d.get("mvol", 80), 0
        self.after_edit()

    # ----------------------------------------------------------- exportación
    def clean_tmp(self):
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp = tempfile.mkdtemp(prefix="isabelledit_")

    def run_job(self, cmd, total, cb):
        if self.job:
            self.job.wait()
        self.busy = True
        self.job = Job(E.Runner(cmd, total))
        self.pb.setValue(0)
        self.pb_box.show()
        self.b_export.setEnabled(False)
        self.job.progress.connect(lambda p: self.pb.setValue(int(p * 100)))
        self.job.done.connect(lambda ok, log: self._job_done(ok, log, cb))
        self.job.start()

    def _job_done(self, ok, log, cb):
        self.busy = False
        self.pb_box.hide()
        self.b_export.setEnabled(True)
        if not self.job.r.cancelled:
            cb(ok, log)

    def out_size(self, res_h):
        c = self.clips[0]
        w, h = c.w, c.h
        if res_h and res_h < h:
            w, h = round(w * res_h / h), res_h
        return max(2, w // 2 * 2), max(2, h // 2 * 2)

    def export(self):
        if self.busy:
            return
        if not self.clips:
            self.statusBar().showMessage("Importa al menos un video para exportar.", 4000)
            return
        dlg = ExportDialog(self)
        if not dlg.exec():
            return
        crf, pre, res_h = dlg.values()
        out, _ = QFileDialog.getSaveFileName(self, "Guardar video", "video_isabelledit.mp4", "MP4 (*.mp4)")
        if not out:
            return
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        self.player.pause()
        self.clean_tmp()
        cmd = None
        if crf is None:
            if E.can_copy(self.clips, self.music):
                cmd = E.copy_cmd(self.clips, out, self.tmp)
            else:
                QMessageBox.information(self, APP, "Hay recortes, efectos o música: se exportará "
                                        "recodificando en calidad idéntica.")
                crf, pre = 16, "medium"
        if cmd is None:
            W, H = self.out_size(res_h)
            cmd = E.build_cmd(self.clips, out, W, H, min(60.0, self.clips[0].fps), crf, pre,
                              self.music, self.mvol, self.tmp)
        self.run_job(cmd, self.total(), lambda ok, log: self.export_done(ok, log, out))

    def export_done(self, ok, log, out):
        if not ok:
            QMessageBox.warning(self, APP, "No se pudo exportar:\n" + (log or "error desconocido"))
            return
        box = QMessageBox(self)
        box.setWindowTitle(APP)
        box.setText(f"¡Listo! Tu video quedó en:\n{out}\n\nTamaño: {os.path.getsize(out) / 1e6:.1f} MB")
        opener = box.addButton("Abrir carpeta", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Cerrar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is opener and hasattr(os, "startfile"):
            os.startfile(os.path.dirname(out))

    def fx_preview(self):
        c = self.cur()
        if not c or self.busy:
            return
        local = self.player.position() / 1000 if (self.loaded == c.path and not self.preview_mode) else c.t_in
        a = copy.deepcopy(c)
        a.t_in = min(max(local, c.t_in), max(c.t_in, c.t_out - 0.3))
        a.t_out = min(c.t_out, a.t_in + 4 * c.speed)
        if a.t_in > c.t_in + 0.01:
            a.fade_in = 0.0
        if a.t_out < c.t_out - 0.01:
            a.fade_out = 0.0
        self.player.pause()
        self.clean_tmp()
        out = os.path.join(self.tmp, "preview.mp4")
        H = 360
        W = max(2, round(c.w * H / c.h / 2) * 2)
        cmd = E.build_cmd([a], out, W, H, min(c.fps, 30), 30, "ultrafast", tmp=self.tmp)
        self.statusBar().showMessage("Preparando vista previa con efectos…")
        self.run_job(cmd, a.length, lambda ok, log: self.preview_done(ok, log, out))

    def preview_done(self, ok, log, out):
        if not ok:
            QMessageBox.warning(self, APP, "No se pudo generar la vista previa:\n" + log)
            return
        self.statusBar().clearMessage()
        self.preview_mode = True
        self.loaded = "__preview__"
        self.pending = (0.0, True)
        self.player.setSource(QUrl.fromLocalFile(out))

    def closeEvent(self, e):
        if self.job and self.busy:
            self.job.r.cancel()
            self.job.wait(3000)
        self.player.stop()
        self.player.setSource(QUrl())
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    ico = os.path.join(E.base_dir(), "icon.ico")
    if os.path.exists(ico):
        app.setWindowIcon(QIcon(ico))
    w = Main()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
