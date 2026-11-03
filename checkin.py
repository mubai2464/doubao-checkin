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
            page.goto(CHECKIN_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)

            # 检测登录状态
            body_text = page.inner_text("body")
            if "登录" in body_text and "立即领取" not in body_text:
                log("ERROR: 登录态已失效，请更新 STORAGE_STATE_B64 Secret")
                page.screenshot(path="/tmp/failed.png")
                sys.exit(1)

            log("页面加载成功")

            # 点击"立即领取"
            claim = page.get_by_role("button", name="立即领取")
            if claim.count() > 0:
                log("点击「立即领取」...")
                claim.first.click()
                time.sleep(2)
            else:
                log("未找到「立即领取」按钮，可能已展开")

            # 点击签到按钮
            checkin_btn = page.locator("#explore-tasks button", has_text="^点$")
            if checkin_btn.count() == 0:
                checkin_btn = page.locator("#explore-tasks button").first

            if checkin_btn.count() == 0:
                log("未找到签到按钮，今日可能已签到")
                sys.exit(0)

            if checkin_btn.first.is_disabled():
                log("签到按钮已禁用，今日已签到过")
                sys.exit(0)

            log("点击签到按钮...")
            checkin_btn.first.click()
            time.sleep(3)

            # 确认结果
            dialog = page.locator("div[role='dialog']")
            if dialog.count() > 0:
                text = dialog.first.inner_text()
                log(f"结果: {text[:200]}")
                if "每日签到" in text:
                    log("✅ 签到成功！")
                else:
                    log("对话框已出现，请查看日志确认")
            else:
                log("未检测到结果对话框")

            log("签到流程结束")

        except Exception as e:
            log(f"❌ 签到异常: {type(e).__name__}: {e}")
            try:
                page.screenshot(path="/tmp/error.png")
            except Exception:
                pass
            sys.exit(1)
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
