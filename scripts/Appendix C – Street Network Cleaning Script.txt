import os

import arcpy

arcpy.env.overwriteOutput = True


# -----------------------------------------------------------------------------
# Paths and settings
# -----------------------------------------------------------------------------

INPUT_GPKG = (
    r"<Project Directory>\01_RawData\Street_Network_GIP_Raw"
    r"\B_gip_network_ogd\gip_network_ogd.gpkg"
)

OUTPUT_GDB = (
    r"<Project Directory>\02_CleanData\Street_Network_GIP_Clean"
    r"\Street_Network_Clean.gdb"
)

AOI = (
    r"<Project Directory>\04_Geodatabase\MasterThesis_Main.gdb"
    r"\Flachgau_AOI_Clean"
)

TARGET_EPSG = 31255
BUFFER_DISTANCE = "5000 Meters"

# GIP layers required for the street-network workflow.
GIP_LAYERS = {
    "EDGE_Clean": "main.EDGE_OGD",
    "LINKNETZ_Clean": "main.GIP_LINKNETZ_OGD",
    "LINEARUSE_Clean": "main.LINEARUSE_OGD",
    "NODE_Clean": "main.NODE_OGD",
    "TURNUSE_Clean": "main.TURNUSE_OGD",
}


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

def ensure_gdb(path):
    """Create a file geodatabase when it does not already exist."""
    if not arcpy.Exists(path):
        arcpy.management.CreateFileGDB(
            os.path.dirname(path),
            os.path.basename(path),
        )


def scratch_path(name):
    """Return a temporary feature-class path in the ArcGIS scratch GDB."""
    return os.path.join(arcpy.env.scratchGDB, name)


def copy_and_project(input_layer, output_fc):
    """Copy a GeoPackage layer and project it to the analysis CRS."""
    layer_name = (
        os.path.basename(input_layer)
        .replace("main.", "")
        .replace(".", "_")
    )
    temp_copy = scratch_path(f"copy_{layer_name}")

    if arcpy.Exists(temp_copy):
        arcpy.management.Delete(temp_copy)
    if arcpy.Exists(output_fc):
        arcpy.management.Delete(output_fc)

    # Copying first avoids problems with some GeoPackage field types during
    # projection and later geoprocessing.
    arcpy.management.CopyFeatures(input_layer, temp_copy)
    arcpy.management.Project(
        temp_copy,
        output_fc,
        arcpy.SpatialReference(TARGET_EPSG),
    )


def decode_access(feature_class):
    """Decode directional GIP access bitmasks for cars and pedestrians.

    ACCESS_TOW describes access in the digitised direction and ACCESS_BKW in
    the opposite direction. Bit 0 (value 1) represents pedestrian access and
    bit 2 (value 4) private-car access.
    """
    output_fields = ["CAR_TOW", "CAR_BKW", "PED_TOW", "PED_BKW"]
    existing_fields = {field.name for field in arcpy.ListFields(feature_class)}

    for field_name in output_fields:
        if field_name not in existing_fields:
            arcpy.management.AddField(feature_class, field_name, "SHORT")

    cursor_fields = [
        "ACCESS_TOW",
        "ACCESS_BKW",
        "CAR_TOW",
        "CAR_BKW",
        "PED_TOW",
        "PED_BKW",
    ]

    with arcpy.da.UpdateCursor(feature_class, cursor_fields) as cursor:
        for row in cursor:
            access_tow = int(row[0]) if row[0] not in (None, "") else 0
            access_bkw = int(row[1]) if row[1] not in (None, "") else 0

            # Private-car access: bit 2 / value 4.
            row[2] = 1 if access_tow & 4 else 0
            row[3] = 1 if access_bkw & 4 else 0

            # Pedestrian access: bit 0 / value 1.
            row[4] = 1 if access_tow & 1 else 0
            row[5] = 1 if access_bkw & 1 else 0

            cursor.updateRow(row)


# -----------------------------------------------------------------------------
# 1. Prepare the output workspace and AOI buffer
# -----------------------------------------------------------------------------

ensure_gdb(OUTPUT_GDB)
arcpy.env.workspace = OUTPUT_GDB

# The buffer prevents routes close to the Flachgau boundary from being cut off
# simply because a reasonable path briefly leaves the study area.
buffer_fc = scratch_path("Flachgau_AOI_Buffer_5km")
if arcpy.Exists(buffer_fc):
    arcpy.management.Delete(buffer_fc)

arcpy.analysis.Buffer(AOI, buffer_fc, BUFFER_DISTANCE)


# -----------------------------------------------------------------------------
# 2. Process the required GIP layers
# -----------------------------------------------------------------------------

for output_name, layer_name in GIP_LAYERS.items():
    input_layer = f"{INPUT_GPKG}\\{layer_name}"
    projected_fc = scratch_path(f"{output_name}_projected")
    output_fc = os.path.join(OUTPUT_GDB, output_name)

    copy_and_project(input_layer, projected_fc)

    if arcpy.Exists(output_fc):
        arcpy.management.Delete(output_fc)

    arcpy.analysis.Clip(projected_fc, buffer_fc, output_fc)

    # Only layers that contain both directional ACCESS fields need decoding.
    fields = {field.name for field in arcpy.ListFields(output_fc)}
    if {"ACCESS_TOW", "ACCESS_BKW"}.issubset(fields):
        decode_access(output_fc)

print("Street network preprocessing completed successfully.")
