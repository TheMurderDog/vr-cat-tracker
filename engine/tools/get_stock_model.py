"""Get the stock YOLO11s model (downloaded by Ultralytics on first use) and export it for the tracker, in the current
folder (3_first_test\\1_get_stock_model.bat runs it in my_data\\models). Ultralytics' usage events are off (core.ultra).
Run with the training environment:  ..\\.venv-train\\Scripts\\python.exe <this file>"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the engine folder, for core.ultra
from core.ultra import load_yolo  # noqa: E402

YOLO = load_yolo()  # with Ultralytics' usage events off

YOLO("yolo11s.pt").export(format="onnx", imgsz=960, opset=17, dynamic=True, simplify=True)
