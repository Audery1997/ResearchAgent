from __future__ import annotations

from pathlib import Path

import argparse
import json
import re
import shutil
import subprocess

from codex_worker import (
    find_codex_executable,
)


# ============================================================
# Structured manuscript package returned by Codex
# ============================================================

MANUSCRIPT_PACKAGE_SCHEMA = {
    "type": "object",

    "properties": {

        "title": {
            "type": "string",
        },

        "abstract": {
            "type": "string",
        },

        "introduction": {
            "type": "string",
        },

        "methods": {
            "type": "string",
        },

        "results": {
            "type": "string",
        },

        "discussion": {
            "type": "string",
        },

        "figure_captions": {
            "type": "array",

            "items": {
                "type": "object",

                "properties": {

                    "figure_id": {
                        "type": "string",
                    },

                    "caption": {
                        "type": "string",
                    },
                },

                "required": [
                    "figure_id",
                    "caption",
                ],

                "additionalProperties": False,
            },
        },

        "claim_map": {
            "type": "object",

            "properties": {

                "statements": {
                    "type": "array",

                    "items": {
                        "type": "object",

                        "properties": {

                            "section": {
                                "type": "string",
                            },

                            "statement": {
                                "type": "string",
                            },

                            "claim_ids": {
                                "type": "array",

                                "items": {
                                    "type": "string",
                                },
                            },

                            "paper_ids": {
                                "type": "array",

                                "items": {
                                    "type": "string",
                                },
                            },
                        },

                        "required": [
                            "section",
                            "statement",
                            "claim_ids",
                            "paper_ids",
                        ],

                        "additionalProperties": False,
                    },
                },
            },

            "required": [
                "statements",
            ],

            "additionalProperties": False,
        },
    },

    "required": [
        "title",
        "abstract",
        "introduction",
        "methods",
        "results",
        "discussion",
        "figure_captions",
        "claim_map",
    ],

    "additionalProperties": False,
}


# ============================================================
# Utility
# ============================================================

def load_json(
    path: Path,
):

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


# ============================================================
# Build validated claim catalog
# ============================================================

def build_claim_catalog(
    evidence_store: dict,
):

    claims = []

    for claim in evidence_store[
        "claims"
    ]:

        validation = claim.get(
            "validation",
            {}
        )

        # ----------------------------------------------------
        # Only validated claims may reach the writer
        # ----------------------------------------------------

        if (
            validation.get(
                "status"
            )
            != "PASS"
        ):

            continue


        # Unsupported claims must not become manuscript claims
        if (
            claim.get(
                "support_status"
            )
            == "UNSUPPORTED"
        ):

            continue


        claims.append(
            {
                "claim_id":
                    claim[
                        "claim_id"
                    ],

                "claim":
                    claim[
                        "claim"
                    ],

                "claim_type":
                    claim[
                        "claim_type"
                    ],

                "support_status":
                    claim[
                        "support_status"
                    ],

                "limitations":
                    claim.get(
                        "limitations",
                        [],
                    ),

                "confidence":
                    claim.get(
                        "confidence"
                    ),

                "evidence":
                    claim.get(
                        "evidence",
                        [],
                    ),
            }
        )

    return claims


# ============================================================
# Build verified citation catalog
# ============================================================

