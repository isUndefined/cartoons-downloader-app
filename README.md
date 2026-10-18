# Cartoon Downloader Desktop

Windows application for discovering YouTube cartoons, downloading videos and sending
them to an Android device over MTP. Current version: **0.30.3**.

## Features

- Find new cartoons while excluding previously seen recommendations.
- Download in 360p, 480p, 720p or 1080p and play videos inside the application.
- Transfer videos to Android over MTP with filename and size verification.
- Cancel operations and retain source files after failed device transfers.
- Manage retained sources in Settings → Storage maintenance.
- Dark and light themes, including the native Windows 11 title bar.

Python, SQLite and native JavaScript modules power the application. Its own WinForms
window hosts a bundled WebView2 Fixed Version engine. Packaged releases include compiled Python code,
yt-dlp, Deno, FFmpeg and ffprobe. No installed browser or system Python is needed.
Internet access is used for installation, YouTube search and downloads.

## Source repository

This repository contains sources, UI assets, database migrations, packaging scripts,
dependency metadata and third-party licenses. Tests and validation reports have been
removed. User databases, browser profiles, downloads, temporary files, logs, binary
dependencies and generated releases are excluded from Git.

**A fresh clone needs binary dependencies before running or building.**
See [DEPENDENCIES.md](DEPENDENCIES.md). These components are already present in the
original prepared development workspace.

## Run and build

Requires Windows 10 x64 version 1607 or newer with .NET Framework 4.6.2+, or Windows 11 x64.
In a release folder, run `CartoonDownloader.exe` and keep its resource folders together.

In the prepared source workspace, double-click **BUILD_SETUP.bat**. It verifies files,
dependency hashes and tool startup, checks frontend formatting, then builds the
application and online installer. Failed checks stop the build. Previous clean builds are
preserved under `build/`.

From 0.30.3, Nuitka compiles the backend into native code. SQL migrations and text UI
assets are embedded in that executable; application `.py`, `.sql`, `.cs`, frontend
source files and build scripts are excluded from the installed folder. The MTP
helper is a compiled DLL. This makes casual inspection harder; it cannot prevent
reverse engineering or recovery of UI content served by the local application.
Developer sources remain in this repository. Compiler dependencies live only in
`build/compiler-tools/`; prepare them once using [DEPENDENCIES.md](DEPENDENCIES.md).

Release packages exclude Python debug symbols, use the official Deno 2.9.7 release
binary and share FFmpeg libraries between ffmpeg and ffprobe. Keep all files in
`tools/ffmpeg/` together. WebView2 remains fully bundled. Dependency origins and
archive hashes are recorded in each component's `DEPENDENCY.json`; executable
and FFmpeg DLL hashes are checked through `BUNDLED_COMPONENTS.sha256`.

Increase `__version__` in `cartoon_downloader/__init__.py` before publishing an update.
Keep the installer AppId unchanged.

```powershell
.\BUILD_SETUP.bat --no-pause --check-only
.\runtime\python\python.exe -B verify_package.py
.\tools\deno\deno.exe fmt --check static
```

Output: `dist/CartoonDownloader-<version>-Online-Setup/CartoonDownloader-Online-Setup.exe`.
The compiled backend, its required Python libraries and license terms are embedded in the installer. It downloads
pinned yt-dlp, Deno, FFmpeg and WebView2 components over HTTPS, verifies their archives
and every required extracted file, then installs the application. Download failures
leave the existing installation unchanged. The installed window continues to use its
private Fixed Version WebView2 engine. No component downloads occur at app startup.

`BUILD_SETUP.bat --offline` builds the full installer instead. Both build modes are
offline; network access is required by the online installer when installing.
Download versions, URLs, archive hashes and directory layouts are pinned in
`packaging/online-components.json`.

See [setup.md](setup.md) for building and [INSTALLATION.md](INSTALLATION.md) for
installation, updates and removal. For source development, build the package once;
`START_WINDOWS.bat` then runs the source server with that package's native window.
`--no-browser` runs only the local server; `--diagnostics` prints read-only diagnostics.

## Data and reliability

Portable mode stores data beside the application. Installed mode stores the library,
settings, logs, staging and relative download folders under
`%LOCALAPPDATA%\Cartoon Downloader`. `--data-dir` selects another data location.
Installing does not migrate a portable library automatically. Uninstalling keeps
user data and downloaded media.

The loopback server validates Host, Origin and CSRF tokens. One application instance
owns each data directory. Closing the window stops workers and child tools before
releasing the directory lock.

MTP completion requires Windows confirmation and exact filename and size verification.
Device names preserve the video ID and extension within a 120-byte UTF-8 limit.
Failed or cancelled transfers retain the source. Retained media has no automatic
expiry; deletion requires explicit selection and confirmation.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for dependency terms and
[todo.md](todo.md) for remaining release work.
