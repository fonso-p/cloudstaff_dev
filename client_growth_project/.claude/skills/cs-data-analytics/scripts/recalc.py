"""Recalculate an .xlsx so formula results can be read back and verified.

Engines tried, in order:
  1. LibreOffice (soffice)          - Linux, Windows, macOS (free install)
  2. Microsoft Excel via COM        - Windows, needs `pip install pywin32`
  3. Microsoft Excel via xlwings    - macOS/Windows, needs `pip install xlwings`

recalc_copy()    never touches the original; it returns a recalculated COPY that
                 QA reads values from.
excel_finalize() optional, Windows/Mac with Excel: recalculates the deliverable in
                 place so cached values also show in Outlook/Teams/SharePoint previews.
"""
import os
import shutil
import subprocess
import sys
import tempfile


class RecalcUnavailable(RuntimeError):
    pass


def _find_soffice():
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe",
              r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
              "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if os.path.exists(p):
            return p
    return None


def _recalc_soffice(src, out_dir):
    soffice = _find_soffice()
    if not soffice:
        return None
    profile = tempfile.mkdtemp(prefix="lo_profile_")
    profile_url = "file:///" + profile.replace("\\", "/").lstrip("/")
    cmd = [soffice, f"-env:UserInstallation={profile_url}", "--headless", "--calc",
           "--convert-to", "xlsx", "--outdir", out_dir, src]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    out = os.path.join(out_dir, os.path.basename(src))
    return out if os.path.exists(out) else None


def _recalc_excel_com(src, dst):
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return None
    xl = win32com.client.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    try:
        wb = xl.Workbooks.Open(os.path.abspath(src))
        xl.CalculateFull()
        wb.SaveAs(os.path.abspath(dst), 51)  # 51 = .xlsx
        wb.Close(False)
    finally:
        xl.Quit()
    return dst if os.path.exists(dst) else None


def _recalc_xlwings(src, dst):
    try:
        import xlwings as xw  # type: ignore
    except ImportError:
        return None
    app = xw.App(visible=False)
    try:
        book = app.books.open(os.path.abspath(src))
        app.calculate()
        book.save(os.path.abspath(dst))
        book.close()
    finally:
        app.quit()
    return dst if os.path.exists(dst) else None


def _work_root():
    """Sandboxed Excel on macOS can only save inside its own container, so work there."""
    box = os.path.expanduser("~/Library/Containers/com.microsoft.Excel/Data")
    if sys.platform == "darwin" and os.path.isdir(box):
        root = os.path.join(box, "cs_recalc")
        os.makedirs(root, exist_ok=True)
        return root
    return None


def recalc_copy(src):
    """Return the path of a recalculated copy of `src`. Raises RecalcUnavailable."""
    work = tempfile.mkdtemp(prefix="cs_recalc_", dir=_work_root())
    tmp_src = os.path.join(work, os.path.basename(src))
    shutil.copy(src, tmp_src)
    res_dir = os.path.join(work, "out")
    os.makedirs(res_dir, exist_ok=True)
    out = _recalc_soffice(tmp_src, res_dir)
    if out:
        return out
    dst = os.path.join(res_dir, os.path.basename(src))
    for fn in (_recalc_excel_com, _recalc_xlwings):
        try:
            out = fn(tmp_src, dst)
        except Exception as e:  # engine present but failed
            print(f"[recalc] {fn.__name__} failed: {e}", file=sys.stderr)
            out = None
        if out:
            return out
    raise RecalcUnavailable(
        "No recalculation engine found. Install LibreOffice (free), or use a machine with "
        "Microsoft Excel plus `pip install pywin32` (Windows) or `pip install xlwings` (Mac).")


def excel_finalize(path):
    """Optional: recalculate the deliverable in place with real Excel."""
    tmp = path + ".tmp.xlsx"
    for fn in (_recalc_excel_com, _recalc_xlwings):
        try:
            ok = fn(path, tmp)
        except Exception:
            ok = None
        if ok:
            os.replace(tmp, path)
            return True
    return False


if __name__ == "__main__":
    print(recalc_copy(sys.argv[1]))
