import arcpy
import os
import re
import math

arcpy.env.overwriteOutput = True


# ============================================================
# PATHS AND SETTINGS
# ============================================================

# Replace this placeholder with the geodatabase that contains
# the final routing outputs used for the thesis.
GDB = r"<Project Directory>\MasterThesis_New.gdb"

# Car OD Cost Matrix
CAR_TABLE = os.path.join(
    GDB,
    r"ODCostMatrixSolver1wfanvg\ODLines12g8iaw"
)

# Mean public transport results for the six analysed periods
BUS_TABLES = {
    "MO_AM": os.path.join(GDB, "OD_PT_MO_RushHour_AM"),
    "MO_PM": os.path.join(GDB, "OD_PT_MO_RushHour_PM"),
    "FR_AM": os.path.join(GDB, "OD_PT_FR_RushHour_AM"),
    "FR_PM": os.path.join(GDB, "OD_PT_FR_RushHour_PM"),
    "SA_AM": os.path.join(GDB, "OD_PT_SA_RushHour_AM"),
    "SA_PM": os.path.join(GDB, "OD_PT_SA_RushHour_PM"),
}

# Combined Park & Ride results
PR_TABLE = os.path.join(GDB, "PR_Final_AllScenarios")

# Intermediate and final output tables
BASE_TABLE = os.path.join(
    GDB,
    "Mode_Comparison_Wide_Final_Corrected_v2"
)

FINAL_TABLE = os.path.join(
    GDB,
    "Mode_Comparison_Wide_Final_WithCosts"
)

SCENARIOS = [
    "MO_AM", "MO_PM",
    "FR_AM", "FR_PM",
    "SA_AM", "SA_PM",
]


# ============================================================
# DESTINATION STANDARDISATION
# ============================================================

# Common destination IDs used in the final table.
DESTINATIONS = {
    1: "Salzburg Main Station",
    2: "Salzburg Airport",
    3: "Paris Lodron University Salzburg",
    4: "SALK",
    5: "Europark Salzburg",
}

# Destination order differed in the original car OD output.
CAR_DEST_MAP = {
    1: 1,
    2: 3,
    3: 2,
    4: 5,
    5: 4,
}

# P&R output stores destination names rather than IDs.
PR_DEST_MAP = {
    name: dest_id
    for dest_id, name in DESTINATIONS.items()
}

# Convert long P&R scenario names to the common short form.
PR_SCENARIO_MAP = {
    "MO_RushHour_AM": "MO_AM",
    "MO_RushHour_PM": "MO_PM",
    "FR_RushHour_AM": "FR_AM",
    "FR_RushHour_PM": "FR_PM",
    "SA_RushHour_AM": "SA_AM",
    "SA_RushHour_PM": "SA_PM",
}

# Final destination-specific parking costs and walking times.
# These values replace the earlier values stored in the original
# car OD output and correspond to the final corrected analysis.
CAR_DESTINATION_COMPONENTS = {
    1: {"parking": 2.20, "walk": 3.313282},
    2: {"parking": 3.90, "walk": 0.028592},
    3: {"parking": 1.20, "walk": 8.081189},
    4: {"parking": 2.00, "walk": 5.965121},
    5: {"parking": 0.00, "walk": 0.000000},
}

# The P&R Closest Facility output stored residential AddressIDs
# with a constant offset of +45. Subtracting the offset restores
# the AddressID used by the car and bus result tables.
PR_ADDRESS_ID_OFFSET = 45


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def safe_num(value):
    """Convert a value to float; missing or invalid values become 0."""
    try:
        return 0.0 if value is None else float(value)
    except (TypeError, ValueError):
        return 0.0


def extract_address_id(name):
    """
    Extract the residential address ID from the car OD Name field.

    Example:
    'Location 30353 - Location 2' -> 30353
    """
    match = re.search(r"Location\s+(\d+)", str(name))
    return int(match.group(1)) if match else None


def normalise_car_destination(raw_id):
    """Convert car destination IDs to the common destination system."""
    if raw_id is None:
        return None

    try:
        dest_id = int(raw_id)
    except (TypeError, ValueError):
        return None

    # OD destination IDs may occur as 11-15.
    if dest_id > 10:
        dest_id -= 10

    return CAR_DEST_MAP.get(dest_id)


def add_field(table, name, field_type="DOUBLE", length=None):
    """Add a field only if it does not already exist."""
    existing = {field.name for field in arcpy.ListFields(table)}

    if name in existing:
        return

    if field_type == "TEXT":
        arcpy.management.AddField(
            table,
            name,
            field_type,
            field_length=length
        )
    else:
        arcpy.management.AddField(
            table,
            name,
            field_type
        )


