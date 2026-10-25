- **A same-day sibling run no longer lends its directory to a report** (#694 review).
  `run_report.py`'s `run_directory` took the alphabetically first same-day directory that named
  the mission, so `2026-10-25-trajectories-602-live.md` was checked against the
  `…-602-adapters/` directory and failed to bind, although the run index listed it as binding. A
  directory named exactly for the report now wins, and an ambiguous fuzzy match fails closed. The
  roadmap, the concepts page and the A2A example no longer describe #604 as unmeasured or pin the
  0.8.0 version.
