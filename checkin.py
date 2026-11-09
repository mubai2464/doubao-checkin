"""
豆包每日自动签到 - GitHub Actions版
无头 Chromium + storage_state 保持登录态，签到失败会明确报错（不再假成功）
"""
import base64
import os
import re
import sys
from datetime import datetime

from playwright.sync_api import sync_playwright

CHECKIN_URL = "https://www.doubao.com/pc/agent-explore"
HOME_URL = "https://www.doubao.com/chat/"

# 豆包电脑版浏览器 User-Agent（绕过「该活动仅支持在豆包电脑版参与」）
DOUBAO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36 "
    "SamanthaDoubaoWork/2.32.14 SamanExplorer"
)


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def dump_page(page, tag: str):
    """失败时把页面关键信息打进日志，便于定位是风控、登录失效还是加载慢。"""
    try:
        log(f"页面URL: {page.url}")
        log(f"页面标题: {page.title()}")
        body = page.inner_text("body")[:300].replace("\n", " | ")
        log(f"页面文本: {body}")
        html_len = len(page.content())
        log(f"HTML长度: {html_len}")
    except Exception as e:
        log(f"导出页面信息失败: {e}")
    try:
        page.screenshot(path=f"/tmp/checkin_{tag}.png", full_page=False)
    except Exception:
        pass


def read_balance(page):
    """从页面文本解析「累计获得额度：N 点」，用于确证签到是否真的生效。"""
    try:
        body = page.inner_text("body")
    except Exception:
        return None
    m = re.search(r"累计获得额度[：:]\s*\n?\s*([0-9]+)", body)
    if not m:
        m = re.search(r"累计获得额度[^0-9]{0,10}([0-9]+)", body)
    return int(m.group(1)) if m else None


def wait_task_area(page, timeout_s: int) -> bool:
    """等待任务区渲染出来：出现签到按钮、签到卡片或领取按钮任一即可。"""
    sign = page.get_by_role("button", name="立即签到")
    claim = page.get_by_role("button", name="立即领取")
    card = page.get_by_text("每日签到")
    deadline = datetime.now().timestamp() + timeout_s
    while datetime.now().timestamp() < deadline:
        if sign.count() > 0 or card.count() > 0 or claim.count() > 0:
            return True
        page.wait_for_timeout(1500)
    return False


def main():
    state_b64 = os.environ.get("STORAGE_STATE_B64", "")
    if not state_b64:
        log("ERROR: 未设置 STORAGE_STATE_B64 环境变量")
        sys.exit(1)

    state_path = "/tmp/storage_state.json"
    with open(state_path, "wb") as f:
        f.write(base64.b64decode(state_b64))

    log("开始签到流程...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--lang=zh-CN",
            ],
        )
        context = browser.new_context(
            storage_state=state_path,
            user_agent=DOUBAO_UA,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1280, "height": 900},
            extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9"},
        )
        page = context.new_page()

        try:
            sign_btn = page.get_by_role("button", name="立即签到")
            claim_btn = page.get_by_role("button", name="立即领取")
            card = page.get_by_text("每日签到")

            # 最多重试 3 轮，每轮重新加载页面
            ready = False
            for attempt in range(1, 4):
                log(f"第 {attempt} 次打开签到页...")
                page.goto(CHECKIN_URL, wait_until="load", timeout=60000)
                page.wait_for_timeout(3000)

                if "/login" in page.url:
                    log("ERROR: 登录态已失效（跳转到登录页），请更新 STORAGE_STATE_B64 Secret")
                    dump_page(page, "login")
                    sys.exit(1)

                if wait_task_area(page, 30):
                    ready = True
                    log("任务区已渲染")
                    break

                log(f"第 {attempt} 次未渲染出任务区，页面状态如下：")
                dump_page(page, f"not_ready_{attempt}")

            if not ready:
                try:
                    body = page.inner_text("body")
                except Exception:
                    body = ""
                if "该页面暂时不可用" in body or "请尝试刷新此页面" in body:
                    log("SKIP: IP_BLOCKED 页面被风控拦截（该页面暂时不可用），本轮放弃")
                else:
                    log("ERROR: 3 次尝试后仍无法加载任务区")
                sys.exit(1)

            # 任务区没展开时先点「立即领取」
            if claim_btn.count() > 0:
                try:
                    claim_btn.first.click(timeout=10000)
                    log("已点击「立即领取」展开任务区")
                    page.wait_for_timeout(2000)
                except Exception as e:
                    log(f"点击「立即领取」失败（继续尝试）: {e}")

            before_balance = read_balance(page)
            log(f"签到前累计额度: {before_balance}")

            # 等签到按钮出现（最多 30 秒）
            found = False
            for _ in range(20):
                if sign_btn.count() > 0:
                    found = True
                    break
                page.wait_for_timeout(1500)

            if not found:
                if card.count() > 0 and before_balance is not None:
                    log(f"任务卡片存在但没有「立即签到」按钮，额度可读（{before_balance}）→ 今日已签到，跳过")
                    dump_page(page, "already")
                    sys.exit(0)
                log("ERROR: 找不到「立即签到」按钮，也无法读取额度，状态不明（不再默认当作已签到）")
                dump_page(page, "no_button")
                sys.exit(1)

            try:
                sign_btn.first.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass

            log("点击「立即签到」...")
            sign_btn.first.click(timeout=15000)
            page.wait_for_timeout(4000)

            # 成功判定：以「累计额度是否真的增加」为准，弹窗/按钮消失只作辅助证据
            success = False
            after_balance = None
            for _ in range(15):
                page.wait_for_timeout(1000)
                after_balance = read_balance(page)
                if before_balance is not None and after_balance is not None and after_balance > before_balance:
                    success = True
                    break

            dialog = page.locator("div[role='dialog']")
            if dialog.count() > 0:
                log(f"结果弹窗: {dialog.first.inner_text()[:200]}")

            log(f"签到后累计额度: {after_balance}")

            dump_page(page, "after_click")

            if success:
                log(f"✅ 签到成功，额度增加 {after_balance - before_balance} 点（{before_balance} → {after_balance}）")
                sys.exit(0)

            if sign_btn.count() == 0:
                log("⚠️ 按钮已消失但额度未增加，结果不确定 → 按失败处理")
            log("ERROR: 点击后额度没有增加，签到未生效")
            sys.exit(1)

        except SystemExit:
            raise
        except Exception as e:
            log(f"❌ 签到异常: {type(e).__name__}: {e}")
            dump_page(page, "error")
            sys.exit(1)
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
