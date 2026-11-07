# 4. Teach it your cat

Train the detector on your own cat. This is the biggest improvement you can make: on the reference setup it went
from 1 camera in 4 seeing the cat to all 4.

About an hour of your time, plus 20 to 60 minutes of the computer training by itself.

## Before you start

- [ ] Step 3 done.
- [ ] Your cat in the room, for about 20 minutes.
- [ ] A few hundred MB of free disk space for the pictures.
- [ ] Good, steady light. Dim light makes labelling much slower. Capture in the light you'll play in; if it changes
      (day and night), capture some of both: a model taught only one kind of light does worse in the other. (One room,
      one night: a helper taught only dim pictures found the cat in 39% of bright pictures, the basic model in 63%.)

## Run these in order

### 1. `1_capture.bat`

Leave it running for 10 to 20 minutes while your cat wanders, plays and naps. It says when it has enough for a
first model; `q` stops. Try to get:

- your cat lying down and sleeping in its usual spots, and walking across the room,
- a few minutes of the room **without** the cat.

The most useful pictures are the moments it tracks badly: your cat half hidden behind furniture, in dim light,
close to your feet, jumping or running, or curled up small. Just as useful: a while with the cat out of the room,
doing what fools it (walking around, moving cat-sized things like bags, pillows, slippers or toys, changing the
lights). In `2_label.bat` pass those with `S` (no cat). Run it again any time later to add more.

**NO CAT** (EXPERIMENTAL, tried on one setup so far; `n`, or the button at the top left): when it says it has enough with your cat, take your cat out and
close the door so it can't come back in. Then press `n` twice (the first press shows this reminder). From then on
every picture is saved as "no cat" without labelling; press `n` again if the cat comes back. Pictures where the model
still saw something cat-like are listed in `2_label.bat` under Possible mistakes, to check.

### 2. `2_label.bat`

The first time it opens a new capture, it fills in the boxes the detector missed, where the other cameras say the
cat is ("Preparing boxes...", once per session, usually under a minute). Boxes it isn't sure about say **CHECK
THIS**. Where it can't find the cat, it leaves no box for you to add.

Then check every box, one picture at a time. The keys are WASD and Space, shown under the picture. You can stop with `Q`
and carry on later.

How to box:
- Click the cat: a box snaps to it. Drag only if it's off.
- Box only the part of the cat you can see, tight around the fur. Never guess where the hidden part is.
- Leave a sticking-out tail outside the box; include the tail only when it's curled against the body.
- No cat at all: `S`. Can't tell whether it's the cat (a blur, only a tail tip): `D` skips it, so it isn't used.

