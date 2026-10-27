"""Standalone tool to safely apply a new MSV Desktop build onto an
existing shared MSV-Desktop/ folder, without ever touching data/.

Built as its own small exe (apply_update.spec) and shipped at the TOP
LEVEL of MSV-Desktop/, sibling to app/ and data/ — never inside app/,
since app/ is exactly what this tool replaces; it can't safely delete
the folder it's running from.

There's no internet on the target network (confirmed with the user), so
there's no "check for updates" button here — a new build has to be
carried in on a USB drive from a machine that does have internet. This
tool is only the "apply it safely" half: point it at the .zip (or an
already-extracted folder) you brought in, and it does the rest —
checking nobody's currently running the app against this folder, backing
up the old app/ in case anything goes wrong, and never going near data/.
"""
import json
import os
import shutil
import sys
import tempfile
import tkinter as tk
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox

HOST_PORT_DEFAULT = 8420
TITLE = 'تحديث نظام التصاريح والعقود'


def _here() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _check_host_alive(msv_dir: Path):
    """Returns a human-readable "name (ip)" for the live host if the app is
    currently running against this folder's data/, else None."""
    lock_path = msv_dir / 'data' / 'desktop_state' / 'host.lock'
    if not lock_path.exists():
        return None
    try:
        info = json.loads(lock_path.read_text())
    except (OSError, ValueError):
        return None
    host_ip = info.get('host_ip')
    if not host_ip:
        return None
    port = info.get('port', HOST_PORT_DEFAULT)
    try:
        url = f'http://{host_ip}:{port}/__desktop_ping__/'
        with urllib.request.urlopen(url, timeout=2) as resp:
            resp.read()
        return f"{info.get('hostname', host_ip)} ({host_ip})"
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def _find_new_app_dir(src: Path, cleanup: list) -> Path:
    """`src` may be a .zip, a folder containing app/, or an app/ folder
    itself — normalize to the actual app/ folder to copy from. Appends any
    temp directory created to `cleanup` so the caller can remove it after."""
    if src.is_file() and src.suffix.lower() == '.zip':
        tmp = Path(tempfile.mkdtemp(prefix='msv_update_'))
        cleanup.append(tmp)
        with zipfile.ZipFile(src) as zf:
            zf.extractall(tmp)
        src = tmp

    def _looks_like_app_dir(p: Path) -> bool:
        return (p / 'msv-desktop.exe').exists() or (p / '_internal').is_dir()

    if (src / 'app').is_dir():
        return src / 'app'
    if _looks_like_app_dir(src):
        return src
    # A zip often has one wrapping folder (e.g. MSV-Desktop/) around app/.
    for child in src.iterdir():
        if not child.is_dir():
            continue
        if (child / 'app').is_dir():
            return child / 'app'
        if _looks_like_app_dir(child):
            return child
    raise FileNotFoundError('ملف التحديث ده مش شكله صحيح — مش لاقي فولدر app فيه.')


def main() -> None:
    root = tk.Tk()
    root.withdraw()

    msv_dir = _here()
    if not (msv_dir / 'data').is_dir() or not (msv_dir / 'app').is_dir():
        messagebox.showerror(
            TITLE,
            'لازم تشغّل أداة التحديث من نفس فولدر MSV-Desktop (جنب فولدر app و data مباشرة).',
        )
        return

    live_host = _check_host_alive(msv_dir)
    if live_host:
        messagebox.showerror(
            TITLE,
            f'البرنامج شغال دلوقتي على جهاز: {live_host}\n\n'
            'لازم تقفل البرنامج من على كل الأجهزة أولاً قبل التحديث، وبعدين جرب تاني.',
        )
        return

    update_path_str = filedialog.askopenfilename(
        title='اختر ملف التحديث (.zip)',
        filetypes=[('MSV Update', '*.zip'), ('كل الملفات', '*.*')],
    )
    if not update_path_str:
        update_path_str = filedialog.askdirectory(title='أو اختر فولدر التحديث لو كان مفكوك الضغط بالفعل')
        if not update_path_str:
            return

    update_path = Path(update_path_str)
    cleanup_dirs: list[Path] = []

    try:
        new_app_dir = _find_new_app_dir(update_path, cleanup_dirs)

        if not messagebox.askyesno(
            TITLE,
            'هيتم استبدال نسخة البرنامج الحالية بالنسخة الجديدة.\n'
            'بيانات المستخدمين والصور (data/) هتفضل كما هي تماماً.\n\n'
            'متأكد عايز تستمر؟',
        ):
            return

        app_dir = msv_dir / 'app'
        backup_dir = msv_dir / 'app.old'
        if backup_dir.exists():
            shutil.rmtree(backup_dir)

        try:
            os.replace(app_dir, backup_dir)
            shutil.copytree(new_app_dir, app_dir)
        except Exception as e:
            if backup_dir.exists() and not app_dir.exists():
                os.replace(backup_dir, app_dir)
            messagebox.showerror(TITLE, f'فشل التحديث، وتم الرجوع للنسخة القديمة تلقائياً.\n\n{e}')
            return

        shutil.rmtree(backup_dir, ignore_errors=True)
        messagebox.showinfo(TITLE, 'تم التحديث بنجاح. تقدر تشغّل البرنامج دلوقتي.')

    except FileNotFoundError as e:
        messagebox.showerror(TITLE, str(e))
    finally:
        for d in cleanup_dirs:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    main()
