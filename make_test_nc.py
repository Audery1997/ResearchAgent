from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


# ============================================================
# Output location
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACE = PROJECT_ROOT / "workspace"

WORKSPACE.mkdir(exist_ok=True)

output_file = WORKSPACE / "test_climate.nc"


# ============================================================
# Coordinates
# ============================================================

time = pd.date_range(
    "2000-01-01",
    periods=24,
    freq="MS",
)

lat = np.arange(
    -90,
    91,
    30,
    dtype=float,
)

lon = np.arange(
    0,
    360,
    30,
    dtype=float,
)


# ============================================================
# Create artificial temperature data
# ============================================================

rng = np.random.default_rng(42)

tas = (
    280.0
    + rng.normal(
        loc=0.0,
        scale=3.0,
        size=(len(time), len(lat), len(lon)),
    )
)


# ============================================================
# Build xarray Dataset
# ============================================================

ds = xr.Dataset(
    data_vars={
        "tas": (
            ("time", "lat", "lon"),
            tas,
            {
                "long_name": "Near-Surface Air Temperature",
                "standard_name": "air_temperature",
                "units": "K",
            },
        ),
    },

    coords={
        "time": (
            "time",
            time,
            {
                "standard_name": "time",
            },
        ),

        "lat": (
            "lat",
            lat,
            {
                "long_name": "Latitude",
                "standard_name": "latitude",
                "units": "degrees_north",
            },
        ),

        "lon": (
            "lon",
            lon,
            {
                "long_name": "Longitude",
                "standard_name": "longitude",
                "units": "degrees_east",
            },
        ),
    },

    attrs={
        "title": "ResearchAgent test climate dataset",
        "experiment": "Synthetic test",
    },
)


# ============================================================
# Save
# ============================================================

ds.to_netcdf(output_file)

print(f"Created:")
print(output_file)