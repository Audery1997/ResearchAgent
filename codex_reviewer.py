from __future__ import annotations

from pathlib import Path

import argparse
import json
import subprocess

from codex_worker import (
    find_codex_executable,
)


# ============================================================
# Structured reviewer output
# ============================================================

REVIEW_SCHEMA = {
    "type": "object",

    "properties": {

        "verdict": {
            "type": "string",
            "enum": [
                "ACCEPT",
                "REVISE",
                "NEW_ANALYSIS",
                "BLOCK",
            ],
        },

        "summary": {
            "type": "string",
        },

        "strengths": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },

        "major_issues": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },

        "minor_issues": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },

        "required_actions": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },

        "claims_checked": {
            "type": "array",

            "items": {
                "type": "object",

                "properties": {

                    "claim": {
                        "type": "string",
                    },

                    "status": {
                        "type": "string",
                        "enum": [
                            "SUPPORTED",
                            "PARTIALLY_SUPPORTED",
                            "UNSUPPORTED",
                            "NOT_CHECKED",
                        ],
                    },

                    "evidence": {
                        "type": "string",
                    },
                },

                "required": [
                    "claim",
                    "status",
                    "evidence",
                ],

                "additionalProperties": False,
            },
        },

        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
    },

    "required": [
        "verdict",
        "summary",
        "strengths",
        "major_issues",
        "minor_issues",
        "required_actions",
        "claims_checked",
        "confidence",
    ],

    "additionalProperties": False,
}


# ============================================================
# Review one Codex research run
# ============================================================

def review_codex_run(
    run_dir: str | Path,
    timeout_seconds: int = 1800,
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

    schema_file = (
        run_dir
        / "review_schema.json"
    )

    review_file = (
        run_dir
        / "review.json"
    )

    stdout_file = (
        run_dir
        / "reviewer_stdout.log"
    )

    stderr_file = (
        run_dir
        / "reviewer_stderr.log"
    )


    # ========================================================
    # Save reviewer schema
    # ========================================================

    schema_file.write_text(
        json.dumps(
            REVIEW_SCHEMA,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    # ========================================================
    # Reviewer instructions
    # ========================================================

    prompt = """
You are an independent scientific reviewer.

You are reviewing a research analysis produced by another
autonomous coding agent.

You MUST NOT modify any files.

Inspect the available materials, especially:

- TASK.md
- input/
- scripts/
- results/metrics.json
- analysis_report.md
- worker_run.json
- figure files and figure-generation code

Your job is NOT to praise the work.

Your job is to determine whether the scientific analysis is
numerically supported, reproducible, internally consistent,
and appropriately interpreted.


REVIEW REQUIREMENTS
===================

Check at least the following:

1. DATA / METADATA

- Were the actual input data inspected?
- Are dimensions and units handled correctly?
- Are coordinate conventions understood correctly?


2. NUMERICAL METHODS

- Are spatial weights appropriate?
- Are temporal means or anomalies computed correctly?
- Are NaNs and missing data treated sensibly?
- Are quantities compared with compatible units?
- Are reported numbers traceable to executed code?


3. CODE / REPRODUCIBILITY

- Do the scripts actually reproduce the reported metrics?
- Are methods hard-coded incorrectly?
- Are there hidden assumptions?
- Is the workflow reproducible from the supplied input?


4. FIGURES

- Check the figure-generation code.
- Check whether figure descriptions match what the code
  actually plots.
- Do not claim visual properties that you cannot directly
  verify from available evidence.


5. SCIENTIFIC INTERPRETATION

- Separate evidence from interpretation.
- Flag causal claims unsupported by the dataset.
- Flag conclusions that go beyond the available variables,
  timescale, or experiment design.


6. REPORT CONSISTENCY

Cross-check important quantitative claims in
analysis_report.md against:

- results/metrics.json
- executed analysis code
- available data-derived results


VERDICT DEFINITIONS
===================

ACCEPT
    No major scientific or reproducibility problem was found.

REVISE
    The overall analysis is usable, but one or more important
    issues must be corrected.

NEW_ANALYSIS
    Additional analysis is necessary before the scientific
    question can be addressed adequately.

BLOCK
    The analysis contains a fundamental numerical,
    provenance, or scientific integrity problem.


IMPORTANT
=========

Do not invent problems.

Do not assume a numerical result is correct merely because
it appears in the report.

Do not modify files.

Return the required structured review.
"""


    # ========================================================
    # Run reviewer in read-only mode
    # ========================================================

    command = [
        str(codex),

        "exec",

        "--sandbox",
        "read-only",

        "--output-schema",
        str(schema_file),

        "--output-last-message",
        str(review_file),

        prompt,
    ]


    print()
    print("=" * 70)
    print("CODEX SCIENTIFIC REVIEWER")
    print("=" * 70)

    print(
        "Reviewing:",
        run_dir,
    )

    print()


    process = subprocess.run(
        command,

        cwd=run_dir,

        capture_output=True,

        text=True,

        encoding="utf-8",

        errors="replace",

        timeout=timeout_seconds,
    )


    stdout_file.write_text(
        process.stdout,
        encoding="utf-8",
    )

    stderr_file.write_text(
        process.stderr,
        encoding="utf-8",
    )


    # ========================================================
    # Parse structured review
    # ========================================================

    if not review_file.is_file():

        raise RuntimeError(
            "Codex reviewer did not produce review.json.\n"
            f"Return code: {process.returncode}\n"
            f"stderr:\n{process.stderr[-3000:]}"
        )


    review = json.loads(
        review_file.read_text(
            encoding="utf-8"
        )
    )


    return {
        "return_code":
            process.returncode,

        "review_file":
            str(review_file),

        "review":
            review,
    }


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "run_dir",
        help=(
            "Path to a Codex research run directory."
        ),
    )

    args = parser.parse_args()


    result = review_codex_run(
        args.run_dir
    )


    print()
    print("=" * 70)
    print("REVIEW RESULT")
    print("=" * 70)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )