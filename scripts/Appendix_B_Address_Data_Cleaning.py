import os

import arcpy
import pandas as pd

arcpy.env.overwriteOutput = True


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

INPUT_FILE = (
    r"<Project Directory>\01_RawData"
    r"\Addresses_Flachgau_Raw\ADRESSE.csv"
)

OUTPUT_DIR = (
    r"<Project Directory>\02_CleanData"
    r"\Addresses_Flachgau_Clean"
)
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "Addresses_Flachgau_Clean.csv")

TEMP_FOLDER = r"<Project Directory>\03_Intermediate"
TEMP_POINTS = os.path.join(TEMP_FOLDER, "Addresses_Flachgau_Points_Temp.shp")

OUTPUT_GDB = (
    r"<Project Directory>\04_Geodatabase"
    r"\MasterThesis_Main.gdb"
)
OUTPUT_POINTS = os.path.join(OUTPUT_GDB, "Addresses_Flachgau_Points_Clean")
AOI = os.path.join(OUTPUT_GDB, "Flachgau_AOI_Clean")

TARGET_EPSG = 31255


# -----------------------------------------------------------------------------
# 1. Clean the address table
# -----------------------------------------------------------------------------

# The source file is semicolon-separated and all fields are read as text first.
df = pd.read_csv(
    INPUT_FILE,
    sep=";",
    dtype=str,
    on_bad_lines="skip",
)

# Only fields needed for identification and spatial processing are retained.
required_fields = [
    "ADRCD",
    "GKZ",
    "PLZ",
    "ZAEHLSPRENGEL",
    "RW",
    "HW",
    "EPSG",
]

missing_fields = [field for field in required_fields if field not in df.columns]
if missing_fields:
    raise ValueError(f"Missing required fields: {missing_fields}")

df = df[required_fields].copy()

# The analysis uses MGI / Austria GK Central (EPSG:31255).
df = df[df["EPSG"] == str(TARGET_EPSG)]

# Invalid or missing coordinate values cannot be converted to point features.
df["RW"] = pd.to_numeric(df["RW"], errors="coerce")
df["HW"] = pd.to_numeric(df["HW"], errors="coerce")
df = df.dropna(subset=["RW", "HW"])

os.makedirs(OUTPUT_DIR, exist_ok=True)
df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")


# -----------------------------------------------------------------------------
# 2. Create address points
# -----------------------------------------------------------------------------

os.makedirs(TEMP_FOLDER, exist_ok=True)

if not arcpy.Exists(OUTPUT_GDB):
    arcpy.management.CreateFileGDB(
        os.path.dirname(OUTPUT_GDB),
        os.path.basename(OUTPUT_GDB),
    )

# Recreate the temporary point layer on every run so it always reflects the
# current cleaned CSV.
if arcpy.Exists(TEMP_POINTS):
    arcpy.management.Delete(TEMP_POINTS)

arcpy.management.XYTableToPoint(
    in_table=OUTPUT_FILE,
    out_feature_class=TEMP_POINTS,
    x_field="RW",
    y_field="HW",
    coordinate_system=arcpy.SpatialReference(TARGET_EPSG),
)


# -----------------------------------------------------------------------------
# 3. Limit the origins to the study area
# -----------------------------------------------------------------------------

# Only addresses inside the Flachgau AOI are retained as origins.
arcpy.analysis.Clip(
    in_features=TEMP_POINTS,
    clip_features=AOI,
    out_feature_class=OUTPUT_POINTS,
)

print("Address preprocessing completed successfully.")
