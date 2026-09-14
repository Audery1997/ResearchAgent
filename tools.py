from pathlib import Path
import json

import numpy as np
import xarray as xr

PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = (PROJECT_ROOT / "workspace").resolve()


EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
}


def list_research_files(folder: str = ".") -> str:
    """
    List research-related files inside the research workspace.

    Args:
        folder:
            A directory relative to the workspace root.
            Use "." for the entire workspace.

    Returns:
        A newline-separated list of research-related files.
    """

    target = (WORKSPACE_ROOT / folder).resolve()

    # ========================================================
    # Security boundary
    #
    # The agent is not allowed to leave workspace/
    # ========================================================

    try:
        target.relative_to(WORKSPACE_ROOT)

    except ValueError:

        return (
            "ERROR: Access outside the research workspace "
            "is not allowed."
        )

    if not target.exists():

        return f"ERROR: Folder does not exist: {folder}"

    if not target.is_dir():

        return f"ERROR: Path is not a directory: {folder}"

    allowed_suffixes = {
        ".nc",
        ".nc4",
        ".py",
        ".ncl",
        ".sh",
        ".csv",
        ".txt",
        ".md",
        ".ipynb",
        ".json",
        ".yaml",
        ".yml",
    }

    files = []

    for path in target.rglob("*"):

        if not path.is_file():
            continue

        relative_path = path.relative_to(WORKSPACE_ROOT)

        if any(
            part in EXCLUDED_DIRS
            for part in relative_path.parts
        ):
            continue

        if path.suffix.lower() in allowed_suffixes:
            files.append(str(relative_path))

    files.sort()

    print()
    print(
        "[TOOL EXECUTED] "
        f"list_research_files(folder={folder!r})"
    )

    if not files:

        return "No research-related files were found."

    return "\n".join(files[:100])

def inspect_netcdf(file_path: str) -> str:
    """
    Inspect the metadata and structure of a NetCDF file.

    Args:
        file_path:
            Path to a NetCDF file relative to the workspace root.

    Returns:
        Metadata including dimensions, coordinates, variables,
        units, shapes, and time range.
    """

    target = (WORKSPACE_ROOT / file_path).resolve()

    # ========================================================
    # Security boundary
    # ========================================================

    try:
        target.relative_to(WORKSPACE_ROOT)

    except ValueError:

        return (
            "ERROR: Access outside the research workspace "
            "is not allowed."
        )

    # ========================================================
    # Basic validation
    # ========================================================

    if not target.exists():

        return f"ERROR: File does not exist: {file_path}"

    if not target.is_file():

        return f"ERROR: Path is not a file: {file_path}"

    if target.suffix.lower() not in {".nc", ".nc4"}:

        return (
            "ERROR: inspect_netcdf only supports "
            ".nc and .nc4 files."
        )

    print()
    print(
        "[TOOL EXECUTED] "
        f"inspect_netcdf(file_path={file_path!r})"
    )

    # ========================================================
    # Open the NetCDF file
    #
    # Important:
    # xarray uses lazy loading here.
    # We are NOT loading the entire climate field into memory.
    # ========================================================

    try:

        with xr.open_dataset(
            target,
            decode_times=True,
        ) as ds:

            info = {
                "file": str(
                    target.relative_to(WORKSPACE_ROOT)
                ),

                "global_attributes": dict(ds.attrs),

                "dimensions": {
                    name: int(size)
                    for name, size in ds.sizes.items()
                },

                "coordinates": {},

                "data_variables": {},
            }

            # =================================================
            # Coordinates
            # =================================================

            for name, variable in ds.coords.items():

                coordinate_info = {
                    "dimensions": list(variable.dims),
                    "shape": list(variable.shape),
                    "dtype": str(variable.dtype),
                    "units": variable.attrs.get("units"),
                    "standard_name": variable.attrs.get(
                        "standard_name"
                    ),
                    "long_name": variable.attrs.get(
                        "long_name"
                    ),
                }

                # For simple 1-D coordinates such as
                # lat/lon/time, report first and last values.
                if variable.ndim == 1 and variable.size > 0:

                    coordinate_info["first_value"] = str(
                        variable.values[0]
                    )

                    coordinate_info["last_value"] = str(
                        variable.values[-1]
                    )

                info["coordinates"][name] = coordinate_info

            # =================================================
            # Data variables
            # =================================================

            for name, variable in ds.data_vars.items():

                info["data_variables"][name] = {
                    "dimensions": list(variable.dims),
                    "shape": list(variable.shape),
                    "dtype": str(variable.dtype),
                    "units": variable.attrs.get("units"),
                    "standard_name": variable.attrs.get(
                        "standard_name"
                    ),
                    "long_name": variable.attrs.get(
                        "long_name"
                    ),
                }

            # =================================================
            # Explicit time range
            # =================================================

            if "time" in ds.coords:

                time = ds["time"]

                if time.size > 0:

                    info["time_range"] = {
                        "start": str(time.values[0]),
                        "end": str(time.values[-1]),
                    }

            return json.dumps(
                info,
                indent=2,
                ensure_ascii=False,
                default=str,
            )

    except Exception as error:

        return (
            "ERROR while reading NetCDF file: "
            f"{type(error).__name__}: {error}"
        )

