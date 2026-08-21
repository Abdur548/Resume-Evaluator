"""Fail CI when the installed environment drifts from backend/requirements.txt.

This exists because the manifest and the environment silently disagreed once
already: the suite was being run against interpreter-global site-packages where
two pins were unsatisfied, so "79 tests pass" described an environment nobody
had declared. Checking the pins in CI makes that failure loud instead of quiet.
"""

import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

REQUIREMENTS = Path(__file__).resolve().parents[2] / "backend" / "requirements.txt"


def _normalize(name: str) -> str:
    return name.lower().replace("_", "-")


def read_pins(path: Path) -> dict[str, str]:
    """Return {distribution: exact_version} for every ``name==version`` line."""
    pins = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "==" not in line:
            raise SystemExit(
                f"{path.name}: '{line}' is not an exact pin. Every dependency "
                "must be pinned with '==' so CI and local runs agree."
            )
        name, _, want = line.partition("==")
        pins[_normalize(name)] = want.strip()
    return pins


def main() -> int:
    pins = read_pins(REQUIREMENTS)
    drift = []

    print(f"interpreter: {sys.executable}")
    print(f"checking {len(pins)} pins from {REQUIREMENTS.name}\n")

    for name, want in sorted(pins.items()):
        try:
            got = version(name)
        except PackageNotFoundError:
            got = None
        if got == want:
            print(f"  ok     {name:<18} {want}")
        else:
            print(f"  DRIFT  {name:<18} pinned={want:<10} installed={got or 'MISSING'}")
            drift.append((name, want, got))

    if drift:
        noun = "dependency does" if len(drift) == 1 else "dependencies do"
        print(f"\n{len(drift)} {noun} not match the pins.")
        print("Run: python -m pip install -r backend/requirements.txt")
        return 1

    print("\nAll pins satisfied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
