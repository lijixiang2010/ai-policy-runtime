from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_policy_runtime import PolicyRuntime, RuntimeConfig


def main() -> None:
    runtime = PolicyRuntime(RuntimeConfig.from_values(root=ROOT, policy_root=ROOT))
    result = runtime.resolve(
        "写一个 C++20 数据通道，主循环里不能有分配和阻塞，尾延迟要稳",
        ("cpp.low_latency",),
    )
    print((result.current / "effective-prompt.md").read_text(encoding="utf-8").rstrip())


if __name__ == "__main__":
    main()
