import subprocess

import pytest

from issue_agent.errors import PatchError
from issue_agent.patches import apply_unified_diff, extract_unified_diff, validate_unified_diff

PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-print("bad")
+print("good")
"""


def test_extract_unified_diff_from_markdown():
    text = f"Here is the patch:\n```diff\n{PATCH}```"

    assert extract_unified_diff(text) == PATCH


def test_validate_rejects_explanation():
    with pytest.raises(PatchError):
        validate_unified_diff("change app.py please")


def test_apply_unified_diff(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "app.py").write_text('print("bad")\n', encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=a@example.com", "-c", "user.name=A", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    apply_unified_diff(tmp_path, PATCH)

    assert (tmp_path / "app.py").read_text(encoding="utf-8") == 'print("good")\n'