def area_weighted_mean(
    file_path: str,
    variable: str,
    lat_min: float,
    lat_max: float,
) -> str:
    """
    Calculate a cosine-latitude weighted spatial mean
    over all longitudes for a latitude band.

    This tool currently supports only regular
    rectilinear latitude-longitude grids.

    Args:
        file_path:
            NetCDF file path relative to workspace.

        variable:
            Name of the data variable.

        lat_min:
            Southern latitude boundary in degrees north.

        lat_max:
            Northern latitude boundary in degrees north.

    Returns:
        JSON containing spatial-mean metadata and statistics.
    """

    target = (WORKSPACE_ROOT / file_path).resolve()

    # ========================================================
    # Security boundary
    # ========================================================

    try:
        target.relative_to(WORKSPACE_ROOT)

    except ValueError:

        return (
            "ERROR: Access outside the research workspace "
            "is not allowed."
        )

    # ========================================================
    # File validation
    # ========================================================

    if not target.exists():

        return f"ERROR: File does not exist: {file_path}"

    if target.suffix.lower() not in {".nc", ".nc4"}:

        return "ERROR: Only NetCDF files are supported."

    print()
    print(
        "[TOOL EXECUTED] "
        f"area_weighted_mean("
        f"file_path={file_path!r}, "
        f"variable={variable!r}, "
        f"lat_min={lat_min}, "
        f"lat_max={lat_max})"
    )

    try:

        with xr.open_dataset(
            target,
            decode_times=True,
        ) as ds:

            # =================================================
            # Variable validation
            # =================================================

            if variable not in ds.data_vars:

                return (
                    f"ERROR: Variable {variable!r} "
                    "does not exist in the dataset."
                )

            da = ds[variable]

            # =================================================
            # Detect latitude and longitude
            # =================================================

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

            if lat_name is None:

                return (
                    "ERROR: Could not identify "
                    "the latitude coordinate."
                )

            if lon_name is None:

                return (
                    "ERROR: Could not identify "
                    "the longitude coordinate."
                )

            lat = ds[lat_name]
            lon = ds[lon_name]

            # =================================================
            # Scientific validity checks
            # =================================================

            if lat.ndim != 1 or lon.ndim != 1:

                return (
                    "ERROR: This version of "
                    "area_weighted_mean supports only "
                    "1-D latitude and longitude coordinates."
                )

            if (
                lat_name not in da.dims
                or lon_name not in da.dims
            ):

                return (
                    "ERROR: The requested variable does not "
                    "contain both latitude and longitude "
                    "dimensions."
                )

            # -------------------------------------------------
            # Verify approximately regular coordinate spacing
            # -------------------------------------------------

            lat_values = np.asarray(
                lat.values,
                dtype=float,
            )

            lon_values = np.asarray(
                lon.values,
                dtype=float,
            )

            if lat_values.size > 2:

                lat_diff = np.diff(
                    np.sort(lat_values)
                )

                if not np.allclose(
                    lat_diff,
                    lat_diff[0],
                    rtol=1e-5,
                    atol=1e-8,
                ):

                    return (
                        "ERROR: Latitude spacing is not "
                        "uniform. Cosine-latitude weighting "
                        "alone is not sufficient."
                    )

            if lon_values.size > 2:

                lon_diff = np.diff(
                    np.sort(lon_values)
                )

                if not np.allclose(
                    lon_diff,
                    lon_diff[0],
                    rtol=1e-5,
                    atol=1e-8,
                ):

                    return (
                        "ERROR: Longitude spacing is not "
                        "uniform. This tool currently "
                        "supports regular longitude grids."
                    )

            # =================================================
            # Latitude-band selection
            #
            # Boolean masking works whether latitude runs
            # south-to-north or north-to-south.
            # =================================================

            southern_bound = min(
                lat_min,
                lat_max,
            )

            northern_bound = max(
                lat_min,
                lat_max,
            )

            mask = (
                (lat >= southern_bound)
                & (lat <= northern_bound)
            )

            subset = da.where(
                mask,
                drop=True,
            )

            if subset.sizes.get(lat_name, 0) == 0:

                return (
                    "ERROR: No latitude grid points "
                    "fall inside the requested region."
                )

            # =================================================
            # Cosine-latitude weights
            #
            # w(phi) = cos(phi)
            # =================================================

            weights = np.cos(
                np.deg2rad(
                    subset[lat_name]
                )
            )

            # Numerical roundoff near the poles can produce
            # tiny negative values, so clip them to zero.
            weights = weights.clip(
                min=0.0
            )

            # =================================================
            # Weighted horizontal mean
            #
            # xarray broadcasts latitude weights over longitude.
            # =================================================

            spatial_mean = (
                subset
                .weighted(weights)
                .mean(
                    dim=[
                        lat_name,
                        lon_name,
                    ],
                    skipna=True,
                )
            )

            # =================================================
            # Return compact information to the LLM
            # =================================================

            result = {
                "file": file_path,

                "variable": variable,

                "variable_units": da.attrs.get(
                    "units"
                ),

                "latitude_coordinate": lat_name,

                "longitude_coordinate": lon_name,

                "requested_latitude_band": [
                    southern_bound,
                    northern_bound,
                ],

                "selected_latitudes": [
                    float(x)
                    for x in subset[
                        lat_name
                    ].values
                ],

                "weighting_method":
                    "cosine(latitude)",

                "result_dimensions":
                    list(spatial_mean.dims),

                "result_shape":
                    list(spatial_mean.shape),
            }

            # =================================================
            # If a time dimension remains, report summary
            # statistics without dumping the entire series.
            # =================================================

            if "time" in spatial_mean.dims:

                temporal_mean = (
                    spatial_mean.mean(
                        dim="time",
                        skipna=True,
                    )
                )

                result[
                    "temporal_mean_of_spatial_mean"
                ] = float(
                    temporal_mean.values
                )

                result[
                    "first_time_step_spatial_mean"
                ] = float(
                    spatial_mean.isel(
                        time=0
                    ).values
                )

                result[
                    "last_time_step_spatial_mean"
                ] = float(
                    spatial_mean.isel(
                        time=-1
                    ).values
                )

            elif spatial_mean.ndim == 0:

                result[
                    "spatial_mean"
                ] = float(
                    spatial_mean.values
                )

            return json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
                default=str,
            )

    except Exception as error:

        return (
            "ERROR while calculating area-weighted mean: "
            f"{type(error).__name__}: {error}"
        )