# ============================================================
# 1. CREATE THE COMMON RESULT TABLE
# ============================================================

def create_result_table():
    """Create the common wide table used to combine all modes."""

    if arcpy.Exists(BASE_TABLE):
        arcpy.management.Delete(BASE_TABLE)

    arcpy.management.CreateTable(
        GDB,
        os.path.basename(BASE_TABLE)
    )

    # Identification fields
    add_field(BASE_TABLE, "AddressID", "LONG")
    add_field(BASE_TABLE, "DestinationID", "LONG")
    add_field(BASE_TABLE, "DestinationName", "TEXT", 150)

    # Car attributes
    for scenario in SCENARIOS:
        add_field(
            BASE_TABLE,
            f"Car_{scenario}_Time"
        )

    for field in [
        "Car_CO2",
        "Car_Cost",
        "Car_ParkingCost",
        "Car_WalkFromParking_Time",
    ]:
        add_field(BASE_TABLE, field)

    # Bus attributes
    for scenario in SCENARIOS:
        for suffix in [
            "Time",
            "Walk",
            "CO2",
            "ZoneChange",
            "Cost",
        ]:
            add_field(
                BASE_TABLE,
                f"Bus_{scenario}_{suffix}"
            )

    # Park & Ride attributes
    for scenario in SCENARIOS:
        for suffix in [
            "Time",
            "CO2",
            "Cost",
            "ZoneChange",
            "BusCost",
        ]:
            add_field(
                BASE_TABLE,
                f"PR_{scenario}_{suffix}"
            )


# ============================================================
# 2. ADD CAR RESULTS
# ============================================================

def add_car_results():
    """
    Add car results and apply the final destination-specific
    parking costs and walking times.
    """

    source_fields = [
        "Name",
        "DestinationID",
        "Total_Driving_Mo_Morning",
        "Total_Driving_Mo_Evening",
        "Total_Driving_Fr_Morning",
        "Total_Driving_Fr_Evening",
        "Total_Driving_Sa_Morning",
        "Total_Driving_Sa_Evening",
        "Total_CO2_Car",
        "Total_Price_Car",
    ]

    target_fields = [
        "AddressID",
        "DestinationID",
        "DestinationName",
        "Car_MO_AM_Time",
        "Car_MO_PM_Time",
        "Car_FR_AM_Time",
        "Car_FR_PM_Time",
        "Car_SA_AM_Time",
        "Car_SA_PM_Time",
        "Car_CO2",
        "Car_Cost",
        "Car_ParkingCost",
        "Car_WalkFromParking_Time",
    ]

    seen = set()

    with arcpy.da.SearchCursor(
        CAR_TABLE,
        source_fields
    ) as source, arcpy.da.InsertCursor(
        BASE_TABLE,
        target_fields
    ) as target:

        for row in source:

            address_id = extract_address_id(row[0])
            dest_id = normalise_car_destination(row[1])

            if address_id is None or dest_id is None:
                continue

            # Keep one row for each address-destination combination.
            key = (address_id, dest_id)

            if key in seen:
                continue

            seen.add(key)

            components = CAR_DESTINATION_COMPONENTS[dest_id]
            parking = components["parking"]
            walk = components["walk"]

            target.insertRow([
                address_id,
                dest_id,
                DESTINATIONS[dest_id],

                # Door-to-door car time:
                # driving time + walk from parking to destination.
                safe_num(row[2]) + walk,
                safe_num(row[3]) + walk,
                safe_num(row[4]) + walk,
                safe_num(row[5]) + walk,
                safe_num(row[6]) + walk,
                safe_num(row[7]) + walk,

                # Route-based car CO2.
                safe_num(row[8]),

                # Distance-based car cost + destination parking cost.
                safe_num(row[9]) + parking,

                parking,
                walk,
            ])


# ============================================================
# 3. CREATE ADDRESS-DESTINATION LOOKUP
# ============================================================

def build_lookup():
    """
    Return a lookup from (AddressID, DestinationID)
    to the OBJECTID of the common result table.
    """

    return {
        (int(address), int(destination)): oid
        for oid, address, destination
        in arcpy.da.SearchCursor(
            BASE_TABLE,
            ["OBJECTID", "AddressID", "DestinationID"]
        )
    }


# ============================================================
# 4. ADD BUS RESULTS
# ============================================================

