"""
Arena2API Playwright Bot - 通过 CDP 连接已有 Chrome 会话
=======================================================
连接桌面上已登录 arena.ai 的 Chrome 浏览器，
用它的 cookie 和 reCAPTCHA 环境直接对话。
"""
import asyncio
import json
import sys
import time
import logging
import secrets as _secrets

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bot")

SERVER = "http://localhost:9090"
SITEKEY = "6Led_uYrAAAAAKjxDIF58fgFtX3t8loNAK85bW9I"


def uuid7() -> str:
    ts = int(time.time() * 1000)
    ra = _secrets.randbits(12)
    rb = _secrets.randbits(62)
    u = ts << 80 | (0x7000 | ra) << 64 | (0x8000000000000000 | rb)
    h = f"{u:032x}"
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


async def main():
    from playwright.async_api import async_playwright

    log.info("使用 Chrome user-data-dir 启动（复用已有会话）...")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="/tmp/chrome-profile",
            channel="chrome",
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1280, "height": 720},
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://arena.ai/text/direct", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(3)
        log.info(f"✓ 使用页面: {page.url}")

        # 等 reCAPTCHA
        for _ in range(10):
            has = await page.evaluate("""() => {
                const g = window.grecaptcha && window.grecaptcha.enterprise;
                return !!(g && typeof g.execute === 'function');
            }""")
            if has:
                break
            await asyncio.sleep(1)
        log.info(f"✓ reCAPTCHA: {'就绪' if has else '未找到'}")

        # 提取 cookies（包括 HttpOnly）
        context = page.context
        all_cookies = await context.cookies("https://arena.ai")
        cookies = {c["name"]: c["value"] for c in all_cookies}
        log.info(f"✓ Cookies ({len(cookies)}): {list(cookies.keys())}")

        has_auth = any("auth" in k.lower() for k in cookies)
        log.info(f"✓ Auth cookie: {'有' if has_auth else '无'}")

        # 提取模型
        models = await page.evaluate("""() => {
            if (window.__next_f) {
                for (let i = 0; i < window.__next_f.length; i++) {
                    const e = window.__next_f[i];
                    if (!e || !e[1]) continue;
                    const s = typeof e[1] === 'string' ? e[1] : '';
                    if (s.indexOf('initialModels') >= 0) {
                        const idx = s.indexOf('{"initialModels"');
                        if (idx >= 0) {
                            let depth = 0;
                            for (let j = idx; j < s.length; j++) {
                                if (s[j] === '{') depth++;
                                else if (s[j] === '}') depth--;
                                if (depth === 0) {
                                    try { return JSON.parse(s.substring(idx, j+1)).initialModels; } catch {}
                                    break;
                                }
                            }
                        }
                    }
                }
            }
            return null;
        }""") or []
        log.info(f"✓ 模型: {len(models)} 个")

        # 找目标模型
        text_models = {}
        for m in models:
            caps = m.get("capabilities", {})
            if "text" in caps.get("outputCapabilities", []):
                text_models[m.get("publicName", "")] = m.get("id", "")

        target_name, target_id = None, None
        for prefer in ["gemini-2.5-flash", "gemini-2.0-flash-001", "gpt-4.1-mini-2025-04-14", "claude-3-5-sonnet-20241022"]:
            if prefer in text_models:
                target_name, target_id = prefer, text_models[prefer]
                break
        if not target_name and text_models:
            target_name = next(iter(text_models))
            target_id = text_models[target_name]

        log.info(f"✓ 目标模型: {target_name}")

        # ===== 对话 =====
        async def chat(prompt: str) -> str:
            """通过浏览器 fetch 发送对话请求"""
            token = await page.evaluate(f"""() => {{
                return new Promise((resolve, reject) => {{
                    const g = window.grecaptcha && window.grecaptcha.enterprise ? window.grecaptcha.enterprise : window.grecaptcha;
                    if (!g) {{ reject('no recaptcha'); return; }}
                    g.ready(() => g.execute('{SITEKEY}', {{action: 'chat_submit'}}).then(resolve).catch(reject));
                }});
            }}""")
            log.info(f"  Token: {len(token)} chars")

            payload = {
                "id": uuid7(),
                "mode": "direct",
                "modelAId": target_id,
                "userMessageId": uuid7(),
                "modelAMessageId": uuid7(),
                "userMessage": {"content": prompt, "experimental_attachments": [], "metadata": {}},
                "modality": "chat",
                "recaptchaV3Token": token,
            }

            result = await page.evaluate("""async (payload) => {
                try {
                    const r = await fetch('https://arena.ai/nextjs-api/stream/create-evaluation', {
                        method: 'POST',
                        headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
                        body: JSON.stringify(payload),
                        credentials: 'include'
                    });
                    if (!r.ok) return { error: true, status: r.status, body: await r.text() };
                    const reader = r.body.getReader();
                    const dec = new TextDecoder();
                    let content = '', buf = '';
                    while (true) {
                        const { done, value } = await reader.read();
                        if (done) break;
                        buf += dec.decode(value, { stream: true });
                        const lines = buf.split('\\n');
                        buf = lines.pop();
                        for (const line of lines) {
                            if (line.startsWith('a0:')) {
                                try { const t = JSON.parse(line.substring(3)); if (typeof t === 'string' && t !== 'hasArenaError') content += t; } catch {}
                            } else if (line.startsWith('ag:')) {
                                try { const t = JSON.parse(line.substring(3)); if (typeof t === 'string') content += t; } catch {}
                            }
                        }
                    }
                    return { error: false, content };
                } catch (e) { return { error: true, status: 0, body: e.message || String(e) }; }
            }""", payload)

            if result.get("error"):
                return f"[错误 {result.get('status')}] {result.get('body', '')[:300]}"
            return result.get("content", "")

        # ===== 开始对话 =====
        log.info("\n" + "=" * 50)
        log.info("对话测试")
        log.info("=" * 50)

        prompts = [
            "你好，请用中文简短介绍一下你自己（2-3句话）",
            "What is 2+2? Answer in one word.",
        ]

        for i, prompt in enumerate(prompts, 1):
            log.info(f"\n[{i}] 发送: {prompt}")
            reply = await chat(prompt)
            print(f"\n{target_name}:\n{reply}\n")

            if reply.startswith("[错误"):
                log.error(f"对话失败: {reply}")
                break
            else:
                log.info(f"✅ 回复 {len(reply)} 字符")

        # 推送到服务器（让 Web UI 也能用）
        tokens = []
        for _ in range(3):
            t = await page.evaluate(f"""() => {{
                return new Promise((resolve, reject) => {{
                    const g = window.grecaptcha.enterprise || window.grecaptcha;
                    g.ready(() => g.execute('{SITEKEY}', {{action: 'chat_submit'}}).then(resolve).catch(reject));
                }});
            }}""")
            tokens.append(t)

        auth_parts = [v for k, v in sorted(cookies.items()) if "auth" in k.lower()]
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{SERVER}/v1/extension/push", json={
                "cookies": cookies,
                "auth_token": "".join(auth_parts),
                "models": models,
                "v3_tokens": [{"token": t, "action": "chat_submit", "age_ms": 0} for t in tokens],
            })
        log.info("✓ 已推送数据到服务器")

        # 现在试试通过服务器代理
        log.info("\n--- 通过 OpenAI SDK 代理测试 ---")
        try:
            from openai import OpenAI
            client = OpenAI(base_url=f"{SERVER}/v1", api_key="not-needed")
            stream = client.chat.completions.create(
                model=target_name,
                messages=[{"role": "user", "content": "Say hello in Chinese"}],
                stream=True,
            )
            full = ""
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    t = chunk.choices[0].delta.content
                    full += t
                    print(t, end="", flush=True)
            print()
            if full and "[Error" not in full:
                log.info(f"✅ 代理模式也成功了！{len(full)} chars")
            else:
                log.warning(f"代理模式: {full}")
        except Exception as e:
            log.warning(f"代理测试: {e}")


if __name__ == "__main__":
    asyncio.run(main())
