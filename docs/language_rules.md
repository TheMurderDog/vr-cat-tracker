# Language rules

This is a free hobby project, **not a safety device**. Words that promise safety, accuracy or reliability can be
quoted against the author if someone or their pet gets hurt. These rules apply to everything people read or hear:
READMEs, the DISCLAIMER, docs, on-screen text, voice lines, log messages, the GitHub About text, releases, issues, and
posts about the project anywhere else.

Not legal advice: it's a careful, plain-language baseline. When in doubt, say less and point to
[DISCLAIMER.md](../DISCLAIMER.md).

## Words to avoid, and what to say instead

| Don't say | Say instead |
| --- | --- |
| safe, safety feature, protects, prevents, keeps your cat safe | helps you notice your cat |
| always, whenever, never misses, guaranteed, will warn you | is set to, tries to, when it sees the cat |
| where it really is, exactly, accurate, precise | where the cameras think it is, roughly |
| It tells you when it stops working | It tries to tell you when it stops working |
| now my cat can be in the room while I play (any story that suggests changing your habits) | it's an extra hint; I still keep my play area clear |
| a time or distance that sounds safe ("fine beyond half a metre") | an estimate, how it was measured, and "you still need time to react" |
| 96% (or any score) on its own | the score, plus "one room, one cat, one test day; yours will differ" |
| GOOD / ready / passed, as if tracking is safe | what was checked: "picture checks passed" |
| running at 100% is normal | what the load is, for how long, and what to check (fans, vents) |

## Always

- **Limits next to claims.** When text says what it does, the nearest sentence or the DISCLAIMER says what it can't do.
- **Physical steps carry one short precaution, as an instruction.** Headset on: "Clear the floor first." Mounting:
  rated mounts, a proper ladder. Long GPU runs: clean fans, clear vents.
- **Step READMEs stay instructions only.** Precautions go in as instructions; warnings and legal text go in the
  DISCLAIMER, which each step points to.
- **Numbers say where they came from.** Measured or estimated, on what setup, and that other setups will differ.
- **Anything that saves pictures says so when it starts**, on screen or in the log. Never add audio recording,
  telemetry, uploads or new network output without a privacy review first.
- **Recording laws are the user's.** Tell users to check the laws where they live. Don't give them legal advice.
- **Never ask for pictures from captures, logs or calibration folders** in issues or support. Text from logs is fine.
- **New dependency, model or voice:** add it to [NOTICE.md](../NOTICE.md) with its license. Keep everything
  AGPL-3.0 compatible, and never put model files with research-only or non-commercial terms in the repository.
- **Other products are named only to say what it works with**, and each new one goes on the DISCLAIMER's
  "Not affiliated" list.
- **Installers keep the YES prompt.** Any new install or setup tool must show the short disclaimer and get a typed
  YES before installing, as `setup.bat` does.
- **Keep it free.** No sales, paid set-ups, paid support or sponsorships tied to it without asking a lawyer first.

## Before publishing a change

Search the changed text for: `safe`, `safety`, `always`, `never`, `guarantee`, `protect`, `prevent`, `ensure`,
`reliable`, `accurate`, `exactly`, `really is`, `will warn`, `100%`. Each hit should either describe a limit ("never
rely on it") or be reworded using the table above.

## If someone says they or their pet got hurt

Reply kindly, don't argue, don't admit fault or offer money, don't delete the issue, the history or the repository, fix
what you can, and talk to a lawyer before saying anything about blame.
