"""Spoken prompts and beeps for the calibration wizards, so you can follow them from across the room.

The voice is Piper (offline neural speech, `piper-tts`) with the en_US-ljspeech-medium voice that
0_start_here/1_install.bat downloads into engine/voices. Each prompt is rendered once to a WAV file in
my_data/voice_cache and played from there, so repeats are instant; prompts known in advance are rendered in the
background as soon as the wizard starts. If Piper or the voice file is missing, it falls back to Windows' built-in
voice (System.Speech in one PowerShell process, the text on its standard input, never on a command line), and failing
that it only beeps. Nothing here ever holds up the camera loop: rendering, speaking and beeps run on their own threads.
"""

import hashlib
import os
import queue
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

ENGINE = Path(__file__).resolve().parent.parent
VOICE_FILE = ENGINE / "voices" / "en_US-ljspeech-medium.onnx"
CACHE = ENGINE.parent / "my_data" / "voice_cache"

_SPEAKER = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Rate = 1; "
    "while (($l = [Console]::In.ReadLine()) -ne $null) { $s.SpeakAsyncCancelAll(); if ($l) { [void]$s.SpeakAsync($l) } }"
)


class Voice:
    def __init__(self, on=True, repeat_s=6.0, volume=0.8, prerender=(), cache=CACHE, gap_s=1.5):
        self.on = on
        self.repeat_s = repeat_s
        self.volume = float(min(max(volume, 0.0), 1.0))
        self.cache = Path(cache)
        self.last = {}          # text -> when it was last said
        self.gap_s = gap_s       # quiet time after a phrase ends before the next one starts
        self.busy_until = 0.0    # when the phrase playing now ends (estimated until it starts playing)
        self.first_wait_s, self.max_wait_s = repeat_s, 30.0  # back-off for repeating the same prompt
        self.stale_s = 1.0       # a waiting ordinary prompt not asked again within this is dropped
        self.wait, self.next_ok = {}, {}
        self.situation = None    # the last text asked for
        self.pending = None      # (text, when asked, important) waiting for the phrase playing now to end
        self.engine = None      # "piper", "windows", or None (beeps only)
        self.proc = None
        self.piper = None
        self.beeps = queue.Queue()
        self.next_park = 0.0
        self._want = None       # the newest prompt to speak; an older one not yet spoken is dropped
        self._wake = threading.Event()
        if not on or sys.platform != "win32":
            self.on = False
            return
        threading.Thread(target=self._beeper, daemon=True).start()
        if VOICE_FILE.is_file():
            try:
                import piper  # noqa: F401  (checked here so a broken install falls back at once)
                self.engine = "piper"
                threading.Thread(target=self._piper_worker, args=(list(prerender),), daemon=True).start()
                return
            except ImportError:
                pass
        self._start_windows_voice()

    # ---- speaking -------------------------------------------------------------------------------------------------

    def say(self, text, now=None, force=False, every=None):
        """Ask for a prompt. One phrase plays at a time and is never cut off; after it ends there's a gap_s pause.
        While a phrase plays, a newer request replaces the waiting one (only the latest is kept), and a waiting
        ordinary request is dropped if it isn't asked again within stale_s (the situation moved on).
        Repeats back off: the same text waits first_wait_s (or `every`), then twice as long each time, up to
        max_wait_s; asking for a different text than last time resets the wait for that text.
        force: skip the back-off and go first (e.g. "Got it"), still without cutting anything off.
        Returns True if it was spoken now."""
        now = time.monotonic() if now is None else now
        if text != self.situation:  # the situation changed: this prompt may be said again straight away
            self.situation = text
            self.wait[text] = float(every or self.first_wait_s)
            self.next_ok.pop(text, None)
        if force:
            self.pending = (text, now, True)
        elif now >= self.next_ok.get(text, -1e9) and not (self.pending and self.pending[2]):
            self.pending = (text, now, False)
        return self.tick(now) == text

    def tick(self, now=None):
        """Speak the waiting prompt if nothing is playing and the gap has passed. Call it every frame.
        Returns the text spoken, or None."""
        now = time.monotonic() if now is None else now
        if self.pending is None or now < self.busy_until + self.gap_s:
            return None
        text, asked, important = self.pending
        self.pending = None
        if not important and now - asked > self.stale_s:
            return None
        w = self.wait.get(text, self.first_wait_s)
        self.next_ok[text] = now + w
        self.wait[text] = min(w * 2, self.max_wait_s)
        self.last[text] = now
        self.busy_until = now + 0.4 * max(1, len(text.split())) + 0.3  # a guess, until the real length is known
        self._send(text)
        return text

    def flush(self, timeout=4.0):
        """Wait (up to timeout) until the waiting prompt has started, e.g. before a step that blocks for a while."""
        end = time.monotonic() + timeout
        while self.pending is not None and time.monotonic() < end:
            self.tick()
            time.sleep(0.05)

    def _send(self, text):
        if not self.on:
            return
        if self.engine == "piper":
            self._want = text
            self._wake.set()
        elif self.engine == "windows" and self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.stdin.write(text.replace("\n", " ") + "\n")
                self.proc.stdin.flush()
            except OSError:
                self.proc, self.engine = None, None

    def _wav(self, text):
        key = hashlib.sha1(f"{VOICE_FILE.name}|{self.volume:.2f}|{text}".encode("utf-8")).hexdigest()[:20]
        return self.cache / f"{key}.wav"

    def _render(self, text):
        """The cached WAV for text, rendering it first if needed. None if Piper fails."""
        path = self._wav(text)
        if path.is_file():
            return path
        try:
            if self.piper is None:
                from piper import PiperVoice
                self.piper = PiperVoice.load(str(VOICE_FILE))
            self.cache.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            with wave.open(str(tmp), "wb") as w:
                self.piper.synthesize_wav(text, w)
            if self.volume < 1.0:
                with wave.open(str(tmp), "rb") as w:
                    params, frames = w.getparams(), w.readframes(w.getnframes())
                quieter = (np.frombuffer(frames, np.int16) * self.volume).astype(np.int16)
                with wave.open(str(tmp), "wb") as w:
                    w.setparams(params)
                    w.writeframes(quieter.tobytes())
            tmp.replace(path)
            return path
        except Exception:  # noqa: BLE001  (any Piper problem: fall back to Windows' voice)
            return None

    def _piper_worker(self, prerender):
        import winsound
        for text in prerender:  # known prompts first, so they play instantly later
            if self._want is not None:
                break
            if self._render(text) is None:
                break
        while True:
            self._wake.wait()
            self._wake.clear()
            text, self._want = self._want, None
            if text is None:
                continue
            path = self._render(text)
            if path is None:
                self._start_windows_voice()
                self._send(text)  # this one in Windows' voice; the next ones go there directly
                return
            if self._want is None:  # nothing newer arrived while rendering
                with wave.open(str(path), "rb") as w:
                    length = w.getnframes() / float(w.getframerate())
                self.busy_until = time.monotonic() + length
                winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)

    def _start_windows_voice(self):
        ps = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0",
                          "powershell.exe")  # full path: never whatever powershell.exe is first on PATH
        try:
            self.proc = subprocess.Popen([ps, "-NoProfile", "-NonInteractive", "-Command", _SPEAKER],
                                         stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.engine = "windows"
        except OSError:
            self.proc, self.engine = None, None

    # ---- beeps ----------------------------------------------------------------------------------------------------

    def _beeper(self):
        import winsound
        while True:
            freq, ms = self.beeps.get()
            try:
                winsound.Beep(freq, ms)
            except RuntimeError:
                pass

    def click(self):
        """A clear two-note chime when a view is captured (instead of saying "Got it")."""
        if self.on:
            self.beeps.put((1000, 90))
            self.beeps.put((1500, 160))

    def park(self, closeness, now=None):
        """A parking-sensor beep while moving toward a target: closeness 0 (far) to 1 (there) makes it faster.
        None stops it."""
        now = time.monotonic() if now is None else now
        if not self.on or closeness is None or now < self.next_park:
            return
        c = min(max(closeness, 0.0), 1.0)
        self.beeps.put((600 + int(500 * c), 35))
        self.next_park = now + 0.9 - 0.75 * c  # about once a second far away, about 7 a second when nearly there

    # ---- soft sounds (the focus meter) -------------------------------------------------------------------------

    def _sound(self, name, samples, rate=22050):
        """A short sound rendered once to a WAV in the cache (PlaySound can only play memory sounds blocking)."""
        path = self.cache / f"sound_{name}_{self.volume:.2f}.wav"
        if not path.is_file():
            self.cache.mkdir(parents=True, exist_ok=True)
            pcm = (np.clip(samples * self.volume, -1, 1) * 32767).astype(np.int16)
            tmp = path.with_suffix(".tmp")
            with wave.open(str(tmp), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(pcm.tobytes())
            tmp.replace(path)
        return path, len(samples) / rate

    def _play(self, path):
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)

    def focus_tick(self, closeness, now=None):
        """A soft wooden tick, about 35 ms: 1.5 a second when blurry, up to 6 a second once it's in focus. Quiet
        next to the voice, and never over it (no tick while a phrase plays)."""
        now = time.monotonic() if now is None else now
        if not self.on or closeness is None or now < self.next_park or now < self.busy_until:
            return False
        c = min(max(closeness, 0.0), 1.0)
        self.next_park = now + 1.0 / (1.5 + 4.5 * c)
        rate = 22050
        t = np.arange(int(0.035 * rate)) / rate
        tone = np.sin(2 * np.pi * 900 * t) + 0.3 * np.sin(2 * np.pi * 1800 * t)
        env = np.minimum(t / 0.003, 1.0) * np.exp(-t / 0.008)  # 3 ms fade in, then dies away like a woodblock
        path, _ = self._sound("tick", 0.22 * tone * env, rate)
        self._play(path)
        return True

    def focus_chime(self, now=None):
        """A soft two-note chime (in focus). The voice waits until it has finished."""
        now = time.monotonic() if now is None else now
        if not self.on:
            return False
        rate = 22050
        t = np.arange(int(0.45 * rate)) / rate
        out = np.zeros_like(t)
        for start, f in ((0.0, 660.0), (0.13, 990.0)):
            tt = np.clip(t - start, 0, None)
            on = t >= start
            out += on * np.sin(2 * np.pi * f * tt) * np.minimum(tt / 0.005, 1.0) * np.exp(-tt / 0.12)
        path, length = self._sound("chime", 0.3 * out, rate)
        self.busy_until = max(self.busy_until, now + length)
        self._play(path)
        return True

    def close(self):
        if self.proc is not None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()
            self.proc = None
