#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "scripts" / "browser_cli.py"
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from browser_runtime import BrowserRuntime, BrowserRuntimeError, detect_human_blocker, snapshot_page


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class OAuthSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures_dir = Path(__file__).resolve().parent / "fixtures"
        handler = partial(QuietHandler, directory=str(fixtures_dir))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_credential_fill_enforces_target_domain_allow_rule(self):
        """RED 3: 目标域 Allow Rule 优先。当前页面域名不匹配 target_domain 时严禁 credential_fill"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / "profile"
            cred_root = root / "credentials"

            actions = [
                {
                    "type": "credential_fill",
                    "selector": "#password",
                    "credential": "site_password",
                    "mode": "create_or_reuse",
                    "account": "test@example.com",
                }
            ]

            # 指定目标平台域名为 target-directory.com，而当前测试服务器为 127.0.0.1
            # 必须被 Target Domain Allow Rule 拒绝，严禁向非目标域填充密码
            with self.assertRaises(BrowserRuntimeError) as ctx:
                with BrowserRuntime(
                    profile_dir=profile,
                    browser_channel="chromium",
                    credential_root=cred_root,
                    target_domain="target-directory.com",
                    allow_local_fallback=True,
                ) as rt:
                    rt.execute(f"{self.base_url}/form.html", actions)

            self.assertIn(ctx.exception.code, {"CREDENTIAL_TARGET_MISMATCH", "PROTECTED_OAUTH_DOMAIN"})

    def test_credential_fill_strictly_forbids_third_party_idp_domains(self):
        """RED 3 (二层防御): 第三方 IdP 域名（Google, GitHub, Twitter 等）严禁 credential_fill"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / "profile"
            cred_root = root / "credentials"

            actions = [
                {
                    "type": "credential_fill",
                    "selector": "#password",
                    "credential": "site_password",
                    "mode": "create_or_reuse",
                    "account": "test@example.com",
                }
            ]

            # 即使 target_domain 错误地配置为 google.com，第二层 IdP 黑名单也必须拦截
            with self.assertRaises(BrowserRuntimeError) as ctx:
                with BrowserRuntime(
                    profile_dir=profile,
                    browser_channel="chromium",
                    credential_root=cred_root,
                    target_domain="accounts.google.com",
                    allow_local_fallback=True,
                ) as rt:
                    rt.execute(f"{self.base_url}/form.html", actions)

            self.assertIn(ctx.exception.code, {"PROTECTED_OAUTH_DOMAIN", "CREDENTIAL_TARGET_MISMATCH"})

    def test_email_otp_requires_composite_evidence(self):
        """RED 4: EMAIL_OTP 必须使用组合证据（验证码 + 邮箱上下文），单项证据不误报 EMAIL_OTP"""
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"
            with BrowserRuntime(
                profile_dir=profile,
                browser_channel="chromium",
                allow_local_fallback=True,
            ) as rt:
                # 场景 A: 仅有普通 verification code，无邮箱上下文 -> 不能是 EMAIL_OTP
                rt.navigate(f"{self.base_url}/form.html")
                assert rt.page is not None
                blocker_generic = detect_human_blocker(
                    rt.page,
                    body_excerpt="Please enter the verification code to continue."
                )
                if blocker_generic is not None:
                    self.assertNotEqual(blocker_generic["code"], "EMAIL_OTP", "Single verification code without email context falsely classified as EMAIL_OTP!")

                # 场景 B: 组合证据（验证码 + 邮箱发送/inbox 上下文） -> 精确判定为 EMAIL_OTP
                blocker_email_otp = detect_human_blocker(
                    rt.page,
                    body_excerpt="We sent a 6-digit verification code to your email. Please check your inbox and enter the code."
                )
                self.assertIsNotNone(blocker_email_otp, "Failed to detect email OTP blocker")
                self.assertEqual(blocker_email_otp["code"], "EMAIL_OTP")

    def test_red_email_otp_priority_over_two_factor_and_long_page(self):
        """RED: 页面包含长前置文案且具有 Verify Email / verification code，同时 input 带有 one-time-code 时，
        必须优先判定为 EMAIL_OTP，不得误判为 TWO_FACTOR。"""
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"
            with BrowserRuntime(
                profile_dir=profile,
                browser_channel="chromium",
                allow_local_fallback=True,
            ) as rt:
                assert rt.page is not None
                # 模拟类似真实页面的长内容（超过 4000 字符的前置文本）以及尾部的邮箱验证码表单
                long_prefix = "Testimonial and community feedback about modern apps. " * 100  # > 5000 chars
                html = f"""<!DOCTYPE html>
                <html>
                <body>
                    <div>{long_prefix}</div>
                    <section>
                        <h2>Verify Email</h2>
                        <p>Enter the verification code we sent to your email</p>
                        <input type="text" autocomplete="one-time-code" placeholder="6-digit code">
                        <button type="submit">Verify & Continue</button>
                    </section>
                </body>
                </html>
                """
                rt.page.set_content(html)
                snapshot = snapshot_page(rt.page)
                blocker = snapshot.get("human_blocker")
                self.assertIsNotNone(blocker, "Human blocker was not detected")
                self.assertEqual(blocker["code"], "EMAIL_OTP", f"Expected EMAIL_OTP but got {blocker.get('code')}")


if __name__ == "__main__":
    unittest.main()
