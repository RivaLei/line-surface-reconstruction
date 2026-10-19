#!/usr/bin/env python3
"""Run the official Andalusian reconstruction demo from any working directory."""

import os
from pathlib import Path
import subprocess
import sys

from plane_visualization import export_plane_lines


def main():
    project_dir = Path(__file__).resolve().parent.parent
    mosek_dir = Path("/home/lz/project/third_/mosek")
    env = os.environ.copy()
    env["MOSEK_DIR"] = str(mosek_dir)
    env["MOSEKLM_LICENSE_FILE"] = str(mosek_dir / "mosek.lic")
    library_dir = str(mosek_dir / "8/tools/platform/linux64x86/bin")
    previous_library_path = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = library_dir + (
        ":" + previous_library_path if previous_library_path else ""
    )

    (project_dir / "result/demo-Andalusian").mkdir(parents=True, exist_ok=True)
    export_plane_lines(
        project_dir / "data/Andalusian/input_lines_from_residuals.json",
        project_dir / "result/demo-Andalusian",
    )
    command = [
        "./build/line_based_recons",
        "-i", "data/Andalusian/input_lines_from_residuals.json",
        "-o", "result/demo-Andalusian/",
        "-cp", "1",
        "-cv", "1",
        "-ca", "0",
        "-ce", "0.1",
        "-cc", "0.1",
        "-ext",
        "-sa",
        "-v",
    ]
    try:
        return subprocess.run(command, cwd=project_dir, env=env).returncode
    except FileNotFoundError:
        print("Executable not found: build/line_based_recons. Build the project first.",
              file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
