"""Prepend pip-installed NVIDIA lib dirs to LD_LIBRARY_PATH before CUDA loads.

faster-whisper (via ctranslate2) links against cuBLAS / cuDNN at import time.
When those come from pip packages (nvidia-cublas-cu12, nvidia-cudnn-cu12) the
loader won't find them unless their directories are on LD_LIBRARY_PATH. Setting
the env var after interpreter start is too late, so if we detect the need we
re-exec with the updated environment.

Call bootstrap_cuda() once at process startup, before importing anything that
pulls in CUDA.
"""

from __future__ import annotations

import os
import sys


def bootstrap_cuda() -> None:
    # Skip the re-exec when running under pytest — tests don't need the CUDA
    # libs on LD_LIBRARY_PATH and the execv() would thrash the test runner.
    if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.argv[0]:
        return

    try:
        import nvidia.cublas.lib
        import nvidia.cudnn.lib
    except ImportError:
        return

    new_dirs: list[str] = []
    for mod in (nvidia.cublas.lib, nvidia.cudnn.lib):
        paths = getattr(mod, "__path__", None)
        d = (
            str(paths[0])
            if paths
            else (os.path.dirname(mod.__file__) if mod.__file__ else None)
        )
        if d and d not in os.environ.get("LD_LIBRARY_PATH", ""):
            new_dirs.append(d)

    if not new_dirs:
        return

    existing = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = ":".join(
        new_dirs + ([existing] if existing else [])
    )
    os.execv(sys.executable, [sys.executable] + sys.argv)
