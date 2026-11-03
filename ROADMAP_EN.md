# Roadmap

> 🌐 Language / 语言: [English](ROADMAP_EN.md) | [中文](ROADMAP.md)

This file does one thing: it **keeps fixes and features in two different versions**, and it writes that split down *before* anyone starts coding.

## The contract (read this first)

**Rule 1 — `fix` lands in the current patch line; `feat` waits for the next minor.**

| Kind | Version it belongs to | Examples |
| --- | --- | --- |
| `fix` (something broken is repaired; no behaviour is redefined) | the next release of the current patch line (currently `1.1.x`) | a gesture that stopped working, a wrong animation direction, the wrong card shown after going back |
| `feat` (a new behaviour, a new interaction, something the user can tell is *new*) | the next minor (currently `1.2.0`) | a new protocol, a new rendering strategy, a re-unified interaction meaning |
| `ui` (purely cosmetic) | by whether it changes behaviour: a new coat of paint → current patch line; a changed interaction → next minor | repainting a button = patch; removing a capability = minor |

One question decides it: **would the user notice that there is now one more (or one fewer) thing they can do?** Yes → `feat`. "This was always supposed to work and it didn't" → `fix`.

**Rule 2 — a `feat` you receive is logged, not implemented, that round.**

If a `feat` arrives in any session (or a `ui` item that the test above classifies as a `feat`), **the round only writes it into the most recent `feat` bucket that has not started work (currently `1.2.0`) — no implementation code**.
Implementation starts only once the matching branch is **actually cut** (e.g. `git checkout -b v1.2.0-beta`); that is when the bucket is opened and its entries move into the workflow.

> This is an explicit request from the maintainer: he recognises a tendency to slip feats into patch releases, so **logging** and **implementing** are separated in *time* rather than left to a round's self-discipline. Writing it down makes it a contract; going around it breaks it.

**Rule 3 — an entry may only leave its bucket for one of three reasons.**

An entry leaves its `feat` bucket only when: (1) the corresponding branch has been cut and work has begun; (2) the maintainer explicitly reclassifies it as a `fix`; or (3) the maintainer explicitly drops it. It is **not** allowed to *quietly* implement an entry because it happened to be convenient — an opportunistically implemented `feat` must be logged retroactively, or reverted.

## 1.1.x — current patch line (`fix` only)

Completed releases are no longer duplicated in the ROADMAP; release history belongs in `CHANGELOG.md`. The current patch line repairs existing behaviour only and does not add new feature surface.

## 1.2.0 — current minor worklist

**The `v1.2.0-beta` branch is active.** `feat-1`, `feat-3` and `feat-4` are complete; `feat-5` awaits implementation.

| # | What | Why it is not a patch item |
| --- | --- | --- |
| feat-1 | **Complete: Surface Duo hinge avoidance** for the feed, right-panel preview, reader spreads, and left-panel filter/sort dialogs. Long-press pickers retain whole-row candidates and are positioned on the screen where the press began. Use the **27 CSS px** gap calibrated on a Duo 2 when segment APIs are unavailable, with a manual layout switch and an optional geometry overlay. Prefer measured segments when the enumeration API is available | Adds a segment-aware layout strategy → `feat`; verified on the device and in ordinary phone/desktop layouts |
| feat-3 | **Complete: reader double buffering and page transitions**. The navigated page and the displayed page are separate: a turn commits only after the target has decoded (both halves in a spread), a burst of turns commits only its last target, and stale requests are dropped. The swap is a cross-fade rather than `out-in`, so the old page stays painted until the new one is ready. Stress run on a 220-page gallery: 40 turns at normal speed with zero blank frames; continuous fast flipping (~15-20 pages/s) leaves about 1% of single frames undecoded | Adds a rendering state machine, buffering policy, and page-turn behaviour → `feat` |
| feat-4 | **Complete: remove in-app page/DPI zoom**. Delete the zoom menu, state and storage reads, CSS zoom, and gesture coordinate compensation; ignore legacy browser preferences and leave whole-page scaling to browser zoom or device DPI | Contracts the user-facing feature surface and unifies touch coordinates → `feat` |
| feat-5 | **Infinite-scroll performance**: scrolling starts stuttering at roughly 500–600 items. **Measure before changing anything**: build a library of about 1000 items, then use a separate scroll test to measure frame time, long tasks, layout/paint work, and image decoding; decide the fix (list virtualisation, image decoding policy, or the rendering path) only after the bottleneck is known | Likely changes the feed's rendering and data-layer structure, and adds a reproducible performance criterion → `feat` |

## 1.3.0 — the minor after that (`feat` work plus major dependency upgrades)

**Logged only, not implemented.** Same contract as the bucket above: no code until the branch is cut.

| # | What | Note |
| --- | --- | --- |
| feat-1 | **OPDS**: expose the local library as an OPDS catalog for third-party readers (Panels, KyBook, Moon+ Reader, ...) | Moved here from `1.2.0` on 2026-11-03; handled together with the dependency upgrades |
| chore-1 | **Major dependency upgrades**: front end `vue-router` 5 / `vuetify` 4 / `pinia` 4 / `vite-plugin-pwa` 2; back end `fastapi` 0.159 / `scipy` 1.18; CI `upload-artifact` 7 / `download-artifact` 8 | All change behaviour or need code adaptation, so none belongs in the patch line; `fastapi` and `scipy` do not even pass CI today and need separate investigation |

## Relationship to the other files

- **This file is the single version-allocation list.** Do not copy it into `AGENTS.md`, the README, or a chat round — a second copy will drift.
- `AGENTS.md` (repository root, gitignored) carries **the rule itself** ("a received `feat` is logged, not implemented") and points here; **it does not repeat the entries**.
- When a version really starts: cut its branch → move the entries out of the bucket → record them per `CHANGELOG.md` when done.
- Versioning mechanics (`scripts/bump_version.py`, what `fix` means for a patch release) are in [CONTRIBUTING_EN.md](CONTRIBUTING_EN.md);
  the release-engineering guards are in [STARTUP_EN.md](STARTUP_EN.md) section 7.
