"""Prueba de humo: abre la interfaz sin pantalla y exporta un clip con efectos."""
import os
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from PySide6.QtWidgets import QApplication  # noqa: E402
import engine as E  # noqa: E402
import main  # noqa: E402

tmp = tempfile.mkdtemp()
clip = os.path.join(tmp, "demo.mp4")
subprocess.run([E.tool("ffmpeg"), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                "testsrc2=s=640x360:r=30:d=3", "-f", "lavfi", "-i", "sine=d=3",
                "-c:v", "libx264", "-c:a", "aac", clip], check=True)

app = QApplication([])
w = main.Main()
w.show()
w.import_media([clip])
assert len(w.clips) == 1, "no se importó el clip"
w.duplicate()
assert len(w.clips) == 2
c = w.clips[0]
c.look, c.text, c.speed, c.fade_in = "Sepia", "Prueba", 1.5, 0.3
out = os.path.join(tmp, "out.mp4")
cmd = E.build_cmd(w.clips, out, 640, 360, 30, 20, "ultrafast", None, 80, tmp)
ok, log = E.Runner(cmd, w.total()).run()
assert ok and os.path.getsize(out) > 1000, "falló la exportación: " + log
w.close()
print("SMOKE OK")
