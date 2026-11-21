"""Isabelledit · motor (sin interfaz): clips, sondeo y exportación con FFmpeg."""
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

NOFLASH = 0x08000000 if os.name == "nt" else 0  # evita ventanas de consola
VIDEO_FILTER = "Videos (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.mts *.flv)"
AUDIO_FILTER = "Audio (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)"

LOOKS = {
    "Blanco y negro": "hue=s=0",
    "Sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131:0",
    "Cálido": "colorbalance=rs=.12:rm=.08:bs=-.12:bm=-.08",
    "Frío": "colorbalance=rs=-.12:rm=-.08:bs=.12:bm=.08",
    "Cine": "eq=contrast=1.12:saturation=1.15,colorbalance=rs=-.05:bs=.07:rh=.06:bh=-.05",
    "Viñeta": "vignette=PI/4",
    "Nítido": "unsharp=5:5:0.9:5:5:0.0",
}
TEXT_POS = {
    "Abajo": "x=(w-text_w)/2:y=h*0.86-text_h",
    "Centro": "x=(w-text_w)/2:y=(h-text_h)/2",
    "Arriba": "x=(w-text_w)/2:y=h*0.08",
}


def base_dir():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def tool(name):
    """Busca ffmpeg/ffprobe junto a la app (empaquetados) o en el PATH."""
    exe = name + (".exe" if os.name == "nt" else "")
    for d in (os.path.join(base_dir(), "ffmpeg"),
              os.path.join(os.path.dirname(sys.executable), "ffmpeg")):
        p = os.path.join(d, exe)
        if os.path.exists(p):
            return p
    return shutil.which(name) or name


@dataclass
class Clip:
    path: str
    dur: float
    w: int
    h: int
    fps: float
    has_audio: bool
    t_in: float = 0.0
    t_out: float = 0.0
    speed: float = 1.0
    bright: int = 0
    contrast: int = 0
    sat: int = 100
    vol: int = 100
    look: str = "Ninguno"
    fade_in: float = 0.0
    fade_out: float = 0.0
    text: str = ""
    text_pos: str = "Abajo"
    text_size: int = 48

    def __post_init__(self):
        if not self.t_out:
            self.t_out = self.dur

    @property
    def length(self):  # duración final en la línea de tiempo
        return max(0.05, (self.t_out - self.t_in) / self.speed)

    @property
    def plain(self):  # sin cortes ni efectos → se puede copiar sin recodificar
        return (self.t_in < 0.05 and self.t_out > self.dur - 0.05 and self.speed == 1
                and self.bright == 0 and self.contrast == 0 and self.sat == 100
                and self.vol == 100 and self.look == "Ninguno" and self.fade_in == 0
                and self.fade_out == 0 and not self.text)


