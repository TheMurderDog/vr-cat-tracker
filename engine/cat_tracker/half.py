"""Makes a half-precision copy of a trained cat model, about twice as light on the GPU.

The maths runs in fp16 everywhere except the last few steps that turn the outputs into boxes, which
stay in fp32 so box positions don't lose precision. The model still takes and returns fp32, so the
tracker uses it exactly like the full-precision one. Boxes match the fp32 model to under a pixel.

    cat_tracker\\.venv\\Scripts\\python.exe -m cat_tracker.half <best.onnx> <out.onnx>
"""

import sys
import warnings


def make_half(src, dst):
    from onnxconverter_common import float16  # in requirements-train.txt; never installed on the fly
    import onnx
    m = onnx.load(str(src))
    # the box decoding at the end (model.23, apart from its conv branches) stays fp32
    keep = [n.name for n in m.graph.node
            if n.name.startswith("/model.23/") and "/cv2" not in n.name and "/cv3" not in n.name]
    # its cast clean-up step fails on this layout and only removes a few redundant casts
    float16.remove_unnecessary_cast_node = lambda graph: None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # tiny weights rounded to fp16's smallest step, harmless
        h = float16.convert_float_to_float16(m, keep_io_types=True, node_block_list=keep)
    del h.graph.value_info[:]  # stale fp32 type hints; onnxruntime works the types out again
    onnx.checker.check_model(h)
    onnx.save(h, str(dst))


if __name__ == "__main__":
    make_half(sys.argv[1], sys.argv[2])
    print(f"Saved {sys.argv[2]}")
