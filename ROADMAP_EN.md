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

If a `feat` arrives in any session (or a `ui` item that the test above classifies as a `feat`), **the round only writes it into the most recent `feat` bucket that has not started work (currently `1.2.0`) — no implementation code**.
Implementation starts only once the matching branch is **actually cut** (e.g. `git checkout -b v1.2.0-beta`); that is when the bucket is opened and its entries move into the workflow.

> This is an explicit request from the maintainer: he recognises a tendency to slip feats into patch releases, so **logging** and **implementing** are separated in *time* rather than left to a round's self-discipline. Writing it down makes it a contract; going around it breaks it.

**Rule 3 — an entry may only leave its bucket for one of three reasons.**

An entry leaves its `feat` bucket only when: (1) the corresponding branch has been cut and work has begun; (2) the maintainer explicitly reclassifies it as a `fix`; or (3) the maintainer explicitly drops it. It is **not** allowed to *quietly* implement an entry because it happened to be convenient — an opportunistically implemented `feat` must be logged retroactively, or reverted.

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

**The `v1.1.0-beta` branch is cut**, so this bucket *is* that version's worklist. Completed entries are recorded per `CHANGELOG.md`.

> **Done this round (2026-09-26)**: `feat-6`, `feat-9`, `ui-10`, `ui-11`, `ui-12`, `feat-13`, `feat-14`, `ui-15`, `ui-17`, `feat-16`.
> Every entry in this bucket is **complete**.

| # | What | Why it is not a patch item |
| --- | --- | --- |
| feat-6 | "Guess you like" should be **unified** with the rabbit hole: clicking goes to the detail page instead of straight into reading; or returning from the reader lands on **the current gallery's own** `PreviewCard` | Redefines an interaction's meaning; the user can plainly feel the change → `feat` |
| feat-9 | **Haptic feedback** on the thumbnail wheel | A brand-new, user-perceivable capability → `feat` |
| ui-10 | The thumbnail wheel should show a **placeholder while fast-scrolling** | Introduces a new state (placeholder) and the loading strategy that comes with it → `feat`, not paint |
| ui-11 | "Refresh" is possibly redundant and could be **removed** | Removes something the user can do — a contraction of the feature surface → `feat` |
| ui-12 | Mobile filter buttons should **drop their text** to match PC and save space | Purely cosmetic, no behaviour change → it looks like `ui`, but the maintainer has explicitly filed it under `1.1.0` |
| feat-13 | **Global reader shortcuts**: configurable page-turn keys (default `A`/`D`); mouse-wheel paging with 150 ms damping and a **direction reversal** option (macOS natural scrolling). Volume-key paging was removed after Android device testing confirmed that browsers do not receive system volume events. | Two new input channels plus a keybinding UI; the user plainly sees that new inputs exist → `feat` |
| feat-14 | A **private / incognito reading mode** on the home page (🕶️ **blocks history and bookmark writes**), with the UI **shifting its whole colour tone** to signal it, and the toggle placed **next to folder mode** | Adds a mode that **changes write semantics** (history/bookmarks are intercepted); both interaction and appearance change → `feat` |
| ui-15 | Remove the "browse the local library by folder structure" text on the home page | Deletes a piece of user-visible copy — a contraction of the feature surface → `feat` |
| feat-16 | **Auto resolution**: the reader's auto quality tier **Lanczos-downsamples** pages **larger than the screen** to a contain-fit of it (shrink only, never enlarge); pages that already fit, and requests without a usable hint, are **served as their original bytes**. The page URL carries a `res=WxH` screen hint, and the server caches derivatives on disk keyed by source hash + resolution | A whole new transport/quality semantic the user can feel (big scans cost far less bandwidth and decode) → `feat`. **Implemented on `v1.1.0-beta`** (see `CHANGELOG.md`) |
| ui-17 | A **progress capsule** on home gallery cards: same size as the existing category capsule, in **orange (deep orange)** — deliberately off every colour the system already uses, and matching the "history" association; it holds a **ring on the left and a percentage on the right**. On a **full card** it sits at the cover's **bottom-left**, mirroring the category capsule at the bottom-right; on a **compact card** it sits at the bottom-left; in the **list view** it is prepended to the metadata string (`Local • 2026/09/25 10:33 • Non-H • 63P`), at its **leftmost position** | Adds a user-perceivable information block that has to be laid out across three card shapes → `feat` |

## 1.2.0 — the next minor's `feat` bucket (logged only, not implemented)

**The branch has not been cut** (wait until `1.1.0` is tested and merged, then cut `v1.2.0-beta`). Until that branch really exists, entries here are **logged only — no code**.

| # | What | Why it is not a patch item |
| --- | --- | --- |
| feat-1 | **OPDS**: expose the local library as an OPDS catalog for third-party readers (Panels, KyBook, Moon+ Reader, ...) | A whole new outward protocol surface and data exit; the user plainly gains a new way to use the library → `feat` |

## Relationship to the other files

- **This file is the single version-allocation list.** Do not copy it into `AGENTS.md`, the README, or a chat round — a second copy will drift.
- `AGENTS.md` (repository root, gitignored) carries **the rule itself** ("a received `feat` is logged, not implemented") and points here; **it does not repeat the entries**.
- When a version really starts: cut its branch → move the entries out of the bucket → record them per `CHANGELOG.md` when done.
- Versioning mechanics (`scripts/bump_version.py`, what `fix` means for `1.0.x`) are in [CONTRIBUTING_EN.md](CONTRIBUTING_EN.md);
  the release-engineering guards are in [STARTUP_EN.md](STARTUP_EN.md) section 7.
