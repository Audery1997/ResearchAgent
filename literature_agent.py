from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import argparse
import difflib
import json
import os
import re
import subprocess
import time

import httpx

from codex_worker import (
    find_codex_executable,
)


# ============================================================
# Literature output schema
# ============================================================

LITERATURE_SCHEMA = {
    "type": "object",

    "properties": {

        "claims": {
            "type": "array",

            "items": {
                "type": "object",

                "properties": {

                    "claim_id": {
                        "type": "string",
                    },

                    "citation_need": {
                        "type": "string",

                        "enum": [
                            "NONE",
                            "BACKGROUND",
                            "METHOD",
                            "CONTEXT",
                            "CONTRAST",
                        ],
                    },

                    "search_queries": {
                        "type": "array",
                        "items": {
                            "type": "string",
                        },
                    },

                    "candidate_papers": {
                        "type": "array",

                        "items": {
                            "type": "object",

                            "properties": {

                                "title": {
                                    "type": "string",
                                },

                                "doi": {
                                    "type": "string",
                                },

                                "journal": {
                                    "type": "string",
                                },

                                "year": {
                                    "type": "integer",
                                },

                                "role": {
                                    "type": "string",

                                    "enum": [
                                        "BACKGROUND",
                                        "METHOD",
                                        "SUPPORT",
                                        "CONTEXT",
                                        "CONTRAST",
                                    ],
                                },

                                "relevance_reason": {
                                    "type": "string",
                                },
                            },

                            "required": [
                                "title",
                                "doi",
                                "journal",
                                "year",
                                "role",
                                "relevance_reason",
                            ],

                            "additionalProperties": False,
                        },
                    },
                },

                "required": [
                    "claim_id",
                    "citation_need",
                    "search_queries",
                    "candidate_papers",
                ],

                "additionalProperties": False,
            },
        },
    },

    "required": [
        "claims",
    ],

    "additionalProperties": False,
}


# ============================================================
# DOI / title normalization
# ============================================================

def normalize_doi(
    doi: str,
) -> str:

    doi = doi.strip()

    doi = re.sub(
        r"^https?://(dx\.)?doi\.org/",
        "",
        doi,
        flags=re.IGNORECASE,
    )

    doi = re.sub(
        r"^doi:\s*",
        "",
        doi,
        flags=re.IGNORECASE,
    )

    return doi.strip()


def normalize_title(
    title: str,
) -> str:

    title = title.lower()

    title = re.sub(
        r"[^a-z0-9]+",
        " ",
        title,
    )

    return " ".join(
        title.split()
    )


def titles_compatible(
    candidate: str,
    authoritative: str,
):

    a = normalize_title(
        candidate
    )

    b = normalize_title(
        authoritative
    )

    similarity = (
        difflib.SequenceMatcher(
            None,
            a,
            b,
        )
        .ratio()
    )

    substring_match = (
        len(a) >= 20
        and len(b) >= 20
        and (
            a in b
            or b in a
        )
    )

    return (
        similarity >= 0.72
        or substring_match,
        similarity,
    )


# ============================================================
# Crossref lookup
# ============================================================

def crossref_lookup(
    doi: str,
    client: httpx.Client,
    max_attempts: int = 4,
):

    doi = normalize_doi(
        doi
    )

    encoded_doi = quote(
        doi,
        safe="",
    )

    url = (
        "https://api.crossref.org/"
        f"works/{encoded_doi}"
    )

    params = {}

    mailto = os.environ.get(
        "CROSSREF_MAILTO"
    )

    if mailto:

        params[
            "mailto"
        ] = mailto


    for attempt in range(
        1,
        max_attempts + 1,
    ):

        try:

            response = client.get(
                url,
                params=params,
            )

            if (
                response.status_code
                == 404
            ):

                return None

            if response.status_code in {
                429,
                500,
                502,
                503,
                504,
            }:

                if (
                    attempt
                    < max_attempts
                ):

                    time.sleep(
                        2 ** attempt
                    )

                    continue

            response.raise_for_status()

            payload = (
                response.json()
            )

            message = payload[
                "message"
            ]

            return message

        except httpx.HTTPError:

            if (
                attempt
                == max_attempts
            ):

                raise

            time.sleep(
                2 ** attempt
            )

    return None


