import subprocess
import sys

# List of packages to install
packages = [
    "nextcord",
    "yt-dlp",
    "beautifulsoup4",
    "aiohttp",
    "sqlite3",
    "requests",
    "lyricsgenius",
    "spotipy"
]

# Install each package using pip
for package in packages:
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

print("All packages have been installed.")
