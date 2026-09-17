from __future__ import annotations

from datetime import datetime
from pathlib import Path

import argparse
import hashlib
import json
import shutil
import sys


from codex_worker import (
    run_codex_research_worker,
)

from research_cycle import (
    run_review_cycle,
)

from evidence_store import (
    build_evidence_store,
)

from literature_agent import (
    build_citation_store,
)

from manuscript_writer import (
    write_manuscript,
)

from paper_cycle import (
    run_paper_cycle,
)


# ============================================================
# Paths
# ============================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
)


# ============================================================
# Utilities
# ============================================================

def read_task_file(
    task_file: str | Path,
) -> str:

    task_file = Path(
        task_file
    ).resolve()

    if not task_file.is_file():

        raise FileNotFoundError(
            f"Task file does not exist: "
            f"{task_file}"
        )

    task = task_file.read_text(
        encoding="utf-8"
    ).strip()

    if not task:

        raise ValueError(
            "Research task is empty."
        )

    return task


def write_json(
    path: Path,
    data,
):

    path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )


def sha256_file(
    path: Path,
):

    digest = hashlib.sha256()

    with path.open(
        "rb"
    ) as file:

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
# Save director state progressively
# ============================================================

def save_director_state(
    run_dir: Path,
    state: dict,
):

    write_json(
        run_dir
        / "director_state.json",
        state,
    )


# ============================================================
# Build final accepted package
# ============================================================

def build_final_package(
    run_dir: Path,
):

    final_dir = (
        run_dir
        / "final_package"
    )

    # Clean an old package so it can never contain stale files.
    if final_dir.exists():

        shutil.rmtree(
            final_dir
        )

    final_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    manuscript_dir = (
        run_dir
        / "manuscript"
        / "draft"
    )


    # ========================================================
    # Final manuscript files
    # ========================================================

    manuscript_files = [
        "manuscript.md",
        "manuscript_traceable.md",
        "manuscript_claim_map.json",
        "references.md",
        "title_abstract.md",
        "introduction.md",
        "methods.md",
        "results.md",
        "discussion.md",
        "figure_captions.md",
    ]


    for name in manuscript_files:

        source = (
            manuscript_dir
            / name
        )

        if source.is_file():

            shutil.copy2(
                source,
                final_dir / name,
            )


    # ========================================================
    # Figures
    # ========================================================

    source_figures = (
        run_dir
        / "figures"
    )

    final_figures = (
        final_dir
        / "figures"
    )

    if source_figures.is_dir():

        shutil.copytree(
            source_figures,
            final_figures,
        )


    # ========================================================
    # Reproducible code
    # ========================================================

    source_scripts = (
        run_dir
        / "scripts"
    )

    final_scripts = (
        final_dir
        / "scripts"
    )

    if source_scripts.is_dir():

        shutil.copytree(
            source_scripts,
            final_scripts,
        )


    # ========================================================
    # Scientific results / evidence
    # ========================================================

    result_files = [
        (
            run_dir
            / "results"
            / "metrics.json"
        ),

        (
            run_dir
            / "analysis_report.md"
        ),

        (
            run_dir
            / "evidence_store.json"
        ),

        (
            run_dir
            / "citation_store.json"
        ),

        (
            run_dir
            / "research_cycle.json"
        ),

        (
            run_dir
            / "worker_run.json"
        ),

        (
            run_dir
            / "manuscript"
            / "paper_cycle.json"
        ),

        (
            run_dir
            / "manuscript"
            / "manuscript_validation.json"
        ),
    ]


    support_dir = (
        final_dir
        / "provenance"
    )

    support_dir.mkdir(
        exist_ok=True
    )


    for source in result_files:

        if source.is_file():

            shutil.copy2(
                source,
                support_dir
                / source.name,
            )


    # ========================================================
    # Scientific reviews
    # ========================================================

    research_reviews = (
        run_dir
        / "reviews"
    )

    if research_reviews.is_dir():

        shutil.copytree(
            research_reviews,
            support_dir
            / "scientific_reviews",
        )


    paper_reviews = (
        run_dir
        / "manuscript"
        / "reviews"
    )

    if paper_reviews.is_dir():

        shutil.copytree(
            paper_reviews,
            support_dir
            / "paper_reviews",
        )


    # ========================================================
    # Manifest
    # ========================================================

    files = []

    for path in sorted(
        final_dir.rglob("*")
    ):

        if not path.is_file():
            continue

        # Do not hash the manifest while it is being built.
        if (
            path.name
            == "final_manifest.json"
        ):
            continue

        files.append(
            {
                "path":
                    str(
                        path.relative_to(
                            final_dir
                        )
                    ),

                "size_bytes":
                    path.stat().st_size,

                "sha256":
                    sha256_file(
                        path
                    ),
            }
        )


    manifest = {
        "created_at":
            datetime.now()
            .astimezone()
            .isoformat(
                timespec="seconds"
            ),

        "source_run":
            str(
                run_dir
            ),

        "file_count":
            len(
                files
            ),

        "files":
            files,
    }


    write_json(
        final_dir
        / "final_manifest.json",
        manifest,
    )


    return final_dir


