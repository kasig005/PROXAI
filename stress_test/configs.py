"""
Back-compat shim. The SSG-LUGIA configs + stage mapping now live in the
`ssg_lugia` profile; new pipelines get their own profile module (e.g.
`census_ml`). `run_stress_test.py --profile <name>` / `compare.py --profile
<name>` select one.
"""

from ssg_lugia import CONFIGS  # noqa: F401