def add_bus_results(lookup):
    """Add the six public transport scenarios to the common table."""

    source_fields = [
        "OriginID",
        "DestinationID",
        "MEAN_Total_PublicTransportation_Minutes",
        "MEAN_Total_Walking_Minutes",
        "MEAN_Total_CO2_Bus_Other",
        "MEAN_Total_ZoneChanges_Other",
    ]

    for scenario, table in BUS_TABLES.items():

        values = {}

        with arcpy.da.SearchCursor(
            table,
            source_fields
        ) as cursor:

            for row in cursor:

                try:
                    key = (
                        int(row[0]),
                        int(row[1])
                    )
                except (TypeError, ValueError):
                    continue

                if key in lookup:
                    values[lookup[key]] = [
                        safe_num(row[2]),  # total PT time
                        safe_num(row[3]),  # walking component
                        safe_num(row[4]),  # CO2
                        safe_num(row[5]),  # zone changes
                        0.0,               # fare added later
                    ]

        fields = [
            "OBJECTID",
            f"Bus_{scenario}_Time",
            f"Bus_{scenario}_Walk",
            f"Bus_{scenario}_CO2",
            f"Bus_{scenario}_ZoneChange",
            f"Bus_{scenario}_Cost",
        ]

        with arcpy.da.UpdateCursor(
            BASE_TABLE,
            fields
        ) as cursor:

            for row in cursor:

                if row[0] in values:
                    row[1:] = values[row[0]]
                    cursor.updateRow(row)


# ============================================================
# 5. ADD PARK & RIDE RESULTS
# ============================================================

def add_pr_results(lookup):
    """
    Add the six P&R scenarios.

    The source AddressID is corrected by the constant offset
    identified during validation of the Closest Facility output.
    """

    source_fields = [
        "AddressID",
        "DestinationName",
        "Scenario",
        "PR_Total_Time",
        "PR_Total_CO2",
        "PR_Total_Cost",
        "PT_from_PR_ZoneChange",
    ]

    updates = {}

    with arcpy.da.SearchCursor(
        PR_TABLE,
        source_fields
    ) as cursor:

        for row in cursor:

            dest_id = PR_DEST_MAP.get(row[1])
            scenario = PR_SCENARIO_MAP.get(row[2])

            if dest_id is None or scenario is None:
                continue

            try:
                corrected_address_id = (
                    int(row[0]) - PR_ADDRESS_ID_OFFSET
                )
            except (TypeError, ValueError):
                continue

            key = (
                corrected_address_id,
                dest_id
            )

            if key not in lookup:
                continue

            oid = lookup[key]
            updates.setdefault(oid, {})

            updates[oid].update({
                f"PR_{scenario}_Time": safe_num(row[3]),
                f"PR_{scenario}_CO2": safe_num(row[4]),
                f"PR_{scenario}_Cost": safe_num(row[5]),
                f"PR_{scenario}_ZoneChange": safe_num(row[6]),
                f"PR_{scenario}_BusCost": 0.0,
            })

    fields = ["OBJECTID"]

    for scenario in SCENARIOS:
        fields += [
            f"PR_{scenario}_Time",
            f"PR_{scenario}_CO2",
            f"PR_{scenario}_Cost",
            f"PR_{scenario}_ZoneChange",
            f"PR_{scenario}_BusCost",
        ]

    index = {
        field: i
        for i, field in enumerate(fields)
    }

    with arcpy.da.UpdateCursor(
        BASE_TABLE,
        fields
    ) as cursor:

        for row in cursor:

            if row[0] not in updates:
                continue

            for field, value in updates[row[0]].items():
                row[index[field]] = value

            cursor.updateRow(row)


# ============================================================
# 6. PUBLIC TRANSPORT FARES
# ============================================================

# Full-price fare table used in the thesis.
# The starting zone is counted as the first zone.
FARES = {
    1: 2.60,
    2: 3.60,
    3: 4.70,
    4: 5.90,
    5: 7.10,
    6: 8.30,
    7: 9.40,
    8: 10.60,
    9: 11.70,
    10: 12.80,
    11: 13.90,
    12: 14.80,
    13: 15.80,
    14: 16.70,
    15: 17.70,
    16: 18.30,
    17: 18.90,
    18: 19.50,
    19: 20.00,
    20: 20.50,
    21: 21.00,
}


def fare_from_zonechanges(zone_changes):
    """
    Convert crossed zone boundaries to the full-price fare.

    The starting zone is counted as one additional zone.
    Fares for 21 or more zones are capped at EUR 21.00.
    """

    zone_changes = int(
        math.floor(
            float(zone_changes) + 0.5
        )
    )

    zone_count = max(
        0,
        zone_changes
    ) + 1

    if zone_count >= 21:
        return 21.00

    return FARES.get(
        zone_count,
        2.60
    )


def first_positive(values):
    """Return the first positive value in a sequence, otherwise zero."""

    for value in values:
        if value is not None and float(value) > 0:
            return value

    return 0.0


