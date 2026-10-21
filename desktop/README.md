# MSV Desktop

A portable, no-install build of the MSV system. No central server, no
Python install, no `pip install` — double-click the exe and it runs.

## How it works

Multiple office PCs can open the **same shared folder** (on a network
share, a USB drive, wherever) at the same time. Whichever one opens it
first becomes the "host" — it's the one process that actually runs the
app and touches the database. Every other PC that opens the same folder
detects the live host and just connects to it as a client, through its
own native window. If the host PC closes the app, the next PC to open the
folder automatically becomes the new host. Only one process ever writes
to the database at a time, no matter how many PCs have the folder open —
see `hostlock.py` for the full protocol.

## Folder layout

```
MSV-Desktop/        <- move/copy this whole folder anywhere, it keeps working
  apply-update.exe   <- run this to install a new version (see "Updating" below)
  app/               <- the program itself. Replaced wholesale on every update.
    msv-desktop.exe
    msv-desktop-debug.exe   <- same app, with a console window (see below)
    django_src/      <- the Django project, as plain source
    _internal/       <- bundled Python runtime + libraries
  data/              <- created on first run. NEVER touched by an update.
    db.sqlite3
    media/
    desktop_state/   (host.lock, secret.key, logs)
```

Because `app/` is the one copy shared by every PC that opens this folder,
updating it once updates it for everyone — there's no need to update each
PC separately, and no need to pick one PC as "the main one" for updates.

## First-run notes

- **Windows Firewall will prompt** the first time the host PC runs the
  app, because it listens for connections from other PCs on the LAN
  (port 8420). This is normal — click "Allow access." If you don't see
  the prompt and other PCs can't connect, check Windows Defender
  Firewall → allowed apps.
- **A client PC needs the host PC to be reachable on the network** (same
  LAN/Wi-Fi). If the host PC is asleep, off, or disconnected, other PCs
  opening the folder will become the new host themselves — that's
  expected, not a bug.

## Operational rules

- **Never open `data/db.sqlite3` directly from a client machine** — e.g.
  no `manage.py dbshell`, no DB Browser for SQLite pointed at a client's
  view of the shared file, no copying it "just to check something" while
  the app is running elsewhere. Only the elected host process is allowed
  to touch that file. Everyone else talks to it over HTTP, same as
  talking to a real server.
- If something looks wrong and you need to see what's actually
  happening, run `msv-desktop-debug.exe` instead of the normal one — it's
  the identical app with a console window attached, so you can see
  Django/startup errors live instead of just the generic "failed to
  start" dialog. Crash details are always written to
  `data/desktop_state/launcher_errors.log` either way.

## Building it yourself

CI (`.github/workflows/build-desktop.yml`) builds this automatically on
every push to `main` and on version tags, producing a downloadable
`MSV-Desktop-windows.zip` artifact — that's the easiest way to get a
build. To build locally on Windows:

```
pip install -r desktop/requirements-desktop.txt
set DJANGO_SETTINGS_MODULE=msv.settings
set PYTHONPATH=<path to a copy of msv/ containing msv/ and hcsd/>
python -m django collectstatic --noinput
cd desktop
pyinstaller msv_desktop.spec --noconfirm
```

Then copy that same `msv/` source copy into `desktop/dist/app/django_src/`
(the build doesn't freeze it in — see the comment at the top of
`msv_desktop.spec` for why) before running `dist/app/msv-desktop.exe`.

## Updating (no internet on the target network)

There's no "check for updates" button, because the network this runs on
has no internet access at all — a new build has to be carried in on a
USB drive from a machine that does have internet (e.g. downloading
`MSV-Desktop-windows.zip` from this repo's GitHub Actions artifacts).

Once the new build is on the network:

1. Make sure the app is closed on **every** PC first.
2. Run `apply-update.exe` (sitting at the top of this same `MSV-Desktop/`
   folder — not inside `app/`, since that's exactly what it replaces).
3. Point it at the `.zip` you brought in (or the already-extracted folder
   — either works).
4. Confirm. It backs up the current `app/` first, swaps in the new one,
   and only deletes the backup once the swap succeeds — if anything goes
   wrong partway through, it automatically restores the old version
   instead of leaving you with a half-updated folder. `data/` is never
   touched.

If the app is still running anywhere when you try this, `apply-update.exe`
refuses and tells you which PC is running it (checked the same way a
client PC finds the host) — close it there first, then try again.
