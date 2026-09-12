import json

import arcpy
import numpy as np

arcpy.env.overwriteOutput = True


# -----------------------------------------------------------------------------
# Paths and settings
# -----------------------------------------------------------------------------

EVIS_JSON = (
    r"<Project Directory>\01_RawData\EVIS_Data_Raw"
    r"\EVIS_speeddistributioncurve_salzburg.json"
)

LINKNETZ = (
    r"<Project Directory>\02_CleanData\Street_Network_GIP_Clean"
    r"\Street_Network_Clean.gdb\LINKNETZ_Clean"
)

LINK_ID = "LINK_ID"

VMAX = {
    "TOW": "VMAX_CAR_T",
    "BKW": "VMAX_CAR_B",
}

SPEEDCAR = {
    "TOW": "SPEEDCAR_T",
    "BKW": "SPEEDCAR_B",
}

CAR_ACCESS = {
    "TOW": "CAR_TOW",
    "BKW": "CAR_BKW",
}

# EVIS day-group identifiers used in the analysis.
DAY_GROUPS = {
    "MO": 25,
    "FR": 27,
    "SA": 29,
}

# EVIS interval IDs used for the two analysed peak periods.
MORNING_INTERVALS = range(1, 13)
EVENING_INTERVALS = range(42, 52)

WALK_SPEED = 4.5  # km/h
MISSING_SPEED = 0.0


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

