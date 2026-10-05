"""ブラウザE2E: 擬似カメラで 宣言→撮影→タグ付け(iframe連携)→単体自動タグ→終了サマリー を通す。
使い方: python scripts/e2e.py   （APIと静的サーバーを一時起動します。要 playwright）"""
import json, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
API, APPS = "http://localhost:8000", "http://localhost:8081"
OUT = Path(os.environ.get("E2E_SHOTS", tempfile.gettempdir())) 

def get(path):
    return json.load(urllib.request.urlopen(API + path))

def wait_up(url):
    for _ in range(50):
        try:
            urllib.request.urlopen(url); return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("server did not start: " + url)

data = tempfile.mkdtemp()
env = {**os.environ, "IC_DATA_DIR": data}
api = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.asgi:app", "--port", "8000"], cwd=ROOT / "backend", env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
web = subprocess.Popen([sys.executable, "-m", "http.server", "8081", "--directory", str(ROOT / "apps")],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    wait_up(API + "/health"); wait_up(APPS + "/capture/index.html")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 800})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(f"{APPS}/capture/index.html?api={API}")
        pg.select_option("#f-source", "mock")
        pg.fill("#f-operator", "e2e")
        pg.click("#btn-start")

        # --- 複数撮影: ペアン直×2 + ケリー×1
        pg.wait_for_selector("#search-results li")
        pg.click("#search-results li:nth-child(1) button"); pg.click("#search-results li:nth-child(1) button")
        pg.click("#search-results li:nth-child(3) button")
        assert "複数撮影" in pg.inner_text("#declared-summary")
        pg.click("#btn-declare")
        pg.wait_for_selector("#view-confirm:not([hidden])"); pg.check("#chk-confirm"); pg.click("#btn-confirm")
        pg.wait_for_selector("#btn-shoot")
        pg.click("#btn-shoot")
        pg.wait_for_selector("#tagger-overlay:not([hidden])")
        f = pg.frame_locator("#tagger-frame")
        cv = f.locator("#canvas"); cv.wait_for()
        pg.wait_for_timeout(500)
        f.locator("#palette li:nth-child(1) .name").click()
        cv.click(position={"x": 200, "y": 150}); cv.click(position={"x": 100, "y": 150}); cv.click(position={"x": 300, "y": 150})  # 中心,A,B
        cv.click(position={"x": 200, "y": 300}); f.locator("#btn-finish-hint").click()                                          # 2個目(中心のみ)
        f.locator("#palette li:nth-child(2) .name").click()
        cv.click(position={"x": 450, "y": 220}); f.locator("#btn-finish-hint").click()
        f.locator("#issues .ok").wait_for()
        pg.screenshot(path=str(OUT / "e2e_tagger.png"))
        f.locator("#btn-save").click()
        pg.wait_for_selector("#tagger-overlay", state="hidden")
        assert pg.locator(".shot.tagged").count() == 1

        imgs = get("/images")
        tags = get(f"/images/{imgs[0]['image_id']}/tags")["hints"]
        assert imgs[0]["tag_status"] == "tagged" and len(tags) == 3, tags
        assert sorted(h["hint_quality"] for h in tags) == ["center_only", "center_only", "full"], tags
        print("multi OK:", [(h["instrument_uid"], h["instance_no"], h["hint_quality"]) for h in tags])

        # --- 単体撮影 + 自動タグ + 置き直し
        pg.click("#btn-new-decl")
        pg.wait_for_selector("#search-results li")
        pg.click("#search-results li:nth-child(2) button"); pg.click("#btn-declare")
        pg.wait_for_selector("#view-confirm:not([hidden])"); pg.check("#chk-confirm"); pg.click("#btn-confirm")
        pg.wait_for_selector("#chk-auto:visible")
        pg.click("#btn-shoot"); pg.wait_for_selector(".shot.tagged")
        pg.click("#btn-rearrange"); pg.click("#btn-shoot"); pg.wait_for_timeout(600)
        imgs = get("/images")
        single = [i for i in imgs if i["tag_status"] == "tagged"]
        assert len(imgs) == 3 and len(single) == 3, imgs
        assert {i["arrangement_no"] for i in imgs[1:]} == {1, 2}

        # --- 終了サマリー
        pg.click("#btn-finish"); pg.wait_for_selector("#view-summary:not([hidden])")
        pg.screenshot(path=str(OUT / "e2e_summary.png"))
        d = get("/stats/daily")
        assert d["images"] == 3 and d["arrangements"] == 3 and not d["untagged_images"], d
        assert list(Path(data, "reports").glob("daily_*.html")), "report missing"
        assert not errors, errors
        print("single/auto-tag OK, summary OK:", {k: d[k] for k in ("images", "arrangements", "tagged_images")})

        # --- 単独起動のタグ付け(未タグ一覧)
        pg2 = b.new_page(); pg2.goto(f"{APPS}/tagger/index.html?api={API}")
        pg2.wait_for_selector("#view-list:not([hidden])"); assert "未タグの画像はありません" in pg2.inner_text("#untagged")
        b.close()
    print("E2E PASSED")
finally:
    api.terminate(); web.terminate()