def build_citation_catalog(
    citation_store: dict,
):

    by_doi = {}


    for claim in citation_store[
        "claims"
    ]:

        claim_id = claim[
            "claim_id"
        ]

        for citation in claim.get(
            "verified_citations",
            [],
        ):

            if not citation.get(
                "verified",
                False,
            ):

                continue


            metadata = citation[
                "metadata"
            ]

            doi = (
                metadata[
                    "doi"
                ]
                .lower()
                .strip()
            )


            if doi not in by_doi:

                by_doi[
                    doi
                ] = {
                    "doi":
                        metadata[
                            "doi"
                        ],

                    "title":
                        metadata[
                            "title"
                        ],

                    "authors":
                        metadata.get(
                            "authors",
                            [],
                        ),

                    "year":
                        metadata.get(
                            "year"
                        ),

                    "journal":
                        metadata.get(
                            "journal",
                            "",
                        ),

                    "url":
                        metadata.get(
                            "url"
                        ),

                    "roles":
                        [],

                    "linked_claim_ids":
                        [],
                }


            role = citation.get(
                "role"
            )

            if (
                role
                and role
                not in by_doi[
                    doi
                ][
                    "roles"
                ]
            ):

                by_doi[
                    doi
                ][
                    "roles"
                ].append(
                    role
                )


            if (
                claim_id
                not in by_doi[
                    doi
                ][
                    "linked_claim_ids"
                ]
            ):

                by_doi[
                    doi
                ][
                    "linked_claim_ids"
                ].append(
                    claim_id
                )


    # ========================================================
    # Assign deterministic paper IDs
    # ========================================================

    papers = []

    for index, doi in enumerate(
        sorted(
            by_doi.keys()
        ),
        start=1,
    ):

        paper = by_doi[
            doi
        ]

        paper[
            "paper_id"
        ] = (
            f"P{index:03d}"
        )

        papers.append(
            paper
        )


    return papers


# ============================================================
# Build deterministic References section
# ============================================================

def build_references_markdown(
    papers: list[dict],
):

    lines = [
        "# References",
        "",
    ]


    for paper in papers:

        authors = paper.get(
            "authors",
            [],
        )

        author_text = (
            ", ".join(
                authors
            )
            if authors
            else "Unknown authors"
        )


        year = (
            paper.get(
                "year"
            )
            or "n.d."
        )


        lines.append(
            (
                f"- **[{paper['paper_id']}]** "
                f"{author_text} ({year}). "
                f"{paper['title']}. "
                f"*{paper.get('journal', '')}*. "
                f"DOI: {paper['doi']}"
            )
        )


    return "\n".join(
        lines
    )


# ============================================================
# Validate manuscript markers
# ============================================================

