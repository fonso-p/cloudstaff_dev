"""Open a built dashboard in headless Chrome (or Edge) and report JavaScript errors.

A copy of the page is made in a temp folder with an error catcher injected first. The browser renders it and
dumps the DOM, and any error it caught (window.onerror, unhandled rejections, console.error) is printed.
The check passes only when it prints "errors: []".

Usage:
    python check_page.py page.html                       # every page: errors per page
    python check_page.py page.html --page breakdown      # one page
    python check_page.py page.html --screenshot out.png [--page list] [--height 3000]
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]
CATCHER = """<script>window.__errs=[];
window.addEventListener('error',e=>__errs.push('error: '+e.message+' @line '+e.lineno));
window.addEventListener('unhandledrejection',e=>__errs.push('promise: '+e.reason));
const __ce=console.error;console.error=(...a)=>{__errs.push('console.error: '+a.join(' '));__ce(...a)};
window.addEventListener('load',()=>setTimeout(()=>{const p=document.createElement('pre');p.id='__errors';
p.textContent=JSON.stringify(__errs);document.body.appendChild(p)},1500));</script>"""


def browser():
    for c in CANDIDATES:
        if os.path.exists(c):
            return c
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome", "msedge"):
        if shutil.which(name):
            return shutil.which(name)
    sys.exit("No Chrome or Edge found. Install Chrome or edit CANDIDATES in check_page.py.")


def run(path, screenshot=None, page=None, budget=20000, height=1000):
    html = open(path, encoding="utf-8").read().replace("<head>", "<head>" + CATCHER, 1)
    if page:   # open the given page after load
        html = html.replace("</body>", f"<script>window.addEventListener('load',()=>go('{page}'))</script></body>", 1)
    tmpdir = tempfile.mkdtemp()
    tmp = os.path.join(tmpdir, "page.html")
    open(tmp, "w", encoding="utf-8").write(html)
    args = [browser(), "--headless=new", "--disable-gpu", f"--virtual-time-budget={budget}", f"--window-size=1440,{height}",
            f"--user-data-dir={os.path.join(tmpdir, 'profile')}"]
    args += [f"--screenshot={os.path.abspath(screenshot)}"] if screenshot else ["--dump-dom"]
    try:
        out = subprocess.run(args + [pathlib.Path(tmp).as_uri()], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90).stdout
    except subprocess.TimeoutExpired as e:   # headless Chrome sometimes does not exit; the output is still usable
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
    if screenshot:
        return None
    m = re.search(r'<pre id="__errors">(.*?)</pre>', out, re.S)
    return m.group(1) if m else "NO RESULT (page did not finish loading)"


def pages_in(path):
    return re.findall(r'data-page="([\w-]+)"', open(path, encoding="utf-8").read())


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0].startswith("--"):
        sys.exit(__doc__)
    path = a[0]
    shot = a[a.index("--screenshot") + 1] if "--screenshot" in a else None
    pg = a[a.index("--page") + 1] if "--page" in a else None
    h = int(a[a.index("--height") + 1]) if "--height" in a else 1000
    if shot:
        run(path, shot, pg, height=h)
        print(f"screenshot saved to {shot}")
    else:
        bad = False
        for p in [pg] if pg else pages_in(path):
            res = run(path, None, p)
            bad |= res != "[]"
            print(f"{p:<14} errors: {res}")
        sys.exit(1 if bad else 0)
