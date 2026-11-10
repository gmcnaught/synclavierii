# Contributing

## Workflow (decision D2)

* `main` is protected by convention: no direct pushes.
* Do each piece of work on a **feature branch** and open a **pull request**
  into `main`.
* CI (`.github/workflows/tests.yml`) runs every `tests/test_*.py` and
  `tests/*/test_*.py` on each PR and on pushes to `main`. A PR merges only when CI is green.
* Keep PRs focused: one milestone task (e.g. `M1.1`) or one finding per PR.

## Conventions

* Tests use the Python standard library only and run as scripts
  (`python3 tests/test_<name>.py`), so CI needs no dependencies. The
  simulator tests run the same way: `python3 tests/sim/test_cpu.py`.
* New facts go into the relevant `docs/` file and into
  `docs/research-log.md`, with their source (see `docs/sources.md`).
* Tag uncertain hardware claims **[STD]**, **[OBS]** or **[HYP]** as in
  `data/netlist.csv`.
* Never commit NED disk images (`*.simg`), timbre or sound files
  (`*.stmb`, `*.ssnd`, `*.sprg`), images built from them (`*.IMG`,
  `*.SST`), ROMs, board photos or other unlicensed material
  (`tests/test_repo_hygiene.py` checks the file types). Only MIT-licensed
  NED material may be added, with its licence notice, and recorded in
  `docs/sources.md`.

## Licence (decision D1)

Contributions are accepted under the MIT licence in [`LICENSE`](LICENSE).
Changes to `mister/sys/` (avoid them; update from upstream instead) are
GPL-2.0, like the rest of that directory.

## Pull requests from forks

Workflows of pull requests from forks wait for a maintainer's approval.
Build RBF runs them on GitHub-hosted runners only.
