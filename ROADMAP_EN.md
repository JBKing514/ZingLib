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

## 1.2.0 — the next minor's `feat` bucket (logged only, not implemented)

**The branch has not been cut.** Until `v1.2.0-beta` really exists, entries here are **logged only — no code**.

| # | What | Why it is not a patch item |
| --- | --- | --- |
| feat-1 | **OPDS**: expose the local library as an OPDS catalog for third-party readers (Panels, KyBook, Moon+ Reader, ...) | A whole new outward protocol surface and data exit; the user plainly gains a new way to use the library → `feat` |
| feat-2 | **Auto-resolution resampling strategy**: offer Performance (BILINEAR) and Quality (Lanczos) modes, with clear copy that every server-side downsample trades CPU time for network bandwidth; users may choose for their host or bypass processing with Original | Adds a visible quality/compute policy and setting that changes server image-processing cost → `feat` |
| feat-3 | **Reader double buffering and page transitions**: retain current and next display buffers; if the next page is not ready, keep the current page visible with loading progress and transition only after decoding completes, never exposing the black stage | Adds a rendering state machine, buffering policy, and page-turn behaviour → `feat` |
| feat-4 | **Remove in-app page/DPI zoom**: delete the zoom setting, runtime CSS scaling, and related coordinate compensation; keep application rendering at 100%, ignore existing saved values, and leave whole-page scaling to browser zoom or device DPI | Contracts the user-facing feature surface and reunifies the coordinate system used by long press, dragging, overlays, and hit testing → `feat` |

## Relationship to the other files

- **This file is the single version-allocation list.** Do not copy it into `AGENTS.md`, the README, or a chat round — a second copy will drift.
- `AGENTS.md` (repository root, gitignored) carries **the rule itself** ("a received `feat` is logged, not implemented") and points here; **it does not repeat the entries**.
- When a version really starts: cut its branch → move the entries out of the bucket → record them per `CHANGELOG.md` when done.
- Versioning mechanics (`scripts/bump_version.py`, what `fix` means for a patch release) are in [CONTRIBUTING_EN.md](CONTRIBUTING_EN.md);
  the release-engineering guards are in [STARTUP_EN.md](STARTUP_EN.md) section 7.
