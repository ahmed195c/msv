"""Single entry point for the portable desktop build. PyInstaller freezes
this file; double-clicking the resulting exe runs it.

Responsibilities, in order:
  1. Work out where "here" is (the frozen exe's own folder, or this
     script's folder when run directly for testing) and where the
     relocatable data folder is, so the whole app/+data/ pair can be
     moved anywhere and keep working.
  2. Run the elected-host protocol (hostlock.py) using ONLY the shared
     data folder for coordination.
  3. Host: boot Django against the local SQLite file, migrate, serve it
     with waitress, run the daily scheduler, open a window at 127.0.0.1.
     Client: skip Django entirely, just open a window at the host's URL.
  4. On window close, release the host lock (if we held it) so the next
     launch doesn't have to wait out the staleness window.

See desktop/README.md for the Windows Firewall first-run prompt and other
operational notes.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from pathlib import Path

PORT = 8420
WINDOW_TITLE = 'نظام التصاريح والعقود'


def _is_frozen() -> bool:
    return bool(getattr(sys, 'frozen', False))


def resolve_dirs() -> tuple[Path, Path, Path]:
    """Returns (code_dir, django_src_dir, data_dir).

    Layout when frozen (PyInstaller one-folder build):
        MSV-Desktop/
          app/launcher.exe          <- sys.executable
          app/django_src/msv/...    <- the Django project tree, bundled as data
          data/                     <- sibling of app/, never touched by updates

    Layout when run as a plain script (dev/testing, not frozen):
        repo root/
          desktop/launcher.py       <- this file
          msv/msv/, msv/hcsd/       <- the existing Django project tree
        data dir defaults to desktop/dev_data/ so this never touches the
        real dev db.sqlite3 used by `python manage.py runserver`.
    """
    if _is_frozen():
        code_dir = Path(sys.executable).resolve().parent
        django_src = code_dir / 'django_src'
        data_dir = Path(os.getenv('MSV_DESKTOP_DATA_DIR', str(code_dir.parent / 'data')))
    else:
        code_dir = Path(__file__).resolve().parent.parent
        django_src = code_dir / 'msv'
        data_dir = Path(os.getenv('MSV_DESKTOP_DATA_DIR', str(code_dir / 'desktop' / 'dev_data')))
    return code_dir, django_src, data_dir


def _get_or_create_secret_key(data_dir: Path) -> str:
    state_dir = data_dir / 'desktop_state'
    state_dir.mkdir(parents=True, exist_ok=True)
    key_path = state_dir / 'secret.key'
    if key_path.exists():
        return key_path.read_text().strip()
    import secrets
    key = secrets.token_urlsafe(50)
    key_path.write_text(key)
    return key


def _unblock_bundled_dlls(code_dir: Path) -> None:
    """Strip Windows' Mark-of-the-Web from the bundled DLLs.

    A zip downloaded from GitHub tags every extracted file with a
    Zone.Identifier stream, and .NET then refuses to load pythonnet's
    Python.Runtime.dll ("Failed to resolve Python.Runtime.Loader.Initialize")
    — webview can't open a window. Deleting the stream is what
    'Properties → Unblock' does by hand. Files without the mark, or on a
    read-only share, are left as they are; the import below reports any
    real failure.
    """
    if sys.platform != 'win32' or not _is_frozen():
        return
    for dll in code_dir.rglob('*.dll'):
        try:
            os.remove(f'{dll}:Zone.Identifier')
        except OSError:
            continue


def _show_fatal_error(message: str) -> None:
    sys.stderr.write(message + '\n')
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, f'{WINDOW_TITLE} — خطأ في التشغيل', 0x10)
        except Exception:
            pass


def _log_crash(data_dir: Path, exc: BaseException) -> None:
    try:
        state_dir = data_dir / 'desktop_state'
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(state_dir / 'launcher_errors.log', 'a') as f:
            f.write(f'\n--- {time.strftime("%Y-%m-%d %H:%M:%S")} ---\n')
            f.write(''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except Exception:
        pass


def run_as_host(django_src: Path, data_dir: Path, claim) -> None:
    os.environ['MSV_DESKTOP_MODE'] = '1'
    os.environ['MSV_DESKTOP_DATA_DIR'] = str(data_dir)
    os.environ['DJANGO_SECRET_KEY'] = _get_or_create_secret_key(data_dir)
    os.environ['MSV_DESKTOP_LAN_ORIGIN'] = f'http://{claim.host_ip}:{claim.port}'
    os.environ['MSV_DESKTOP_EPOCH'] = str(claim.epoch)
    os.environ['MSV_DESKTOP_STARTED_AT'] = str(claim.started_at)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'msv.settings')

    sys.path.insert(0, str(django_src))

    import django
    django.setup()

    from django.core.management import call_command
    call_command('migrate', interactive=False, verbosity=0)

    from django.core.wsgi import get_wsgi_application
    application = get_wsgi_application()

    import waitress

    def _serve():
        waitress.serve(application, host='0.0.0.0', port=claim.port)

    server_thread = threading.Thread(target=_serve, name='waitress', daemon=True)
    server_thread.start()

    claim.start_heartbeat_thread()

    import scheduler
    stop_event = threading.Event()
    scheduler.start(stop_event)

    import webview

    # Printed once Django/waitress/webview have all actually loaded
    # successfully, right before we try to open a real window — CI's smoke
    # test (build-desktop.yml) greps for this exact marker, so a real
    # startup failure (a missing bundled module, a migration error, webview
    # itself failing to import) can't be masked by whatever create_window/
    # start() does or doesn't manage to do on a given machine (e.g. no
    # interactive desktop session on a CI runner).
    print('MSV_DESKTOP_SERVER_READY', flush=True)

    webview.create_window(WINDOW_TITLE, f'http://127.0.0.1:{claim.port}/')
    try:
        webview.start()
    finally:
        stop_event.set()
        claim.release()


def run_as_client(client) -> None:
    import webview
    webview.create_window(WINDOW_TITLE, client.url)
    webview.start()


def main() -> None:
    code_dir, django_src, data_dir = resolve_dirs()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / 'media').mkdir(parents=True, exist_ok=True)
    _unblock_bundled_dlls(code_dir)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import hostlock

    outcome = hostlock.elect(data_dir, PORT)

    if isinstance(outcome, hostlock.HostClaim):
        run_as_host(django_src, data_dir, outcome)
    else:
        run_as_client(outcome)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        try:
            _, _, data_dir = resolve_dirs()
        except Exception:
            data_dir = Path('.')
        _log_crash(data_dir, exc)
        _show_fatal_error(
            'تعذّر تشغيل البرنامج:\n\n'
            f'{exc}\n\n'
            f'حُفظت تفاصيل الخطأ في الملف: {data_dir / "desktop_state" / "launcher_errors.log"}'
        )
        sys.exit(1)