| Do this | Key |
| --- | --- |
| The boxes are right: next picture | Space |
| No cat in this picture | `S` |
| Not sure: leave it out of training | `D` |
| Copy the blue box (the previous picture's; the cat sat still), then Space | `W` |
| Back one picture | `A` |
| Step back / forward without deciding (hold to scrub) | `,` / `.` or the arrow keys |
| Jump to any picture | click or drag on the timeline under the picture |
| A stretch with no cat: `N` on its first picture, go to its last, `N` again | `N` ... `N` |
| Undo the latest stretch (again: the one before), even after more labelling | **UNDO STRETCH** or `U` |
| Snap a box to the cat (also fixes a box that's a bit off) | click on the cat |
| Draw a box | drag on an empty spot |
| Resize or move a box | drag its corner or side, or its middle |
| Delete a box | right-click in it |
| Zoom in on a small cat / move the zoomed view | mouse wheel / drag with the middle button |
| Undo | `Z` |
| The hint on or off | `H` |
| Every session, to open another or review one | **SESSIONS** or Tab |
| All of this explained, with pictures | the yellow **? HELP** button |
| Save and quit | `Q` |

On a picture with no box, a magenta cross shows where the other cameras place the cat at that moment. It's only a
hint: if the cat is really visible there, click it to snap a box. There, Space won't save "no cat" by accident:
press `S` if it really isn't there, or `D` if you're not sure. The TRANSPARENCY sliders at the top set how
see-through the blue box, your boxes and the hint are; the BRIGHT slider beside the picture makes it brighter or darker
on screen only. While zoomed in, the next picture opens centred on its box (or the hint).

**TRAIN A HELPER** (EXPERIMENTAL, tried on one setup so far; top of the window): once you've decided about 150 pictures with the cat, it lights up. Click it
and a quick helper learns from the pictures you've decided (about 3 minutes, in the background: keep labelling), then
suggests boxes for the rest, in orange to check. It helps most when the auto boxes miss a lot (a dim room, a new
camera). Your tracker isn't changed: `3_train.bat` still does the real training. A teal line under the timeline marks
the pictures a helper learned from; after about 75 more, the button lights up again
(each helper builds on the last and tries to do a little better; one that doesn't pass its check on held-back pictures
isn't used). Its suggestions can box empty pictures too, so check each one.

The **timeline** under the picture is this camera's pictures in order: green cat, grey no cat, yellow skipped,
orange auto box, dark still to do. Under it, a mark only where it needs you: magenta, a picture to do where the other cameras see the cat but
there's no box yet; red, one you marked no cat where they see it (a possible mistake); white is where
you are.

Holding `S` or Space to go fast is fine: a held `S` stops by itself at a picture with a box or the hint, and a held
Space at an empty picture, the hint or CHECK THIS. Let go and press again to go on. For a long stretch without the
cat: press `N` on its first picture, move to its last (it shows blue on the timeline), and press `N` again. Every
picture in it becomes no cat in one go, whatever it was before: its boxes are deleted (false boxes too) and it says how
many had one. `Z` undoes the whole stretch; Esc cancels one you've started.

One box per cat: a new box replaces the old one. More than one cat? Set `cats` under `label` in
`settings\cat_tracker.yaml` to how many you have, and box every cat in a picture (an unboxed cat teaches "not a cat").
Tiny boxes (under 12 pixels a side) aren't drawn. A picture with too many boxes says so, and Space waits until
one per cat is left; `2_label.bat --review-extra` goes through only those pictures.

Orange boxes were filled in for you (from the other cameras, or snapped at the hint): check them carefully. If the
detector boxed something that isn't your cat (like the headset on the floor), those orange copies of it are wrong too:
delete them, or open that capture with `2_label.bat --no-autolabel` and box it by hand.

A few hundred pictures with the cat in them is plenty for a first round.

**SESSIONS** (top right, or Tab) lists every session: waiting for labels, and done. Click one to open it; a done
one opens for review, backed up first. **Practice copy** opens a throwaway copy to try things: nothing you change
there reaches training. When nothing is left to check, `2_label.bat` opens on this screen.

### 3. `3_train.bat`

Trains on your pictures, 20 to 60 minutes. Then it scores the new model and the one you have on the same
pictures, and only switches the tracker to the new one if it finds the cat better; it says which it kept and why.

For a fair score, capture a second short session (about 5 minutes) on another day and label it: it becomes your
test set, held back from training. Until then it says the score isn't reliable yet.

Want a longer, better run? `later_rounds\train_overnight.bat` trains for up to 6 hours, keeps the PC awake, picks
up where it stopped if it's interrupted (just run it again), and leaves a summary for the morning. It keeps your
graphics card at full load for hours, so run it only on a PC with clean fans and clear vents. The summary says how
hot it got.

## You're done when

`3_train.bat` says your model is saved and switched on. Run `3_first_test\2_desktop_test.bat` again: many more
cameras should box your cat.

## Later, to make it even better

- **It misses the cat somewhere** (the couch, under the desk): capture a couple of minutes of it there, run
  `2_label.bat`, then `later_rounds\train_more.bat`.
- **It boxes something that isn't the cat:** capture the room with that thing in view, label those pictures with `S` (no cat),
  then `later_rounds\train_more.bat`.
- While you play, the tracker saves the moments it struggled with. Now and then, run `2_label.bat`, then
  `later_rounds\train_more.bat`.
- **Back up a good model:** copy `my_data\models\cat_finetuned_half.onnx` somewhere safe. Each training run
  replaces it.

## If something's wrong

- **Training setup failed:** delete the `.venv-train` folder in the top folder and run `3_train.bat` again.
- **"No checked images yet":** run `2_label.bat` and pass some pictures with Space, `S` or `W`.
- **Out of GPU memory:** run `3_train.bat --batch 4`.
- More detail: [docs/training.md](../docs/training.md).

## Next

Open [5_play_in_vr](../5_play_in_vr/README.md).

## Your notes

<!-- Leave notes here as you go: anything confusing, broken or missing. -->
