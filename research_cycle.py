from __future__ import annotations

from pathlib import Path

import argparse
import json

from codex_reviewer import (
    review_codex_run,
)

from codex_revision import (
    revise_codex_run,
)


# ============================================================
# Researcher <-> Reviewer loop
# ============================================================

def run_review_cycle(
    run_dir: str | Path,
    max_revision_rounds: int = 3,
):

    run_dir = Path(
        run_dir
    ).resolve()


    history = []


    for round_number in range(
        1,
        max_revision_rounds + 2,
    ):

        print()
        print("#" * 70)
        print(
            f"SCIENTIFIC REVIEW ROUND {round_number}"
        )
        print("#" * 70)


        # ====================================================
        # Independent review
        # ====================================================

        review_result = (
            review_codex_run(
                run_dir
            )
        )

        review = (
            review_result[
                "review"
            ]
        )


        # ----------------------------------------------------
        # Archive review
        # ----------------------------------------------------

        reviews_dir = (
            run_dir
            / "reviews"
        )

        reviews_dir.mkdir(
            parents=True,
            exist_ok=True,
        )


        archived_review = (
            reviews_dir
            / f"review_round_{round_number:02d}.json"
        )

        archived_review.write_text(
            json.dumps(
                review,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


        verdict = review[
            "verdict"
        ]


        print()
        print(
            "VERDICT:",
            verdict,
        )

        print()

        print(
            "SUMMARY:",
            review["summary"],
        )


        history.append(
            {
                "round":
                    round_number,

                "verdict":
                    verdict,

                "review_file":
                    str(
                        archived_review
                    ),
            }
        )


        # ====================================================
        # ACCEPT
        # ====================================================

        if verdict == "ACCEPT":

            final_status = (
                "ACCEPTED"
            )

            break


        # ====================================================
        # BLOCK
        # ====================================================

        if verdict == "BLOCK":

            final_status = (
                "BLOCKED"
            )

            break


        # ====================================================
        # Revision limit
        # ====================================================

        if (
            round_number
            > max_revision_rounds
        ):

            final_status = (
                "REVISION_LIMIT_REACHED"
            )

            break


        # ====================================================
        # REVISE / NEW_ANALYSIS
        # ====================================================

        if verdict in {
            "REVISE",
            "NEW_ANALYSIS",
        }:

            revision_result = (
                revise_codex_run(
                    run_dir=run_dir,
                    review=review,
                    round_number=(
                        round_number
                    ),
                )
            )


            # ------------------------------------------------
            # Input files MUST remain unchanged
            # ------------------------------------------------

            if (
                revision_result[
                    "input_integrity"
                ][
                    "status"
                ]
                != "PASS"
            ):

                print()
                print(
                    "INPUT INTEGRITY FAILURE"
                )

                final_status = (
                    "BLOCKED_INPUT_MODIFICATION"
                )

                break


            # ------------------------------------------------
            # Revised artifact contract must still pass
            # ------------------------------------------------

            if (
                revision_result[
                    "artifact_validation"
                ][
                    "status"
                ]
                != "PASS"
            ):

                print()
                print(
                    "REVISED ARTIFACT "
                    "VALIDATION FAILED"
                )

                final_status = (
                    "BLOCKED_ARTIFACT_FAILURE"
                )

                break


            # continue to next review
            continue


        # ====================================================
        # Unknown verdict
        # ====================================================

        final_status = (
            "UNKNOWN_VERDICT"
        )

        break


    # ========================================================
    # Save overall cycle
    # ========================================================

    summary = {
        "status":
            final_status,

        "history":
            history,

        "max_revision_rounds":
            max_revision_rounds,
    }


    (
        run_dir
        / "research_cycle.json"
    ).write_text(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    return summary


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

    parser.add_argument(
        "--max-revisions",
        type=int,
        default=3,
    )


    args = parser.parse_args()


    result = run_review_cycle(
        run_dir=args.run_dir,
        max_revision_rounds=(
            args.max_revisions
        ),
    )


    print()
    print("=" * 70)
    print("FINAL RESEARCH CYCLE")
    print("=" * 70)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )