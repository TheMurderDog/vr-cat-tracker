# Disclaimer, risks and your responsibility

**Please read this before you build or use this project.** By using any part of it, you accept the terms below.

## Not a safety device

This is a hobby project shared for free. It is **not** a safety product, and it has not been certified, independently
tested or reviewed for safety. It is meant to *help* you notice a pet while you're in VR. It does **not** guarantee
that you will notice your pet, and it can't prevent injury to you, your pet, other people or property.

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
  it safely (secure mounts, no trip hazards, safe wiring).

## Your responsibility

You are solely responsible for:

- deciding whether this software is safe enough for your setup, your pets and your household;
- installing, calibrating, training and testing it properly before relying on it, and re-testing after changes;
- using your VR equipment safely and following its manufacturers' safety guidance;
- complying with laws that apply to you, including privacy and recording laws. The cameras see, and the software can
  save pictures of, anyone in the room. Tell the people you live with, and get consent where required.

If you aren't comfortable taking on these responsibilities, don't use this software.

## No warranty, no liability

This software is provided **"as is", without warranty of any kind**, express or implied, including fitness for a
particular purpose. To the fullest extent permitted by law, the authors and contributors are **not liable for any
damages or injuries** of any kind, including to people, animals or property, arising from using, misusing or being
unable to use this software, even if advised of the possibility of such damage. You use it entirely at your own risk.

This summarises, and does not replace, sections 15 and 16 of the [license](LICENSE) (GNU AGPL-3.0), which are the
binding terms. Where this page and the license differ, the license applies.

## Not affiliated

This project is not affiliated with, endorsed by or sponsored by Valve (SteamVR), VRChat, Ultralytics, OpenMMLab or
any camera or headset maker. Those names belong to their owners and are used only to describe what this works with.

## Third-party parts

Dependencies and the optional pose models have their own licenses and terms, listed in [NOTICE.md](NOTICE.md). Some of
the datasets behind the pose models are for research or non-commercial use only. Checking those terms for your use is
up to you.
