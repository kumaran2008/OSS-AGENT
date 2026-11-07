import os
import csv
from datetime import datetime

# Project folder to scan
ROOT = os.getcwd()

# Output CSV file
OUTPUT = os.path.join(ROOT, "all_file_timestamps.csv")


def format_timestamp(timestamp):
    if timestamp is None:
        return "Not available"

    return datetime.fromtimestamp(timestamp).astimezone().isoformat(
        timespec="microseconds"
    )


file_count = 0

with open(OUTPUT, "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.writer(csvfile)

    writer.writerow([
        "File Name",
        "Full Path",
        "Creation Time",
        "Last Modified Time",
        "Metadata Change Time",
        "Last Access Time",
        "File Size (Bytes)"
    ])

    for folder, dirs, files in os.walk(ROOT):

        # Avoid scanning Git internals
        dirs[:] = [d for d in dirs if d != ".git"]

        for filename in files:

            filepath = os.path.join(folder, filename)

            # Skip the generated CSV itself
            if filepath == OUTPUT:
                continue

            try:
                stats = os.stat(filepath)

                creation_time = getattr(
                    stats, "st_birthtime", None
                )

                writer.writerow([
                    filename,
                    filepath,
                    format_timestamp(creation_time),
                    format_timestamp(stats.st_mtime),
                    format_timestamp(stats.st_ctime),
                    format_timestamp(stats.st_atime),
                    stats.st_size
                ])

                file_count += 1

            except Exception as error:
                print(f"Error reading {filepath}: {error}")

print("\nTimestamp extraction completed!")
print(f"Files scanned: {file_count}")
print(f"CSV saved to: {OUTPUT}")
