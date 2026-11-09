"""本地真实签到：打开签到页 → 点「立即签到」→ 用额度数字确证结果。

判定原则（避免假成功）：
1. 点按钮后额度必须真的增加，才算成功；
2. 没有「立即签到」按钮时，必须能证明今天已领过（同日已运行过，或额度比上次记录多了 200/400），
   否则一律按失败退出（exit 1），不再默认当作“已签到”。
"""
import json
import os
import re
import sys

sys.path.insert(0, r"C:\Users\丘\AppData\Roaming\Python\Python313\site-packages")

from datetime import datetime
from playwright.sync_api import sync_playwright

CHECKIN_URL = "https://www.doubao.com/pc/agent-explore"
DOUBAO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36 "
    "SamanthaDoubaoWork/2.32.14 SamanExplorer"
)

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "storage_state.json")
OUT = os.path.join(HERE, "shots")
HISTORY = os.path.join(HERE, "history.json")
os.makedirs(OUT, exist_ok=True)


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def read_balance(page):
    """从页面文本里解析「累计获得额度：N 点」。"""
    body = page.inner_text("body")
    m = re.search(r"累计获得额度[：:]\s*\n?\s*([0-9]+)", body)
    if not m:
        m = re.search(r"累计获得额度[^0-9]{0,10}([0-9]+)", body)
    return int(m.group(1)) if m else None


def load_history():
    try:
        with open(HISTORY, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_history(balance):
    data = {"last_date": datetime.now().strftime("%Y-%m-%d"), "last_balance": balance}
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    log(f"已记录基线: {data}")


PAGE_BLOCKED_HINT = "该页面暂时不可用"


def main():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    today = datetime.now().strftime("%Y-%m-%d")
    hist = load_history()
    last_balance = hist.get("last_balance")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            storage_state=STATE,
            user_agent=DOUBAO_UA,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.goto(CHECKIN_URL, wait_until="load", timeout=60000)

        sign = page.get_by_role("button", name="立即签到")
        card = page.get_by_text("每日签到")
        ready = False
        for i in range(20):
            page.wait_for_timeout(2000)
            if sign.count() > 0 or card.count() > 0:
                ready = True
                log(f"页面就绪（等待 {(i + 1) * 2} 秒）")
                break
        if not ready:
            body = page.inner_text("body")
            if PAGE_BLOCKED_HINT in body:
                log("SKIP: 页面被风控拦截（IP 受限），无法签到")
            else:
                log(f"40 秒内页面未就绪，文本: {body[:200]}")
            page.screenshot(path=os.path.join(OUT, f"local_{stamp}_notready.png"))
            ctx.storage_state(path=STATE)
            sys.exit(1)

        # 登录态失效检测
        if "/login" in page.url:
            log("登录态已失效，请重新登录（脚本不会伪造成功）")
            page.screenshot(path=os.path.join(OUT, f"local_{stamp}_login.png"))
            sys.exit(1)

        before = read_balance(page)
        log(f"签到前累计额度: {before}")

        if sign.count() == 0:
            # 没有签到按钮 —— 必须证明今天已经领过，否则报错
            page.screenshot(path=os.path.join(OUT, f"local_{stamp}_nobutton.png"))
            if before is None:
                log("没有「立即签到」按钮，且读不到额度数字，无法确认 → 按失败处理")
                ctx.storage_state(path=STATE)
                sys.exit(1)
            if hist.get("last_date") == today and last_balance == before:
                log(f"今日已运行过且额度未变（{before} 点），确认今日已签到")
                ctx.storage_state(path=STATE)
                sys.exit(0)
            if last_balance is not None and before > last_balance:
                log(f"额度已从 {last_balance} 增至 {before}，确认今日已由其他渠道签到")
                save_history(before)
                ctx.storage_state(path=STATE)
                sys.exit(0)
            log(f"没有「立即签到」按钮，但额度为 {before}、上次基线为 {last_balance}，"
                f"无法证明今天已签到 → 按失败处理（请人工确认）")
            ctx.storage_state(path=STATE)
            sys.exit(1)

        page.screenshot(path=os.path.join(OUT, f"local_{stamp}_before.png"))
        log("点击「立即签到」...")
        try:
            sign.first.click(timeout=15000)
        except Exception as e:
            log(f"点击失败: {e}")
            page.screenshot(path=os.path.join(OUT, f"local_{stamp}_clickfail.png"))
            ctx.storage_state(path=STATE)
            sys.exit(1)

        # 等额度真的变化（最多 15 秒）
        after = None
        for i in range(15):
            page.wait_for_timeout(1000)
            after = read_balance(page)
            if before is None or after is None or after > before:
                break
        page.screenshot(path=os.path.join(OUT, f"local_{stamp}_after.png"))
        log(f"签到后累计额度: {after}")

        ctx.storage_state(path=STATE)
        log("登录态已保存更新")

        if before is not None and after is not None and after > before:
            log(f"✅ 签到成功，额度增加 {after - before} 点（{before} → {after}）")
            save_history(after)
            ctx.close()
            browser.close()
            sys.exit(0)

        if sign.count() == 0 and before is not None and after is None:
            log("按钮已消失但读不到额度，结果不确定 → 按失败处理")
            ctx.close()
            browser.close()
            sys.exit(1)

        log("⚠️ 额度未增加，签到未生效 → 按失败处理")
        ctx.close()
        browser.close()
        sys.exit(1)


if __name__ == "__main__":
    main()