# ============================================================
# Crossref metadata helpers
# ============================================================

def first_item(
    value,
    default=None,
):

    if (
        isinstance(value, list)
        and value
    ):

        return value[0]

    return default


def extract_year(
    record: dict,
):

    for key in [
        "published-print",
        "published-online",
        "published",
        "issued",
    ]:

        value = record.get(
            key
        )

        try:

            return int(
                value[
                    "date-parts"
                ][0][0]
            )

        except Exception:

            continue

    return None


def extract_authors(
    record: dict,
):

    authors = []

    for author in record.get(
        "author",
        [],
    ):

        given = author.get(
            "given",
            ""
        )

        family = author.get(
            "family",
            ""
        )

        name = (
            f"{given} {family}"
            .strip()
        )

        if name:

            authors.append(
                name
            )

    return authors


# ============================================================
# Verify candidate
# ============================================================

def verify_candidate(
    candidate: dict,
    client: httpx.Client,
):

    doi = normalize_doi(
        candidate.get(
            "doi",
            "",
        )
    )

    if not doi:

        return {
            "verified": False,
            "reason":
                "No DOI supplied.",
            "candidate":
                candidate,
        }


    try:

        record = crossref_lookup(
            doi,
            client,
        )

    except Exception as error:

        return {
            "verified": False,

            "reason":
                "Crossref lookup failed: "
                f"{type(error).__name__}: "
                f"{error}",

            "candidate":
                candidate,
        }


    if record is None:

        return {
            "verified": False,

            "reason":
                "DOI was not found in Crossref.",

            "candidate":
                candidate,
        }


    crossref_title = first_item(
        record.get(
            "title"
        ),
        "",
    )


    compatible, similarity = (
        titles_compatible(
            candidate[
                "title"
            ],
            crossref_title,
        )
    )


    if not compatible:

        return {
            "verified": False,

            "reason":
                "DOI exists, but title does "
                "not match the proposed paper.",

            "title_similarity":
                similarity,

            "candidate":
                candidate,

            "crossref_title":
                crossref_title,
        }


    authoritative = {
        "doi":
            record.get(
                "DOI",
                doi,
            ),

        "title":
            crossref_title,

        "authors":
            extract_authors(
                record
            ),

        "year":
            extract_year(
                record
            ),

        "journal":
            first_item(
                record.get(
                    "container-title"
                ),
                "",
            ),

        "publisher":
            record.get(
                "publisher"
            ),

        "type":
            record.get(
                "type"
            ),

        "url":
            record.get(
                "URL"
            ),
    }


    return {
        "verified":
            True,

        "verification_source":
            "Crossref",

        "title_similarity":
            similarity,

        "role":
            candidate[
                "role"
            ],

        "relevance_reason":
            candidate[
                "relevance_reason"
            ],

        "metadata":
            authoritative,
    }


# ============================================================
# Build Citation Store
# ============================================================

