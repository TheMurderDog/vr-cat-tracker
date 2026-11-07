# Disclaimer, risks and your responsibility

**Please read this before you build or use this project.** By using any part of it, you accept the terms below.

## Not a safety device

This is a hobby project shared for free. It is **not** a safety product, and it has not been certified, independently
tested or reviewed for safety. It is meant to *help* you notice a pet while you're in VR. It does **not** guarantee
that you will notice your pet, and it can't prevent injury to you, your pet, other people or property.

**Warnings can come late, or not at all.** It looks for your pet only a few times a second, and you also need time to
notice a warning and react. A fast or close pet can reach you before you can do anything, at any distance.

Never rely on it as your only protection. Keep the usual VR precautions: a clear play area, your VR system's boundary,
and taking the headset off or playing more carefully when animals or people are nearby.

## Known risks and limits

- **Missed detections.** It can fail to see your pet, for example when the pet is hidden from the cameras, in a blind
  spot, in poor or changing light, moving fast, or simply looks unlike what the model learned. The stock model misses
  pets often until you train it on your own, and even a trained model makes mistakes.
- **Wrong position.** A bad calibration, a camera or base station that has moved, or SteamVR's play space shifting can
  put the marker in the wrong place.
- **Delay.** It checks a few times a second. A fast pet can reach you before a warning appears.
- **False alarms.** It can mark something that isn't your pet, which may distract you or make you move suddenly.
- **Software failures.** It can crash, freeze or stop getting pictures from a camera. A watchdog tries to warn you
  when this happens, but it can fail too, for example if your PC, SteamVR or the watchdog itself stops working.
- **Untested setups.** It was built and tested on one room with four cameras and one cat. Other hardware, rooms,
  animals, operating systems and software versions have not been tested.
- **Other animals and people.** It is trained to find cats only (or the pet you train it on). It does not detect
  children, other people or other animals, and must never be relied on for them.
- **AI-written code.** Most of the code was written by an AI model (see the README). It may contain bugs that no one
  has found yet.
- **Hardware.** Mounting cameras, running cables, lighting and other hardware are your responsibility, including doing
  it safely (secure mounts, no trip hazards, safe wiring). A camera or mount falling from near the ceiling can hurt
  someone: use mounts rated for the weight, a proper ladder, and keep cameras out of reach of swinging controllers.
- **Training runs** keep your graphics card at full load for up to an hour or more. Check your PC's cooling first
  (clean fans, clear vents).

## Your responsibility

You are solely responsible for:

- deciding whether this software is safe enough for your setup, your pets and your household;
- installing, calibrating, training and testing it properly before relying on it, and re-testing after changes;
- using your VR equipment safely and following its manufacturers' safety guidance;
- complying with laws that apply to you, including privacy and recording laws. The cameras see, and the software can
  save pictures of, anyone in the room. Tell the people you live with, and get consent where required.

If you aren't comfortable taking on these responsibilities, don't use this software.

## Lowering the risk

- **Keep your normal VR habits:** a cleared play area, SteamVR's boundary, and slower movements when your cat is
  around. No marker doesn't mean no cat.
- **Check it's working at the start of every session:** see its marker on your cat when it walks in.
- **It tries to tell you when it stops working:** a notice in VR if a camera stops or detection fails, and a red
  "CAT TRACKER STOPPED" notice with a controller buzz if the tracker itself crashes or freezes. That can't help if
  your whole PC or SteamVR hangs. Don't count on that notice: an empty view can mean the tracker stopped, not that
  your pet is away.
- **If cameras or base stations move,** the marker can be in the wrong place. Run `drift_check.bat` and re-anchor.

## Privacy

- It runs on your PC only and opens no network ports. The optional VRChat link sends positions to this PC only.
- **It saves pictures of your room**: training captures (`capture.bat`), and "hard" frames while the tracker runs
  (turn those off with `hard_frames: enabled: false` in `cat_tracker/config.yaml`). They're kept out of git. Be careful
  sharing them, and never attach them to a public GitHub issue (copying text from a log is fine).
- **Recording laws differ by country and state,** so check yours before you mount cameras. Don't point cameras at a
  bed, bathroom or anywhere people undress, and make sure everyone who uses the room knows the cameras are there.
- Nothing needs admin rights, and nothing runs by itself unless you choose to make it start with SteamVR (which you
  can undo). More in [SECURITY.md](SECURITY.md).

## No warranty, no liability

This software is provided **"as is", without warranty of any kind**, express or implied, including fitness for a
particular purpose. To the fullest extent permitted by law, the authors and contributors are **not liable for any
damages or injuries** of any kind, including to people, animals or property, arising from using, misusing or being
unable to use this software, even if advised of the possibility of such damage. You use it entirely at your own risk.

This summarises, and does not replace, sections 15 and 16 of the [license](LICENSE) (GNU AGPL-3.0), which are the
binding terms. Where this page and the license differ, the license applies.

This covers the code, the trained models, the settings and all the documentation. Where the law doesn't allow some of
these limits, they apply as far as it does.

## Not affiliated

This project is not affiliated with, endorsed by or sponsored by Valve (SteamVR), VRChat, Ultralytics, OpenMMLab,
Anthropic (Claude), NVIDIA or any camera or headset maker. Those names belong to their owners and are used only to
describe what this works with.

## Third-party parts

Dependencies and the pose models have their own licenses and terms, listed in [NOTICE.md](NOTICE.md). Some of
the datasets behind the pose models are for research or non-commercial use only. Checking those terms for your use is
up to you.
