"""Cat detection with YOLO11 (COCO-trained, class 15 = cat) on ONNX Runtime.

All cameras go through the GPU in one batch. Frames are letterboxed to the model's input (1280x720
becomes 960x544 at the default size, padded only to a multiple of 32, not to a square) and boxes are mapped back to
full-frame pixels.
"""

import cv2
import numpy as np


class CatDetector:
    def __init__(self, dc, model_path, providers=("CUDAExecutionProvider", "CPUExecutionProvider"), require_gpu=True):
        import onnxruntime as ort
        self.session = ort.InferenceSession(str(model_path), providers=list(providers))
        if require_gpu and self.session.get_providers()[0] != "CUDAExecutionProvider":
            raise RuntimeError(f"cat model fell back to {self.session.get_providers()}, not the GPU")
        self._in = self.session.get_inputs()[0].name
        self.size = int(dc.get("input", 640))
        self.cls = int(dc.get("cat_class", 15))
        self.score = float(dc.get("score", 0.35))
        self.iou = float(dc.get("nms_iou", 0.5))
        self.min_px = float(dc.get("min_box_px", 12))
        # brighten dark frames before detection: a gamma curve lifts shadows (where a dark cat
        # lies) far more than highlights; 1.0 = unchanged
        g = float(dc.get("gamma", 1.0))
        self.lut = None if g == 1.0 else np.array([255 * (i / 255) ** g for i in range(256)], np.uint8)

    def _shape(self, h, w):
        s = self.size / max(h, w)
        nh, nw = int(round(h * s)), int(round(w * s))
        return s, nh, nw, -(-nh // 32) * 32, -(-nw // 32) * 32

    def __call__(self, frames):
        """frames: list of BGR images, all the same size. Returns one (n, 5) array per frame of
        [x1, y1, x2, y2, score] in full-frame pixels, best first (n may be 0)."""
        if not frames:
            return []
        h, w = frames[0].shape[:2]
        s, nh, nw, ph, pw = self._shape(h, w)
        x = np.full((len(frames), ph, pw, 3), 114, np.uint8)
        for i, f in enumerate(frames):
            small = cv2.resize(f, (nw, nh), interpolation=cv2.INTER_LINEAR)
            x[i, :nh, :nw] = cv2.LUT(small, self.lut) if self.lut is not None else small
        x = np.ascontiguousarray(x[..., ::-1].transpose(0, 3, 1, 2), np.float32) / 255.0
        out = self.session.run(None, {self._in: x})[0]  # (batch, 4 + 80 classes, anchors)
        res = []
        for p in out:
            sc = p[4 + self.cls]
            keep = sc > self.score
            if not keep.any():
                res.append(np.zeros((0, 5)))
                continue
            cx, cy, bw, bh = (p[k, keep] / s for k in range(4))
            boxes = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2, sc[keep]], axis=1).astype(np.float64)
            boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w - 1)
            boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h - 1)
            big = np.minimum(boxes[:, 2] - boxes[:, 0], boxes[:, 3] - boxes[:, 1]) >= self.min_px
            boxes = boxes[big]
            idx = cv2.dnn.NMSBoxes([[b[0], b[1], b[2] - b[0], b[3] - b[1]] for b in boxes],
                                   boxes[:, 4].tolist(), self.score, self.iou) if len(boxes) else []
            idx = np.array(idx, int).reshape(-1)
            boxes = boxes[idx]
            res.append(boxes[np.argsort(-boxes[:, 4])])
        return res


def draw(img, boxes, best=None, color=(0, 200, 255)):
    """Boxes on an image: the one used for its position thick, others thin."""
    for i, b in enumerate(boxes):
        x1, y1, x2, y2 = (int(v) for v in b[:4])
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 3 if i == best else 1, cv2.LINE_AA)
        cv2.putText(img, f"cat {b[4]:.2f}", (x1, max(y1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