def validate_manuscript(
    manuscript_dir: Path,
    claims: list[dict],
    papers: list[dict],
):

    problems = []


    traceable_file = (
        manuscript_dir
        / "manuscript_traceable.md"
    )

    claim_map_file = (
        manuscript_dir
        / "manuscript_claim_map.json"
    )


    required_files = [
        "title_abstract.md",
        "introduction.md",
        "methods.md",
        "results.md",
        "discussion.md",
        "figure_captions.md",
        "manuscript_traceable.md",
        "manuscript_claim_map.json",
        "references.md",
    ]


    for name in required_files:

        if not (
            manuscript_dir
            / name
        ).is_file():

            problems.append(
                f"Missing manuscript file: "
                f"{name}"
            )


    if not traceable_file.is_file():

        return {
            "status":
                "FAIL",

            "problems":
                problems,
        }


    text = (
        traceable_file
        .read_text(
            encoding="utf-8"
        )
    )


    valid_claim_ids = {
        claim[
            "claim_id"
        ]
        for claim
        in claims
    }


    valid_paper_ids = {
        paper[
            "paper_id"
        ]
        for paper
        in papers
    }


    # ========================================================
    # Find evidence markers
    #
    # Examples:
    # [C01] or [C001]
    # [P002]
    # ========================================================

    used_claim_ids = set(
        re.findall(
            r"\[(C\d+)\]",
            text,
        )
    )


    # ========================================================
    # A traceable scientific manuscript must actually use
    # validated local claims.
    # ========================================================

    if not used_claim_ids:

        problems.append(
            "Traceable manuscript contains no [Cxxx] "
            "local evidence markers."
        )


    used_paper_ids = set(
        re.findall(
            r"\[(P\d{3})\]",
            text,
        )
    )


    invalid_claims = (
        used_claim_ids
        - valid_claim_ids
    )


    invalid_papers = (
        used_paper_ids
        - valid_paper_ids
    )


    if invalid_claims:

        problems.append(
            "Manuscript uses invalid claim IDs: "
            + ", ".join(
                sorted(
                    invalid_claims
                )
            )
        )


    if invalid_papers:

        problems.append(
            "Manuscript uses unverified paper IDs: "
            + ", ".join(
                sorted(
                    invalid_papers
                )
            )
        )


    # ========================================================
    # Results must use validated, quantitative local evidence.
    # ========================================================

    results_file = (
        manuscript_dir
        / "results.md"
    )


    if results_file.is_file():

        results_text = results_file.read_text(
            encoding="utf-8"
        )

        results_claim_ids = set(
            re.findall(
                r"\[(C\d+)\]",
                results_text,
            )
        )

        if not results_claim_ids:

            problems.append(
                "Results section contains no validated "
                "local Claim IDs."
            )

    else:

        results_claim_ids = set()


    claim_by_id = {
        claim["claim_id"]: claim
        for claim in claims
    }


    quantitative_results_claims = [
        claim_id
        for claim_id
        in results_claim_ids
        if (
            claim_id in claim_by_id
            and claim_by_id[
                claim_id
            ][
                "claim_type"
            ]
            == "QUANTITATIVE"
        )
    ]


    if (
        results_claim_ids
        and not quantitative_results_claims
    ):

        problems.append(
            "Results section uses Claim IDs, "
            "but none correspond to a validated "
            "QUANTITATIVE claim."
        )


    # ========================================================
    # No raw DOI is allowed unless it belongs to catalog
    # ========================================================

    doi_pattern = re.compile(
        r"\b10\.\d{4,9}/"
        r"[-._;()/:A-Za-z0-9]+",
        re.IGNORECASE,
    )


    manuscript_dois = {
        doi.rstrip(
            ".,;)"
        ).lower()
        for doi
        in doi_pattern.findall(
            text
        )
    }


    verified_dois = {
        paper[
            "doi"
        ].lower()
        for paper
        in papers
    }


    unknown_dois = (
        manuscript_dois
        - verified_dois
    )


    if unknown_dois:

        problems.append(
            "Manuscript contains DOI(s) "
            "outside Citation Store: "
            + ", ".join(
                sorted(
                    unknown_dois
                )
            )
        )


    # ========================================================
    # Validate claim map
    # ========================================================

    if claim_map_file.is_file():

        try:

            claim_map = load_json(
                claim_map_file
            )


            statements = claim_map.get(
                "statements",
                [],
            )


            if not statements:

                problems.append(
                    "manuscript_claim_map.json contains "
                    "no traceable manuscript statements."
                )


            mapped_claim_ids = set()
            mapped_paper_ids = set()


            for item in statements:

                section = (
                    item.get(
                        "section",
                        ""
                    )
                    .strip()
                    .lower()
                )

                claim_ids = item.get(
                    "claim_ids",
                    [],
                )

                paper_ids = item.get(
                    "paper_ids",
                    [],
                )

                mapped_claim_ids.update(
                    claim_ids
                )

                mapped_paper_ids.update(
                    paper_ids
                )

                # Results statements should be grounded in
                # local scientific evidence.
                if (
                    section == "results"
                    and not claim_ids
                ):

                    problems.append(
                        "A Results statement in the claim map "
                        "has no local Claim ID."
                    )

                for claim_id in claim_ids:

                    if (
                        claim_id
                        not in valid_claim_ids
                    ):

                        problems.append(
                            "Claim map contains "
                            f"invalid claim ID: "
                            f"{claim_id}"
                        )


                for paper_id in paper_ids:

                    if (
                        paper_id
                        not in valid_paper_ids
                    ):

                        problems.append(
                            "Claim map contains "
                            f"unverified paper ID: "
                            f"{paper_id}"
                        )


            unmapped_manuscript_claims = (
                used_claim_ids
                - mapped_claim_ids
            )


            if unmapped_manuscript_claims:

                problems.append(
                    "Claim IDs appear in the manuscript but "
                    "not in the claim map: "
                    + ", ".join(
                        sorted(
                            unmapped_manuscript_claims
                        )
                    )
                )


            mapped_but_missing_claims = (
                mapped_claim_ids
                - used_claim_ids
            )


            if mapped_but_missing_claims:

                problems.append(
                    "Claim map references Claim IDs that do "
                    "not appear in manuscript_traceable.md: "
                    + ", ".join(
                        sorted(
                            mapped_but_missing_claims
                        )
                    )
                )


        except Exception as error:

            problems.append(
                "manuscript_claim_map.json "
                "is invalid JSON: "
                f"{error}"
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

        "used_claim_ids":
            sorted(
                used_claim_ids
            ),

        "used_paper_ids":
            sorted(
                used_paper_ids
            ),

        "available_claim_count":
            len(
                valid_claim_ids
            ),

        "available_paper_count":
            len(
                valid_paper_ids
            ),
    }


