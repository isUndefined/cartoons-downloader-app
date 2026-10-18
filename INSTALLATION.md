# Installing Cartoon Downloader

Run `CartoonDownloader-Online-Setup.exe` with an internet connection. Python is
included; yt-dlp, Deno, FFmpeg and the private WebView2 engine are downloaded from
pinned upstream sources. Archive hashes and all required files are checked before
the existing installation is changed. A failed download can be retried or cancelled.
Windows 10 x64 version 1607 or newer
with .NET Framework 4.6.2+, or Windows 11 x64, is required.

The online installer downloads approximately 428 MiB of components. The installed
application remains approximately 968 MiB, with its own window and bundled engine.
The full `CartoonDownloader-Setup.exe`, if supplied separately, needs no downloads.
This first online version downloads the component set on each installation. A retry
within the same setup session reuses files that already passed their hash check.

Installation is for the current Windows user and does not require administrator
rights. The default program folder is `%LOCALAPPDATA%\Programs\Cartoon Downloader`.
A Start menu shortcut is created; a desktop shortcut is optional. The last page
can launch the application after installation.

The database, settings, logs, temporary files and relative download folders are
stored separately under `%LOCALAPPDATA%\Cartoon Downloader`. The installer never
imports an older portable library automatically. Portable folders and external
download folders remain where they were; keep them until any deliberate migration.

To update, close the application and run the newer installer. It reuses the
installation folder and preserves the library and settings. Installation and
uninstallation are refused while a current application launcher is running;
downloads and phone transfers are never forcibly stopped by the installer.
From 0.30.1 onward, upgrades remove obsolete Python debug symbols only when they
match the previous installation's SHA256 inventory. Modified or unlisted files
and redirected paths are preserved.

To uninstall, use Windows Settings → Apps → Installed apps → Cartoon Downloader →
Uninstall. Program files and its shortcuts are removed. **Settings, library,
downloads and retained transfer sources are kept.** Reinstalling reconnects to
the same user data. This installer does not include a delete-personal-data option.

Third-party license terms are displayed during installation and are included
with the application. See `THIRD_PARTY_NOTICES.md` and
`tools/webview2/RUNTIME-LICENSE.txt` for Microsoft's runtime, codec and privacy notices.

For read-only diagnostics, run `CartoonDownloader.exe --diagnostics` from the
installation folder. `--data-dir` explicitly selects another data folder for
launch or diagnostics; it does not migrate or delete files.

## Как собрать установщик после изменений

Проще всего запустить `BUILD_SETUP.bat` двойным щелчком из исходной папки проекта:
он выполнит проверки и обе сборки автоматически. Версия берётся из
`cartoon_downloader/__init__.py`. Подробности и повторная сборка — в [setup.md](setup.md).
Ниже приведены команды для ручного запуска.

Работай в исходной папке проекта, а не внутри `dist` или установленной программы.

1. После изменений повысь `__version__` в `cartoon_downloader/__init__.py`.
   Например, для следующего обновления: `__version__ = "0.30.3"`.
   EXE и установщик получат эту версию автоматически; AppId в `packaging/installer.iss`
   менять не нужно — он связывает обновления с уже установленной программой.
2. Выполни проверки из корня проекта:

   ```powershell
   .\runtime\python\python.exe -B verify_package.py
   .\tools\deno\deno.exe fmt --check static
   ```

3. После успешных проверок собери приложение и затем установщик:

   ```powershell
   .\runtime\python\python.exe -B packaging/build_windows.py
   .\runtime\python\python.exe -B packaging/build_setup.py --package dist/CartoonDownloader-0.30.3 --online
   ```

   В последней команде укажи версию из `__version__`.

Для примера 0.30.3 результат находится здесь:

```text
dist/CartoonDownloader-0.30.3-Online-Setup/CartoonDownloader-Online-Setup.exe
```

Рядом появятся `SHA256SUMS.txt`, `SETUP.json` и `BUILD.log`.
Пользователю достаточно передать один `CartoonDownloader-Online-Setup.exe`;
при установке потребуется интернет. Для полной автономной поставки используй
`BUILD_SETUP.bat --offline`.

Для сборки необходим уже подготовленный компилятор
`build/installer-tools/inno-7.1.0/ISCC.exe`; сохраняй эту папку при очистке build/.
Его версия и SHA256 закреплены в `packaging/installer-toolchain.json`.
Python, media tools и WebView2 проверяются по исходному проекту; загрузок при сборке нет.
Онлайн-вариант скачивает внешние компоненты уже во время установки.

Для каждого обновления используй новую версию: скрипты сохраняют прежние сборки
и не перезаписывают существующий установщик. Если папка dist с этой версией уже
содержит рабочие данные, не удаляй её ради пересборки — повысь номер версии.
Не запускай portable EXE из свежего dist перед упаковкой: он создаёт там данные,
и `build_setup.py` правильно отклонит такой пакет. Для проверки окна с отдельными
данными запусти EXE с `--data-dir "%TEMP%\CartoonDownloader-review-0.30.3"`
из cmd (в PowerShell используй "$env:TEMP\CartoonDownloader-review-0.30.3").
Затем проверь новый установщик на отдельной Windows.

В Git хранятся исходники, лицензии и метаданные зависимостей. Перед сборкой
из свежего клона подготовь бинарные компоненты по [DEPENDENCIES.md](DEPENDENCIES.md).
