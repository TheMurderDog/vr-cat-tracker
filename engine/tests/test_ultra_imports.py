"""Ultralytics is only ever imported through core.ultra (which switches its usage events off first). Fails if any
other file in engine/ imports ultralytics directly. Run from engine/:  python tests/test_ultra_imports.py
(plain Python, no Ultralytics needed)."""
import ast
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
ALLOWED = {ENGINE / "core" / "ultra.py"}


def direct_imports(path):
    """Line numbers of `import ultralytics...` / `from ultralytics... import ...` in a file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "ultralytics" for a in node.names):
            out.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "ultralytics":
            out.append(node.lineno)
    return out


def main():
    bad = []
    for p in sorted(ENGINE.rglob("*.py")):
        if p in ALLOWED or ".venv" in p.parts:
            continue
        bad += [f"{p.relative_to(ENGINE)}:{n}" for n in direct_imports(p)]
    if bad:
        print("FAIL: import Ultralytics through core.ultra.load_yolo() (its usage events off), not directly:")
        print("\n".join("  " + b for b in bad))
        return 1
    print("ok: no direct Ultralytics imports outside core/ultra.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
