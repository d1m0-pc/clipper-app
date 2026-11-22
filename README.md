# Clipper - viral moments from YouTube

Clipper is a Windows app that finds the most-watched parts of YouTube videos
and cuts them into short clips for TikTok, YouTube Shorts and Instagram Reels.

**What the app does:**

- Accepts a link to a single video **or** a channel link (e.g. `https://youtube.com/@waveform`).
  For a channel it shows the latest videos (title, date, views, duration).
- Reads YouTube's **"Most replayed"** graph (the parts of a video people most often
  rewind and watch again) and shows the 10 strongest segments, with a score.
  - The first 60 seconds are skipped (the intro is always high).
  - Neighboring strong segments are merged into one longer moment.
- Downloads English subtitles and shows the text of each moment (starting 15 seconds earlier).
- If a video has no "Most replayed" graph, it reads up to 500 top comments,
  finds timestamps (e.g. "4:12 best part") and shows the most mentioned
  moments with example comments.
- Cuts the selected part of the video (downloads **only that part**) in the original 16:9
  format or vertical 9:16 (center crop) for Shorts/TikTok/Reels.
- Exports results to a `.txt` or `.csv` (Excel) file.

---

## What you need

- Windows 10 or 11
- An internet connection
- Python 3.14 (free)
- ffmpeg (free, for cutting clips)
- Deno (free, needed for yt-dlp to work with YouTube)

---

## Step-by-step installation

### Step 1: Install Python

1. Open <https://www.python.org/downloads/> and click **Download Python 3.14**.
2. Run the downloaded installer.
3. **IMPORTANT:** on the first screen, check the box **"Add python.exe to PATH"**.
4. Click **Install Now** and wait for it to finish.

### Step 2: Install ffmpeg and Deno

1. Click **Start**, type `cmd` and press **Enter**. A black window
   (Command Prompt) will open.
2. Type (or paste) the following command and press **Enter**:

   ```
   winget install Gyan.FFmpeg
   ```

   If it asks you to accept the terms, type `Y` and press **Enter**.
3. Then type this command too and press **Enter**:

   ```
   winget install DenoLand.Deno
   ```

4. When both installations are done, **close** the black window.

> If you skip this, that's fine: `setup.bat` and the app itself will offer
> to install whatever is missing (tab **"Tools & help"** → **"Install now"**).

### Step 3: Install the app

1. Open the `clipper` folder.
2. Double-click **`setup.bat`**.
3. Wait for the message **"Setup is complete."** (the first time this can take
   a few minutes) and press any key.

### Step 4: Start the app

Double-click **`start.bat`**. Do this every time you want to use
the app. (Tip: right-click `start.bat` → *Send to* → *Desktop (create shortcut)*
to get a shortcut on your desktop.)

If something is missing at startup, the app shows a **"Missing tools"** dialog.

---

## How to use it

### A single video

1. Copy the video link from your browser (e.g. `https://www.youtube.com/watch?v=...`).
2. Paste it into the **"YouTube link"** field (or click **"Paste"**) and click **"Load"**.
3. Wait for the analysis to finish (the bar at the bottom of the window shows progress, and
   below it are messages about what is happening right now).

### A channel

1. Paste a channel link, e.g. `https://youtube.com/@waveform`, and click **"Load"**.
2. A list of the latest videos appears (20 by default).
3. Select one or more videos (hold **Ctrl** or **Shift** while clicking) and
   click **"Analyze selected"**. Double-clicking a video analyzes just that one.
4. Click a video in the list to see its results.

### Results

- **Graph**: blue bars are "Most replayed", orange bars are the best moments,
  red is the selected moment, and gray is the skipped intro. Clicking an orange bar
  selects that moment.
- **Moments table**: start, end, duration and score of each moment.
- **Right side**: a link to that exact spot in the video, the transcript (text from subtitles) and,
  if the moments come from comments, example comments.

### Cutting a clip

1. Click a moment in the table. The **Start** and **End** fields fill in automatically
   (start is 15 seconds before the moment, so the clip has a lead-in).
2. Change the times if you like (format `m:ss` or `h:mm:ss`, e.g. `12:34`).
   **"Preview on YouTube"** opens the video at the entered start time.
3. Choose **"Original 16:9"** or **"Vertical 9:16"**.
4. Click **"Cut"**. The finished clip is saved in the **`clips`** folder next to the app,
   and the file name is the video title + time, e.g. `Video title_12m34s-13m10s_9x16.mp4`.
   **"Open clips folder"** opens that folder.

### Exporting results

Click **"Export TXT"** (easy to read) or **"Export CSV"** (opens in Excel).
All videos analyzed in the current session are exported. Dates are written in ISO
format (e.g. `2026-10-15`), and the CSV separator follows your Windows regional
list separator, so Excel opens it in columns.

---

## Settings ("Settings" tab)

| Setting | Default | Description |
|---|---|---|
| Path to cookies.txt | empty | optional, see below |
| Videos per channel | 20 | how many of the latest videos are shown for a channel |
| Seconds before segment | 15 | the transcript and clip start this much earlier |
| Skip intro (seconds) | 60 | start of the video that is ignored on the graph |
| Number of top segments | 10 | how many graph segments are picked |
| Clips folder | `clips` | where cut clips are saved |

Click **"Save settings"** after making changes.

### cookies.txt (optional)

Cookies help when YouTube asks you to sign in, to confirm "you're not a bot", or returns error 429.

> **WARNING:** `cookies.txt` contains your Google account session. Anyone who gets this
> file can get into your account. **Never share it**, never send it to anyone and never
> upload it to the internet. If you share it by accident, immediately sign out of your
> Google account on all devices (myaccount.google.com → Security).

How to create it:

1. In your browser (Brave/Chrome), install the extension **"Get cookies.txt LOCALLY"**
   (Chrome Web Store).
2. Open <https://www.youtube.com> and make sure you are signed in.
3. Click the extension icon and choose **Export** - save the file, e.g. in Documents.
4. In the app: **Settings** → **"Browse..."** → choose that file → **"Save settings"**.

The app intentionally **does not read** cookies directly from the Brave/Chrome browser, because
that does not work on Windows (error "Could not copy Chrome cookie database").

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Error **"nsig extraction failed"** or **"Precondition check failed"** | Tab **"Tools & help"** → **"Check/update yt-dlp"**, then restart the app. Also check that Deno is installed (`winget install DenoLand.Deno`). |
| **"Requested format is not available"** | Update yt-dlp (same button) and check Deno. |
| **Error 429 (Too Many Requests)** | YouTube is temporarily limiting requests. The app automatically waits 30, 60, then 120 seconds and tries again (the countdown is shown at the bottom of the window). If it still fails, wait 15-30 minutes or add cookies.txt. |
| **"Could not copy Chrome cookie database"** | Use a cookies.txt file (see above). |
| Video has **no "Most replayed"** graph | Normal for new or less-watched videos. The app then uses timestamps from comments. |
| The **"Cut"** button is gray | ffmpeg is not installed: `winget install Gyan.FFmpeg`, then **"Tools & help"** → **"Recheck"**. |
| No transcript | The video has no English subtitles, or YouTube is not providing them right now (429). Moments and cutting still work. |
| `winget` is not recognized | Install **"App Installer"** from the Microsoft Store, or download ffmpeg from <https://www.gyan.dev/ffmpeg/builds/> and Deno from <https://deno.com>. |
| Nothing happens after `start.bat` | Run `setup.bat` again. Details of all errors are in the file `logs\clipper.log`. |
| CSV in Excel is all in one column | In Excel: **Data** → **From Text/CSV** and choose the right separator (`;` or `,`). |

---

## How the score is computed

- **"Most replayed" (heatmap):** YouTube splits the video into ~100 parts and gives each
  a value of 0-100 (most-watched part = 100). The app skips the first 60 seconds,
  takes the 10 strongest parts and merges neighbors. A moment's score is its strongest part.
- **Comments:** every comment with a timestamp gives that minute `1 + number of likes`.
  Overlapping moments (e.g. 3:58 and 4:00) are merged into one, and each comment is
  counted only once. Comments with more than 4 timestamps (chapter lists) and the
  `0:00` timestamp are ignored.

---

## For developers

```
clipper/
├── main.py                 # entry point (start.bat runs it)
├── start.bat / setup.bat   # start / install for users
├── run_tests.bat           # runs the tests
├── requirements.txt
├── clipper_app/
│   ├── heatmap.py          # heatmap parsing, intro skipping, merging
│   ├── comments.py         # timestamps from comments, ranking by likes
│   ├── transcript.py       # subtitle selection and json3 parser
│   ├── analyzer.py         # analysis flow: heatmap -> comments -> subtitles
│   ├── youtube.py          # all yt-dlp work (channel list, metadata, comments)
│   ├── clipping.py         # downloading part of a video and ffmpeg 9:16
│   ├── retry.py            # retries on HTTP 429 (30 s, 60 s, 120 s)
│   ├── environment.py      # finding ffmpeg/Deno, updating yt-dlp
│   ├── errors.py           # user-friendly error messages
│   ├── exporter.py         # export to TXT/CSV
│   ├── config.py           # settings (settings.json)
│   └── gui/                # tkinter window (tabs, graph, background jobs)
└── tests/                  # pytest tests (no internet needed)
```

Tests: double-click `run_tests.bat` or run `.venv\Scripts\python -m pytest`.
Check that the window opens: `.venv\Scripts\python main.py --smoke-test`.
