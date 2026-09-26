# Roadmap

> 🌐 Language / 语言: [English](ROADMAP_EN.md) | [中文](ROADMAP.md)

This file does one thing: it **keeps fixes and features in two different versions**, and it writes that split down *before* anyone starts coding.

## The contract (read this first)

**Rule 1 — `fix` lands in the current patch line; `feat` waits for the next minor.**

| Kind | Version it belongs to | Examples |
| --- | --- | --- |
| `fix` (something broken is repaired; no behaviour is redefined) | the next release of the current patch line (`1.0.x`) | a gesture that stopped working, a wrong animation direction, the wrong card shown after going back |
| `feat` (a new behaviour, a new interaction, something the user can tell is *new*) | the next minor (`1.1.0`) | haptic feedback, a new placeholder/loading strategy, a re-unified interaction meaning |
| `ui` (purely cosmetic) | by whether it changes behaviour: a new coat of paint → `1.0.x`, a changed interaction → `1.1.0` | dropping the text on a button = paint → patch line |

One question decides it: **would the user notice that there is now one more (or one fewer) thing they can do?** Yes → `feat`. "This was always supposed to work and it didn't" → `fix`.

**Rule 2 — a `feat` you receive is logged, not implemented, that round.**

If a `feat` arrives in any session (or a `ui` item that the test above classifies as a `feat`), **the round only writes it into the `1.1.0` bucket below — no implementation code**.
Implementation starts only once the matching branch is **actually cut** (e.g. `git checkout -b v1.1.0-beta`); that is when the bucket is opened and its entries move into the workflow.

> This is an explicit request from the maintainer: he recognises a tendency to slip feats into patch releases, so **logging** and **implementing** are separated in *time* rather than left to a round's self-discipline. Writing it down makes it a contract; going around it breaks it.

**Rule 3 — an entry may only leave its bucket for one of three reasons.**

An entry leaves the `1.1.0` bucket only when: (1) the corresponding branch has been cut and work has begun; (2) the maintainer explicitly reclassifies it as a `fix`; or (3) the maintainer explicitly drops it. It is **not** allowed to *quietly* implement an entry because it happened to be convenient — an opportunistically implemented `feat` must be logged retroactively, or reverted.

## 1.0.x — `fix` only

What has to be repaired before the `1.0.4` release.

> All `fix`: each is "this was supposed to work this way and it doesn't", none introduces a new interaction.

| # | What | State |
| --- | --- | --- |
| bug-1 | The sidebar edge swipe stops working at **non-100% zoom**; and on mobile, long-pressing to summon the gallery-picker slider **releases it instantly** | Fixed (1.0.4) |
| bug-2 | Tablet **landscape + left-handed**: the `PreviewCard` does not hug the edge; the Android back gesture triggers a stiff "back one page" animation instead of a natural collapse | Fixed (1.0.4) |
| bug-3 | On tablet, after opening 2+ galleries in a row, the `PreviewCard`'s top back button makes the current card vanish and **the previous gallery's `PreviewCard` reappear** | Fixed (1.0.4) |
| bug-4 | After editing metadata the `PreviewCard` should **refresh in place** (today the stale values stay on the card) | Fixed (1.0.4) |
| bug-5 | Long-pressing on the **last page** must **disable the rabbit hole** (it still navigates away) | Fixed (1.0.4) |
| bug-7 | A reading started from a **rabbit-hole suggestion** is **not recorded in history** | Fixed (1.0.4) |
| bug-8 | After a search, opening a gallery and going back **does not preserve the search results** (the feed is empty again) | Fixed (1.0.4) |

## 1.1.0 — `feat` only

**None of these may be implemented before `1.1.0-beta` is cut.** The current round (`1.0.4`) only did the `1.0.x` bucket above.

| # | What | Why it is not a patch item |
| --- | --- | --- |
| feat-6 | "Guess you like" should be **unified** with the rabbit hole: clicking goes to the detail page instead of straight into reading; or returning from the reader lands on **the current gallery's own** `PreviewCard` | Redefines an interaction's meaning; the user can plainly feel the change → `feat` |
| feat-9 | **Haptic feedback** on the thumbnail wheel | A brand-new, user-perceivable capability → `feat` |
| ui-10 | The thumbnail wheel should show a **placeholder while fast-scrolling** | Introduces a new state (placeholder) and the loading strategy that comes with it → `feat`, not paint |
| ui-11 | "Refresh" is possibly redundant and could be **removed** | Removes something the user can do — a contraction of the feature surface → `feat` |
| ui-12 | Mobile filter buttons should **drop their text** to match PC and save space | Purely cosmetic, no behaviour change → it looks like `ui`, but the maintainer has explicitly filed it under `1.1.0` |

## Relationship to the other files

- **This file is the single version-allocation list.** Do not copy it into `AGENTS.md`, the README, or a chat round — a second copy will drift.
- `AGENTS.md` (repository root, gitignored) carries **the rule itself** ("a received `feat` is logged, not implemented") and points here; **it does not repeat the entries**.
- When a version really starts: cut its branch → move the entries out of the bucket → record them per `CHANGELOG.md` when done.
- Versioning mechanics (`scripts/bump_version.py`, what `fix` means for `1.0.x`) are in [CONTRIBUTING_EN.md](CONTRIBUTING_EN.md);
  the release-engineering guards are in [STARTUP_EN.md](STARTUP_EN.md) section 7.
