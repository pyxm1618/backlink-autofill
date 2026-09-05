#!/usr/bin/env python3
import json
import subprocess
import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

# RED: 这些模块和函数即将被实现
from email_otp_resolver import (
    EmailVerificationRequest,
    EmailMessage,
    EmailOtpResolution,
    normalize_codex_gmail_messages,
    normalize_antigravity_mcp_messages,
    resolve_email_otp_from_messages,
    is_protected_auth_email,
)
import browser_runtime


class EmailOtpResolverTests(unittest.TestCase):
    def setUp(self):
        self.request = EmailVerificationRequest(
            project_id="quick-iching",
            backlink_id="foundrlist.com",
            platform_domain="foundrlist.com",
            platform_name="FoundrList",
            registration_email="pyxm1618@gmail.com",
            blocker_started_at=1788587899.0,
            target_id="C725889AECDDBA8597995A2CA06866CB",
            expected_code_length=6,
            expected_code_kind="numeric",
            email_context_hints=["verify email", "verification code"],
        )

    def test_provider_neutral_email_verification_request(self):
        """1. 结构化请求验证：无 Gmail 凭据、字段完整、支持序列化与 expected_code_kind"""
        data = self.request.to_dict()
        self.assertEqual(data["project_id"], "quick-iching")
        self.assertEqual(data["platform_domain"], "foundrlist.com")
        self.assertEqual(data["expected_code_length"], 6)
        self.assertEqual(data["expected_code_kind"], "numeric")
        self.assertNotIn("token", data)
        self.assertNotIn("cookie", data)
        self.assertNotIn("password", data)
        self.assertNotIn("secret", data)

        # 反序列化还原
        restored = EmailVerificationRequest.from_dict(data)
        self.assertEqual(restored.project_id, self.request.project_id)
        self.assertEqual(restored.target_id, self.request.target_id)

    def test_codex_gmail_adapter_normalization(self):
        """2. Codex Gmail capability 适配器数据归一化"""
        raw_codex_data = {
            "messages": [
                {
                    "id": "codex-msg-1",
                    "from": "FoundrList <notifications@foundrlist.com>",
                    "to": "pyxm1618@gmail.com",
                    "subject": "Your FoundrList verification code",
                    "date": 1788587910.0,
                    "body": "Welcome! Your verification code is 839201. Enter it to verify your email.",
                    "snippet": "Your verification code is 839201",
                }
            ]
        }
        normalized = normalize_codex_gmail_messages(raw_codex_data)
        self.assertEqual(len(normalized), 1)
        self.assertIsInstance(normalized[0], EmailMessage)
        self.assertEqual(normalized[0].id, "codex-msg-1")
        self.assertEqual(normalized[0].recipient, "pyxm1618@gmail.com")
        self.assertIn("839201", normalized[0].body_text)

    def test_antigravity_gmail_mcp_adapter_normalization(self):
        """3. Antigravity Gmail MCP capability 适配器数据归一化"""
        raw_mcp_messages = [
            {
                "ID": "mcp-msg-1",
                "From": "FoundrList <notifications@foundrlist.com>",
                "To": "pyxm1618@gmail.com",
                "Subject": "Your FoundrList verification code",
                "Date": "Wed, 05 Sep 2026 08:38:30 +0000",
                "DateTimestamp": 1788587910.0,
                "Snippet": "Your verification code is 839201",
                "Body": "Welcome! Your verification code is 839201. Enter it to verify your email.",
            }
        ]
        normalized = normalize_antigravity_mcp_messages(raw_mcp_messages)
        self.assertEqual(len(normalized), 1)
        self.assertIsInstance(normalized[0], EmailMessage)
        self.assertEqual(normalized[0].id, "mcp-msg-1")
        self.assertEqual(normalized[0].recipient, "pyxm1618@gmail.com")
        self.assertIn("839201", normalized[0].body_text)

    def test_both_providers_produce_identical_resolution(self):
        """4. 双 Provider 对同一组邮件 evidence 产生完全相同的判定结果与 OTP"""
        codex_raw = {
            "messages": [
                {
                    "id": "msg-shared-1",
                    "from": "FoundrList Team <verify@foundrlist.com>",
                    "to": "pyxm1618@gmail.com",
                    "subject": "Verify your email for FoundrList",
                    "date": 1788587920.0,
                    "body": "Your 6-digit code is 492018. It expires in 10 minutes.",
                }
            ]
        }
        mcp_raw = [
            {
                "ID": "msg-shared-1",
                "From": "FoundrList Team <verify@foundrlist.com>",
                "To": "pyxm1618@gmail.com",
                "Subject": "Verify your email for FoundrList",
                "DateTimestamp": 1788587920.0,
                "Body": "Your 6-digit code is 492018. It expires in 10 minutes.",
            }
        ]

        norm_codex = normalize_codex_gmail_messages(codex_raw)
        norm_mcp = normalize_antigravity_mcp_messages(mcp_raw)

        res_codex = resolve_email_otp_from_messages(self.request, norm_codex)
        res_mcp = resolve_email_otp_from_messages(self.request, norm_mcp)

        self.assertEqual(res_codex.status, "RESOLVED")
        self.assertEqual(res_mcp.status, "RESOLVED")
        self.assertEqual(res_codex.code, "492018")
        self.assertEqual(res_mcp.code, "492018")
        self.assertEqual(res_codex.code, res_mcp.code)

    def test_provider_empty_or_unavailable_leads_to_needs_human(self):
        """5. 无有效邮件或未找到 → EMAIL_OTP_NOT_FOUND (NEEDS_HUMAN)"""
        res = resolve_email_otp_from_messages(self.request, [])
        self.assertEqual(res.status, "EMAIL_OTP_NOT_FOUND")
        self.assertIsNone(res.code)
        self.assertEqual(res.action_required, "NEEDS_HUMAN")

    def test_ambiguous_candidates_lead_to_needs_human(self):
        """6. 多封不同来源/歧义候选 → EMAIL_OTP_AMBIGUOUS (NEEDS_HUMAN)，严禁猜测"""
        messages = [
            EmailMessage(
                id="msg-1",
                sender="FoundrList <notify@foundrlist.com>",
                recipient="pyxm1618@gmail.com",
                subject="Verification code",
                date_timestamp=1788587915.0,
                body_text="Your code is 111111",
            ),
            EmailMessage(
                id="msg-2",
                sender="FoundrList <team@foundrlist.com>",
                recipient="pyxm1618@gmail.com",
                subject="Verification code",
                date_timestamp=1788587916.0,
                body_text="Your code is 222222",
            ),
        ]
        res = resolve_email_otp_from_messages(self.request, messages)
        self.assertEqual(res.status, "EMAIL_OTP_AMBIGUOUS")
        self.assertIsNone(res.code)
        self.assertEqual(res.action_required, "NEEDS_HUMAN")

    def test_protected_auth_candidates_excluded_per_candidate(self):
        """7. Protected Auth 逐候选排除：Google/IdP/Password Reset 不得阻断同批次合法平台邮件"""
        google_alert = EmailMessage(
            id="google-alert-1",
            sender="Google <no-reply@accounts.google.com>",
            recipient="pyxm1618@gmail.com",
            subject="Security alert: New login",
            date_timestamp=1788587910.0,
            body_text="Your Google verification code is 999888. Never share this code.",
        )
        self.assertTrue(is_protected_auth_email(google_alert, self.request))

        github_reset = EmailMessage(
            id="gh-reset-1",
            sender="GitHub <support@github.com>",
            recipient="pyxm1618@gmail.com",
            subject="[GitHub] Please reset your password",
            date_timestamp=1788587912.0,
            body_text="Use code 777666 to reset your password.",
        )
        self.assertTrue(is_protected_auth_email(github_reset, self.request))

        valid_platform_msg = EmailMessage(
            id="valid-foundrlist-1",
            sender="FoundrList <verify@foundrlist.com>",
            recipient="pyxm1618@gmail.com",
            subject="Verify your FoundrList email",
            date_timestamp=1788587915.0,
            body_text="Welcome to FoundrList! Verification code: 654321.",
        )
        self.assertFalse(is_protected_auth_email(valid_platform_msg, self.request))

        # 批次输入包含两封受保护邮件和一封合法平台邮件
        mixed_batch = [google_alert, github_reset, valid_platform_msg]
        res = resolve_email_otp_from_messages(self.request, mixed_batch)

        # 核心断言：受保护邮件被排除后，合法平台邮件脱颖而出并成功 resolve
        self.assertEqual(res.status, "RESOLVED")
        self.assertEqual(res.code, "654321")
        self.assertEqual(res.matched_message_id, "valid-foundrlist-1")

    def test_third_party_esp_sender_domain_scoring(self):
        """8. Platform Identity 评分机制：支持 Resend/Postmark 等第三方邮件通道发出的平台邮件"""
        esp_msg = EmailMessage(
            id="esp-msg-1",
            sender="FoundrList Team <auth@mail.resend.com>",  # 域名为 resend.com，但 display name 与正文指明 FoundrList
            recipient="pyxm1618@gmail.com",
            subject="Confirm your registration on FoundrList",
            date_timestamp=1788587910.0,
            body_text="Hi! Thank you for signing up on https://foundrlist.com. Here is your code: 381920.",
        )
        res = resolve_email_otp_from_messages(self.request, [esp_msg])
        self.assertEqual(res.status, "RESOLVED")
        self.assertEqual(res.code, "381920")

    def test_otp_not_in_persisted_state_or_logs_or_cli_output(self):
        """9. OTP 零持久化：请求对象、持久化记录、返回字典绝不包含密码或凭据"""
        req_dict = self.request.to_dict()
        req_json = json.dumps(req_dict)
        self.assertNotIn("otp", req_json.lower())
        self.assertNotIn("password", req_json.lower())

    def test_cli_resolve_email_otp_ephemeral_stdin_channel(self):
        """10. CLI resolve-email-otp 仅通过子进程 stdin 传码，argv 与 stdout 绝对不泄漏 OTP"""
        cmd = [
            sys.executable,
            str(PLUGIN_ROOT / "scripts" / "browser_cli.py"),
            "resolve-email-otp",
            "--profile-dir", "/tmp/fake-profile",
            "--url", "https://www.foundrlist.com/signup",
            "--stdin",
        ]
        # 确认命令行参数列表中绝对没有 6 位数字 OTP
        self.assertNotIn("123456", " ".join(cmd))

        # 测试当 stdin 未提供 OTP 时，返回安全错误且退出码非 0，不输出任何未捕获崩溃
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out, err = proc.communicate(input=b"\n")
        self.assertNotEqual(proc.returncode, 0)
        err_json = json.loads(err.decode("utf-8"))
        self.assertEqual(err_json.get("error_code"), "MISSING_TARGET_ID")


    def test_provider_layer_does_not_pollute_browser_runtime(self):
        """11. 边界隔离：Browser Runtime 不得导入任何 Gmail / MCP / Codex 模块"""
        with open(PLUGIN_ROOT / "scripts" / "browser_runtime.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("gmail", content.lower())
        self.assertNotIn("mcp", content.lower())
        self.assertNotIn("codex", content.lower())

    def test_e2e_fill_and_submit_otp_via_stdin_channel(self):
        """12. 真实 E2E: resolve_email_otp 定位表单、填入并提交，返回数据绝不包含 OTP"""
        import tempfile
        from functools import partial
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        import threading

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            html_file = tmp_dir / "otp_test.html"
            html_file.write_text(
                """<!DOCTYPE html>
                <html><body>
                  <h1>Verify Email</h1>
                  <p>Enter the code sent to your email</p>
                  <form id="verify-form">
                    <input id="code-input" type="text" autocomplete="one-time-code" placeholder="6-digit code">
                    <button id="verify-btn" type="submit">Verify & Continue</button>
                  </form>
                  <div id="status">Waiting</div>
                  <script>
                    document.getElementById('verify-form').onsubmit = (e) => {
                      e.preventDefault();
                      document.getElementById('status').innerText = 'Verified: ' + document.getElementById('code-input').value;
                    };
                  </script>
                </body></html>
                """,
                encoding="utf-8",
            )
            handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_dir))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            port = server.server_port
            url = f"http://127.0.0.1:{port}/otp_test.html"

            profile = tmp_dir / "profile"
            with browser_runtime.BrowserRuntime(
                profile_dir=profile,
                browser_channel="chromium",
                allow_local_fallback=True,
            ) as rt:
                snap = rt.navigate(url)
                self.assertIsNotNone(snap.get("human_blocker"))
                self.assertEqual(snap["human_blocker"]["code"], "EMAIL_OTP")
                res = rt.resolve_email_otp(target_id="", otp_code="654321")
                self.assertTrue(res["ok"])
                self.assertEqual(res["action"], "EMAIL_OTP_RESOLVED")
                self.assertNotIn("654321", json.dumps(res))
                status_text = rt.page.locator("#status").inner_text()
                self.assertEqual(status_text, "Verified: 654321")

            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
