"""
Validation tests for all output_redirection permissions.

Tests every redirection pattern (> >> &> >& 2>&1 2&>) against
allow/ask/deny policies, including mixed redirections and object-form
per-kind policies.  Outcomes are documented in comments so the plan
can be updated from this file's results.

Compare against TS version at ../jftlo/lovely-devin-permissions/.
"""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_test(command: str) -> dict:
    """Run `lovely-devin-permissions --test` and return parsed JSON."""
    env = os.environ.copy()
    env["DEVIN_PROJECT_DIR"] = str(ROOT)
    r = subprocess.run(
        ["uv", "run", "python", "-m", "lovely_bash_permissions.devin_cli", "--test", command],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    return json.loads(r.stdout) if r.stdout.strip() else {"error": r.stderr}


def run_test_with_config(command: str, config: dict) -> dict:
    """Test a command under an ad-hoc config written to .devin/."""
    d = ROOT / ".devin"
    d.mkdir(exist_ok=True)
    (d / "lovely-permissions.local.jsonc").write_text(json.dumps(config))
    try:
        return run_test(command)
    finally:
        (d / "lovely-permissions.local.jsonc").unlink(missing_ok=True)


# ── helper ───────────────────────────────────────────────
def summary(r: dict) -> str:
    d = r.get("decision", "??")
    hook = r.get("hookSpecificOutput", {})
    inp = hook.get("updatedInput", {}).get("command", "")
    # extract label text between [♡ perms:  and ]
    label = ""
    if "perms:" in inp:
        a = inp.index("perms:") + 7
        b = inp.index("]", a)
        label = inp[a:b]
    return f"{d} ({label})"


# ── 1. Basic patterns under default config (object-form with per-kind allow) ──
# Current effective config: output_redirection = {"*":"ask", "stderr_to_dev_null":"allow", "stderr_to_stdout":"allow"}
# So only non-special redirs (stdout_to_dev_null, other) should ask; stderr variants auto-allow.

BASIC_PATTERNS = [
    # (description, command)
    ("simple stdout >", "echo hi > /tmp/out.txt"),
    ("append >>", "echo hi >> /tmp/out.txt"),
    ("&> both (shfmt &>)", "echo hi &> /tmp/out.txt"),
    (">& both (bash >&)", "echo hi >& /tmp/out.txt"),
    ("2>&1 stderr-to-stdout", "echo hi 2>&1"),
    ("2> stderr to file", "echo hi 2> /tmp/err.txt"),
    ("2>> stderr append", "echo hi 2>> /tmp/err.txt"),
    ("&>> both-append (shfmt &>>)", "echo hi &>> /tmp/out.txt"),
    (">&> both-append (bash >&>)", "echo hi >&> /tmp/out.txt"),
    ("pipe + redirect", "ls -la | grep txt > /tmp/out.txt"),
    ("no redirection (baseline)", "ls -la"),
]

print("=" * 72)
print("STEP 3: Output redirection validation")
print("=" * 72)
print(
    "\nDefault config (from global): output_redirection = {'*':'ask', 'stderr_to_dev_null':'allow', 'stderr_to_stdout':'allow'}"
)
print("Expected: non-special redirs → ask;  stderr-to-stdout / stderr-to-null → auto-allow\n")

results = []
for desc, cmd in BASIC_PATTERNS:
    r = run_test(cmd)
    s = summary(r)
    results.append((desc, cmd, s))
    ok = "auto-approved" in s.lower() or "allowed" in s.lower()
    mark = "✓" if ok else "?"
    print(f"  {mark} {desc:40s} → {s}")

# ── 2. Mixed redirections (both stdout & stderr) ──
print("\n--- Mixed redirections ---")
MIXED = [
    ("stdout+stderr same target (2>&1 after >)", "echo hi > /tmp/out.txt 2>&1"),
    ("stderr redirect then stdout", "echo hi 2> /tmp/err.txt > /tmp/out.txt"),
    ("&> then &1", "echo hi &> /dev/null"),
]
for desc, cmd in MIXED:
    r = run_test(cmd)
    s = summary(r)
    results.append((desc, cmd, s))
    print(f"  ? {desc:40s} → {s}")

# ── 3. Object-form policies: deny all, allow all, mixed per-kind ──
print("\n--- Object-form policies ---")

POLICIES = [
    ("deny-all", {"*": "allow", "output_redirection": {"*": "deny"}}),
    ("allow-all", {"*": "allow", "output_redirection": {"*": "allow"}}),
    (
        "per-kind deny stderr_to_dev_null",
        {"*": "allow", "output_redirection": {"*": "ask", "stderr_to_dev_null": "deny"}},
    ),
    ("per-kind deny stderr_to_stdout", {"*": "allow", "output_redirection": {"*": "ask", "stderr_to_stdout": "deny"}}),
    (
        "per-kind deny stdout_to_dev_null",
        {"*": "allow", "output_redirection": {"*": "ask", "stdout_to_dev_null": "deny"}},
    ),
    (
        "per-kind deny all three",
        {
            "*": "allow",
            "output_redirection": {
                "*": "ask",
                "stderr_to_dev_null": "deny",
                "stderr_to_stdout": "deny",
                "stdout_to_dev_null": "deny",
            },
        },
    ),
]

for label, cfg in POLICIES:
    print(f"\n  Policy: {label} = {json.dumps(cfg['output_redirection'])}")
    for desc, cmd in [
        ("redir", "echo hi > /tmp/out.txt"),
        ("stderr-null", "echo hi 2> /dev/null"),
        ("stderr-stdout", "echo hi 2>&1"),
    ]:
        r = run_test_with_config(cmd, cfg)
        s = summary(r)
        results.append((f"{label} / {desc}", cmd, s))
        print(f"    {desc:24s} → {s}")

# ── 4. Compare with TS version ──
print("\n--- Comparison with TS version ---")
TS_PATH = Path("../jftlo/lovely-devin-permissions/dist/hook.js")
if TS_PATH.exists():
    for desc, cmd in [
        ("> stdout", "echo hi > /tmp/out.txt"),
        ("2> null", "echo hi 2> /dev/null"),
        ("2>&1", "echo hi 2>&1"),
    ]:
        env = os.environ.copy()
        env["DEVIN_PROJECT_DIR"] = str(ROOT)
        r_py = run_test(cmd)
        ts_r = subprocess.run(
            ["node", str(TS_PATH), "--test", cmd],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=False,
        )
        py_status = r_py.get("decision", "?") if isinstance(r_py, dict) else "?"
        ts_status = json.loads(ts_r.stdout).get("decision", "?") if ts_r.stdout.strip() else "?"
        match = "✓" if py_status == ts_status else "✗ MISMATCH"
        results.append((f"TS compare {desc}", cmd, f"Py:{py_status} vs TS:{ts_status} {match}"))
        print(f"  {match} {desc:24s} Py:{py_status} vs TS:{ts_status}")
else:
    print("  (TS hook.js not found, skipping comparison)")

# ── Summary table ──
print("\n" + "=" * 72)
print("FULL RESULTS TABLE")
print("=" * 72)
for desc, cmd, status in results:
    print(f"  {desc:48s} → {status}")
