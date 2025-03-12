import datetime
import os

def calculate_version():
    """Calculates the semantic version based on date."""
    now = datetime.datetime.now()
    major_version = (now.year - 2025) * 4 + (now.month - 1) // 3 + 1 
    minor_version_file = "files/minor_version.txt" 
    try:
        with open(minor_version_file, "r") as f:
            content = f.read().strip()
            if content:
                minor_version = int(content) + 1
            else:
                minor_version = 1 # if the file is empty, start at 1.
    except FileNotFoundError:
        minor_version = 1 # if the file does not exist, start at 1.
    except ValueError:
        minor_version = 1 # if the content is invalid, start at 1.

    os.makedirs("files", exist_ok=True) # ensure the directory exists.
    with open(minor_version_file, "w") as f:
        f.write(str(minor_version))

    return f"{major_version}.{minor_version}"

print(calculate_version())