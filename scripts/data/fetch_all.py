"""Run every fetcher in order. Each one is resumable or cheap to repeat."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
STEPS = [
    ["fetch_trek_tiles.py"],
    ["fetch_usgs_rasters.py"],
    ["fetch_msl.py"],
    ["fetch_space_weather.py"],
]

for step in STEPS:
    print(f"== {' '.join(step)}", flush=True)
    subprocess.run([sys.executable, "-u", str(HERE / step[0]), *step[1:]], check=True, cwd=HERE)