def probe(path):
    r = subprocess.run(
        [tool("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOFLASH)
    info = json.loads(r.stdout or "{}")
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    dur = float((info.get("format") or {}).get("duration") or 0)
    if not v or dur <= 0:
        raise ValueError("el archivo no parece un video válido")
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    rot = 0
    for sd in v.get("side_data_list") or []:
        rot = sd.get("rotation", rot)
    try:
        rot = int(float((v.get("tags") or {}).get("rotate", rot)))
    except ValueError:
        rot = 0
    if abs(rot) % 180 == 90:  # videos verticales de celular
        w, h = h, w
    try:
        n, _, d = (v.get("avg_frame_rate") or "30/1").partition("/")
        fps = float(n) / float(d or 1) or 30.0
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    return Clip(path, dur, w, h, fps, any(s.get("codec_type") == "audio" for s in streams))


def _q(path):  # ruta segura dentro de un filtro de FFmpeg
    return "'" + path.replace("\\", "/").replace(":", "\\:") + "'"


def _font():
    cands = []
    if os.name == "nt":
        win = os.environ.get("WINDIR", r"C:\Windows")
        cands = [os.path.join(win, "Fonts", n) for n in ("segoeui.ttf", "arial.ttf")]
    else:
        cands = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for p in cands:
        if os.path.exists(p):
            return "fontfile=" + _q(p) + ":"
    return ""


def _atempo(s):
    out = []
    while s > 2.0:
        out.append("atempo=2.0")
        s /= 2
    while s < 0.5:
        out.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1) > 1e-3:
        out.append(f"atempo={s:.4f}")
    return out


def _head(extra=()):
    return [tool("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
            "-progress", "pipe:1", "-nostats", *extra]


def can_copy(clips, music):
    return bool(clips) and not music and all(c.plain for c in clips)


def copy_cmd(clips, out, tmp):
    """Unión sin recodificar: calidad 100 % idéntica y casi instantánea."""
    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for c in clips:
            f.write("file '" + c.path.replace("\\", "/").replace("'", "'\\''") + "'\n")
    return _head(["-f", "concat", "-safe", "0", "-i", lst]) + \
        ["-c", "copy", "-movflags", "+faststart", out]


def build_cmd(clips, out, W, H, fps, crf, preset, music=None, mvol=80, tmp="."):
    cmd, g, total = _head(), [], 0.0
    font = _font()
    for i, c in enumerate(clips):
        cmd += ["-i", c.path]
        L = c.length
        total += L
        # ---- video ----
        v = [f"trim=start={c.t_in:.3f}:end={c.t_out:.3f}",
             f"setpts=(PTS-STARTPTS)/{c.speed:.4f}", f"fps={fps:g}",
             f"scale={W}:{H}:force_original_aspect_ratio=decrease",
             f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black", "setsar=1"]
        if c.bright or c.contrast or c.sat != 100:
            v.append(f"eq=brightness={c.bright / 200:.3f}:contrast={1 + c.contrast / 100:.3f}"
                     f":saturation={c.sat / 100:.3f}")
        if c.look in LOOKS:
            v.append(LOOKS[c.look])
        if c.fade_in > 0:
            v.append(f"fade=t=in:st=0:d={c.fade_in:.2f}")
        if c.fade_out > 0:
            v.append(f"fade=t=out:st={max(0, L - c.fade_out):.3f}:d={c.fade_out:.2f}")
        if c.text.strip():
            tf = os.path.join(tmp, f"t{i}.txt")
            with open(tf, "w", encoding="utf-8") as f:
                f.write(c.text)
            size = max(8, int(c.text_size * H / 1080))
            v.append(f"drawtext={font}textfile={_q(tf)}:expansion=none:fontsize={size}:fontcolor=white"
                     f":box=1:boxcolor=black@0.4:boxborderw={max(4, size // 4)}:{TEXT_POS.get(c.text_pos, TEXT_POS['Abajo'])}")
        g.append(f"[{i}:v]" + ",".join(v) + f"[v{i}]")
        # ---- audio ----
        if c.has_audio:
            a = [f"[{i}:a]atrim=start={c.t_in:.3f}:end={c.t_out:.3f}", "asetpts=PTS-STARTPTS",
                 *_atempo(c.speed)]
            head = ",".join(a)
        else:
            head = f"anullsrc=r=48000:cl=stereo,atrim=duration={L:.3f},asetpts=PTS-STARTPTS"
        a = [head, "aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo"]
        if c.vol != 100:
            a.append(f"volume={c.vol / 100:.2f}")
        if c.fade_in > 0:
            a.append(f"afade=t=in:st=0:d={c.fade_in:.2f}")
        if c.fade_out > 0:
            a.append(f"afade=t=out:st={max(0, L - c.fade_out):.3f}:d={c.fade_out:.2f}")
        g.append(",".join(a) + f"[a{i}]")
    n = len(clips)
    g.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]")
    amap = "[a]"
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
        g.append(f"[{n}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                 f"volume={mvol / 100:.2f}[m]")
        g.append("[a][m]amix=inputs=2:duration=first:dropout_transition=0,volume=2,alimiter=limit=0.97[aout]")
        amap = "[aout]"
    cmd += ["-filter_complex", ";".join(g), "-map", "[v]", "-map", amap]
    if music:
        cmd += ["-t", f"{total:.3f}"]
    cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
    return cmd


_PROG = re.compile(r"^(frame|fps|stream_\d+_\d+_q|bitrate|total_size|out_time\w*|"
                   r"dup_frames|drop_frames|speed|progress)=")


class Runner:
    """Ejecuta FFmpeg y reporta el avance (0..1)."""

    def __init__(self, cmd, total, on_progress=None):
        self.cmd, self.total, self.on_progress = cmd, max(total, 0.1), on_progress
        self.proc, self.cancelled = None, False

    def run(self):
        log = []
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace",
                                     creationflags=NOFLASH)
        for line in self.proc.stdout:
            k, _, val = line.strip().partition("=")
            if k in ("out_time_us", "out_time_ms"):
                try:
                    if self.on_progress:
                        self.on_progress(min(1.0, int(val) / 1e6 / self.total))
                except ValueError:
                    pass
            elif line.strip() and not _PROG.match(line):
                log.append(line.strip())
        rc = self.proc.wait()
        return (rc == 0 and not self.cancelled), "\n".join(log[-8:])

    def cancel(self):
        self.cancelled = True
        if self.proc:
            self.proc.kill()