def _find_coordinate(
    ds,
    standard_name: str,
    candidates: list[str],
):
    """
    Find a coordinate using CF standard_name first,
    then fall back to common coordinate names.
    """

    # First choice: CF metadata
    for name in ds.coords:

        if (
            ds[name].attrs.get("standard_name")
            == standard_name
        ):
            return name

    # Second choice: common names
    for name in candidates:

        if name in ds.coords:
            return name

    return None


def subtract_step_results(
    left_step_id: int,
    right_step_id: int,
    result_field: str,
    left_label: str,
    right_label: str,
    step_outputs: dict,
) -> str:
    """
    Subtract one previously validated plan-step result
    from another.

    Computes:
        left - right

    step_outputs is injected internally by the workflow,
    not supplied by the user.
    """

    print()
    print(
        "[TOOL EXECUTED] "
        "subtract_step_results("
        f"left_step_id={left_step_id}, "
        f"right_step_id={right_step_id})"
    )

    left_entry = step_outputs.get(
        str(left_step_id)
    )

    right_entry = step_outputs.get(
        str(right_step_id)
    )

    if left_entry is None:

        return (
            "ERROR: Required output from "
            f"step {left_step_id} is missing."
        )

    if right_entry is None:

        return (
            "ERROR: Required output from "
            f"step {right_step_id} is missing."
        )

    left_result = left_entry.get(
        "result"
    )

    right_result = right_entry.get(
        "result"
    )

    if not isinstance(
        left_result,
        dict,
    ):

        return (
            "ERROR: Left step result is not "
            "a structured result."
        )

    if not isinstance(
        right_result,
        dict,
    ):

        return (
            "ERROR: Right step result is not "
            "a structured result."
        )

    if result_field not in left_result:

        return (
            f"ERROR: Field {result_field!r} "
            f"is missing from step {left_step_id}."
        )

    if result_field not in right_result:

        return (
            f"ERROR: Field {result_field!r} "
            f"is missing from step {right_step_id}."
        )

    left_value = float(
        left_result[result_field]
    )

    right_value = float(
        right_result[result_field]
    )

    left_units = (
        left_result.get(
            "variable_units"
        )
        or left_result.get(
            "units"
        )
    )

    right_units = (
        right_result.get(
            "variable_units"
        )
        or right_result.get(
            "units"
        )
    )

    if left_units != right_units:

        return (
            "ERROR: Cannot subtract results "
            f"with different units: "
            f"{left_units!r} vs {right_units!r}."
        )

    difference = (
        left_value
        - right_value
    )

    result = {
        "operation":
            "difference",

        "left_step_id":
            left_step_id,

        "right_step_id":
            right_step_id,

        "left_label":
            left_label,

        "right_label":
            right_label,

        "result_field":
            result_field,

        "left_value":
            left_value,

        "right_value":
            right_value,

        "difference":
            difference,

        "units":
            left_units,

        "formula":
            f"{left_label} - {right_label}",
    }

    return json.dumps(
        result,
        indent=2,
        ensure_ascii=False,
    )
