# Flask-only backend: yt-dlp (for downloading) + ytmusicapi for search

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from ytmusicapi import YTMusic
import os
import subprocess
import shutil
from pathlib import Path
from collections import OrderedDict

app = Flask(__name__)
CORS(app)

ytmusic = YTMusic()
cmd = [
    "chmod",
    "+x",
    "./yt-dlp"
]
result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
DOWNLOAD_DIR = Path("downloads")
MAX_FILES = 10
ALLOWED_EXTENSIONS = {".mp3", ".webm", ".m4a"}

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# -------------------- Cache --------------------
search_cache = OrderedDict()
MAX_CACHE_SIZE = 15

# -------------------- Utility --------------------

def cleanup_downloads_dir():
    files = [f for f in DOWNLOAD_DIR.iterdir() if f.suffix.lower() in ALLOWED_EXTENSIONS]
    file_stats = [
        {
            "file": f,
            "time": f.stat().st_atime,
            "size": f.stat().st_size
        }
        for f in files
    ]
    file_stats.sort(key=lambda x: x["time"])
    total_size = sum(f["size"] for f in file_stats)
    max_size = 500 * 1024 * 1024

    to_delete = []
    while len(file_stats) - len(to_delete) > MAX_FILES or total_size > max_size:
        file_to_delete = file_stats[len(to_delete)]
        to_delete.append(file_to_delete)
        total_size -= file_to_delete["size"]

    for f in to_delete:
        try:
            f["file"].unlink()
        except Exception as e:
            print(f"Error deleting {f['file']}: {e}")

# -------------------- /search Endpoint --------------------

@app.route("/search")
def search():
    query = request.args.get("q")
    if not query or len(query) < 2:
        return jsonify({"error": "Missing or too short query"}), 400

    if query in search_cache:
        search_cache.move_to_end(query)
        return jsonify(search_cache[query])

    try:
        results = ytmusic.search(query, limit=10)
        search_cache[query] = results
        search_cache.move_to_end(query)
        if len(search_cache) > MAX_CACHE_SIZE:
            search_cache.popitem(last=False)
        return jsonify(results)
    except Exception as e:
        print("Search error:", e)
        return jsonify({"error": "Search failed"}), 500

# -------------------- /download Endpoint --------------------

@app.route("/download")
def download():
    video_id = request.args.get("id")
    audio_format = request.args.get("format", "mp3")
    if not video_id:
        return jsonify({"error": "Missing video ID"}), 400

    expected_file = DOWNLOAD_DIR / f"{video_id}.{audio_format}"
    if expected_file.exists():
        # Touch file to update access time
        expected_file.touch()
        return jsonify({
            "message": "Already downloaded",
            "filename": expected_file.name,
            "url": f"/file/{expected_file.name}"
        })

    video_url = f"https://youtube.com/watch?v={video_id}"
    try:
        output_path = str(DOWNLOAD_DIR / "%(id)s.%(ext)s")
        cmd = [
            "./yt-dlp", "-x", "--audio-format", audio_format,
            "-o", output_path,
            video_url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        cleanup_downloads_dir()

        match = None
        for line in result.stdout.splitlines():
            if "Destination:" in line:
                match = line.split("Destination:", 1)[1].strip()
                break

        if match:
            filename = os.path.basename(match)
            return jsonify({
                "message": "Downloaded",
                "filename": filename,
                "url": f"/file/{filename}"
            })
        return jsonify({"error": "Could not detect output filename"}), 500
    except Exception as e:
        return jsonify({"error": "Download failed", "details": str(e)}), 500

# -------------------- File Serving --------------------

@app.route("/file/<path:filename>")
def serve_file(filename):
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)

# -------------------- Run Server --------------------

if __name__ == "__main__":
    cleanup_downloads_dir()
    app.run(host='0.0.0.0', port=5000)  