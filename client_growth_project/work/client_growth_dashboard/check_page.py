"""Load the dashboard in headless Chrome and report JavaScript errors (Phase 4 check).

A copy of the page is made in a temp folder with an error catcher injected first; Chrome renders it and
dumps the DOM; any error caught (window.onerror, unhandled rejections, console.error) is printed.
Usage:  python work/client_growth_dashboard/check_page.py [path.html] [--screenshot out.png] [--page clients] [--height 3000]
"""
import glob
import os
import re
import subprocess
import sys
import tempfile

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CATCHER = """<script>window.__errs=[];
window.addEventListener('error',e=>__errs.push('error: '+e.message+' @line '+e.lineno));
window.addEventListener('unhandledrejection',e=>__errs.push('promise: '+e.reason));
const __ce=console.error;console.error=(...a)=>{__errs.push('console.error: '+a.join(' '));__ce(...a)};
window.addEventListener('load',()=>setTimeout(()=>{const p=document.createElement('pre');p.id='__errors';
p.textContent=JSON.stringify(__errs);document.body.appendChild(p)},1500));</script>"""


def run(path, screenshot=None, page=None, budget=20000, height=1000):
    html = open(path, encoding="utf-8").read()
    html = html.replace("<head>", "<head>" + CATCHER, 1)
    if page:   # open a given page after load (for screenshots of other pages)
        html = html.replace("</body>", f"<script>window.addEventListener('load',()=>go('{page}'))</script></body>", 1)
    tmp = os.path.join(tempfile.mkdtemp(), "page.html")
    open(tmp, "w", encoding="utf-8").write(html)
    args = [CHROME, "--headless=new", "--disable-gpu", f"--virtual-time-budget={budget}", f"--window-size=1440,{height}"]
    args += [f"--screenshot={screenshot}"] if screenshot else ["--dump-dom"]
    try:
        out = subprocess.run(args + ["file://" + tmp], capture_output=True, text=True, timeout=90).stdout
    except subprocess.TimeoutExpired as e:   # headless Chrome sometimes does not exit; output is still usable
        out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        subprocess.run(["pkill", "-f", tmp])
    if screenshot:
        return None
    m = re.search(r'<pre id="__errors">(.*?)</pre>', out, re.S)
    return m.group(1) if m else "NO RESULT (page did not finish loading)"


if __name__ == "__main__":
    a = sys.argv[1:]
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))   # works from any folder
    path = a[0] if a and not a[0].startswith("--") else sorted(glob.glob(os.path.join(root, "outputs/html/*_Client_Growth_Dashboard.html")))[-1]
    shot = a[a.index("--screenshot") + 1] if "--screenshot" in a else None
    pg = a[a.index("--page") + 1] if "--page" in a else None
    h = int(a[a.index("--height") + 1]) if "--height" in a else 1000   # taller window for full-page screenshots
    res = run(path, shot, pg, height=h)
    print(path, "| errors:", res if res is not None else f"screenshot saved to {shot}")
