from __future__ import annotations

from pathlib import Path

import argparse
import json
import subprocess

from codex_worker import (
    find_codex_executable,
)


# ============================================================
# Evidence Store schema
# ============================================================

EVIDENCE_SCHEMA = {
    "type": "object",

    "properties": {

        "research_summary": {
            "type": "string",
        },

        "claims": {
            "type": "array",

            "items": {
                "type": "object",

                "properties": {

                    "claim_id": {
                        "type": "string",
                    },

                    "claim": {
                        "type": "string",
                    },

                    "claim_type": {
                        "type": "string",

                        "enum": [
                            "QUANTITATIVE",
                            "DESCRIPTIVE",
                            "INTERPRETIVE",
                            "LIMITATION",
                        ],
                    },

                    "support_status": {
                        "type": "string",

                        "enum": [
                            "SUPPORTED",
                            "PARTIALLY_SUPPORTED",
                            "UNSUPPORTED",
                        ],
                    },

                    "evidence": {
                        "type": "array",

                        "items": {
                            "type": "object",

                            "properties": {

                                "source_type": {
                                    "type": "string",

                                    "enum": [
                                        "METRIC",
                                        "FIGURE",
                                        "SCRIPT",
                                        "REPORT",
                                        "INPUT",
                                        "REVIEW",
                                    ],
                                },

                                "source_path": {
                                    "type": "string",
                                },

                                "locator": {
                                    "type": "string",
                                },

                                "rationale": {
                                    "type": "string",
                                },
                            },

                            "required": [
                                "source_type",
                                "source_path",
                                "locator",
                                "rationale",
                            ],

                            "additionalProperties": False,
                        },
                    },

                    "limitations": {
                        "type": "array",

                        "items": {
                            "type": "string",
                        },
                    },

                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                },

                "required": [
                    "claim_id",
                    "claim",
                    "claim_type",
                    "support_status",
                    "evidence",
                    "limitations",
                    "confidence",
                ],

                "additionalProperties": False,
            },
        },
    },

    "required": [
        "research_summary",
        "claims",
    ],

    "additionalProperties": False,
}


# ============================================================
# JSON pointer
# ============================================================

def resolve_json_pointer(
    document,
    pointer: str,
):
    """
    Resolve a JSON Pointer such as:

        /annual/global_mean
    """

    if pointer == "":

        return document

    if not pointer.startswith("/"):

        raise ValueError(
            "Metric locator must be a JSON Pointer "
            "starting with '/'."
        )

    current = document

    parts = pointer[1:].split("/")

    for part in parts:

        part = (
            part
            .replace("~1", "/")
            .replace("~0", "~")
        )

        if isinstance(
            current,
            list,
        ):

            current = current[
                int(part)
            ]

        else:

            current = current[
                part
            ]

    return current


# ============================================================
# Deterministic evidence validation
# ============================================================

def validate_evidence_store(
    run_dir: Path,
    evidence_store: dict,
):

    validated_claims = []

    seen_claim_ids = set()

    overall_valid = True


    for claim in evidence_store[
        "claims"
    ]:

        claim_id = claim[
            "claim_id"
        ]

        problems = []

        # ----------------------------------------------------
        # Unique claim IDs
        # ----------------------------------------------------

        if claim_id in seen_claim_ids:

            problems.append(
                "Duplicate claim_id."
            )

        seen_claim_ids.add(
            claim_id
        )


        validated_evidence = []

        valid_metric_count = 0


        # ----------------------------------------------------
        # Validate every evidence reference
        # ----------------------------------------------------

        for reference in claim[
            "evidence"
        ]:

            source_path = (
                run_dir
                / reference[
                    "source_path"
                ]
            ).resolve()

            valid = True

            reference_problem = None

            resolved_value = None


            # Security boundary
            try:

                source_path.relative_to(
                    run_dir
                )

            except ValueError:

                valid = False

                reference_problem = (
                    "Evidence path escapes run directory."
                )


            if (
                valid
                and not source_path.exists()
            ):

                valid = False

                reference_problem = (
                    "Referenced evidence file "
                    "does not exist."
                )


            # ------------------------------------------------
            # Metric evidence:
            # actually resolve the JSON pointer
            # ------------------------------------------------

            if (
                valid
                and reference[
                    "source_type"
                ]
                == "METRIC"
            ):

                try:

                    metric_document = json.loads(
                        source_path.read_text(
                            encoding="utf-8"
                        )
                    )

                    resolved_value = (
                        resolve_json_pointer(
                            metric_document,
                            reference[
                                "locator"
                            ],
                        )
                    )

                    valid_metric_count += 1

                except Exception as error:

                    valid = False

                    reference_problem = (
                        "Metric locator could not "
                        f"be resolved: {error}"
                    )


            validated_reference = dict(
                reference
            )

            validated_reference[
                "reference_valid"
            ] = valid

            validated_reference[
                "resolved_value"
            ] = resolved_value

            validated_reference[
                "validation_problem"
            ] = reference_problem


            validated_evidence.append(
                validated_reference
            )


            if not valid:

                problems.append(
                    f"Invalid evidence reference: "
                    f"{reference['source_path']} "
                    f"{reference['locator']}"
                )


        # ----------------------------------------------------
        # Supported claims must actually have evidence
        # ----------------------------------------------------

        if (
            claim["support_status"]
            in {
                "SUPPORTED",
                "PARTIALLY_SUPPORTED",
            }
            and not claim["evidence"]
        ):

            problems.append(
                "Supported claim has no evidence."
            )


        # ----------------------------------------------------
        # Quantitative supported claims must have
        # at least one machine-verifiable metric.
        # ----------------------------------------------------

        if (
            claim["claim_type"]
            == "QUANTITATIVE"
            and claim["support_status"]
            == "SUPPORTED"
            and valid_metric_count == 0
        ):

            problems.append(
                "Supported quantitative claim has "
                "no valid METRIC evidence."
            )


        claim_valid = (
            len(problems) == 0
        )

        if not claim_valid:

            overall_valid = False


        validated_claim = dict(
            claim
        )

        validated_claim[
            "evidence"
        ] = validated_evidence

        validated_claim[
            "validation"
        ] = {
            "status":
                (
                    "PASS"
                    if claim_valid
                    else "FAIL"
                ),

            "problems":
                problems,
        }


        validated_claims.append(
            validated_claim
        )


    return {
        "validation_status":
            (
                "PASS"
                if overall_valid
                else "FAIL"
            ),

        "research_summary":
            evidence_store[
                "research_summary"
            ],

        "claims":
            validated_claims,
    }


