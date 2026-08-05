"""
Local YouTube playlist downloader.

Run:
    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt
    python app.py

Open http://127.0.0.1:5000

ffmpeg must be installed and available on PATH.
"""

import os
import re
import shutil
import tempfile
import threading
import queue
import uuid
import time
from pathlib import Path

from flask import Flask, request, jsonify, Response, send_file, render_template
from yt_dlp import YoutubeDL

app = Flask(__name__)

JOBS = {}
JOBS_LOCK = threading.Lock()

ALLOWED_MP3 = {"128", "192", "256", "320"}
ALLOWED_MP4 = {"360", "480", "720", "1080"}
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


def sizeof_fmt(num):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(num) < 1024:
            return f"{num:3.1f}{unit}"
        num /= 1024
    return f"{num:.1f}TiB"


def cleanup_old_jobs(max_age=3600):
    now = time.time()
    with JOBS_LOCK:
        old_ids = [
            job_id for job_id, job in JOBS.items()
            if job.get("finished_at") and now - job["finished_at"] > max_age
        ]
        for job_id in old_ids:
            job = JOBS.pop(job_id)
            zip_path = job.get("zip_path")
            if zip_path:
                try:
                    os.remove(zip_path)
                except FileNotFoundError:
                    pass


class QueueLogger:
    def __init__(self, q):
        self.q = q

    def debug(self, msg):
        if not msg.startswith("[debug]"):
            self.q.put(msg)

    def info(self, msg):
        self.q.put(msg)

    def warning(self, msg):
        self.q.put(f"WARNING: {msg}")

    def error(self, msg):
        self.q.put(f"ERROR: {msg}")


def make_progress_hook(q, state, total_tracks):
    def hook(d):
        status = d.get("status")

        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)

            if total:
                current_pct = downloaded / total * 100

                overall_pct = (
                    (state.get("completed_tracks", 0) + current_pct / 100)
                    / total_tracks
                ) * 100

                if overall_pct - state.get("last_pct", -5) >= 1 or overall_pct >= 99.9:
                    state["last_pct"] = overall_pct
                    q.put(f"[download] {overall_pct:5.1f}% playlist")

        elif status == "finished":
            state["completed_tracks"] += 1
            state["last_pct"] = -5

            name = os.path.basename(d.get("filename", ""))
            q.put(f"[download] finished: {name}")

    return hook


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/fetch", methods=["POST"])
def fetch_playlist():
    cleanup_old_jobs()

    data = request.get_json(silent=True) or {}
    url = str(data.get("url") or "").strip()

    try:
        limit = int(data.get("limit") or 50)
    except (TypeError, ValueError):
      return jsonify({"error": "limit must be a number"}), 400

    limit = max(1, min(limit, 500))

    if not url:
        return jsonify({"error": "no URL provided"}), 400

    ydl_opts = {
        "quiet": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "noplaylist": False,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    entries = info.get("entries")
    if entries is None:
        entries = [info]

    tracks = []
    for e in entries:
        if not e:
            continue

        title = e.get("title") or ""

        if title in ("Private video", "Deleted video"):
            continue

        if e.get("availability") in ("private", "needs_auth"):
            continue

        vid = str(e.get("id") or "")

        if not VIDEO_ID_RE.fullmatch(vid):
            continue

        title = e.get("title") or "untitled"
        duration = e.get("duration")
        thumb = None

        thumbs = e.get("thumbnails") or []
        if thumbs:
            thumb = thumbs[-1].get("url")

        if not thumb:
            thumb = f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"

        tracks.append({
            "id": vid,
            "index": len(tracks) + 1,
            "title": title,
            "duration": duration,
            "thumbnail": thumb,
        })

    if not tracks:
        return jsonify({"error": "no playable videos were found"}), 400

    return jsonify({
        "playlist_title": info.get("title") or "playlist",
        "tracks": tracks,
    })


def run_job(job_id, playlist_url, playlist_items, fmt, quality):
    job = JOBS[job_id]
    q = job["queue"]
    tmp_dir = tempfile.mkdtemp(prefix="ytpl_")
    job["tmp_dir"] = tmp_dir
    state = {
    "last_pct": -5,
    "completed_tracks": 0,
}

    common_opts = {
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "sleep_interval": 1,
        "max_sleep_interval": 5,
        "quiet": True,
        "no_warnings": False,
        "noplaylist": True,
        "restrictfilenames": False,
        "windowsfilenames": True,
        "noprogress": True,
        "ignoreerrors": True,
        "outtmpl": os.path.join(tmp_dir, "%(title)s.%(ext)s"),
        "logger": QueueLogger(q),
        "progress_hooks": [make_progress_hook(q, state, len(playlist_items))],
        "js_runtimes": {"deno": {}},
        "postprocessors": [{"key": "FFmpegMetadata"}],
    }

    common_opts["playlist_items"] = ",".join(map(str, playlist_items))

    if fmt == "mp3":
        ydl_opts = {
            **common_opts,
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": quality,
            }],
        }
    else:
        height = quality
        ydl_opts = {
            **common_opts,
            "format": (
                f"bestvideo[height<={height}]+bestaudio/"
                f"best[height<={height}]/best"
            ),
            "merge_output_format": "mp4",
        }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([playlist_url])
            state["completed_tracks"] = len(playlist_items)
    except Exception as e:
        q.put(f"ERROR: {e}")

    q.put(f"selected {len(playlist_items)} tracks, creating ZIP...")

    zip_base = os.path.join(tempfile.gettempdir(), f"ytpl_{job_id}")

    try:
        zip_path = shutil.make_archive(zip_base, "zip", tmp_dir)
        job["zip_path"] = zip_path
        job["status"] = "done"
        job["finished_at"] = time.time()
        q.put("__DONE__")
    except Exception as e:
        job["status"] = "error"
        job["finished_at"] = time.time()
        q.put(f"ERROR: ZIP creation failed: {e}")
        q.put("__DONE__")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.route("/api/download", methods=["POST"])