# ============================================================
# Full autonomous research pipeline
# ============================================================

def run_research_director(
    task: str,
    source_files: list[str],
    max_research_revisions: int = 3,
    max_paper_revisions: int = 3,
):

    print()
    print("=" * 78)
    print("FULL RESEARCH DIRECTOR")
    print("=" * 78)

    print()
    print("Research task:")
    print(task)

    print()
    print("Source files:")

    for file_name in source_files:

        print(
            f"  - {file_name}"
        )


    # ========================================================
    # STAGE 1
    # Autonomous research
    # ========================================================

    print()
    print("#" * 78)
    print(
        "STAGE 1 — AUTONOMOUS RESEARCH"
    )
    print("#" * 78)


    worker_result = (
        run_codex_research_worker(
            task=task,
            source_files=source_files,
        )
    )


    run_dir = Path(
        worker_result[
            "run_dir"
        ]
    ).resolve()


    state = {
        "run_id":
            worker_result[
                "run_id"
            ],

        "run_dir":
            str(
                run_dir
            ),

        "status":
            "RUNNING",

        "stages":
            {},
    }


    state["stages"][
        "research"
    ] = worker_result

    save_director_state(
        run_dir,
        state,
    )


    if (
        worker_result[
            "return_code"
        ]
        != 0
    ):

        state["status"] = (
            "RESEARCHER_FAILED"
        )

        save_director_state(
            run_dir,
            state,
        )

        return state


    if (
        worker_result[
            "validation"
        ][
            "status"
        ]
        != "PASS"
    ):

        state["status"] = (
            "RESEARCH_ARTIFACT_FAILURE"
        )

        save_director_state(
            run_dir,
            state,
        )

        return state


    # ========================================================
    # STAGE 2
    # Scientific review / revision
    # ========================================================

    print()
    print("#" * 78)
    print(
        "STAGE 2 — SCIENTIFIC REVIEW"
    )
    print("#" * 78)


    research_cycle = (
        run_review_cycle(
            run_dir=run_dir,
            max_revision_rounds=(
                max_research_revisions
            ),
        )
    )


    state["stages"][
        "scientific_review"
    ] = research_cycle

    save_director_state(
        run_dir,
        state,
    )


    if (
        research_cycle[
            "status"
        ]
        != "ACCEPTED"
    ):

        state["status"] = (
            "SCIENTIFIC_REVIEW_NOT_ACCEPTED"
        )

        save_director_state(
            run_dir,
            state,
        )

        return state


    # ========================================================
    # STAGE 3
    # Evidence Store
    # ========================================================

    print()
    print("#" * 78)
    print(
        "STAGE 3 — EVIDENCE CURATION"
    )
    print("#" * 78)


    evidence_result = (
        build_evidence_store(
            run_dir
        )
    )


    state["stages"][
        "evidence_store"
    ] = evidence_result

    save_director_state(
        run_dir,
        state,
    )


    if (
        evidence_result[
            "validation_status"
        ]
        != "PASS"
    ):

        state["status"] = (
            "EVIDENCE_VALIDATION_FAILED"
        )

        save_director_state(
            run_dir,
            state,
        )

        return state


    # ========================================================
    # STAGE 4
    # Literature + DOI verification
    # ========================================================

    print()
    print("#" * 78)
    print(
        "STAGE 4 — LITERATURE AND "
        "CITATION VERIFICATION"
    )
    print("#" * 78)


    citation_result = (
        build_citation_store(
            run_dir
        )
    )


    state["stages"][
        "citation_store"
    ] = citation_result

    save_director_state(
        run_dir,
        state,
    )


    if (
        citation_result[
            "validation_status"
        ]
        != "PASS"
    ):

        state["status"] = (
            "CITATION_VALIDATION_FAILED"
        )

        save_director_state(
            run_dir,
            state,
        )

        return state


    # ========================================================
    # STAGE 5
    # Manuscript Writer + traceability gate
    # ========================================================

    print()
    print("#" * 78)
    print(
        "STAGE 5 — MANUSCRIPT WRITING"
    )
    print("#" * 78)


    manuscript_result = (
        write_manuscript(
            run_dir
        )
    )


    state["stages"][
        "manuscript"
    ] = manuscript_result

    save_director_state(
        run_dir,
        state,
    )


    if (
        manuscript_result[
            "validation_status"
        ]
        != "PASS"
    ):

        state["status"] = (
            "MANUSCRIPT_TRACEABILITY_FAILED"
        )

        save_director_state(
            run_dir,
            state,
        )

        return state


    # ========================================================
    # STAGE 6
    # Paper review / revision
    # ========================================================

    print()
    print("#" * 78)
    print(
        "STAGE 6 — PAPER REVIEW"
    )
    print("#" * 78)


    paper_cycle = (
        run_paper_cycle(
            run_dir=run_dir,
            max_revisions=(
                max_paper_revisions
            ),
        )
    )


    state["stages"][
        "paper_review"
    ] = paper_cycle

    save_director_state(
        run_dir,
        state,
    )


    if (
        paper_cycle[
            "status"
        ]
        != "ACCEPTED"
    ):

        state["status"] = (
            "PAPER_NOT_ACCEPTED"
        )

        save_director_state(
            run_dir,
            state,
        )

        return state


    # ========================================================
    # STAGE 7
    # Final accepted research package
    # ========================================================

    print()
    print("#" * 78)
    print(
        "STAGE 7 — FINAL PACKAGE"
    )
    print("#" * 78)


    final_dir = (
        build_final_package(
            run_dir
        )
    )


    state[
        "final_package"
    ] = str(
        final_dir
    )


    state[
        "status"
    ] = "ACCEPTED"


    save_director_state(
        run_dir,
        state,
    )


    write_json(
        final_dir
        / "director_summary.json",
        state,
    )


    return state


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "Run the complete autonomous "
            "research-to-manuscript pipeline."
        )
    )


    parser.add_argument(
        "--task-file",
        required=True,
    )


    parser.add_argument(
        "--source",
        nargs="+",
        required=True,
    )


    parser.add_argument(
        "--max-research-revisions",
        type=int,
        default=3,
    )


    parser.add_argument(
        "--max-paper-revisions",
        type=int,
        default=3,
    )


    args = parser.parse_args()


    try:

        task = read_task_file(
            args.task_file
        )


        result = (
            run_research_director(
                task=task,

                source_files=(
                    args.source
                ),

                max_research_revisions=(
                    args.max_research_revisions
                ),

                max_paper_revisions=(
                    args.max_paper_revisions
                ),
            )
        )


    except KeyboardInterrupt:

        print()
        print(
            "Research Director interrupted "
            "by user."
        )

        sys.exit(130)


    except Exception as error:

        print()
        print(
            "FULL RESEARCH DIRECTOR FAILED"
        )

        print(
            f"{type(error).__name__}: "
            f"{error}"
        )

        raise


    print()
    print("=" * 78)
    print(
        "FINAL DIRECTOR RESULT"
    )
    print("=" * 78)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


    if (
        result.get(
            "status"
        )
        == "ACCEPTED"
    ):

        print()
        print(
            "The complete research workflow "
            "passed all acceptance gates."
        )

        print()
        print(
            "FINAL PACKAGE:"
        )

        print(
            result[
                "final_package"
            ]
        )