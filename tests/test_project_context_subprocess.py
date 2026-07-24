from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ai_policy_runtime.services.project_context import ProjectContextAnalyzer


class ProjectContextSubprocessTests(unittest.TestCase):
    def test_git_collectors_hide_windows_processes(self) -> None:
        class FakeStartupInfo:
            def __init__(self) -> None:
                self.dwFlags = 0
                self.wShowWindow = None

        completed = subprocess.CompletedProcess([], 0, stdout="")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            with (
                patch(
                    "ai_policy_runtime.services.project_context.subprocess.run",
                    return_value=completed,
                ) as run,
                patch(
                    "ai_policy_runtime.services.project_context.subprocess.CREATE_NO_WINDOW",
                    0x08000000,
                    create=True,
                ),
                patch(
                    "ai_policy_runtime.services.project_context.subprocess.STARTUPINFO",
                    FakeStartupInfo,
                    create=True,
                ),
                patch(
                    "ai_policy_runtime.services.project_context.subprocess.STARTF_USESHOWWINDOW",
                    0x00000001,
                    create=True,
                ),
                patch(
                    "ai_policy_runtime.services.project_context.subprocess.SW_HIDE",
                    0,
                    create=True,
                ),
            ):
                analyzer = ProjectContextAnalyzer(root)
                analyzer._git_working_tree_facts()
                analyzer._git_commit_style_facts()

        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["creationflags"], 0x08000000)
            startup_info = call.kwargs["startupinfo"]
            self.assertEqual(startup_info.dwFlags & 0x00000001, 0x00000001)
            self.assertEqual(startup_info.wShowWindow, 0)