# ============================================================
# Build Evidence Store
# ============================================================

def build_evidence_store(
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


    # ========================================================
    # Only accepted research may enter Evidence Store
    # ========================================================

    cycle_file = (
        run_dir
        / "research_cycle.json"
    )


    if not cycle_file.is_file():

        raise RuntimeError(
            "research_cycle.json missing."
        )


    cycle = json.loads(
        cycle_file.read_text(
            encoding="utf-8"
        )
    )


    if (
        cycle.get("status")
        != "ACCEPTED"
    ):

        raise RuntimeError(
            "Evidence Store can only be built "
            "from an ACCEPTED research run."
        )


    codex = (
        find_codex_executable()
    )


    schema_file = (
        run_dir
        / "evidence_schema.json"
    )

    raw_file = (
        run_dir
        / "evidence_store_raw.json"
    )

    validated_file = (
        run_dir
        / "evidence_store.json"
    )


    schema_file.write_text(
        json.dumps(
            EVIDENCE_SCHEMA,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    # ========================================================
    # Evidence curator prompt
    # ========================================================

    prompt = """
You are the evidence-curation component of an autonomous
scientific research system.

The research run has already passed independent scientific review.

Your job is NOT to create new scientific conclusions.

Your job is to extract the important scientific claims that are
actually supported by this accepted research run and connect each
claim to its evidence.


Inspect:

- analysis_report.md
- results/metrics.json
- scripts/
- figures/
- reviews/
- input/
- research_cycle.json


CLAIM RULES
===========

Create claims only when they are supported by the accepted analysis.

Classify each claim as:

QUANTITATIVE
    Contains an explicit numerical scientific result.

DESCRIPTIVE
    Describes a documented pattern or property.

INTERPRETIVE
    Provides a cautious scientific interpretation.

LIMITATION
    States a limitation or constraint.


EVIDENCE RULES
==============

For every evidence item:

source_path
    Must be a path RELATIVE to the current research-run directory.

locator
    For METRIC evidence, this MUST be a valid JSON Pointer into
    results/metrics.json.

    Examples:

        /annual_mean/2000
        /seasonal/DJF
        /global_mean

    For figures/scripts/reports, use a concise human-readable
    locator such as a figure panel, function name, or section.


For quantitative SUPPORTED claims:

- Prefer results/metrics.json as primary evidence.
- Include at least one METRIC evidence item.
- Figures may be included as secondary evidence.


SCIENTIFIC INTEGRITY
====================

- Do not invent claims.
- Do not invent metric paths.
- Do not create stronger causal language than the report supports.
- Preserve limitations.
- An accepted reviewer verdict does not justify adding new claims.
- Unsupported claims should be marked UNSUPPORTED rather than
  silently omitted if they appear materially in the report.


PURPOSE
=======

The resulting Evidence Store will later constrain an autonomous
manuscript writer. It therefore must prioritize traceability over
rhetorical quality.
"""


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
                raw_file
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
        run_dir
        / "evidence_stdout.log"
    ).write_text(
        process.stdout,
        encoding="utf-8",
    )


    (
        run_dir
        / "evidence_stderr.log"
    ).write_text(
        process.stderr,
        encoding="utf-8",
    )


    if not raw_file.is_file():

        raise RuntimeError(
            "Codex did not produce "
            "evidence_store_raw.json."
        )


    raw_store = json.loads(
        raw_file.read_text(
            encoding="utf-8"
        )
    )


    validated = (
        validate_evidence_store(
            run_dir,
            raw_store,
        )
    )


    validated_file.write_text(
        json.dumps(
            validated,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    return {
        "return_code":
            process.returncode,

        "validation_status":
            validated[
                "validation_status"
            ],

        "claim_count":
            len(
                validated[
                    "claims"
                ]
            ),

        "evidence_store":
            str(
                validated_file
            ),
    }


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    parser = (
        argparse.ArgumentParser()
    )

    parser.add_argument(
        "run_dir"
    )


    args = parser.parse_args()


    result = build_evidence_store(
        args.run_dir
    )


    print()
    print("=" * 70)
    print("EVIDENCE STORE RESULT")
    print("=" * 70)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )