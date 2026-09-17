from __future__ import annotations

from pathlib import Path

import argparse
import json
import subprocess

from codex_worker import (
    find_codex_executable,
)


# ============================================================
# Structured paper-review schema
# ============================================================

PAPER_REVIEW_SCHEMA = {
    "type": "object",

    "properties": {

        "verdict": {
            "type": "string",
            "enum": [
                "ACCEPT",
                "REVISE",
                "BLOCK",
            ],
        },

        "summary": {
            "type": "string",
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

        "section_reviews": {
            "type": "array",

            "items": {
                "type": "object",

                "properties": {

                    "section": {
                        "type": "string",
                    },

                    "status": {
                        "type": "string",
                        "enum": [
                            "PASS",
                            "REVISE",
                            "BLOCK",
                        ],
                    },

                    "issues": {
                        "type": "array",
                        "items": {
                            "type": "string",
                        },
                    },
                },

                "required": [
                    "section",
                    "status",
                    "issues",
                ],

                "additionalProperties": False,
            },
        },

        "claim_checks": {
            "type": "array",

            "items": {
                "type": "object",

                "properties": {

                    "claim_id": {
                        "type": "string",
                    },

                    "status": {
                        "type": "string",
                        "enum": [
                            "CORRECTLY_USED",
                            "OVERSTATED",
                            "MISREPRESENTED",
                            "NOT_USED",
                        ],
                    },

                    "comment": {
                        "type": "string",
                    },
                },

                "required": [
                    "claim_id",
                    "status",
                    "comment",
                ],

                "additionalProperties": False,
            },
        },

        "citation_checks": {
            "type": "array",

            "items": {
                "type": "object",

                "properties": {

                    "paper_id": {
                        "type": "string",
                    },

                    "status": {
                        "type": "string",
                        "enum": [
                            "APPROPRIATE",
                            "MISPLACED",
                            "OVERSTATED",
                            "NOT_USED",
                        ],
                    },

                    "comment": {
                        "type": "string",
                    },
                },

                "required": [
                    "paper_id",
                    "status",
                    "comment",
                ],

                "additionalProperties": False,
            },
        },

        "figure_text_consistency": {
            "type": "array",

            "items": {
                "type": "object",

                "properties": {

                    "figure_id": {
                        "type": "string",
                    },

                    "status": {
                        "type": "string",
                        "enum": [
                            "CONSISTENT",
                            "PARTIALLY_CONSISTENT",
                            "INCONSISTENT",
                            "NOT_CHECKED",
                        ],
                    },

                    "comment": {
                        "type": "string",
                    },
                },

                "required": [
                    "figure_id",
                    "status",
                    "comment",
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
        "major_issues",
        "minor_issues",
        "required_actions",
        "section_reviews",
        "claim_checks",
        "citation_checks",
        "figure_text_consistency",
        "confidence",
    ],

    "additionalProperties": False,
}


# ============================================================
# Deterministic review consistency check
# ============================================================

def validate_review(
    review: dict,
):

    problems = []

    verdict = review.get(
        "verdict"
    )

    major_issues = review.get(
        "major_issues",
        [],
    )

    required_actions = review.get(
        "required_actions",
        [],
    )

    # ACCEPT must actually mean no major unresolved issue
    if verdict == "ACCEPT":

        if major_issues:

            problems.append(
                "Reviewer returned ACCEPT "
                "while major_issues is non-empty."
            )

        if required_actions:

            problems.append(
                "Reviewer returned ACCEPT "
                "while required_actions is non-empty."
            )

    # REVISE should contain something actionable
    if verdict == "REVISE":

        if (
            not major_issues
            and not required_actions
        ):

            problems.append(
                "Reviewer returned REVISE "
                "without identifying actionable issues."
            )

    # BLOCK should contain a major problem
    if (
        verdict == "BLOCK"
        and not major_issues
    ):

        problems.append(
            "Reviewer returned BLOCK "
            "without a major issue."
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
# Paper reviewer
# ============================================================

def review_manuscript(
    run_dir: str | Path,
    timeout_seconds: int = 2400,
):

    run_dir = Path(
        run_dir
    ).resolve()

    if not run_dir.is_dir():

        raise FileNotFoundError(
            run_dir
        )


    manuscript_root = (
        run_dir
        / "manuscript"
    )

    draft_dir = (
        manuscript_root
        / "draft"
    )

    context_dir = (
        manuscript_root
        / "context"
    )


    traceable = (
        draft_dir
        / "manuscript_traceable.md"
    )

    claim_map = (
        draft_dir
        / "manuscript_claim_map.json"
    )


    if not traceable.is_file():

        raise RuntimeError(
            "manuscript_traceable.md missing."
        )


    if not claim_map.is_file():

        raise RuntimeError(
            "manuscript_claim_map.json missing."
        )


    codex = (
        find_codex_executable()
    )


    review_dir = (
        manuscript_root
        / "reviews"
    )

    review_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    schema_file = (
        review_dir
        / "paper_review_schema.json"
    )

    output_file = (
        review_dir
        / "paper_review_latest.json"
    )


    schema_file.write_text(
        json.dumps(
            PAPER_REVIEW_SCHEMA,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    # ========================================================
    # Reviewer instructions
    # ========================================================

    prompt = """
You are an independent reviewer of a scientific manuscript.

The underlying numerical research has already passed an
independent scientific-analysis review.

Your task is now to evaluate whether the MANUSCRIPT faithfully
and appropriately represents that accepted research.


READ THESE MATERIALS
====================

Manuscript:

manuscript/draft/manuscript_traceable.md

manuscript/draft/manuscript_claim_map.json

manuscript/draft/figure_captions.md


Authoritative evidence:

manuscript/context/claim_catalog.json

manuscript/context/citation_catalog.json

manuscript/context/analysis_report.md

manuscript/context/final_scientific_review.json

manuscript/context/figure_catalog.json


Original research materials may also be inspected:

results/metrics.json
scripts/
figures/


IMPORTANT ROLE SEPARATION
=========================

Do NOT redo the research from scratch unless needed to verify
a manuscript statement.

Do NOT modify any file.

Do NOT reward stylistic fluency if the manuscript overstates
the evidence.


REVIEW DIMENSIONS
=================

1. CLAIM FIDELITY

Check whether each [Cxxx] marker actually supports the
surrounding manuscript statement.

Flag:

- stronger wording than the Claim Store supports;
- causal wording from descriptive evidence;
- numerical mismatches;
- omitted limitations;
- misleading generalizations.


2. CITATION FIDELITY

Check whether each [Pxxx] citation is used for a purpose that
matches the verified citation catalog.

The existence of a real paper does NOT mean it supports every
statement near the citation.

Flag citation overreach or misplaced citations.


3. RESULTS

Every substantive result must be traceable to validated local
claims.

Check numerical values against the Claim Store and, when useful,
results/metrics.json.

Do not permit unsupported quantitative statements.


4. METHODS

Check that Methods describe what was actually done.

Compare against:

analysis_report.md
scripts/

Flag methods that were never performed or important procedures
that are omitted.


5. FIGURES

Check consistency among:

figure captions,
manuscript text,
figure catalog,
figure-generation code,
and available figure files.

Do not infer unsupported visual features merely from file names.


6. ABSTRACT

The Abstract must not make a stronger or broader claim than the
validated Results and Discussion.

It must preserve major limitations.


7. DISCUSSION

Distinguish:

evidence
interpretation
speculation

The Discussion must not generalize synthetic or short-record
results to the real climate system unless validated evidence
supports that generalization.


8. INTERNAL CONSISTENCY

Check consistency among:

Abstract
Introduction
Methods
Results
Discussion
captions

Flag contradictions.


VERDICT
=======

ACCEPT

Use only when there is no major scientific,
traceability, figure-text, citation, or reproducibility
problem requiring correction.

REVISE

Use when the manuscript is fundamentally usable but corrections
are needed.

BLOCK

Use when the manuscript fundamentally misrepresents the accepted
research or violates evidence/citation integrity.


IMPORTANT
=========

Be critical but evidence-based.

Do not invent problems.

Do not modify files.

Return the required structured review.
"""


    print()
    print("=" * 70)
    print("CODEX PAPER REVIEWER")
    print("=" * 70)

    print(
        "Reviewing manuscript:",
        manuscript_root,
    )

    print()


    process = subprocess.run(
        [
            str(codex),

            "exec",

            "--sandbox",
            "read-only",

            "--output-schema",
            str(
                schema_file
            ),

            "--output-last-message",
            str(
                output_file
            ),

            prompt,
        ],

        cwd=run_dir,

        capture_output=True,

        text=True,

        encoding="utf-8",

        errors="replace",

        timeout=timeout_seconds,
    )


    (
        review_dir
        / "paper_reviewer_stdout.log"
    ).write_text(
        process.stdout,
        encoding="utf-8",
    )


    (
        review_dir
        / "paper_reviewer_stderr.log"
    ).write_text(
        process.stderr,
        encoding="utf-8",
    )


    if not output_file.is_file():

        raise RuntimeError(
            "Paper reviewer did not produce "
            "structured review output."
        )


    review = json.loads(
        output_file.read_text(
            encoding="utf-8"
        )
    )


    validation = (
        validate_review(
            review
        )
    )


    final = {
        "codex_return_code":
            process.returncode,

        "review_validation":
            validation,

        "review":
            review,
    }


    (
        review_dir
        / "paper_review_result.json"
    ).write_text(
        json.dumps(
            final,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    return final


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "run_dir"
    )


    args = parser.parse_args()


    result = review_manuscript(
        args.run_dir
    )


    print()
    print("=" * 70)
    print("PAPER REVIEW RESULT")
    print("=" * 70)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )