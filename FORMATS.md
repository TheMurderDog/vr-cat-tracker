# Calibration file formats

Both files are plain JSON in `calibration/data/` (`calibration.dir` in `config.yaml`). The
calibration tools write them, but you can also write them yourself from another tool's results.
Only the fields marked **required** are read. The others are information from the tools.

## Coordinate conventions

- **World (room) frame: SteamVR standing space.** Metres, right-handed, **+y up**, -z forward,
  floor at about y = 0. This is OpenVR's `TrackingUniverseStanding`, the space tracker and headset
  poses are reported in.
- **Camera frame: OpenCV's.** Origin at the camera's optical centre, **x right, y down, z forward**
  (out of the lens).
- **Pixels: raw sensor frames**, as the camera delivers them at `cameras.width` x `cameras.height`,
  *before* any `cameras.rotate`. Pixel (0, 0) is the top-left corner of the top-left pixel, as in
  OpenCV.

## `intrinsics_<name>.json`, one per camera

`<name>` is the camera's name from `cameras.names`.

```json
{
  "camera": "cam1",
  "device_id": 0,
  "image_size": [1280, 720],
  "model": "fisheye",
  "K": [[700.1, 0.0, 641.2], [0.0, 700.4, 358.9], [0.0, 0.0, 1.0]],
  "D": [0.051, -0.018, 0.009, -0.003],
  "rms_px": 0.23,
  "views_used": 38,
  "views_dropped": 2,
  "note": "raw sensor frame (before cameras.rotate)"
}
```

| Field | | Meaning |
| --- | --- | --- |
| `model` | required | `"fisheye"` means OpenCV's `cv2.fisheye` model (Kannala-Brandt, also called "equidistant" in Kalibr and "OPENCV_FISHEYE" in COLMAP), with 4 coefficients `[k1, k2, k3, k4]`. Any other value (the tool writes `"rational"`) means OpenCV's standard model, used with `cv2.projectPoints` and `cv2.undistortPoints`. |
| `K` | required | 3x3 camera matrix `[[fx, 0, cx], [0, fy, cy], [0, 0, 1]]` in pixels. |
| `D` | required | Distortion coefficients for that model. For the standard model, any length OpenCV accepts (4, 5, 8, 12 or 14), in OpenCV's order `[k1, k2, p1, p2, k3, k4, k5, k6, ...]`, so plain "radtan"/"plumb_bob" (5 coefficients) works too. |
| `image_size` | | `[width, height]` the calibration is for. It must match `cameras.width`/`height`. |
| `camera`, `device_id`, `rms_px`, `views_used`, `views_dropped`, `note` | | Information only. `rms_px` is the reprojection error of the fit. |

## `room.json`, all cameras in one file

```json
{
  "cameras": [
    {"name": "cam1", "rvec": [2.05, 0.71, -0.33], "tvec": [0.12, 1.31, 3.05],
     "position_m": [-1.9, 2.3, -1.7], "observations": 41, "rms_px": 1.6,
     "median_px": 1.2, "outliers": 0.0, "dropped": 1},
    {"name": "cam2", "rvec": [...], "tvec": [...], ...}
  ],
  "marker_offset_m": [0.002, -0.148, 0.011],
  "tilt_spread_deg": 34.0,
  "universe": "standing",
  "created": "2026-11-03 10:00:00"
}
```

| Field | | Meaning |
| --- | --- | --- |
| `cameras` | required | One entry per camera, **in the same order as `cameras.names`**. The code pairs them by position, not by `name`. |
| `cameras[].rvec`, `cameras[].tvec` | required | The camera's pose, as OpenCV extrinsics that map a world point into the camera frame: `X_cam = R @ X_world + tvec`, with `R = cv2.Rodrigues(rvec)`. Metres. |
| `marker_offset_m` | for `calib_check` | Where the printed marker's centre sits in the tracker's own frame. Only the calibration check uses it. |
| `cameras[].name` | | Should match `cameras.names` (written by the tool, checked by people). |
| `position_m` | | The camera's optical centre in the world, `-R.T @ tvec`, for a sanity check. |
| `observations`, `rms_px`, `median_px`, `outliers`, `dropped`, `tilt_spread_deg`, `universe`, `created` | | Information from the solve. |

## Bringing calibration from another tool

1. **Lenses.** Write one `intrinsics_<name>.json` per camera from the other tool's camera matrix
   and distortion coefficients. Check that the model matches (see above), and that it was done at
   the same resolution and on unrotated frames.
2. **Camera poses.** Most tools give either:
   - **World-to-camera** (OpenCV/COLMAP style, `R_wc`, `t_wc`). Use `rvec = Rodrigues(R_wc)` and
     `tvec = t_wc`.
   - **Camera-to-world** (a camera's pose in the room: rotation `R_cw`, position `C`). Use
     `rvec = Rodrigues(R_cw.T)` and `tvec = -R_cw.T @ C`.

   Also check the camera axes. If the other tool's camera looks down -z with y up (OpenGL style),
   flip it to OpenCV's axes first: `R_wc_opencv = diag(1, -1, -1) @ R_wc_opengl`, and the same for
   the translation.
3. **World frame.** If your poses aren't in SteamVR standing space, the 3D points will be correct
   relative to each other but won't line up with SteamVR. Transform the poses into SteamVR space
   first (e.g. with a few points measured with a tracker), or use `calib_room` for this part.
4. **Check.** `calib_check` (with a marked tracker) shows whether SteamVR and the cameras agree.
   Without SteamVR, triangulate a point you can measure (e.g. with `fusion.triangulate`) and
   compare it with a tape measure.