# ============================================================
# 7. ADD FINAL BUS AND P&R FARES
# ============================================================

def add_final_fares():
    """
    Copy the combined table and add the final public transport
    fares for bus and P&R.
    """

    if arcpy.Exists(FINAL_TABLE):
        arcpy.management.Delete(FINAL_TABLE)

    arcpy.management.CopyRows(
        BASE_TABLE,
        FINAL_TABLE
    )

    for field, field_type in [
        ("Bus_ZoneChange_Final", "LONG"),
        ("Bus_Fare_Final", "DOUBLE"),
        ("PR_ZoneChange_Final", "LONG"),
        ("PR_BusFare_Final", "DOUBLE"),
    ]:
        add_field(
            FINAL_TABLE,
            field,
            field_type
        )

    bus_zones = [
        f"Bus_{scenario}_ZoneChange"
        for scenario in SCENARIOS
    ]

    bus_costs = [
        f"Bus_{scenario}_Cost"
        for scenario in SCENARIOS
    ]

    bus_co2 = [
        f"Bus_{scenario}_CO2"
        for scenario in SCENARIOS
    ]

    pr_zones = [
        f"PR_{scenario}_ZoneChange"
        for scenario in SCENARIOS
    ]

    pr_costs = [
        f"PR_{scenario}_Cost"
        for scenario in SCENARIOS
    ]

    pr_bus_costs = [
        f"PR_{scenario}_BusCost"
        for scenario in SCENARIOS
    ]

    pr_co2 = [
        f"PR_{scenario}_CO2"
        for scenario in SCENARIOS
    ]

    helper_fields = [
        "Bus_ZoneChange_Final",
        "Bus_Fare_Final",
        "PR_ZoneChange_Final",
        "PR_BusFare_Final",
    ]

    fields = (
        bus_zones
        + bus_costs
        + bus_co2
        + pr_zones
        + pr_costs
        + pr_bus_costs
        + pr_co2
        + helper_fields
    )

    index = {
        field: i
        for i, field in enumerate(fields)
    }

    with arcpy.da.UpdateCursor(
        FINAL_TABLE,
        fields
    ) as cursor:

        for row in cursor:

            # ----------------------------------------------------
            # BUS FARE
            # ----------------------------------------------------

            # A positive CO2 value is used here as a simple indicator
            # that a valid bus connection is available.
            if first_positive(
                [row[index[field]] for field in bus_co2]
            ) > 0:

                zone_change = int(
                    math.floor(
                        first_positive(
                            [
                                row[index[field]]
                                for field in bus_zones
                            ]
                        ) + 0.5
                    )
                )

                fare = fare_from_zonechanges(
                    zone_change
                )

            else:
                zone_change = 0
                fare = 0.0

            row[
                index["Bus_ZoneChange_Final"]
            ] = zone_change

            row[
                index["Bus_Fare_Final"]
            ] = fare

            # The same final fare is written to all six scenarios.
            for field in bus_costs:
                row[index[field]] = fare

            # ----------------------------------------------------
            # PARK & RIDE PUBLIC TRANSPORT FARE
            # ----------------------------------------------------

            # A positive P&R CO2 value indicates that a valid combined
            # P&R route is available.
            if first_positive(
                [row[index[field]] for field in pr_co2]
            ) > 0:

                pr_zone_change = int(
                    math.floor(
                        first_positive(
                            [
                                row[index[field]]
                                for field in pr_zones
                            ]
                        ) + 0.5
                    )
                )

                pr_fare = fare_from_zonechanges(
                    pr_zone_change
                )

            else:
                pr_zone_change = 0
                pr_fare = 0.0

            row[
                index["PR_ZoneChange_Final"]
            ] = pr_zone_change

            row[
                index["PR_BusFare_Final"]
            ] = pr_fare

            # PR_Total_Cost already contains the car component and
            # P&R parking cost. Add the public transport fare once.
            for cost_field, bus_field in zip(
                pr_costs,
                pr_bus_costs
            ):

                existing_cost = row[
                    index[cost_field]
                ]

                if existing_cost is None:
                    existing_cost = 0.0

                row[
                    index[bus_field]
                ] = pr_fare

                row[
                    index[cost_field]
                ] = (
                    float(existing_cost)
                    + pr_fare
                )

            cursor.updateRow(row)


# ============================================================
# 8. RUN COMPLETE WORKFLOW
# ============================================================

def main():
    """Run the complete multimodal result-table workflow."""

    create_result_table()
    add_car_results()

    lookup = build_lookup()

    add_bus_results(lookup)
    add_pr_results(lookup)

    add_final_fares()

    print("Final multimodal result table created:")
    print(FINAL_TABLE)


if __name__ == "__main__":
    main()
