"""Optional: a pretrained 2D human pose model (RTMPose, Halpe 26 keypoints) run on each camera.

Uses rtmlib's YOLOX person detector and RTMPose classes on ONNX Runtime GPU. The detector is slow
(about 30 ms), so it only runs when a camera has lost the person, for one camera per update;
otherwise the next crop comes from the last keypoints. One person is tracked per camera (the
largest, or the one nearest the last crop).
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

# Halpe 26 keypoint names, in model output order
KEYPOINTS = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee",
    "right_knee", "left_ankle", "right_ankle", "head", "neck", "hip", "left_big_toe", "right_big_toe",
    "left_small_toe", "right_small_toe", "left_heel", "right_heel",
]
K = {n: i for i, n in enumerate(KEYPOINTS)}
SKELETON = [("left_ankle", "left_knee"), ("left_knee", "left_hip"), ("right_ankle", "right_knee"),
            ("right_knee", "right_hip"), ("left_hip", "right_hip"), ("left_shoulder", "left_hip"),
            ("right_shoulder", "right_hip"), ("left_shoulder", "right_shoulder"), ("left_shoulder", "left_elbow"),
            ("right_shoulder", "right_elbow"), ("left_elbow", "left_wrist"), ("right_elbow", "right_wrist"),
            ("neck", "head"), ("left_ankle", "left_heel"), ("left_ankle", "left_big_toe"),
            ("right_ankle", "right_heel"), ("right_ankle", "right_big_toe")]

log = logging.getLogger("pose")


def prepare_onnxruntime(cfg_ort):
    """Load the CUDA/cuDNN DLLs from pip packages before any session is made (see doctor)."""
    import onnxruntime as ort
    ort.set_default_logger_severity(2)
    if cfg_ort.get("preload_cuda_dlls", True) and hasattr(ort, "preload_dlls"):
        ort.preload_dlls()
    if "CUDAExecutionProvider" not in ort.get_available_providers():
        raise RuntimeError("ONNX Runtime has no CUDA provider; run 0_start_here/1_install.bat again")


def _check_gpu(tool, what):
    if tool.session.get_providers()[0] != "CUDAExecutionProvider":
        # ORT silently falls back to CPU when CUDA DLLs fail to load; that would be far too slow
        raise RuntimeError(f"{what} model fell back to {tool.session.get_providers()}, not the GPU")


class _GraphRunner:
    """Runs the pose model as a recorded CUDA graph: the GPU replays the whole network from one
    launch instead of hundreds, which matters when the CPU is busy decoding several camera streams.
    Needs a fixed batch size and fixed buffers, so input is copied into a GPU buffer first."""

    def __init__(self, path, dev, algo, plain, in_name, out_names, batch, hw):
        import onnxruntime as ort
        opts = {"device_id": dev, "enable_cuda_graph": "1"}
        if algo:
            opts["cudnn_conv_algo_search"] = algo
        self.session = ort.InferenceSession(path, providers=[("CUDAExecutionProvider", opts)])
        rng = np.random.default_rng(0)
        x1, x2 = (rng.normal(0, 1, (batch, 3, *hw)).astype(np.float32) for _ in range(2))
        shapes = [o.shape for o in plain.run(out_names, {in_name: x1})]
        self.x = ort.OrtValue.ortvalue_from_numpy(np.zeros_like(x1), "cuda", dev)
        self.y = [ort.OrtValue.ortvalue_from_shape_and_type(sh, np.float32, "cuda", dev) for sh in shapes]
        self.io = self.session.io_binding()
        self.io.bind_ortvalue_input(in_name, self.x)
        for n, y in zip(out_names, self.y):
            self.io.bind_ortvalue_output(n, y)
        self.batch = batch
        # the first runs record the graph; then check that replays follow new input correctly
        for x in (x1, x2, x1, x2):
            got = self.run(x)
        for x in (x1, x2):
            want = plain.run(out_names, {in_name: x})
            got = self.run(x)
            err = max(float(np.abs(g - w).max() / (np.abs(w).max() + 1e-6)) for g, w in zip(got, want))
            if err > 1e-2:
                raise RuntimeError(f"CUDA graph output differs from the normal run (relative error {err:.3g})")

    def run(self, x):
        self.x.update_inplace(x)
        self.session.run_with_iobinding(self.io)
        return [y.numpy() for y in self.y]


class PoseModels:
    """The detector and pose model, loaded once and shared by every camera. The pose model takes a
    batch, so every camera's crop goes through the GPU in one run (about as fast as one crop)."""

    def __init__(self, pc, device="cuda"):
        from rtmlib import YOLOX, RTMPose  # downloads the models on first use (to ~/.cache/rtmlib)
        self.det = YOLOX(pc["detector_url"], model_input_size=tuple(pc["detector_input"]),
                         score_thr=float(pc.get("detector_score", 0.5)), backend="onnxruntime", device=device)
        self.pose = RTMPose(pc["pose_url"], model_input_size=tuple(pc["pose_input"]),
                            backend="onnxruntime", device=device)
        algo = pc.get("cudnn_algo_search", "EXHAUSTIVE")
        if algo:  # rtmlib's sessions use the default cuDNN search; EXHAUSTIVE measured ~10% faster
            import onnxruntime as ort
            dev = int(device.split(":")[1]) if ":" in device else 0
            for tool in (self.det, self.pose):
                tool.session = ort.InferenceSession(tool.onnx_model, providers=[
                    ("CUDAExecutionProvider", {"device_id": dev, "cudnn_conv_algo_search": algo}),
                    "CPUExecutionProvider"])
        _check_gpu(self.det, "detector")
        _check_gpu(self.pose, "pose")
        s = self.pose.session
        self._in = s.get_inputs()[0].name
        self._out = [o.name for o in s.get_outputs()]
        self.batched = not isinstance(s.get_inputs()[0].shape[0], int)
        self._pool = ThreadPoolExecutor(4)  # OpenCV's crop releases the GIL, so crops run side by side
        self.graph = None
        if pc.get("cuda_graph", True) and self.batched:
            try:
                dev = int(device.split(":")[1]) if ":" in device else 0
                w, h = pc["pose_input"]
                self.graph = _GraphRunner(self.pose.onnx_model, dev, algo, s, self._in, self._out,
                                          int(pc.get("batch", 4)), (int(h), int(w)))
                log.info("Pose model runs as a CUDA graph (batch of %d)", self.graph.batch)
            except Exception as e:  # noqa: BLE001 - the normal path still works, just slower
                self.graph = None
                log.warning("CUDA graph not usable (%s); using the normal GPU path", e)
        self.timing = {"crop_ms": 0.0, "gpu_ms": 0.0, "decode_ms": 0.0}

    def _prep(self, fb):
        img, center, scale = self.pose.preprocess(fb[0], fb[1].tolist())
        return np.ascontiguousarray(img.transpose(2, 0, 1), np.float32), center, scale

    def pose_batch(self, frames, boxes):
        """Keypoints and scores for one box per frame, all in one GPU run when the model allows."""
        t0 = time.perf_counter()
        pre = list(self._pool.map(self._prep, zip(frames, boxes)))
        x = np.stack([img for img, _, _ in pre])
        t1 = time.perf_counter()
        if self.graph is not None and len(x) <= self.graph.batch:
            pad = np.zeros((self.graph.batch - len(x), *x.shape[1:]), np.float32)
            outs = self.graph.run(np.concatenate([x, pad]) if len(pad) else x)
        elif self.batched:
            outs = self.pose.session.run(self._out, {self._in: x})
        else:
            runs = [self.pose.session.run(self._out, {self._in: x[i:i + 1]}) for i in range(len(x))]
            outs = [np.concatenate([r[k] for r in runs]) for k in range(len(self._out))]
        t2 = time.perf_counter()
        res = []
        for i, (_, center, scale) in enumerate(pre):
            kp, sc = self.pose.postprocess([o[i:i + 1] for o in outs], center, scale)
            res.append((kp[0].astype(np.float64), sc[0].astype(np.float64)))
        t3 = time.perf_counter()
        self.timing = {"crop_ms": 1000 * (t1 - t0), "gpu_ms": 1000 * (t2 - t1), "decode_ms": 1000 * (t3 - t2)}
        return res


