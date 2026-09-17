from __future__ import annotations

from pathlib import Path

import json
import subprocess

from codex_worker import (
    find_codex_executable,
)

from manuscript_writer import (
    MANUSCRIPT_PACKAGE_SCHEMA,
    build_claim_catalog,
    build_citation_catalog,
    build_references_markdown,
    load_json,
    materialize_manuscript_package,
    validate_manuscript,
)


def revise_manuscript(
    run_dir: str | Path,
    paper_review: dict,
    round_number: int,
    timeout_seconds: int = 3600,
):

    run_dir = Path(
        run_dir
    ).resolve()

    manuscript_root = (
        run_dir
        / "manuscript"
    )

    context_dir = (
        manuscript_root
        / "context"
    )

    draft_dir = (
        manuscript_root
        / "draft"
    )

    revision_dir = (
        manuscript_root
        / "revisions"
        / f"round_{round_number:02d}"
    )

    revision_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    # ========================================================
    # Authoritative stores
    # ========================================================

    evidence_store = load_json(
        run_dir
        / "evidence_store.json"
    )

    citation_store = load_json(
        run_dir
        / "citation_store.json"
    )

    claims = build_claim_catalog(
        evidence_store
    )

    papers = build_citation_catalog(
        citation_store
    )

    references_text = (
        build_references_markdown(
            papers
        )
    )


    # ========================================================
    # Save reviewer instructions
    # ========================================================

    (
        revision_dir
        / "paper_review.json"
    ).write_text(
        json.dumps(
            paper_review,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    # ========================================================
    # Output schema
    # ========================================================

    schema_file = (
        revision_dir
        / "manuscript_package_schema.json"
    )

    output_file = (
        revision_dir
        / "revised_package.json"
    )

    schema_file.write_text(
        json.dumps(
            MANUSCRIPT_PACKAGE_SCHEMA,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    # ========================================================
    # Revision prompt
    # ========================================================

    prompt = f"""
You are revising an evidence-grounded scientific manuscript.

The manuscript has been independently reviewed.

PAPER REVIEW
============

{json.dumps(
    paper_review,
    indent=2,
    ensure_ascii=False
)}


AUTHORITATIVE SOURCES
=====================

Use only:

manuscript/context/claim_catalog.json
manuscript/context/citation_catalog.json
manuscript/context/analysis_report.md
manuscript/context/final_scientific_review.json
manuscript/context/figure_catalog.json

Current manuscript:

manuscript/draft/manuscript_traceable.md
manuscript/draft/manuscript_claim_map.json


YOUR TASK
=========

Produce a COMPLETE revised manuscript package.

Do not return only changed passages.

Address every required_action from the paper review.

Preserve valid parts of the manuscript.

Do not invent:

- numerical results;
- Claim IDs;
- Paper IDs;
- citations;
- scientific mechanisms.


TRACEABILITY
============

Every substantive local result must retain valid [Cxx] markers.

Every quantitative Results statement must be grounded in a
validated Claim ID.

Use only verified [Pxxx] citations.

Return a complete non-empty claim_map.


SCIENTIFIC INTEGRITY
====================

Do not weaken limitations simply to satisfy the reviewer.

Do not turn descriptive evidence into causal claims.

If a reviewer request cannot be satisfied using available evidence,
state that limitation in the manuscript rather than fabricating support.
"""


    codex = (
        find_codex_executable()
    )


    process = subprocess.run(
        [
            str(codex),

            "exec",

            "--sandbox",
            "read-only",

            "--output-schema",
            str(schema_file),

            "--output-last-message",
            str(output_file),

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
        revision_dir
        / "stdout.log"
    ).write_text(
        process.stdout,
        encoding="utf-8",
    )

    (
        revision_dir
        / "stderr.log"
    ).write_text(
        process.stderr,
        encoding="utf-8",
    )


    if not output_file.is_file():

        raise RuntimeError(
            "Manuscript revision produced no structured package."
        )


    package = load_json(
        output_file
    )


    # ========================================================
    # Deterministically write revised manuscript
    # ========================================================

    materialize_manuscript_package(
        package=package,
        draft_dir=draft_dir,
        references_text=(
            references_text
        ),
    )


    # ========================================================
    # Deterministic validation
    # ========================================================

    validation = validate_manuscript(
        manuscript_dir=draft_dir,
        claims=claims,
        papers=papers,
    )


    result = {
        "round":
            round_number,

        "codex_return_code":
            process.returncode,

        "validation":
            validation,
    }


    (
        revision_dir
        / "revision_result.json"
    ).write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    return result