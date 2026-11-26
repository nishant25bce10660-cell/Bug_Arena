import sys
from pathlib import Path
from bugarena.sandbox.manager import EphemeralSandboxManager
from bugarena.sandbox.runner import run_sandboxed_command

mgr = EphemeralSandboxManager(".")

diff5 = '''--- a/src/bugarena/sandbox/manager.py
+++ b/src/bugarena/sandbox/manager.py
@@ -78,6 +78,6 @@
-            if line.startswith(("--- a/", "--- ")):
+            if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                 # Next line should be +++ b/path
                 target_rel = None
                 if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
-                    target_rel = lines[i + 1][4:].strip()
+                    target_rel = lines[i + 1][4:].split("\\t", 1)[0].strip()
                     target_rel = target_rel.removeprefix("b/")
@@ -101,3 +101,3 @@
-                while i < len(lines) and not (
-                    lines[i].startswith("--- a/") or lines[i].startswith("--- ")
-                ):
+                while i < len(lines) and not (
+                    lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")
+                ):
@@ -108,4 +108,4 @@
                         while (
                             i < len(lines)
                             and not lines[i].startswith("@@")
-                            and not lines[i].startswith("--- ")
+                            and not (lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "))
                         ):'''

diff7 = '''--- a/src/bugarena/tournament/patch_parser.py
+++ b/src/bugarena/tournament/patch_parser.py
@@ -14,3 +14,3 @@
 DIFF_HEADER_PATTERN = re.compile(
-    r"^--- (?:a/)?(?P<old_file>\\S+)\\n\\+\\+\\+ (?:b/)?(?P<new_file>\\S+)", re.MULTILINE
+    r"^--- (?:a/)?(?P<old_file>[^\\t\\r\\n]+?)(?:\\t.*)?\\r?\\n\\+\\+\\+ (?:b/)?(?P<new_file>[^\\t\\r\\n]+?)(?:\\t.*)?$", re.MULTILINE
 )
@@ -32,1 +32,1 @@
-    clean_diff = raw_diff.strip()
+    clean_diff = raw_diff.replace("\\r\\n", "\\n").strip()
@@ -54,6 +54,9 @@
+    in_hunk = False
     for line in clean_diff.splitlines():
-        if line.startswith(("+++", "---", "@@")):
+        if line.startswith("@@"):
+            in_hunk = True
+            continue
+        if not in_hunk and line.startswith(("+++", "---")):
             continue'''

with mgr.create_sandbox() as sb:
    mgr.apply_patch(sb, diff5)
    t5 = sb / "tests/repro/t5.py"; t5.parent.mkdir(parents=True, exist_ok=True)
    t5.write_text(Path("bug_report/evidence/repro/BUG-005_repro.py").read_text(encoding="utf-8"), encoding="utf-8")
    r5 = run_sandboxed_command(sb, [sys.executable, "-m", "pytest", "tests/repro/t5.py", "-q"], env_override={"PYTHONPATH": "."})
    print("DEBUG 5:", r5.exit_code, r5.stdout, r5.stderr)

with mgr.create_sandbox() as sb:
    mgr.apply_patch(sb, diff7)
    t7 = sb / "tests/repro/t7.py"; t7.parent.mkdir(parents=True, exist_ok=True)
    t7.write_text(Path("bug_report/evidence/repro/BUG-007_repro.py").read_text(encoding="utf-8"), encoding="utf-8")
    r7 = run_sandboxed_command(sb, [sys.executable, "-m", "pytest", "tests/repro/t7.py", "-q"], env_override={"PYTHONPATH": "."})
    print("DEBUG 7:", r7.exit_code, r7.stdout, r7.stderr)
