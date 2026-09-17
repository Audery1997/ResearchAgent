from __future__ import annotations

from pathlib import Path

import argparse
import json

from paper_reviewer import (
    review_manuscript,
)

from manuscript_revision import (
    revise_manuscript,
)


def run_paper_cycle(
    run_dir: str | Path,
    max_revisions: int = 3,
):

    run_dir = Path(
        run_dir
    ).resolve()

    history = []


    for round_number in range(
        1,
        max_revisions + 2,
    ):

        print()
        print("#" * 70)
        print(
            f"PAPER REVIEW ROUND {round_number}"
        )
        print("#" * 70)


        # ====================================================
        # Review
        # ====================================================

        result = review_manuscript(
            run_dir
        )

        review = result[
            "review"
        ]

        verdict = review[
            "verdict"
        ]


        print()
        print(
            "VERDICT:",
            verdict
        )

        print(
            "SUMMARY:",
            review[
                "summary"
            ]
        )


        history.append(
            {
                "round":
                    round_number,

                "verdict":
                    verdict,

                "summary":
                    review[
                        "summary"
                    ],
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
            > max_revisions
        ):

            final_status = (
                "REVISION_LIMIT_REACHED"
            )

            break


        # ====================================================
        # Revision
        # ====================================================

        revision = revise_manuscript(
            run_dir=run_dir,
            paper_review=review,
            round_number=(
                round_number
            ),
        )


        if (
            revision[
                "validation"
            ][
                "status"
            ]
            != "PASS"
        ):

            final_status = (
                "REVISION_VALIDATION_FAILED"
            )

            break


    summary = {
        "status":
            final_status,

        "history":
            history,

        "max_revisions":
            max_revisions,
    }


    (
        run_dir
        / "manuscript"
        / "paper_cycle.json"
    ).write_text(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    return summary


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "run_dir"
    )

    parser.add_argument(
        "--max-revisions",
        type=int,
        default=3,
    )


    args = parser.parse_args()


    result = run_paper_cycle(
        args.run_dir,
        max_revisions=(
            args.max_revisions
        ),
    )


    print()
    print("=" * 70)
    print("FINAL PAPER CYCLE")
    print("=" * 70)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )