# yt playlist downloader

A local Flask frontend for downloading selected videos from a YouTube playlist with `yt-dlp`, converting them to MP3 or merging them into MP4, then packaging the results into a ZIP.

## Features

- Playlist URL input
- Configurable fetch limit from 1 to 500 tracks
- Compact track list with thumbnails, durations, and checkboxes
- Select all / select none
- MP3 output at 128, 192, 256, or 320 kbps
- MP4 output capped at 360p, 480p, 720p, or 1080p
- Live `yt-dlp` output through server-sent events
- Fixed-height, scrollable log panel
- Temporary download directory
- Automatic ZIP creation
- Automatic cleanup of finished jobs after one hour

## Linux setup

Install FFmpeg:

```bash
sudo apt install ffmpeg
```

Create and activate a virtual environment:

```bash
cd yt-playlist-downloader
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run:

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Notes

The server intentionally binds to `127.0.0.1`, so only the same PC can access it.

If you change the host to `0.0.0.0` to use the site from another device, add authentication before exposing it on a LAN or the internet. The download endpoint causes your PC to run `yt-dlp` jobs.

The ZIP file remains available for up to one hour after the job finishes, then the next request triggers cleanup.