def safe_float(value):
    """Convert a value to float and return None for invalid values."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    if np.isnan(value):
        return None
    return value


def mean_available(values):
    """Return the mean of all valid numeric values in a sequence."""
    clean_values = [safe_float(value) for value in values]
    clean_values = [value for value in clean_values if value is not None]
    return float(np.mean(clean_values)) if clean_values else None


def add_field_if_missing(feature_class, field_name, field_type):
    """Add an output field only when it is not already present."""
    existing_fields = {field.name for field in arcpy.ListFields(feature_class)}
    if field_name not in existing_fields:
        arcpy.management.AddField(feature_class, field_name, field_type)


def fallback_speed(freeflow, vmax, speedcar):
    """Return the best available free-flow speed for one direction.

    Priority: EVIS free-flow -> GIP maximum speed -> GIP reference car speed -> 0.
    """
    if freeflow is not None:
        return freeflow

    vmax = safe_float(vmax)
    if vmax is not None and vmax > 0:
        return vmax

    speedcar = safe_float(speedcar)
    if speedcar is not None and speedcar > 0:
        return speedcar

    return MISSING_SPEED


# -----------------------------------------------------------------------------
# 1. Read and structure the EVIS data
# -----------------------------------------------------------------------------

with open(EVIS_JSON, "r", encoding="utf-8") as file:
    evis_data = json.load(file)

# EVIS_SPEEDS[LINK_ID][DAY][INTERVAL][DIRECTION] = velocity
EVIS_SPEEDS = {}
EVIS_FREEFLOW = {}

for curve in evis_data.get("timevariationcurves", []):
    freeflow = safe_float(curve.get("freeflow"))
    gip_links = curve.get("gipLink", []) or []
    groups = curve.get("group", []) or []

    # Register the GIP links referenced by this EVIS curve.
    for gip_link in gip_links:
        try:
            link_id = int(gip_link.get("linkId"))
        except (TypeError, ValueError):
            continue

        EVIS_SPEEDS.setdefault(link_id, {})
        if freeflow is not None:
            EVIS_FREEFLOW[link_id] = freeflow

    # Read the time-dependent measurements for the selected day groups.
    for group in groups:
        applicable_ids = group.get("applicableForIds", []) or []
        days = [
            day
            for day, group_id in DAY_GROUPS.items()
            if group_id in applicable_ids
        ]

        if not days:
            continue

        for measurement in group.get("measurements", []):
            interval = measurement.get("interval")
            velocity = safe_float(measurement.get("velocity"))

            if interval is None or velocity is None:
                continue

            for gip_link in gip_links:
                try:
                    link_id = int(gip_link.get("linkId"))
                except (TypeError, ValueError):
                    continue

                # EVIS stores direction as fromTo / toFrom.
                evis_direction = (
                    gip_link.get("referenceDirection", "")
                    .strip()
                    .lower()
                )

                for day in days:
                    EVIS_SPEEDS.setdefault(link_id, {})
                    EVIS_SPEEDS[link_id].setdefault(day, {})
                    EVIS_SPEEDS[link_id][day].setdefault(int(interval), {})
                    EVIS_SPEEDS[link_id][day][int(interval)][evis_direction] = velocity


# -----------------------------------------------------------------------------
# 2. Create output fields
# -----------------------------------------------------------------------------

speed_fields = []
for day in DAY_GROUPS:
    for direction in ("TOW", "BKW"):
        speed_fields.extend([
            f"{day}_FREEFLOW_{direction}",
            f"{day}_RUSH_MORNING_{direction}",
            f"{day}_RUSH_EVENING_{direction}",
        ])

for field_name in speed_fields:
    add_field_if_missing(LINKNETZ, field_name, "FLOAT")

add_field_if_missing(LINKNETZ, "WALK_SPEED", "FLOAT")

# These fields are retained for quality control and document the fallback used.
add_field_if_missing(LINKNETZ, "SRC_TOW", "TEXT")
add_field_if_missing(LINKNETZ, "SRC_BKW", "TEXT")


# -----------------------------------------------------------------------------
# 3. Transfer scenario speeds to the GIP street network
# -----------------------------------------------------------------------------

base_fields = [
    LINK_ID,
    VMAX["TOW"],
    VMAX["BKW"],
    SPEEDCAR["TOW"],
    SPEEDCAR["BKW"],
    CAR_ACCESS["TOW"],
    CAR_ACCESS["BKW"],
]

cursor_fields = base_fields + speed_fields + ["WALK_SPEED", "SRC_TOW", "SRC_BKW"]
index = {field: i for i, field in enumerate(cursor_fields)}

with arcpy.da.UpdateCursor(LINKNETZ, cursor_fields) as cursor:
    for row in cursor:
        try:
            link_id = int(row[index[LINK_ID]])
        except (TypeError, ValueError):
            continue

        row[index["WALK_SPEED"]] = WALK_SPEED

        link_speeds = EVIS_SPEEDS.get(link_id, {})
        evis_freeflow = EVIS_FREEFLOW.get(link_id)

        for direction, evis_direction in (
            ("TOW", "fromto"),
            ("BKW", "tofrom"),
        ):
            car_allowed = row[index[CAR_ACCESS[direction]]]
            vmax = row[index[VMAX[direction]]]
            speedcar = row[index[SPEEDCAR[direction]]]

            if car_allowed == 0:
                # Zero speeds are written for directions that are not accessible
                # by car; the network restriction later prevents their use.
                for day in DAY_GROUPS:
                    row[index[f"{day}_FREEFLOW_{direction}"]] = 0.0
                    row[index[f"{day}_RUSH_MORNING_{direction}"]] = 0.0
                    row[index[f"{day}_RUSH_EVENING_{direction}"]] = 0.0
                row[index[f"SRC_{direction}"]] = "restricted"
                continue

            if evis_freeflow is not None:
                source = "freeflow"
            elif safe_float(vmax) is not None and float(vmax) > 0:
                source = "vmax"
            elif safe_float(speedcar) is not None and float(speedcar) > 0:
                source = "speedcar"
            else:
                source = "none"

            freeflow = fallback_speed(evis_freeflow, vmax, speedcar)

            for day in DAY_GROUPS:
                day_data = link_speeds.get(day, {})

                morning_values = [
                    values[evis_direction]
                    for interval, values in day_data.items()
                    if interval in MORNING_INTERVALS and evis_direction in values
                ]

                evening_values = [
                    values[evis_direction]
                    for interval, values in day_data.items()
                    if interval in EVENING_INTERVALS and evis_direction in values
                ]

                # This reproduces the calculation used in the thesis workflow:
                # where peak-period EVIS values are available, the fallback
                # free-flow value is included in the representative mean.
                # If no peak values exist, free-flow is used directly.
                morning = (
                    mean_available(morning_values + [freeflow])
                    if morning_values
                    else freeflow
                )
                evening = (
                    mean_available(evening_values + [freeflow])
                    if evening_values
                    else freeflow
                )

                row[index[f"{day}_FREEFLOW_{direction}"]] = freeflow
                row[index[f"{day}_RUSH_MORNING_{direction}"]] = morning
                row[index[f"{day}_RUSH_EVENING_{direction}"]] = evening

            row[index[f"SRC_{direction}"]] = source

        cursor.updateRow(row)

print("EVIS traffic speeds successfully integrated into the GIP street network.")
