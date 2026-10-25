# ClipAI Pro — self-hosted AI clipping starter

A full-stack starter for a Razycut-style workflow: upload a video, transcribe it with Whisper, rank possible highlights, search the transcript, render vertical clips with burned-in subtitles using FFmpeg, and optionally upload rendered clips to YouTube using your own Google OAuth credentials.

## What is included
- Video upload with configurable size limit.
- Whisper speech transcription (runs on the server).
- Heuristic highlight scoring and suggested 15–45 second clip windows.
- Search transcript and timestamps.
- Manual clip range creation.
- FFmpeg rendering to vertical 9:16, square 1:1, or landscape 16:9.
- Burned-in subtitle captions from Whisper transcript.
- Optional YouTube upload integration with user OAuth.
- Responsive mobile web UI.

## Honest limitations
- "Viral" scoring is a heuristic, not a guarantee of virality.
- This does not download arbitrary YouTube URLs. Upload a video you own or have permission to use.
- YouTube auto-posting requires Google Cloud project/OAuth setup, API quota, consent, and account authorization. New/unaudited OAuth apps may be limited to test users. Keep uploads private until you have tested.
- The free Render plan may sleep, has limited CPU/RAM and ephemeral storage. Large videos or Whisper can time out; persistent storage and more compute may cost money. Do not treat free cloud hosting as guaranteed.
- A local server cannot run directly on iPhone alone. The app must run on a server or computer; iPhone Safari is the control panel. This project is ready for deployment from GitHub, but you must configure hosting.
- For privacy, uploaded videos are stored on the server where deployed. Use a trusted host and delete files when finished.

## Deploy from an iPhone (GitHub + Render)
1. Download and extract the ZIP on your iPhone (Files app).
2. In GitHub, create a repository named `clipai-pro`.
3. Add the project files preserving their folders. Easiest on iPhone: open each file in a code editor app or use GitHub's **Add file → Create new file** for small files; for a ZIP upload, use a browser-based Git client that supports extracting/uploading multiple files, or use a computer later.
4. On Render, create a new **Blueprint** from the GitHub repository. Render reads `render.yaml` and builds the Docker image.
5. Wait for deployment. Open the Render service URL; it should show the ClipAI Pro dashboard.
6. Upload a short MP4 first (try under 30 seconds), click **Analyze video**, wait for transcription, then render one suggested clip.

## YouTube posting setup
1. In Google Cloud Console, create a project and enable **YouTube Data API v3**.
2. Configure OAuth consent screen and create an OAuth Client ID of type Web application.
3. Add the exact callback URL `https://YOUR-SERVICE.onrender.com/api/youtube/callback` as an authorized redirect URI.
4. Download the client JSON securely. The server needs the JSON file and environment variables:
   - `YOUTUBE_CLIENT_SECRETS=/path/to/client_secret.json`
   - `YOUTUBE_REDIRECT_URI=https://YOUR-SERVICE.onrender.com/api/youtube/callback`
5. Add the JSON file securely to the server environment/storage. Do not commit secrets to GitHub.
6. In this app, choose Connect YouTube and approve access. The app stores an OAuth token in its data directory.
7. Render a clip and use its YouTube post controls. Start with `private` visibility.
8. Google may require app verification or test-user configuration. API quota applies.

## Run locally (computer)
Requires Python 3.11+, FFmpeg, and pip:
```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```
Open `http://localhost:8000`.

## API
- `GET /api/health`
- `POST /api/upload` multipart `file`
- `POST /api/analyze/{job_id}`
- `GET /api/jobs/{job_id}`
- `GET /api/search/{job_id}?q=keyword`
- `POST /api/manual-clip/{job_id}` multipart `start`, `end`, `title`
- `POST /api/render/{job_id}/{clip_id}` multipart `ratio`, `quality`, `burn`
- `POST /api/youtube/auth-url`
- `POST /api/youtube/post/{job_id}/{clip_id}` multipart `title`, `description`, `privacy`

## License
This project code is provided as a starter. Dependencies retain their own licenses.