def build_citation_store(
    run_dir: str | Path,
    timeout_seconds: int = 1800,
):

    run_dir = Path(
        run_dir
    ).resolve()


    evidence_file = (
        run_dir
        / "evidence_store.json"
    )


    if not evidence_file.is_file():

        raise RuntimeError(
            "evidence_store.json missing."
        )


    evidence_store = json.loads(
        evidence_file.read_text(
            encoding="utf-8"
        )
    )


    if (
        evidence_store.get(
            "validation_status"
        )
        != "PASS"
    ):

        raise RuntimeError(
            "Citation Store requires a "
            "validated Evidence Store."
        )


    codex = (
        find_codex_executable()
    )


    schema_file = (
        run_dir
        / "literature_schema.json"
    )

    raw_file = (
        run_dir
        / "literature_candidates_raw.json"
    )

    citation_file = (
        run_dir
        / "citation_store.json"
    )


    schema_file.write_text(
        json.dumps(
            LITERATURE_SCHEMA,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    # ========================================================
    # Literature Scout
    # ========================================================

    prompt = """
You are the literature-search component of an autonomous
scientific research system.

Read evidence_store.json.

For each scientific claim, decide whether EXTERNAL scholarly
literature is needed.

Important distinction:

- Results specific to the current research run are supported by
  the local Evidence Store. Do NOT search for papers merely to
  "prove" a numerical result generated from this dataset.

- Literature is appropriate for:
  background,
  scientific context,
  methods,
  interpretation,
  comparison with prior work,
  and limitations.


SEARCH REQUIREMENTS
===================

Use live web search.

Prefer:

- peer-reviewed journal papers;
- primary literature when appropriate;
- authoritative review papers for broad context.

Avoid:

- blogs;
- commercial summaries;
- AI-generated citation lists;
- unverifiable manuscripts unless specifically relevant.


DOI REQUIREMENT
===============

For this version of ResearchAgent, only propose papers for which
you can identify a DOI.

Do NOT invent a DOI.

If uncertain, do not include the paper.

Return at most 3 candidate papers per claim.


PRIVACY / SCIENTIFIC INTEGRITY
==============================

Do not search the web using exact unpublished numerical results
from the local research run.

Search using the scientific topic, method, process, or conceptual
context.

Do not strengthen the local claim merely because literature
exists.

The Python controller will independently verify every DOI against
Crossref. Any unverifiable citation will be rejected.
"""


    command = [
        str(codex),

        "exec",

        "--sandbox",
        "read-only",

        "--config",
        'web_search="live"',

        "--output-schema",
        str(
            schema_file
        ),

        "--output-last-message",
        str(
            raw_file
        ),

        prompt,
    ]


    print()
    print("=" * 70)
    print("LITERATURE SCOUT")
    print("=" * 70)

    print(
        "Research run:",
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


    (
        run_dir
        / "literature_stdout.log"
    ).write_text(
        process.stdout,
        encoding="utf-8",
    )


    (
        run_dir
        / "literature_stderr.log"
    ).write_text(
        process.stderr,
        encoding="utf-8",
    )


    if not raw_file.is_file():

        raise RuntimeError(
            "Literature Scout did not "
            "produce candidate output.\n"
            f"Return code: {process.returncode}"
        )


    raw = json.loads(
        raw_file.read_text(
            encoding="utf-8"
        )
    )


    # ========================================================
    # Deterministic DOI verification
    # ========================================================

    headers = {
        "User-Agent":
            "ResearchAgent/0.1 "
            "(scientific literature verification)"
    }


    verified_claims = []

    overall_status = "PASS"


    with httpx.Client(
        timeout=30.0,
        follow_redirects=True,

        # External web requests may intentionally use
        # the user's configured proxy.
        trust_env=True,

        headers=headers,
    ) as client:

        for claim in raw[
            "claims"
        ]:

            verified = []

            rejected = []


            for candidate in claim[
                "candidate_papers"
            ]:

                result = (
                    verify_candidate(
                        candidate,
                        client,
                    )
                )


                if result[
                    "verified"
                ]:

                    verified.append(
                        result
                    )

                else:

                    rejected.append(
                        result
                    )


            citation_need = claim[
                "citation_need"
            ]


            # If literature is declared necessary,
            # require at least one verified paper.
            claim_status = "PASS"

            if (
                citation_need
                != "NONE"
                and not verified
            ):

                claim_status = "FAIL"

                overall_status = "FAIL"


            verified_claims.append(
                {
                    "claim_id":
                        claim[
                            "claim_id"
                        ],

                    "citation_need":
                        citation_need,

                    "search_queries":
                        claim[
                            "search_queries"
                        ],

                    "verification_status":
                        claim_status,

                    "verified_citations":
                        verified,

                    "rejected_candidates":
                        rejected,
                }
            )


    citation_store = {
        "validation_status":
            overall_status,

        "verification_policy":
            {
                "doi_registry":
                    "Crossref",

                "title_match_required":
                    True,

                "minimum_title_similarity":
                    0.72,

                "unverified_citations_allowed":
                    False,
            },

        "claims":
            verified_claims,
    }


    citation_file.write_text(
        json.dumps(
            citation_store,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    return {
        "codex_return_code":
            process.returncode,

        "validation_status":
            overall_status,

        "claim_count":
            len(
                verified_claims
            ),

        "verified_citation_count":
            sum(
                len(
                    claim[
                        "verified_citations"
                    ]
                )
                for claim
                in verified_claims
            ),

        "citation_store":
            str(
                citation_file
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


    result = build_citation_store(
        args.run_dir
    )


    print()
    print("=" * 70)
    print("CITATION STORE RESULT")
    print("=" * 70)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )