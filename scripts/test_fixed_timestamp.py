import sys
import io
import tarfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, "src")
from taxi.clean import day_bounds

DAY = "20250114"
ARCHIVE = Path.home() / "Downloads" / "PROBE-202501.tar.bz2"

COLS = ["vid", "gps", "lat", "lon", "ts",
        "speed", "heading", "light", "acc"]

BBOX = {
    "lat_min": 13.45, "lat_max": 14.15,
    "lon_min": 100.25, "lon_max": 100.95
}

print("Reading archive:", ARCHIVE)
print("Looking for:", DAY)

with tarfile.open(ARCHIVE, "r|bz2") as tar:
    for member in tar:
        if not member.name.endswith(".csv.out"):
            continue

        if Path(member.name).name[:8] != DAY:
            continue

        print("Found source file:", member.name)

        raw = tar.extractfile(member).read()

        d = pd.read_csv(
            io.BytesIO(raw),
            header=None,
            names=COLS,
            dtype={
                "vid": "category",
                "gps": "int8",
                "speed": "int16",
                "heading": "int16",
                "light": "int8",
                "acc": "int8"
            }
        )

        n_all = len(d)
        n_veh = d["vid"].nunique()

        d["ts"] = pd.to_datetime(d["ts"], errors="coerce")
        d = d[
            (d["gps"] == 1) &
            (d["ts"].dt.normalize() == pd.Timestamp(DAY))
        ]

        n_valid = len(d)

        d = d[
            d["lat"].between(BBOX["lat_min"], BBOX["lat_max"]) &
            d["lon"].between(BBOX["lon_min"], BBOX["lon_max"])
        ]

        n_bkk = len(d)

        d = d.sort_values(["vid", "ts"]).drop_duplicates(
            ["vid", "ts"]
        )

        sw = (
            d["light"].ne(
                d.groupby("vid", observed=True)["light"].shift()
            ) &
            d["vid"].eq(d["vid"].shift())
        )

        n_sw = sw.groupby(d["vid"], observed=True).sum()
        taxis = n_sw[n_sw >= 4].index
        d = d[d["vid"].isin(taxis)]

        # Corrected timestamp conversion:
        out = pd.DataFrame({
            "vid": d["vid"].astype(str).values,
            "t": d["ts"].dt.as_unit("s").astype("int64").values,
            "lat": d["lat"].astype("float32").values,
            "lon": d["lon"].astype("float32").values,
            "speed": d["speed"].values,
            "occ": (1 - d["light"]).astype("int8").values,
            "acc": d["acc"].values
        })

        out.attrs["log"] = {
            "day": DAY,
            "rows": n_all,
            "vehicles": n_veh,
            "removed_invalid_or_wrong_day": n_all - n_valid,
            "removed_outside_bangkok": n_valid - n_bkk,
            "taxis": len(taxis),
            "taxi_rows": len(out)
        }

        start, end = day_bounds(DAY)

        g = (
            out.sort_values(["vid", "t"])
            .groupby("vid", observed=True)
        )

        gaps = g["t"].diff().dropna()

        print("\n===== CORRECTED ONE-DAY CHECK =====")
        print("Datetime dtype:", d["ts"].dtype)
        print("Rows:", len(out))
        print("Vehicles:", out["vid"].nunique())
        print("Timestamp minimum:", out["t"].min())
        print("Timestamp maximum:", out["t"].max())
        print("Expected range:", start, "to", end)
        print(
            "All timestamps inside expected day:",
            bool(((out["t"] >= start) & (out["t"] < end)).all())
        )
        print("Median records per vehicle:", g.size().median())
        print("Median seconds between records:", gaps.median())
        print("Occupancy values:", out["occ"].value_counts().to_dict())
        print("Acceleration values:", out["acc"].value_counts().to_dict())
        print("Original filtering log:", out.attrs["log"])
        print("\nNo daily file has been saved.")

        break
    else:
        raise RuntimeError("Could not find January 14 in the archive.")
