"""Column contract for the NASA C-MAPSS FD001 telemetry text files."""

SETTING_COLUMNS = tuple(f"setting_{index}" for index in range(1, 4))
SENSOR_COLUMNS = tuple(f"sensor_{index}" for index in range(1, 22))
FD001_COLUMNS = ("unit_id", "cycle", *SETTING_COLUMNS, *SENSOR_COLUMNS)
FD001_COLUMN_COUNT = len(FD001_COLUMNS)

