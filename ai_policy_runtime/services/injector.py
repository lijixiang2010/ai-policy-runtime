from __future__ import annotations

from pathlib import Path


BEGIN = "<!-- POLICY_RUNTIME_BEGIN -->"
END = "<!-- POLICY_RUNTIME_END -->"


def inject_current_prompt(root: str | Path, target: str) -> Path:
    root_path = Path(root)
    prompt_path = root_path / ".policy" / "current" / "effective-prompt.md"
    prompt = prompt_path.read_text(encoding="utf-8")

    if target == "codex":
        output = root_path / "AGENTS.md"
    elif target == "claude":
        output = root_path / "CLAUDE.md"
    elif target == "custom":
        output = root_path / ".policy" / "current" / "injected-prompt.md"
    else:
        raise ValueError(f"Unsupported injection target: {target}")

    block = f"{BEGIN}\n{prompt}\n{END}"
    if target == "custom":
        output.write_text(block + "\n", encoding="utf-8")
        return output

    existing = output.read_text(encoding="utf-8") if output.exists() else "# Project Rules\n"
    output.write_text(_replace_block(existing, block), encoding="utf-8")
    return output


def _replace_block(text: str, block: str) -> str:
    if BEGIN in text and END in text:
        start = text.index(BEGIN)
        end = text.index(END) + len(END)
        return text[:start].rstrip() + "\n\n" + block + "\n" + text[end:].lstrip()
    return text.rstrip() + "\n\n" + block + "\n"
