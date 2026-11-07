"""Fetch the pose model the anchor walk uses (a person detector and RTMPose, from OpenMMLab, the URLs in
settings/cameras.yaml under pose), once, at install time, with a progress bar; already there: nothing to do.
Without this they would download silently in the middle of the first anchor walk.

From the engine folder:  python -m pose.get_models
"""

import sys

from core.config import load_config


def main():
    from rtmlib.tools.file import _get_rtmhub_dir, download_checkpoint
    from pathlib import Path
    pc = load_config().get("pose", {})
    urls = [pc.get("detector_url"), pc.get("pose_url")]
    if not all(urls):
        print("No pose model URLs under pose in settings\\cameras.yaml.")
        return 1
    cache = Path(_get_rtmhub_dir()) / "checkpoints"
    for url in urls:
        name = url.rsplit("/", 1)[-1].replace(".zip", ".onnx")
        if (cache / name).is_file():
            print(f"Pose model already here: {name}")
            continue
        print(f"Downloading the pose model the anchor walk uses (one time, from OpenMMLab): {name}")
        try:
            download_checkpoint(url)
        except Exception as e:  # noqa: BLE001
            print(f"Couldn't download it ({e}). The anchor walk will try again the first time it runs.")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