def start_download():
    cleanup_old_jobs()

    data = request.get_json(silent=True) or {}

    playlist_url = str(data.get("playlist_url") or "").strip()
    playlist_items = data.get("playlist_items") or []

    fmt = str(data.get("format") or "mp3")
    quality = str(data.get("quality") or "192")

    if not playlist_url:
        return jsonify({"error": "no playlist URL"}), 400

    if not isinstance(playlist_items, list):
        return jsonify({"error": "playlist_items must be a list"}), 400

    try:
        playlist_items = sorted(set(int(i) for i in playlist_items))
    except (TypeError, ValueError):
        return jsonify({"error": "playlist_items must contain integers"}), 400

    if not playlist_items:
        return jsonify({"error": "no tracks selected"}), 400

    if len(playlist_items) > 500:
        return jsonify({"error": "too many tracks selected"}), 400

    if fmt not in ("mp3", "mp4"):
        return jsonify({"error": "invalid format"}), 400

    if fmt == "mp3" and quality not in ALLOWED_MP3:
        return jsonify({"error": "invalid MP3 bitrate"}), 400

    if fmt == "mp4" and quality not in ALLOWED_MP4:
        return jsonify({"error": "invalid MP4 quality"}), 400

    if shutil.which("ffmpeg") is None:
        return jsonify({
            "error": "ffmpeg was not found on PATH; it is required for MP3 conversion and MP4 merging"
        }), 500

    job_id = uuid.uuid4().hex

    with JOBS_LOCK:
        JOBS[job_id] = {
            "queue": queue.Queue(),
            "status": "running",
            "zip_path": None,
            "tmp_dir": None,
            "finished_at": None,
        }

    thread = threading.Thread(
        target=run_job,
        args=(job_id, playlist_url, playlist_items, fmt, quality),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/progress/<job_id>")
def progress(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "unknown job"}), 404

    def generate():
        q = job["queue"]

        while True:
            try:
                line = q.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue

            if line == "__DONE__":
                if job["status"] == "done":
                    yield f"event: done\ndata: /api/file/{job_id}\n\n"
                else:
                    yield "event: failed\ndata: job failed\n\n"
                break

            safe = str(line).replace("\r", " ").replace("\n", " ")
            yield f"data: {safe}\n\n"

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@app.route("/api/file/<job_id>")
def get_file(job_id):
    job = JOBS.get(job_id)

    if not job or not job.get("zip_path"):
        return jsonify({"error": "file not ready"}), 404

    zip_path = job["zip_path"]

    if not os.path.exists(zip_path):
        return jsonify({"error": "file has expired"}), 404

    return send_file(
        zip_path,
        as_attachment=True,
        download_name="playlist.zip",
        mimetype="application/zip",
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, threaded=True, debug=False)
