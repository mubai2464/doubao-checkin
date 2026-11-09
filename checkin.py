"""
豆包每日自动签到 - GitHub Actions版
在无头Chromium中运行，使用storage_state保持登录态
"""
import os
import sys
import time
import base64
import json
from datetime import datetime

from playwright.sync_api import sync_playwright

# ============ 配置 ============
CHECKIN_URL = "https://www.doubao.com/pc/agent-explore"

# 豆包电脑版浏览器 User-Agent
DOUBAO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36 "
    "SamanthaDoubaoWork/2.32.14 SamanExplorer"
)


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def main():
    # 从环境变量读取 storage_state（base64编码）
    state_b64 = os.environ.get("STORAGE_STATE_B64", "")
    if not state_b64:
        log("ERROR: 未设置 STORAGE_STATE_B64 环境变量")
        sys.exit(1)

    state_json = base64.b64decode(state_b64).decode("utf-8")
    state_path = "/tmp/storage_state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        f.write(state_json)

    log("开始签到流程...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            storage_state=state_path,
            user_agent=DOUBAO_UA,
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        try:
            log("打开签到页面...")
            page.goto(CHECKIN_URL, wait_until="load", timeout=60000)
            page.wait_for_timeout(3000)

            # 登录失效检测（只在明确跳到登录页时判定）
            if "/login" in page.url:
                log("ERROR: 登录态已失效（跳转到登录页），请更新 STORAGE_STATE_B64 Secret")
                page.screenshot(path="/tmp/checkin_login_page.png")
                sys.exit(1)

            log(f"页面已打开: {page.url}")

            sign_btn = page.get_by_role("button", name="立即签到")
            claim_btn = page.get_by_role("button", name="立即领取")
            card = page.get_by_text("每日签到")

            # 等待任务区渲染（页面是懒加载，最多等 40 秒）
            ready = False
            for _ in range(20):
                if sign_btn.count() > 0 or card.count() > 0 or claim_btn.count() > 0:
                    ready = True
                    break
                page.wait_for_timeout(2000)
            if not ready:
                log("ERROR: 40 秒内签到页未渲染出任务区")
                page.screenshot(path="/tmp/checkin_not_loaded.png")
                sys.exit(1)

            # 任务区未展开时先点「立即领取」
            if claim_btn.count() > 0:
                try:
                    claim_btn.first.click(timeout=10000)
                    log("已点击「立即领取」，展开任务区")
                except Exception as e:
                    log(f"点击「立即领取」失败（继续尝试）: {e}")
                page.wait_for_timeout(2000)

            # 等待签到按钮出现（最多 30 秒）
            found = False
            for _ in range(15):
                if sign_btn.count() > 0:
                    found = True
                    break
                page.wait_for_timeout(2000)

            if not found:
                # 区分「今日已签到」和「页面异常」
                if card.count() > 0:
                    log("任务卡片存在但没有「立即签到」按钮 → 今日已签到")
                    page.screenshot(path="/tmp/checkin_already.png")
                    sys.exit(0)
                log("ERROR: 未找到「立即签到」按钮，且任务卡片也不存在")
                page.screenshot(path="/tmp/checkin_no_button.png")
                sys.exit(1)

            try:
                sign_btn.first.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass

            log("点击「立即签到」...")
            sign_btn.first.click(timeout=15000)
            page.wait_for_timeout(4000)

            # 判定成功：弹窗出现 / 按钮消失
            success = False
            dialog = page.locator("div[role='dialog']")
            if dialog.count() > 0:
                text = dialog.first.inner_text()
                log(f"结果弹窗: {text[:200]}")
                if "额度" in text or "签到" in text:
                    success = True

            if not success:
                page.wait_for_timeout(4000)
                if page.get_by_role("button", name="立即签到").count() == 0:
                    success = True
                    log("「立即签到」按钮已消失")

            page.screenshot(path="/tmp/checkin_after_click.png")

            if success:
                log("✅ 签到成功，+200 额度")
                sys.exit(0)

            log("ERROR: 点击后签到状态未变化")
            sys.exit(1)

        except SystemExit:
            raise
        except Exception as e:
            log(f"❌ 签到异常: {type(e).__name__}: {e}")
            try:
                page.screenshot(path="/tmp/checkin_error.png")
            except Exception:
                pass
            sys.exit(1)
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
