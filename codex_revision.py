from __future__ import annotations

from datetime import datetime
from pathlib import Path

import hashlib
import json
import shutil
import subprocess

from codex_worker import (
    find_codex_executable,
    validate_codex_outputs,
)


# ============================================================
# SHA256
# ============================================================

def sha256_file(
    path: Path,
) -> str:

    digest = hashlib.sha256()

    with path.open("rb") as file:

        while True:

            chunk = file.read(
                1024 * 1024
            )

            if not chunk:
                break

            digest.update(
                chunk
            )

    return digest.hexdigest()


# ============================================================
# Check that original scientific inputs were not modified
# ============================================================

def validate_input_integrity(
    run_dir: Path,
):
    """
    Compare current input files against the original
    worker_run.json input manifest.
    """

    metadata_file = (
        run_dir
        / "worker_run.json"
    )

    metadata = json.loads(
        metadata_file.read_text(
            encoding="utf-8"
        )
    )

    manifest = metadata.get(
        "input_manifest",
        [],
    )

    problems = []

    for item in manifest:

        relative_path = item[
            "copied_path"
        ]

        expected_hash = item[
            "sha256"
        ]

        current_file = (
            run_dir
            / relative_path
        )

        if not current_file.is_file():

            problems.append(
                f"Input file disappeared: "
                f"{relative_path}"
            )

            continue

        current_hash = (
            sha256_file(
                current_file
            )
        )

        if (
            current_hash
            != expected_hash
        ):

            problems.append(
                f"Input file was modified: "
                f"{relative_path}"
            )

    return {
        "status":
            (
                "PASS"
                if not problems
                else "FAIL"
            ),

        "problems":
            problems,
    }


# ============================================================
# Snapshot current research state before revision
# ============================================================

def snapshot_before_revision(
    run_dir: Path,
    round_number: int,
):
    """
    Preserve the current analysis before Codex modifies it.
    """

    revisions_dir = (
        run_dir
        / "revisions"
    )

    snapshot_dir = (
        revisions_dir
        / f"round_{round_number:02d}_before"
    )

    snapshot_dir.mkdir(
        parents=True,
        exist_ok=False,
    )


    # --------------------------------------------------------
    # Directories
    # --------------------------------------------------------

    for name in [
        "scripts",
        "figures",
        "results",
    ]:

        source = (
            run_dir
            / name
        )

        if source.exists():

            shutil.copytree(
                source,
                snapshot_dir / name,
            )


    # --------------------------------------------------------
    # Important top-level files
    # --------------------------------------------------------

    for name in [
        "analysis_report.md",
        "review.json",
        "worker_run.json",
    ]:

        source = (
            run_dir
            / name
        )

        if source.is_file():

            shutil.copy2(
                source,
                snapshot_dir / name,
            )


    return snapshot_dir


# ============================================================
# Revision worker
# ============================================================

def revise_codex_run(
    run_dir: str | Path,
    review: dict,
    round_number: int,
    timeout_seconds: int = 3600,
):

    run_dir = Path(
        run_dir
    ).resolve()

    if not run_dir.is_dir():

        raise FileNotFoundError(
            run_dir
        )


    codex = (
        find_codex_executable()
    )


    # ========================================================
    # Preserve pre-revision state
    # ========================================================

    snapshot_dir = (
        snapshot_before_revision(
            run_dir,
            round_number,
        )
    )


    # ========================================================
    # Save reviewer instructions explicitly
    # ========================================================

    review_copy = (
        run_dir
        / "revisions"
        / f"review_round_{round_number:02d}.json"
    )

    review_copy.write_text(
        json.dumps(
            review,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    # ========================================================
    # Revision task
    # ========================================================

    prompt = f"""
You are the revision-stage scientific research coding agent.

Another independent reviewer evaluated your previous analysis.

REVIEW VERDICT
==============

{review.get("verdict")}


REVIEW SUMMARY
==============

{review.get("summary")}


MAJOR ISSUES
============

{json.dumps(
    review.get("major_issues", []),
    indent=2,
    ensure_ascii=False
)}


MINOR ISSUES
============

{json.dumps(
    review.get("minor_issues", []),
    indent=2,
    ensure_ascii=False
)}


REQUIRED ACTIONS
================

{json.dumps(
    review.get("required_actions", []),
    indent=2,
    ensure_ascii=False
)}


YOUR TASK
=========

Revise the existing research analysis to address the reviewer.

You may inspect and modify:

- scripts/
- figures/
- results/
- analysis_report.md

You MUST:

1. Address every reviewer required_action that is technically
   possible with the available data.

2. Correct the underlying analysis/code rather than merely
   editing prose.

3. Re-run modified analysis scripts.

4. Regenerate affected figures.

5. Update results/metrics.json if numerical results change.

6. Update analysis_report.md so that it accurately reflects
   the revised analysis.

7. Preserve reproducibility.

8. Do NOT weaken or remove caveats simply to satisfy the
   reviewer.


INPUT DATA PROTECTION
=====================

Files under input/ are immutable scientific source data.

DO NOT modify, rename, replace, or delete anything under input/.


SCIENTIFIC INTEGRITY
====================

- Never invent results.
- Never claim a correction was made unless the code/output
  actually reflects it.
- Preserve units.
- Distinguish evidence from interpretation.
- Do not hide unresolved reviewer concerns.


COMPLETION CONDITION
====================

Do not finish until:

- all revised scripts run successfully;
- affected figures have been regenerated;
- metrics.json is valid;
- analysis_report.md is updated;
- reviewer actions have been addressed or explicitly identified
  as unresolved.
"""


    print()
    print("=" * 70)
    print(
        f"CODEX REVISION WORKER — ROUND {round_number}"
    )
    print("=" * 70)

    print(
        "Research run:",
        run_dir,
    )

    print(
        "Snapshot:",
        snapshot_dir,
    )

    print()


    process = subprocess.run(
        [
            str(codex),

            "exec",

            "--sandbox",
            "workspace-write",

            prompt,
        ],

        cwd=run_dir,

        capture_output=True,

        text=True,

        encoding="utf-8",

        errors="replace",

        timeout=timeout_seconds,
    )


    # ========================================================
    # Save revision logs
    # ========================================================

    revision_dir = (
        run_dir
        / "revisions"
    )

    (
        revision_dir
        / f"revision_round_{round_number:02d}_stdout.log"
    ).write_text(
        process.stdout,
        encoding="utf-8",
    )

    (
        revision_dir
        / f"revision_round_{round_number:02d}_stderr.log"
    ).write_text(
        process.stderr,
        encoding="utf-8",
    )


    # ========================================================
    # Deterministic checks after revision
    # ========================================================

    artifact_validation = (
        validate_codex_outputs(
            run_dir
        )
    )

    input_integrity = (
        validate_input_integrity(
            run_dir
        )
    )


    result = {
        "round":
            round_number,

        "codex_return_code":
            process.returncode,

        "artifact_validation":
            artifact_validation,

        "input_integrity":
            input_integrity,
    }


    result_file = (
        revision_dir
        / f"revision_round_{round_number:02d}_result.json"
    )

    result_file.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    return result