class CameraPose:
    """Per-camera person tracking: detect when lost, otherwise crop around the last keypoints."""

    def __init__(self, models, pc):
        self.m = models
        self.kp_thr = float(pc.get("keypoint_score", 0.3))
        self.min_visible = int(pc.get("min_visible_keypoints", 6))
        self.redetect_every = int(pc.get("redetect_every_n", 600))
        self.margin = float(pc.get("crop_margin", 0.15))
        self.bbox = None
        self.since_detect = 0
        self.timing = {"det_ms": 0.0}

    def needs_detect(self):
        return self.bbox is None or self.since_detect >= self.redetect_every

    def detect(self, frame):
        """Run the person detector; True if someone was found (their box is used from now on)."""
        t0 = time.perf_counter()
        boxes = np.asarray(self.m.det(frame), np.float64).reshape(-1, 4)
        self.timing["det_ms"] = 1000 * (time.perf_counter() - t0)
        self.since_detect = 0
        if len(boxes) == 0:
            self.bbox = None
        elif self.bbox is not None:  # stay on the same person
            c0 = (self.bbox[:2] + self.bbox[2:]) / 2
            self.bbox = boxes[np.argmin(np.linalg.norm((boxes[:, :2] + boxes[:, 2:]) / 2 - c0, axis=1))]
        else:
            self.bbox = boxes[np.argmax((boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]))]
        return self.bbox is not None

    def update(self, frame_shape, kp, sc):
        """Take the pose result for this camera's box; returns (kp, sc), or (None, None) if lost."""
        self.since_detect += 1
        good = sc > self.kp_thr
        if good.sum() < self.min_visible:
            self.bbox = None  # lost: detect again
            return None, None
        # next crop: the visible keypoints plus a margin (the model adds its own padding too)
        lo, hi = kp[good].min(axis=0), kp[good].max(axis=0)
        pad = self.margin * (hi - lo).max()
        h, w = frame_shape[:2]
        self.bbox = np.array([max(lo[0] - pad, 0), max(lo[1] - pad, 0), min(hi[0] + pad, w - 1), min(hi[1] + pad, h - 1)])
        return kp, sc


def draw(img, kp, sc, thr, scale=1.0):
    import cv2
    if kp is None:
        return img
    p = kp * scale
    for a, b in SKELETON:
        i, j = K[a], K[b]
        if sc[i] > thr and sc[j] > thr:
            cv2.line(img, tuple(int(v) for v in p[i]), tuple(int(v) for v in p[j]), (0, 220, 255), 2, cv2.LINE_AA)
    for i in range(len(p)):
        if sc[i] > thr:
            cv2.circle(img, tuple(int(v) for v in p[i]), 3, (0, 255, 0), -1, cv2.LINE_AA)
    return img
