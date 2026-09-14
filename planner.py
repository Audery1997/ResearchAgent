from typing import (
    Annotated,
    Literal,
    Union,
)

from pydantic import (
    BaseModel,
    Field,
    model_validator,
)

from config import (
    MODEL,
    client,
)


# ============================================================
# Exact argument schemas
# ============================================================

class ListResearchFilesArgs(BaseModel):
    folder: str = "."


class InspectNetCDFArgs(BaseModel):
    file_path: str


class AreaWeightedMeanArgs(BaseModel):
    file_path: str
    variable: str
    lat_min: float
    lat_max: float


class SubtractStepResultsArgs(BaseModel):
    """
    References two previously completed plan steps.
    """

    left_step_id: int
    right_step_id: int

    result_field: Literal[
        "temporal_mean_of_spatial_mean"
    ] = "temporal_mean_of_spatial_mean"

    left_label: str = "left"
    right_label: str = "right"


# ============================================================
# Base plan step
# ============================================================

class StepBase(BaseModel):

    step_id: int

    purpose: str

    depends_on: list[int] = Field(
        default_factory=list
    )


# ============================================================
# Concrete plan steps
# ============================================================

class ListResearchFilesStep(StepBase):

    tool_name: Literal[
        "list_research_files"
    ]

    arguments: ListResearchFilesArgs


class InspectNetCDFStep(StepBase):

    tool_name: Literal[
        "inspect_netcdf"
    ]

    arguments: InspectNetCDFArgs


class AreaWeightedMeanStep(StepBase):

    tool_name: Literal[
        "area_weighted_mean"
    ]

    arguments: AreaWeightedMeanArgs


class SubtractStepResultsStep(StepBase):

    tool_name: Literal[
        "subtract_step_results"
    ]

    arguments: SubtractStepResultsArgs


# ============================================================
# Discriminated union
# ============================================================

PlanStep = Annotated[
    Union[
        ListResearchFilesStep,
        InspectNetCDFStep,
        AreaWeightedMeanStep,
        SubtractStepResultsStep,
    ],
    Field(
        discriminator="tool_name"
    ),
]


# ============================================================
# Research plan
# ============================================================

class ResearchPlan(BaseModel):

    goal: str

    steps: list[PlanStep]

    expected_output: str


    @model_validator(
        mode="after"
    )
    def validate_dag(self):

        step_ids = [
            step.step_id
            for step in self.steps
        ]

        # Require simple sequential IDs:
        # 1, 2, 3, ...
        expected_ids = list(
            range(
                1,
                len(step_ids) + 1,
            )
        )

        if step_ids != expected_ids:

            raise ValueError(
                "step_id values must be sequential "
                "starting from 1."
            )

        valid_ids = set(
            step_ids
        )

        for step in self.steps:

            # -----------------------------------------------
            # Dependencies must exist and point backward.
            # This guarantees an acyclic plan.
            # -----------------------------------------------

            for dependency in step.depends_on:

                if dependency not in valid_ids:

                    raise ValueError(
                        f"Step {step.step_id} depends on "
                        f"unknown step {dependency}."
                    )

                if dependency >= step.step_id:

                    raise ValueError(
                        f"Step {step.step_id} has an "
                        "invalid forward/self dependency."
                    )

            # -----------------------------------------------
            # A derived difference must depend on both
            # source steps that it references.
            # -----------------------------------------------

            if (
                step.tool_name
                == "subtract_step_results"
            ):

                required = {
                    step.arguments.left_step_id,
                    step.arguments.right_step_id,
                }

                declared = set(
                    step.depends_on
                )

                if not required.issubset(
                    declared
                ):

                    raise ValueError(
                        "subtract_step_results must "
                        "depend on both referenced steps."
                    )

        return self


# ============================================================
# Planner prompt
# ============================================================

PLANNER_PROMPT = """
You are the planning component of ResearchAgent.

Create an executable scientific DAG.

Available operations:

1. list_research_files

2. inspect_netcdf

3. area_weighted_mean

4. subtract_step_results
   This operation calculates:
       left step result - right step result
   from previously validated step outputs.

Rules:

- Every step must correspond to one real operation.

- Use exact argument names from the supplied schema.

- Use depends_on to represent scientific dependencies.

- A step may execute only after all depends_on steps
  have completed successfully.

- If two calculations both require the same dataset
  inspection, they may both depend on the inspection step.

- subtract_step_results must depend on both source steps.

- Do not invent pseudo-steps for reading arrays,
  selecting latitude, calculating weights, or validation.

- Deterministic validation happens automatically.

- Do not perform arithmetic during planning.

- Never invent files, variables, regions, or results.
"""


# ============================================================
# Create plan
# ============================================================

def create_research_plan(
    question: str,
) -> dict:

    response = client.chat(
        model=MODEL,

        messages=[
            {
                "role": "system",
                "content": PLANNER_PROMPT,
            },
            {
                "role": "user",
                "content": question,
            },
        ],

        format=(
            ResearchPlan.model_json_schema()
        ),

        think=False,
    )

    plan = (
        ResearchPlan.model_validate_json(
            response.message.content
        )
    )

    return plan.model_dump()
