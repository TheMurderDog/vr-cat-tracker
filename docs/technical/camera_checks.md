# Camera checks: what CHECKS OK means, and the evidence

The camera setup screen (`engine/tools/camera_setup.py`) says **CHECKS OK** for a camera only when it has been watched for a
minute, no problem lasted, and it's focused. This page says how each check is measured, where its line is, and why
that line is where it is. A wrong CHECKS OK is the worst outcome, so the lines were set from what actually hurts cat
tracking, measured on real pictures, not guessed. Measured 2026-11-06.

**EXPERIMENTAL.** Every line on this page was tuned on one setup (one room, one cat, one PC, four webcams); other
rooms and cameras will differ. The motion tripwire and the light check while the tracker runs are new and have only
been tried on that setup; the tripwire's reaction times are estimates added up from measured parts, not an end-to-end
test.

**How the lines were measured.** The fair test session (`20261105-184947`: 700 pictures, 329 with the cat, 371
without, labelled by hand, never trained on), degraded step by step, run through the tracker's own detector (its
model, input 960, score 0.2). Clean: **96.4% of cats found**, 2.2% of empty pictures with a false box. Most of the
final boxes started as the model's own boxes, so the box-position numbers are optimistic; "found or not" is fair.
The same degraded pictures go through the setup screen's own measures, which maps each measure to tracking harm.
The study scripts aren't part of the repo (they need a labelled session to run); the numbers are recorded here.
These numbers come from one room, one cat and one test day. They don't predict how it will work for you. Even
here, about 1 in 28 pictures of the cat was missed.

## How a problem becomes red (timing)

| What | How |
| --- | --- |
| Watching | Each check is sampled once a second, all the time the screen is open, in every view. |
| CHECKING | A camera is watched for 60 s before it can say CHECKS OK (unplugged or frozen: starts over). |
| Red | A problem present in 60% or more of the last 30 s (at least 10 samples). |
| Clear | Only when it's under 20% of the window again: no flicking between red and not. |
| NOT CONNECTED | No new picture for 2 s (unplugged, or the driver keeps handing back the same frame): red at once. |

So someone walking past, a light switched on once, or one burst of damaged frames never turns a camera red.

## Check by check

| Check | Measured as | Old line | New line | Evidence |
| --- | --- | --- | --- | --- |
| Too dark | mean brightness of a 32x24 copy (0-255) | under 40 | **under 50** | dimmed with matching gain noise and a little motion blur: recall 94.8% at 50, 93.9% at 45, 90.6% at 40 |
| Too dark (grainy) | sensor noise from two pictures a second apart (grey levels, measured on floats) | none | **4 or more** | grain 4 in a dim room costs 2.5-5 points (see "Darkness and grain together"). Catches a dark scene the mean misses (bright walls, dark floor) |
| A bit dark and grainy (yellow note) | brightness and grain together | none | **brightness under 85 and grain 2 or more** | costs 1-3 points of recall. Yellow, **blocks nothing**: "It still runs, but more light helps it see the cat." |
| Too bright | the same brightness | over 220 | **over 195** | recall 95.4% at 198, 78.7% at 211: a steep edge just above |
| Compression | blockiness of recent pictures (`jpeg_blocky`) | 1.6 | 1.6 (kept) | 1.61: recall 96.4%; 2.0: 95.7%; 2.6: 93.6%, false alarms up |
| Damaged pictures | share of pictures cut short (blocky bottom), per second | 1% overall | **1% per second, if it lasts** | damaged pictures are dropped, never shown or measured; the line is about USB bandwidth trouble that grows with 4 cameras |
| Too slow | frames a second against `cameras.fps` | under 97% | 97% (kept) | the camera gives about 120 at 1280x720 anyway; detection runs at 3-8 a second, so the frame rate isn't the limit |
| Light flicker | **new:** brightness swing at the mains frequency as the camera samples it (see below), peak to peak | over 1% (std over 0.75 s) | **shown always; a problem only at 40%** | banding up to 70% didn't change recall (96.4-97.0%) |
| Sharpness (SKIP) | **new:** fine detail against coarse detail, noise subtracted (see below) | 1.5 on the old measure | **7.5** on the new | focused 8.8-19; blur 1 px 4.6-10 (harmless); 1.5 px 2.4-6.1 (false alarms rise); 2 px 0.9-4.5. The same in a plain room and a busy one |
| Sharpness dropped | the same, against its value when focused | 60% of then | 60% (kept), new measure | judged only when noise is a small part of it |
| Autofocus stuck | the focus lock (K) found it can't switch autofocus off | red | red (kept) | a hunting autofocus changes the lens's calibration |

### Brightness: the evidence

Cats found (recall at IoU 0.5) on the fair test session as the pictures get darker or brighter. Clean: 96.4%. Darker
pictures also got the gain noise a camera adds in a dim room (from 1 grey level at 120 to 4.6 at 40) and 3 px of
motion blur below 108, as longer exposures bring.

| Brightness (the tool's measure) | Found | Change | Verdict |
| --- | --- | --- | --- |
| 120 | 96.4% | 0 | fine |
| 100 | 96.4% | 0 | fine |
| 85 | 96.7% | +0.3 | fine |
| 70 | 96.4% | 0 | fine |
| 60 | 95.7% | -0.7 | fine |
| 55 | 94.5% | -1.9 | fine |
| **50** | **94.8%** | **-1.6** | **the line: under this is too dark** |
| 45 | 93.9% | -2.5 | too dark |
| 40 | 90.6% | -5.8 | too dark |
| 162 | 97.0% | +0.6 | fine |
| 181 | 96.0% | -0.4 | fine |
| **198** | **95.4%** | **-1.0** | **just over the line (195): too bright** |
| 211 | 78.7% | -17.7 | too bright |
| 220 | 27.4% | -69 | too bright |

Both lines sit within about 2 points of clean. A first, harsher run (stronger noise, no motion blur) found 83% at 40:
either way, 40 was too lenient. False alarms rose sharply with the added noise (26% at 60), more than real cameras
show (their compression smooths noise, and the tracker needs two cameras to agree), so they weren't used for the line.

### Darkness and grain together

The grain line was first set at 4 from a study that measured noise the old way (whole grey levels, so it read only
1.05, 2.1 or 3.15) and mixed dimming, grain and motion blur in one step. Re-done on 2026-11-07: the fair test session
(700 pictures, 329 cats), dimmed, with sensor noise added in steps and measured the same way as the setup screen measures
it. Cats found, change against clean (96.4%), and false alarms (a cat reported in a picture with none; clean 2.2%):

| Brightness | Grain 0 | Grain 2.1 | Grain 3.15 | Grain 4.1-4.2 |
| --- | --- | --- | --- | --- |
| 135 (the test set's own) | 96.4% (0), 2% | 96.4% (0), 4% | 96.0% (-0.4), 8% | 96.0% (-0.4), 11% |
| 85 | 96.0% (-0.4), 10% | 96.0% (-0.4), 16% | 95.4% (-1.0), 24% | 94.8% (-1.6), 29% |
| 70 | 96.0% (-0.4), 12% | 95.7% (-0.7), 22% | 95.1% (-1.3), 32% | 93.9% (-2.5), 36% |
| 55 | 95.7% (-0.7), 13% | 94.8% (-1.6), 29% | 93.3% (-3.1), 35% | 91.5% (-4.9), 52% |

- **Grain alone barely matters** (-0.4 at 4.2 in a bright picture), and **dimness alone barely matters** (-0.7 at
  55). **Together they do**: the test setup's cameras under a dim light (brightness 51-58, grain 2.6-3.1) sit at about -3.
- So CHECKS OK needs either enough light (85 or more) or little grain (under 2). Dim and grainy (2 up to 4) is a
  yellow **CHECKS OK, A BIT DARK**: it can be used, nothing is blocked, the note says more light helps it see the cat.
  Grain 4 or more, or brightness under 50, stays red.
- Dim with little grain stays CHECKS OK: it costs 0.7 at most, and a real camera in a dim room usually turns its gain
  up, so it shows grain; a dim picture without grain comes from a camera good in low light.
- **Mostly, dim light means phantom warnings, not missed cats.** False alarms rose from 2% to 10-13% from dimming
  alone and to 30-50% with grain. These are single pictures with plain added noise: real camera noise is smoothed by
  its compression, the model learned from its own night pictures, and the tracker needs two cameras to agree, so
  real false alarms are far lower. The direction holds: more light, fewer false warnings.
- Caveats: the noise is added in software (plain, per pixel); real noise is smoother and correlated. The model was
  trained on that room's real night pictures, so for that room these numbers are probably pessimistic; no fair night test set
  exists to check (every labelled night session was trained on).

### Light flicker: what was wrong, and the new measure

The test room's light visibly flickers, yet the old check said "no flicker". Recording each camera for 5 s showed why.
Mains lights pulse 120 times a second (100 in 50 Hz countries), and these cameras run at about 122 frames a second,
so each frame catches the light at almost the same moment: the camera sees it as a slow **2 Hz** pulse, and the old
check looked at only 0.75 s, too short for that. It also showed the camera barely sees the flicker at all: about
**0.3-0.9% peak to peak**, because automatic exposure spreads each picture over a whole pulse of the light. What the
eye sees and what the camera sees are different things, and only the camera's matters here.

The new check measures exactly that: the brightness swing at the frequency the light's pulse lands on (120 or 100 Hz
folded by the measured frame rate), over the last 4 s, per row band (rolling shutter), median over the bands.
Something moving in the picture isn't at that exact frequency, so it doesn't count. Tests: synthetic 5%, 20% and 60%
read back as 5.0%, 20.0% and 60.0%, also with someone walking through and with 50 Hz mains; a steady light with
someone walking reads 1%. The test setup's four cameras read 0.86%, 0.31%, 0.42% and 0.44%.

Why flicker is shown but almost never red: on still pictures, horizontal bands up to 70% peak to peak didn't change
how often the cat was found or where its box was. Strong flicker (40% or more) is still flagged, because it means
very short exposures, which come with other troubles (noise, colour shifts) that the bands don't simulate.

### Sharpness: what was wrong, and the new measure

The old measure (the Laplacian's variance in tiles) can't tell sensor noise from detail. In a dim room the camera
turns its gain up, the picture gets grainy, and the grain reads as sharpness: the test setup's cameras read 4-12 at night, mostly
noise, against 2.1-4.1 for the same cameras in daylight. So **SKIP could be offered for a soft camera in a dim room**.

A first fix (half size, noise subtracted, an absolute bar of 6) still had two holes, found by re-testing on the test setup's own
recorded cameras: the noise was measured on whole grey levels, so a noise of 1.5 read as 1.05 and its share was
under-corrected; and an absolute number depends on the room: a busy, textured room blurred by 1.5 px still scored
7-10, over the bar.

The measure now is a ratio: fine detail (at half size) against coarse detail (at an eighth), per tile, with the
noise (measured on floats from two pictures a moment apart) subtracted from both. Blur takes away fine detail first,
while how busy the room is changes both alike, so the ratio is the same for a plain room and a busy one. When noise
is over 60% of the fine detail it isn't judged at all: SKIP isn't offered and the panel says the room is too dim to
judge, use the focus assist.

| Blur | Test scenes (13) and the test setup's 4 rooms, noise 1 and 3 |
| --- | --- |
| none (focused) | 8.8-19 |
| 0.7 px | 6.5-13 |
| 1 px | 4.6-10 |
| 1.5 px | 2.4-6.1 |
| 2 px | 0.9-4.5 |

SKIP needs **7.5**. Tests: test pictures and the test setup's recorded cameras at every combination of blur 1.5-3 px and noise
1-4: **SKIP wasn't offered in any of them**. A focused picture at normal noise gets it. The price is caution: some focused cameras in a dim,
grainy room measure under 7.5 (the test setup's at night: 4.5-9.6, one not judged), so they're asked to use the focus assist.

The focus assist itself (the circle) compares the picture with its own best moments while the ring turns, so a
constant noise level cancels out; it's unaffected.

Focus results saved before this measure (2026-11-07) were on another scale: they still count as focused, but aren't
used for "sharpness dropped" until the camera is focused or skipped again.

## Speed and how early a warning comes

The camera's frame rate isn't what limits warnings: the cameras give about 120 frames a second, so a frame is at
most 8 ms old. What matters is how often the tracker looks: `detector.rate_hz` 8 a second while the cat moves or is
near, `idle_rate_hz` 3 a second while it's still. The worst case is a sleeping cat that bolts toward you.

**Before (measured parts, 2026-11-06):**

| Step | Time |
| --- | --- |
| the next look at the idle rate | up to 333 ms |
| detection (measured 21 ms) and placing it | about 30 ms |
| seen as moving (it has to have moved 15 cm) | about 50 ms at 3 m/s |
| shown in the headset (the tracker's loop runs 30 times a second) | up to 33 ms |
| **worst case** | **about 0.45 s, about 1.4 m at 3 m/s** |

**Now:**
- **A motion tripwire** (`cat_tracker/tripwire.py`): at the idle rate, 30 times a second, each camera's picture around
  the cat's last box is compared with how it looked at the last detection (a 16x16 grey copy, so noise and flicker
  vanish; a change of the whole spot's brightness doesn't count). When it changes, the detector runs at once. Tests:
  the cat's box moved 8 px (about 3 cm at 3 m) wakes it; noise, 2% flicker, a 25% exposure change and movement
  elsewhere in the picture don't. On the test setup's cameras a check takes 0.25 ms for all four (under 1% of one CPU core).
  With the test room live for 40 s it woke 35 times (people moving): each wake costs one extra detection.
- **Full rate while the cat is within 3 m of you** (`full_rate_within_m`), still or not.
- The position filter was already speed-adaptive (One Euro: smooth at rest, quick on a fast start), and a cat within
  1 m (`underfoot_m`) is already set to warn even when it's asleep, so neither needed changing.

| Step | Time |
| --- | --- |
| the tripwire's next check | up to 33 ms |
| detection and placing it | about 30 ms |
| seen as moving | about 50 ms at 3 m/s (the tripwire keeps it looking meanwhile; see the 2026-11-11 note below for slower starts) |
| shown in the headset | up to 33 ms |
| **worst case** | **about 0.15 s, about 0.45 m at 3 m/s** |

These are estimates, added up from parts measured on the test PC, not one end-to-end test of a bolting cat; other
PCs and cameras will differ. They're the tracker's own delay only: you still need time to see the warning and react. The cost: while the cat sleeps
far from you, the same 3 looks a second plus the tripwire (under 1% of a CPU core); within 3 m of you, 8 a second
(about 17% of the GPU's time on the test PC instead of 6%).

**2026-11-11: back to the full rate sooner (`cat_tracker/rate.py`).** The rule above had gaps that kept the idle
rate too long. A tripwire wake ran one extra look but didn't switch to the full rate, so a cat that started slowly
waited until its speed over the last second passed `still_speed`. A cat "last seen" (often behind you when it's
close) dropped to the idle rate, and so did one whose new position the filter set aside as a jump. Now the full rate
comes back at once when any of these happen: it moves `wake_move_m` from where it settled, it's faster than
`still_speed`, it's within `full_rate_within_m` or the warning is on, it's "last seen", something is found while nothing
is shown, the filter sets aside a jump, or the tripwire wakes. It then stays at least `full_rate_hold_s`, so it doesn't
flick between rates. A single look that misses it while it's shown gets one quick look again. The detection beat
also keeps its rhythm now (the 30-a-second loop had rounded each gap up, so 8 a second ran at about 7).

In a simulation (`engine/tests/test_detection_rate.py`: the real filter and speed code, made-up positions with 2 cm
of jitter, the tripwire stood in for by "moved 3 cm"; worst of 20 runs, not a test on a real cat):

| Asleep far from you, then | before | now |
| --- | --- | --- |
| walks off at 0.3 m/s | 0.73 s to the full rate (0.22 m) | 0.23 s (0.07 m) |
| creeps off at 0.12 m/s | 1.93 s (0.23 m) | 0.53 s (0.06 m) |
| walks off at 0.3 m/s, tripwire doesn't notice | 0.83 s (0.25 m) | 0.67 s (0.20 m) |
| bolts at 3 m/s | 0.10 s | 0.03 s |

A cat 2 m from you that the cameras lose ("last seen"): before 2.6 looks a second, now about 8. Asleep far from you,
it still uses the idle rate (3 looks a second), so the GPU saving is kept for that case. The cost is more full-rate
time around a cat that is moving, close, or hard to see. Real rooms, cameras and cats will differ.

## While the tracker runs

A room that passed at setup can be dark at night, so the tracker (`engine/cat_tracker/light.py`) keeps checking the
light with the same measures and lines: brightness, and grain from two of its own looks a moment apart (skipped when
the light or exposure changed between them, which would read as grain). One camera per look, in turn, so each is
checked about every 5 s; about 4 ms each on the test PC (0.3% of one CPU core), so the tracker's loop doesn't pause for
long. It's judged over 3 minutes, like the setup screen: red or yellow only after it has lasted (60% of that time),
and cleared only when it's mostly gone (under 20%), so a lamp switched on or off for a while doesn't make it flick.

- Dim and grainy: a line in the tracker window ("a bit dark and grainy: more light helps it see the cat") and in the
  log. Too dark or too bright: the same in capitals, and a warning in the log.
- Only in the tracker window and the log, not in VR, and it doesn't stop tracking.
- Every 5 minutes, and when the tracker stops, the log gets each camera's brightness and grain (`Light: ...`).
- First run on the test setup's cameras under the dim light: after about 90 s, all four said "a bit dark and grainy" (brightness
  52-59, grain 2.6-3.1), the same as the setup screen.

## What the checks can't catch

- **Aim and coverage.** Whether two or more cameras see every spot the cat uses: only the room calibration and the
  desktop test show that.
- **A camera moved after CHECKS OK.** The setup screen checks the picture, not where the camera points; `drift_check.bat`
  (step 7) does.
- **Real low-light false alarms.** The study added plain sensor noise, which raised false alarms sharply (30-50% in
  a dim, grainy picture; see "Darkness and grain together"). Real camera noise is smoothed by its compression, and the tracker needs two or more cameras to
  agree, so real false alarms are far lower: the test setup's cameras at brightness about 60 tracked well. Still, darker is worse.
- **A light exactly at the frame rate.** A camera at exactly 120.0 frames a second under a 120 Hz light sees still
  bands, which can't be measured; they're harmless (bands didn't hurt detection).
- **Damage that doesn't look blocky.** Only damage that leaves the bottom of the picture blocky is counted.
- **Things the camera can't see.** The cat behind furniture, or under it: no check helps there.

## The log

When a camera's checking finishes, and for every camera in use when you save or quit, the setup screen writes one
log line with its readings: state, frame rate, brightness, noise, light flicker, sharpness, compression, damaged %,
and any lasting problems (`my_data\logs\cameras\<time>_camera_setup.log`).
