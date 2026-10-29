#!/bin/bash
# Writes the case-twall-* directories this study runs. They are generated, so they are git-ignored
# rather than committed: rerun this after changing flash.toml or generate_cases.py, from any
# directory, with the project's .venv active (generate_cases.py needs toml).
set -euo pipefail
cd "$(dirname "$0")"
python3 generate_cases.py --force --wall_temp 70 71.5 73 74.5 76 77.5 79 80.5 82 83.5 85 86.5 88 89.5 91 92.5 94 95.5 97 98.5 100
