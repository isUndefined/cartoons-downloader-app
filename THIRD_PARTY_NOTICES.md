# Third-party notices

Cartoon Downloader Desktop bundles third-party runtime components so the application can run without downloading dependencies at startup.

## Python

A redistributable CPython runtime is bundled under `runtime/python/`.
The CPython and bundled dependency license texts are included under `runtime/python/licenses/`.

## yt-dlp

A Windows yt-dlp executable is bundled under `tools/yt-dlp/`.
yt-dlp's project source is licensed under the Unlicense. The standalone Windows executable also bundles third-party components with additional licenses; their notices are included in `tools/yt-dlp/THIRD_PARTY_LICENSES.txt`.

## Deno

A Deno JavaScript runtime is bundled under `tools/deno/` and is licensed under the MIT License.
The license text is included in `tools/deno/LICENSE.txt`.

## FFmpeg

FFmpeg and ffprobe are bundled under `tools/ffmpeg/` from an LGPL Windows build.
The included license text is at `tools/ffmpeg/LICENSE.txt`.

## Lucide Icons

The UI vendors a small local SVG subset derived from Lucide Icons.
Lucide is licensed under the ISC License.

Copyright (c) Lucide Contributors.

Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted, provided that the above copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

## Microsoft WebView2

The native window bundles the unmodified Microsoft WebView2 Fixed Version Runtime
155.0.4283.62 x64 under `tools/webview2/runtime/`. It is distributed under Microsoft's
proprietary runtime terms, including codec, data collection and warranty notices,
reproduced in `tools/webview2/RUNTIME-LICENSE.txt` and `RUNTIME-LICENSE.html`.
Use and further distribution of this component require acceptance of those terms.
The application does not enable Windows account single sign-on or browser synchronization.
Microsoft's privacy statement is https://aka.ms/privacy.
The included engine has Microsoft Defender SmartScreen enabled by default and can
collect and send end-user information to Microsoft as described in that privacy
statement and https://learn.microsoft.com/en-us/microsoft-edge/privacy-whitepaper#smartscreen.

The SDK 1.0.4258.31 managed assemblies and native loader are supplied under the
Microsoft BSD-style license reproduced in `tools/webview2/LICENSE.txt`.
Chromium and other component credits are embedded in the unmodified runtime; its
`show_third_party_software_licenses.bat` displays them. Additional included license
files (Widevine and Trust Protection Lists) are retained in their original folders.
Origins, versions and archive hashes are recorded in `tools/webview2/DEPENDENCY.json`.
