"""Download the calibration wizards' voice (Piper, en_US-ljspeech-medium) once, from a pinned address, and check it.

Run by 0_start_here/1_install.bat. The files go to engine/voices/ (not in git). Each file's SHA-256 must match the
value below, or it's deleted and the install says so; nothing else is downloaded. The voice is MIT licensed
(rhasspy/piper-voices) and trained on the public-domain LJ Speech recordings: see docs/NOTICE.md.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

VOICE = "en_US-ljspeech-medium"
BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/ljspeech/medium/"
FILES = {
    f"{VOICE}.onnx": "6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22",
    f"{VOICE}.onnx.json": "141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860",
}
DEST = Path(__file__).resolve().parent.parent / "voices"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    for name, want in FILES.items():
        path = DEST / name
        if path.is_file() and sha256(path) == want:
            continue
        print(f"Downloading the calibration voice: {name} ...")
        tmp = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(BASE + name, timeout=60) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        got = sha256(tmp)
        if got != want:
            tmp.unlink()
            print(f"The voice file {name} didn't match its checksum, so it was deleted. The calibration wizards will "
                  "use Windows' own voice instead. Try 1_install.bat again later.")
            return 1
        tmp.replace(path)
    print("Calibration voice ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
