import datetime
import os

def calculate_version():
    """Calculates the semantic version based on date."""
    now = datetime.datetime.now()
    major_version = (now.year - 2025) * 4 + (now.month - 1) // 3 + 1 
    try:
        with open("files/minor_version.txt", "r") as f:
            minor_version = int(f.read().strip()) + 1
    except FileNotFoundError:
        minor_version = 1

    with open("files/minor_version.txt", "w") as f:
        f.write(str(minor_version))

    return f"{major_version}.{minor_version}"

print(calculate_version())