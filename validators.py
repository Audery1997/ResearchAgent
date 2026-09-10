from pathlib import Path
import json

import numpy as np
import xarray as xr


# ============================================================
# Workspace
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = (PROJECT_ROOT / "workspace").resolve()


# ============================================================
# Coordinate detection
# ============================================================

def _find_coordinate(
    ds,
    standard_name: str,
    candidates: list[str],
):
    """
    Independently identify a coordinate.

    This implementation is deliberately kept separate
    from tools.py so the validator does not simply reuse
    the same helper used by the calculation tool.
    """

    for name in ds.coords:

        if (
            ds[name].attrs.get("standard_name")
            == standard_name
        ):
            return name

    for name in candidates:

        if name in ds.coords:
            return name

    return None


# ============================================================
# Area-weighted mean validator
# ============================================================

def validate_area_weighted_mean(
    arguments: dict,
    tool_result: str,
) -> str:
    """
    Independently validate an area_weighted_mean result.

    The validator recomputes the result using an explicit
    numerator / denominator formulation rather than
    xarray.weighted().mean().

    Returns:
        A JSON validation report.
    """

    checks = {}
    warnings = []

    # --------------------------------------------------------
    # 1. Tool must not have returned an error
    # --------------------------------------------------------

    if str(tool_result).startswith("ERROR"):

        report = {
            "validator": "area_weighted_mean_v1",
            "status": "FAIL",
            "reason": "The calculation tool returned an error.",
            "tool_result": str(tool_result),
        }

        return json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        )

    # --------------------------------------------------------
    # 2. Parse tool output
    # --------------------------------------------------------

    try:

        result = json.loads(tool_result)
        checks["tool_result_is_valid_json"] = True

    except Exception as error:

        report = {
            "validator": "area_weighted_mean_v1",
            "status": "FAIL",
            "reason": (
                "The calculation result could not be parsed "
                f"as JSON: {error}"
            ),
        }

        return json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        )

    # --------------------------------------------------------
    # Read original tool arguments
    # --------------------------------------------------------

    file_path = arguments["file_path"]
    variable = arguments["variable"]

    lat_min = float(arguments["lat_min"])
    lat_max = float(arguments["lat_max"])

    southern_bound = min(lat_min, lat_max)
    northern_bound = max(lat_min, lat_max)

    target = (WORKSPACE_ROOT / file_path).resolve()

    # --------------------------------------------------------
    # 3. Security check
    # --------------------------------------------------------

    try:

        target.relative_to(WORKSPACE_ROOT)
        checks["inside_workspace"] = True

    except ValueError:

        checks["inside_workspace"] = False

        report = {
            "validator": "area_weighted_mean_v1",
            "status": "FAIL",
            "checks": checks,
            "reason": "File is outside the workspace.",
        }

        return json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        )

    # --------------------------------------------------------
    # 4. Independent calculation
    # --------------------------------------------------------

    try:

        with xr.open_dataset(
            target,
            decode_times=True,
        ) as ds:

            if variable not in ds.data_vars:

                checks["variable_exists"] = False

                report = {
                    "validator":
                        "area_weighted_mean_v1",
                    "status":
                        "FAIL",
                    "checks":
                        checks,
                    "reason":
                        f"Variable {variable!r} does not exist.",
                }

                return json.dumps(
                    report,
                    indent=2,
                    ensure_ascii=False,
                )

            checks["variable_exists"] = True

            da = ds[variable]

            # -----------------------------------------------
            # Independently identify lat/lon
            # -----------------------------------------------

            lat_name = _find_coordinate(
                ds,
                "latitude",
                ["lat", "latitude"],
            )

            lon_name = _find_coordinate(
                ds,
                "longitude",
                ["lon", "longitude"],
            )

            checks["latitude_identified"] = (
                lat_name is not None
            )

            checks["longitude_identified"] = (
                lon_name is not None
            )

            if lat_name is None or lon_name is None:

                report = {
                    "validator":
                        "area_weighted_mean_v1",
                    "status":
                        "FAIL",
                    "checks":
                        checks,
                    "reason":
                        "Latitude or longitude could not "
                        "be independently identified.",
                }

                return json.dumps(
                    report,
                    indent=2,
                    ensure_ascii=False,
                )

            lat = ds[lat_name]
            lon = ds[lon_name]

            # -----------------------------------------------
            # Require rectilinear coordinates
            # -----------------------------------------------

            checks["latitude_is_1d"] = (
                lat.ndim == 1
            )

            checks["longitude_is_1d"] = (
                lon.ndim == 1
            )

            if lat.ndim != 1 or lon.ndim != 1:

                report = {
                    "validator":
                        "area_weighted_mean_v1",
                    "status":
                        "FAIL",
                    "checks":
                        checks,
                    "reason":
                        "Validator currently supports only "
                        "1-D latitude/longitude grids.",
                }

                return json.dumps(
                    report,
                    indent=2,
                    ensure_ascii=False,
                )

            # -----------------------------------------------
            # Select requested region independently
            # -----------------------------------------------

            mask = (
                (lat >= southern_bound)
                & (lat <= northern_bound)
            )

            subset = da.where(
                mask,
                drop=True,
            )

            expected_latitudes = [
                float(x)
                for x in subset[lat_name].values
            ]

            reported_latitudes = result.get(
                "selected_latitudes",
                [],
            )

            checks["selected_latitudes_match"] = (
                np.allclose(
                    expected_latitudes,
                    reported_latitudes,
                    rtol=0,
                    atol=1e-12,
                )
                if (
                    len(expected_latitudes)
                    == len(reported_latitudes)
                )
                else False
            )

            # -----------------------------------------------
            # Independently create weights
            #
            # w = cos(latitude)
            # -----------------------------------------------

            weights_1d = np.cos(
                np.deg2rad(
                    subset[lat_name]
                )
            )

            weights_1d = weights_1d.clip(
                min=0.0
            )

            # Broadcast latitude weights to full data shape
            weights_full = (
                weights_1d.broadcast_like(subset)
            )

            # -----------------------------------------------
            # Independent explicit formula:
            #
            # sum(X*w) / sum(w)
            #
            # Valid-data masking is applied independently
            # for every time step.
            # -----------------------------------------------

            valid_weights = weights_full.where(
                subset.notnull()
            )

            numerator = (
                subset * valid_weights
            ).sum(
                dim=[
                    lat_name,
                    lon_name,
                ],
                skipna=True,
            )

            denominator = (
                valid_weights
            ).sum(
                dim=[
                    lat_name,
                    lon_name,
                ],
                skipna=True,
            )

            reference_spatial_mean = (
                numerator / denominator
            )

            # -----------------------------------------------
            # Independent temporal summary
            # -----------------------------------------------

            if "time" in reference_spatial_mean.dims:

                reference_temporal_mean = float(
                    reference_spatial_mean.mean(
                        dim="time",
                        skipna=True,
                    ).values
                )

                reference_first = float(
                    reference_spatial_mean.isel(
                        time=0
                    ).values
                )

                reference_last = float(
                    reference_spatial_mean.isel(
                        time=-1
                    ).values
                )

            else:

                reference_temporal_mean = float(
                    reference_spatial_mean.values
                )

                reference_first = None
                reference_last = None

            # -----------------------------------------------
            # Compare numerical result
            # -----------------------------------------------

            reported_temporal_mean = result.get(
                "temporal_mean_of_spatial_mean"
            )

            if reported_temporal_mean is None:

                reported_temporal_mean = result.get(
                    "spatial_mean"
                )

            numerical_match = np.isclose(
                float(reported_temporal_mean),
                reference_temporal_mean,
                rtol=1e-10,
                atol=1e-10,
            )

            checks[
                "temporal_mean_matches_independent_calculation"
            ] = bool(numerical_match)

            # -----------------------------------------------
            # Units
            # -----------------------------------------------

            source_units = da.attrs.get("units")

            reported_units = result.get(
                "variable_units"
            )

            checks["units_match_source"] = (
                source_units == reported_units
            )

            # -----------------------------------------------
            # Weighting method
            # -----------------------------------------------

            checks[
                "reported_weighting_method_is_coslat"
            ] = (
                result.get("weighting_method")
                == "cosine(latitude)"
            )

            # -----------------------------------------------
            # Remaining dimensions
            # -----------------------------------------------

            expected_dimensions = list(
                reference_spatial_mean.dims
            )

            reported_dimensions = result.get(
                "result_dimensions",
                [],
            )

            checks["result_dimensions_match"] = (
                expected_dimensions
                == reported_dimensions
            )

            # -----------------------------------------------
            # Finite result
            # -----------------------------------------------

            checks["result_is_finite"] = bool(
                np.isfinite(
                    reference_temporal_mean
                )
            )

            # -----------------------------------------------
            # Pole warning
            # -----------------------------------------------

            if any(
                np.isclose(
                    np.abs(expected_latitudes),
                    90.0,
                )
            ):

                warnings.append(
                    "The selected region includes a pole. "
                    "Its cosine-latitude weight is zero "
                    "within floating-point precision, which "
                    "is expected for this weighting scheme."
                )

            # -----------------------------------------------
            # Overall status
            # -----------------------------------------------

            status = (
                "PASS"
                if all(checks.values())
                else "FAIL"
            )

            report = {
                "validator":
                    "area_weighted_mean_v1",

                "status":
                    status,

                "checks":
                    checks,

                "reported_temporal_mean":
                    reported_temporal_mean,

                "independent_temporal_mean":
                    reference_temporal_mean,

                "absolute_difference":
                    abs(
                        float(reported_temporal_mean)
                        - reference_temporal_mean
                    ),

                "independent_first_time_step":
                    reference_first,

                "independent_last_time_step":
                    reference_last,

                "warnings":
                    warnings,
            }

            return json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
                default=str,
            )

    except Exception as error:

        report = {
            "validator": "area_weighted_mean_v1",
            "status": "FAIL",
            "reason": (
                "Validator itself failed: "
                f"{type(error).__name__}: {error}"
            ),
        }

        return json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        )


# ============================================================
# Validator dispatcher
# ============================================================

def validate_tool_result(
    tool_name: str,
    arguments: dict,
    tool_result: str,
):
    """
    Route a tool result to its deterministic validator.

    Returns None when no validator exists yet.
    """

    if tool_name == "area_weighted_mean":

        return validate_area_weighted_mean(
            arguments,
            tool_result,
        )

    return None