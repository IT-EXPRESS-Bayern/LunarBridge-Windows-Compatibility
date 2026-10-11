# SPDX-License-Identifier: GPL-3.0-only
"""Run synthetic tests and print a report without traceback or private paths."""

import datetime
import hashlib
import json
from pathlib import Path
import platform
import sys
import unittest


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    suite = unittest.defaultTestLoader.discover(str(root / "tests"))
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
    sources = ["tools/pe_inspector.py", "tools/windows_compatibility.py", "tools/run_tests.py",
               "tests/test_compatibility.py", ".github/workflows/tests.yml", "tools/wine_runtime_ci.py",
               "tests/test_runtime_ci.py", "ci/runtime-pins.json", "ci/payload/runtime_smoke.c",
               ".github/workflows/wine-runtime.yml"]
    report = {
        "schema": 1, "checked_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "host_system": platform.system(), "python_version": platform.python_version(),
        "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "skipped": len(result.skipped), "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
        "fixtures": "synthetic_PE_and_MachO_and_own_runtime_recipe", "process_invocations": "mocked",
        "wine_runtime_tested": False, "native_target_tested": False,
        "windows_application_tested": False, "gpu_acceleration_tested": False,
        "source_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources},
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
