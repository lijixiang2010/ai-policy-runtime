from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ["AI_POLICY_AGENT"] = "claude"

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from hooks.stop_refinement import main


if __name__ == "__main__":
    raise SystemExit(main())