# ============================================================
# Run one structured manuscript-writer attempt
# ============================================================

def run_structured_writer_attempt(
    codex,
    manuscript_root: Path,
    prompt: str,
    attempt: int,
    timeout_seconds: int,
):

    schema_file = (
        manuscript_root
        / "manuscript_package_schema.json"
    )


    output_file = (
        manuscript_root
        / f"writer_package_{attempt:02d}.json"
    )


    if output_file.is_file():

        output_file.unlink()


    schema_file.write_text(
        json.dumps(
            MANUSCRIPT_PACKAGE_SCHEMA,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    command = [
        str(codex),

        "exec",

        "--sandbox",
        "read-only",

        "--output-schema",
        str(schema_file),

        "--output-last-message",
        str(output_file),
    ]


    try:

        process = subprocess.run(
            command,

            cwd=manuscript_root,

            capture_output=True,

            input=prompt,

            text=True,

            encoding="utf-8",

            errors="replace",

            timeout=timeout_seconds,
        )


    except subprocess.TimeoutExpired as error:

        stdout = error.stdout or ""
        stderr = error.stderr or ""


        if isinstance(stdout, bytes):

            stdout = stdout.decode(
                "utf-8",
                errors="replace",
            )


        if isinstance(stderr, bytes):

            stderr = stderr.decode(
                "utf-8",
                errors="replace",
            )


        process = subprocess.CompletedProcess(
            command,
            returncode=124,
            stdout=stdout,
            stderr=(
                stderr
                + "\nStructured writer attempt timed out after "
                f"{timeout_seconds} seconds."
            ),
        )


    (
        manuscript_root
        / f"writer_attempt_{attempt:02d}_stdout.log"
    ).write_text(
        process.stdout,
        encoding="utf-8",
    )


    (
        manuscript_root
        / f"writer_attempt_{attempt:02d}_stderr.log"
    ).write_text(
        process.stderr,
        encoding="utf-8",
    )


    if not output_file.is_file():

        raise RuntimeError(
            "Codex did not produce "
            f"{output_file.name} "
            f"(return code {process.returncode})."
        )


    try:

        package = load_json(
            output_file
        )


    except Exception as error:

        raise RuntimeError(
            "Codex produced an invalid manuscript package: "
            f"{error}"
        ) from error


    return process, package


# ============================================================
# Deterministically materialize the structured manuscript package
# ============================================================

def materialize_manuscript_package(
    package: dict,
    draft_dir: Path,
    references_text: str,
):
    """
    Convert structured manuscript content into manuscript files.
    """

    draft_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    title_abstract = (
        f"# {package['title'].strip()}\n\n"
        "## Abstract\n\n"
        f"{package['abstract'].strip()}\n"
    )


    introduction = (
        "# Introduction\n\n"
        f"{package['introduction'].strip()}\n"
    )


    methods = (
        "# Methods\n\n"
        f"{package['methods'].strip()}\n"
    )


    results = (
        "# Results\n\n"
        f"{package['results'].strip()}\n"
    )


    discussion = (
        "# Discussion\n\n"
        f"{package['discussion'].strip()}\n"
    )


    caption_parts = [
        "# Figure Captions",
        "",
    ]


    for item in package[
        "figure_captions"
    ]:

        caption_parts.extend(
            [
                f"## {item['figure_id'].strip()}",
                "",
                item["caption"].strip(),
                "",
            ]
        )


    figure_captions = "\n".join(
        caption_parts
    )


    files = {
        "title_abstract.md": title_abstract,
        "introduction.md": introduction,
        "methods.md": methods,
        "results.md": results,
        "discussion.md": discussion,
        "figure_captions.md": figure_captions,
        "references.md": references_text,
    }


    for name, content in files.items():

        (
            draft_dir
            / name
        ).write_text(
            content,
            encoding="utf-8",
        )


    (
        draft_dir
        / "manuscript_claim_map.json"
    ).write_text(
        json.dumps(
            package["claim_map"],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    traceable = "\n\n".join(
        [
            title_abstract.strip(),
            introduction.strip(),
            methods.strip(),
            results.strip(),
            discussion.strip(),
            figure_captions.strip(),
        ]
    )


    (
        draft_dir
        / "manuscript_traceable.md"
    ).write_text(
        traceable + "\n",
        encoding="utf-8",
    )


# ============================================================
# Build Manuscript
# ============================================================

def write_manuscript(
    run_dir: str | Path,
    timeout_seconds: int = 3600,
):

    run_dir = Path(
        run_dir
    ).resolve()


    if not run_dir.is_dir():

        raise FileNotFoundError(
            run_dir
        )


    evidence_file = (
        run_dir
        / "evidence_store.json"
    )

    citation_file = (
        run_dir
        / "citation_store.json"
    )


    if not evidence_file.is_file():

        raise RuntimeError(
            "evidence_store.json missing."
        )


    if not citation_file.is_file():

        raise RuntimeError(
            "citation_store.json missing."
        )


    evidence_store = (
        load_json(
            evidence_file
        )
    )

    citation_store = (
        load_json(
            citation_file
        )
    )


    if (
        evidence_store.get(
            "validation_status"
        )
        != "PASS"
    ):

        raise RuntimeError(
            "Evidence Store has not passed "
            "validation."
        )


    if (
        citation_store.get(
            "validation_status"
        )
        != "PASS"
    ):

        raise RuntimeError(
            "Citation Store has not passed "
            "validation."
        )


    # ========================================================
    # Build controlled catalogs
    # ========================================================

    claims = (
        build_claim_catalog(
            evidence_store
        )
    )


    papers = (
        build_citation_catalog(
            citation_store
        )
    )


    # ========================================================
    # Manuscript workspace
    # ========================================================

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


    context_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    draft_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    # ========================================================
    # Save immutable writer context
    # ========================================================

    (
        context_dir
        / "claim_catalog.json"
    ).write_text(
        json.dumps(
            claims,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    (
        context_dir
        / "citation_catalog.json"
    ).write_text(
        json.dumps(
            papers,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    # Accepted analysis report is useful background
    shutil.copy2(
        run_dir
        / "analysis_report.md",
        context_dir
        / "analysis_report.md",
    )


    # Copy final reviewer decision
    reviews = sorted(
        (
            run_dir
            / "reviews"
        ).glob(
            "review_round_*.json"
        )
    )


    if reviews:

        shutil.copy2(
            reviews[-1],
            context_dir
            / "final_scientific_review.json",
        )


    # Figure catalog
    figures = sorted(
        (
            run_dir
            / "figures"
        ).glob(
            "*.png"
        )
    )


    figure_catalog = [
        {
            "figure_id":
                f"F{index:03d}",

            "file":
                path.name,
        }

        for index, path
        in enumerate(
            figures,
            start=1,
        )
    ]


    (
        context_dir
        / "figure_catalog.json"
    ).write_text(
        json.dumps(
            figure_catalog,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    # ========================================================
    # References are NOT generated by LLM
    # ========================================================

    references_text = (
        build_references_markdown(
            papers
        )
    )


    final_review_file = (
        context_dir
        / "final_scientific_review.json"
    )


    final_review_text = (
        final_review_file.read_text(
            encoding="utf-8"
        )
        if final_review_file.is_file()
        else "No final scientific review was provided."
    )


    writer_context = "\n\n".join(
        [
            "VALIDATED CLAIM CATALOG\n"
            + json.dumps(
                claims,
                indent=2,
                ensure_ascii=False,
            ),

            "VERIFIED CITATION CATALOG\n"
            + json.dumps(
                papers,
                indent=2,
                ensure_ascii=False,
            ),

            "ACCEPTED ANALYSIS REPORT\n"
            + (
                context_dir
                / "analysis_report.md"
            ).read_text(
                encoding="utf-8"
            ),

            "FINAL SCIENTIFIC REVIEW\n"
            + final_review_text,

            "FIGURE CATALOG\n"
            + json.dumps(
                figure_catalog,
                indent=2,
                ensure_ascii=False,
            ),
        ]
    )


    # ========================================================
    # Codex writer
    # ========================================================

    codex = (
        find_codex_executable()
    )


    prompt = """
You are the manuscript-writing component of an autonomous
scientific research system.

The underlying analysis has already passed independent scientific
review.

You are NOT allowed to invent new scientific evidence.


AVAILABLE AUTHORITATIVE CONTEXT
===============================

The controller supplies all authoritative scientific context at the end
of this request. Use only that supplied context for manuscript claims.

Do NOT attempt to read or modify workspace files.


OUTPUT CONTRACT
===============

Return one structured manuscript package matching the supplied JSON
schema.

Do NOT create or modify files. The Python controller will
deterministically materialize your structured output into manuscript
files.

Provide every required field: title, abstract, introduction, methods,
results, discussion, figure_captions, and claim_map. Do not include
Markdown section headings in the section fields; the controller adds
them.


CLAIM RULES
===========

Every substantive result derived from the current analysis must be
supported by a Claim ID from claim_catalog.json.

Use inline internal evidence markers:

    [C01]

These markers are for provenance and will later be removed from the
publication version.

TRACEABILITY IS MANDATORY
=========================

The manuscript_traceable.md file MUST contain [Cxxx] markers.

Every Results paragraph that reports or describes a result from the
current analysis must contain at least one valid [Cxxx] marker.

Every sentence containing a quantitative result from the current
analysis must be linked to the corresponding validated Claim ID.

Do not rely on the existence of manuscript_claim_map.json alone.
Claim markers must also appear directly in manuscript_traceable.md.

The Results section must contain validated local Claim IDs. A
manuscript containing only literature [Pxxx] markers is invalid.

Do NOT invent Claim IDs.

Do NOT invent numerical values.

For quantitative statements, use the exact evidence available in the
claim catalog.


CITATION RULES
==============

You may cite ONLY papers listed in citation_catalog.json.

Use the internal citation IDs:

    [P001]

Do NOT cite any other paper.

Do NOT invent authors, years, titles, journals, or DOIs.

Do NOT use your own literature knowledge to add references.

Results specific to the current dataset should normally cite Claim IDs,
not external literature.


SCIENTIFIC WRITING RULES
========================

Write in formal scientific English.

Separate:

- observed evidence;
- interpretation;
- limitations.

Do not convert association into causality.

Do not claim climate trends when the dataset cannot support them.

Do not generalize synthetic-data results to the real climate system.

Preserve caveats from the accepted analysis and review.


SECTION PURPOSES
================

Introduction:
    Motivate the scientific type of analysis using only verified
    literature from the citation catalog.

Methods:
    Describe the actual analysis performed.

Results:
    Report only validated local evidence.

Discussion:
    Interpret cautiously using both validated evidence and verified
    literature.

Figure captions:
    Describe the supplied accepted figures accurately.


CLAIM MAP
=========

Return a non-empty claim_map with structure:

    {
  "statements": [
    {
      "section": "Results",
      "statement": "Exact or concise representation of the manuscript claim",
      "claim_ids": ["C01"],
      "paper_ids": []
    }
  ]
}

A statement may have claim IDs, paper IDs, or both.


Every important Results statement must appear in claim_map with its
corresponding Claim IDs. Use IDs exactly as they appear in the supplied
catalogs.
"""


    prompt += (
        "\n\n"
        "CONTROLLER-SUPPLIED AUTHORITATIVE CONTEXT\n"
        "==========================================\n\n"
        + writer_context
    )


    print()
    print("=" * 70)
    print("CODEX MANUSCRIPT WRITER")
    print("=" * 70)

    print(
        "Manuscript workspace:",
        manuscript_root,
    )

    print()


    max_writer_attempts = 3
    validation = None
    process = None


    for attempt in range(
        1,
        max_writer_attempts + 1,
    ):

        print()
        print(
            f"MANUSCRIPT WRITER ATTEMPT "
            f"{attempt}/{max_writer_attempts}"
        )


        if attempt == 1:

            attempt_prompt = prompt

        else:

            attempt_prompt = (
                prompt
                + "\n\n"
                + """
PREVIOUS ATTEMPT FAILED DETERMINISTIC VALIDATION.

Validation problems:

"""
                + json.dumps(
                    validation["problems"],
                    indent=2,
                    ensure_ascii=False,
                )
                + """

Produce a corrected FULL manuscript package.

Do not return only corrections. Return every required section again.
Pay particular attention to Claim-ID traceability and the claim_map.
"""
            )


        try:

            process, package = run_structured_writer_attempt(
                codex=codex,
                manuscript_root=manuscript_root,
                prompt=attempt_prompt,
                attempt=attempt,
                timeout_seconds=timeout_seconds,
            )


            materialize_manuscript_package(
                package=package,
                draft_dir=draft_dir,
                references_text=references_text,
            )


            # ================================================
            # Deterministic validation after materialization
            # ================================================

            validation = validate_manuscript(
                draft_dir,
                claims,
                papers,
            )


        except Exception as error:

            process = subprocess.CompletedProcess(
                [],
                returncode=1,
                stdout="",
                stderr=str(error),
            )


            validation = {
                "status": "FAIL",
                "problems": [
                    "Structured writer attempt "
                    f"{attempt} failed: {error}"
                ],
            }


        (
            manuscript_root
            / f"manuscript_validation_attempt_{attempt:02d}.json"
        ).write_text(
            json.dumps(
                validation,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


        print()
        print(
            "MANUSCRIPT VALIDATION:",
            validation["status"],
        )


        if (
            validation["status"]
            == "PASS"
        ):

            break


    if (
        validation is None
        or validation["status"] != "PASS"
    ):

        print()
        print(
            "Manuscript writer exhausted repair attempts."
        )


    # Keep the historic log names as aliases for the most recent attempt.
    (
        manuscript_root
        / "writer_stdout.log"
    ).write_text(
        process.stdout,
        encoding="utf-8",
    )


    (
        manuscript_root
        / "writer_stderr.log"
    ).write_text(
        process.stderr,
        encoding="utf-8",
    )


    (
        manuscript_root
        / "manuscript_validation.json"
    ).write_text(
        json.dumps(
            validation,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    # ========================================================
    # Create clean manuscript
    #
    # Remove claim provenance markers only.
    # Keep literature IDs for now.
    # ========================================================

    traceable_file = (
        draft_dir
        / "manuscript_traceable.md"
    )


    clean_file = (
        draft_dir
        / "manuscript.md"
    )


    if (
        validation[
            "status"
        ]
        == "PASS"
        and traceable_file.is_file()
    ):

        text = (
            traceable_file
            .read_text(
                encoding="utf-8"
            )
        )


        clean_text = re.sub(
            r"\s*\[C\d+\]",
            "",
            text,
        )


        clean_text += (
            "\n\n"
            + (
                draft_dir
                / "references.md"
            ).read_text(
                encoding="utf-8"
            )
        )


        clean_file.write_text(
            clean_text,
            encoding="utf-8",
        )


    return {
        "codex_return_code":
            process.returncode,

        "validation_status":
            validation[
                "status"
            ],

        "validation":
            validation,

        "manuscript_root":
            str(
                manuscript_root
            ),

        "manuscript":
            (
                str(
                    clean_file
                )
                if clean_file.is_file()
                else None
            ),
    }


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "run_dir"
    )


    args = parser.parse_args()


    result = write_manuscript(
        args.run_dir
    )


    print()
    print("=" * 70)
    print("MANUSCRIPT WRITER RESULT")
    print("=" * 70)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )
