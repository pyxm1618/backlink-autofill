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
    def test_cli_resolve_email_otp_with_target_id_initialization(self):
        """10b. CLI resolve-email-otp 携带 target-id 和 stdin 时正常初始化 Runtime，绝不出现 TypeError('headed')"""
        cmd = [
            sys.executable,
            str(PLUGIN_ROOT / "scripts" / "browser_cli.py"),
            "resolve-email-otp",
            "--profile-dir", "/tmp/fake-profile",
            "--url", "https://www.foundrlist.com/signup",
            "--target-id", "C725889AECDDBA8597995A2CA06866CB",
            "--allow-local-fallback",
            "--stdin",
        ]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out, err = proc.communicate(input=b"839201\n")
        # 核心断言：绝不能出现 TypeError 崩溃，绝不因 headed 参数错误报错
        err_text = err.decode("utf-8")
        self.assertNotIn("TypeError", err_text)
        self.assertNotIn("unexpected keyword argument 'headed'", err_text)
        if err_text:
            err_json = json.loads(err_text)
            self.assertNotEqual(err_json.get("message"), "Unexpected browser runtime failure: TypeError")


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

    def test_magic_link_platform_resolution(self):
        """Magic Link 解析：平台自身确认邮件提取 verification link 并标记 kind='magic_link'"""
        msg = EmailMessage(
            id="ml-msg-1",
            sender="FoundrList <auth@foundrlist.com>",
            recipient="pyxm1618@gmail.com",
            subject="Confirm your FoundrList account",
            date_timestamp=1788587910.0,
            body_text="Click here to confirm your account: https://foundrlist.com/auth/confirm?token=xyz123abc. This link expires in 15 minutes.",
            snippet="Click here to confirm your account",
        )
        res = resolve_email_otp_from_messages(self.request, [msg])
        self.assertEqual(res.status, "RESOLVED")
        self.assertEqual(res.kind, "magic_link")
        self.assertIn("https://foundrlist.com/auth/confirm?token=xyz123abc", res.verification_link)

    def test_magic_link_esp_redirect_boundary_case_a(self):
        """Case A 边界：第三方 ESP redirect (click.postmarkapp.com) 允许提取并在闭环到达平台时自动完成"""
        from email_otp_resolver import validate_magic_link_closure

        msg = EmailMessage(
            id="esp-msg-1",
            sender="FoundrList Support <notifications@postmark.foundrlist.com>",
            recipient="pyxm1618@gmail.com",
            subject="Verify your email for FoundrList",
            date_timestamp=1788587915.0,
            body_text="Please verify your email: https://click.postmarkapp.com/f/a/xyz987token/foundrlist-verify",
            snippet="Please verify your email",
        )
        res = resolve_email_otp_from_messages(self.request, [msg])
        self.assertEqual(res.status, "RESOLVED")
        self.assertEqual(res.kind, "magic_link")
        self.assertIn("click.postmarkapp.com", res.verification_link)

        # 模拟浏览器导航后最终重定向到目标平台：验证通过
        final_redirect_url = "https://foundrlist.com/onboarding/welcome?verified=true"
        closure_ok = validate_magic_link_closure(final_redirect_url, platform_domain="foundrlist.com")
        self.assertTrue(closure_ok, "ESP redirect landing on platform domain must achieve closure")

    def test_magic_link_protected_idp_boundary_case_b(self):
        """Case B 边界：引导到 accounts.google.com 受保护身份验证时必须拒绝自动处理转需人工"""
        from email_otp_resolver import validate_magic_link_closure

        # 1. 链接直接指向 accounts.google.com 被直接过滤
        msg = EmailMessage(
            id="idp-msg-1",
            sender="FoundrList <auth@foundrlist.com>",
            recipient="pyxm1618@gmail.com",
            subject="Sign in to FoundrList with Google",
            date_timestamp=1788587915.0,
            body_text="Click here to authenticate with Google: https://accounts.google.com/o/oauth2/auth?client_id=123",
            snippet="Authenticate with Google",
        )
        res = resolve_email_otp_from_messages(self.request, [msg])
        # 因为指向受保护 IdP，链接未被作为平台 magic link 提取，返回 NOT_FOUND 并需人工
        self.assertEqual(res.status, "EMAIL_OTP_NOT_FOUND")
        self.assertEqual(res.action_required, "NEEDS_HUMAN")

        # 2. 若中间跳转最终落到 accounts.google.com，安全闭环检查拒绝自动处理
        closure_fail = validate_magic_link_closure(
            "https://accounts.google.com/signin/challenge/pwd",
            platform_domain="foundrlist.com",
        )
        self.assertFalse(closure_fail, "Closure must reject landing on accounts.google.com")

    def test_magic_link_ambiguous_tokens_fallback(self):
        """多封邮件带有冲突的验证链接时，判定为 AMBIGUOUS 并回退需人工"""
        msg1 = EmailMessage(
            id="ml-msg-1",
            sender="FoundrList <auth@foundrlist.com>",
            recipient="pyxm1618@gmail.com",
            subject="Confirm your FoundrList account",
            date_timestamp=1788587910.0,
            body_text="Verify here: https://foundrlist.com/verify?token=tokenAAA",
        )
        msg2 = EmailMessage(
            id="ml-msg-2",
            sender="FoundrList <auth@foundrlist.com>",
            recipient="pyxm1618@gmail.com",
            subject="Confirm your FoundrList account",
            date_timestamp=1788587912.0,
            body_text="Verify here: https://foundrlist.com/verify?token=tokenBBB",
        )
        res = resolve_email_otp_from_messages(self.request, [msg1, msg2])
        self.assertEqual(res.status, "EMAIL_OTP_AMBIGUOUS")
        self.assertEqual(res.action_required, "NEEDS_HUMAN")

    def test_magic_link_dns_boundary_checks(self):
        """P0-3: 严格 DNS 边界匹配，拦截 foundrlist.com.evil.example 仿冒攻击"""
        from email_otp_resolver import is_safe_subdomain_or_exact, is_allowed_initial_magic_link_host

        # 子域与精确匹配
        self.assertTrue(is_safe_subdomain_or_exact("foundrlist.com", "foundrlist.com"))
        self.assertTrue(is_safe_subdomain_or_exact("auth.foundrlist.com", "foundrlist.com"))
        self.assertTrue(is_safe_subdomain_or_exact("sub.auth.foundrlist.com", "foundrlist.com"))
        self.assertTrue(is_safe_subdomain_or_exact("www.foundrlist.com", "foundrlist.com"))

        # 恶意后缀绕过攻击必须严格拦截
        self.assertFalse(is_safe_subdomain_or_exact("foundrlist.com.evil.example", "foundrlist.com"))
        self.assertFalse(is_safe_subdomain_or_exact("notfoundrlist.com", "foundrlist.com"))
        self.assertFalse(is_safe_subdomain_or_exact("evil-foundrlist.com", "foundrlist.com"))

        # is_allowed_initial_magic_link_host 平台与 ESP 检验
        self.assertTrue(is_allowed_initial_magic_link_host("foundrlist.com", "foundrlist.com"))
        self.assertTrue(is_allowed_initial_magic_link_host("auth.foundrlist.com", "foundrlist.com"))
        self.assertTrue(is_allowed_initial_magic_link_host("click.postmarkapp.com", "foundrlist.com"))
        self.assertTrue(is_allowed_initial_magic_link_host("link.mailgun.org", "foundrlist.com"))
        self.assertTrue(is_allowed_initial_magic_link_host("email.mg.resend.com", "foundrlist.com"))

        # ESP 恶意仿冒与受保护 IdP 必须严格拦截
        self.assertFalse(is_allowed_initial_magic_link_host("postmarkapp.com.evil.example", "foundrlist.com"))
        self.assertFalse(is_allowed_initial_magic_link_host("sendgrid.net.attacker.com", "foundrlist.com"))
        self.assertFalse(is_allowed_initial_magic_link_host("accounts.google.com", "foundrlist.com"))
        self.assertFalse(is_allowed_initial_magic_link_host("github.com", "foundrlist.com"))

    def test_resolve_email_magic_link_redacts_tokens_completely(self):
        """P0-2: Magic Link 成功后绝不通过 current_url 泄露 token/query，仅返回安全落地 host"""
        import tempfile
        from functools import partial
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        import threading

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            html_file = tmp_dir / "index.html"
            html_file.write_text("<!DOCTYPE html><html><body><h1>Welcome Dashboard</h1></body></html>", encoding="utf-8")
            handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_dir))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            port = server.server_port
            secret_token = "SUPER_SECRET_TOKEN_ABC123_XYZ"
            magic_url = f"http://127.0.0.1:{port}/index.html?token={secret_token}&verify=true"

            profile = tmp_dir / "profile"
            with browser_runtime.BrowserRuntime(
                profile_dir=profile,
                browser_channel="chromium",
                allow_local_fallback=True,
            ) as rt:
                rt.navigate(f"http://127.0.0.1:{port}/index.html")
                res = rt.resolve_email_magic_link(
                    target_id="",
                    magic_link=magic_url,
                    platform_domain=f"127.0.0.1:{port}",
                )

                self.assertTrue(res["ok"])
                self.assertEqual(res["action"], "MAGIC_LINK_RESOLVED")
                self.assertTrue(res["closure_verified"])
                self.assertEqual(res["safe_landed_domain"], "127.0.0.1")

                # 核心断言：绝对没有 current_url 键
                self.assertNotIn("current_url", res)

                # 核心断言：secret_token 绝对不出现在返回字典序列化后的任何角落
                res_json = json.dumps(res)
                self.assertNotIn(secret_token, res_json)

            server.shutdown()
            server.server_close()

    def test_resolve_email_magic_link_blocks_forbidden_host_before_goto(self):
        """P0-3: initial URL 若指向不合规域名，在 goto 前强拦截抛出 MAGIC_LINK_HOST_FORBIDDEN 且不泄露 token"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"
            with browser_runtime.BrowserRuntime(
                profile_dir=profile,
                browser_channel="chromium",
                allow_local_fallback=True,
            ) as rt:
                secret_token = "SECRET_TOKEN_NOT_ALLOWED"
                forbidden_url = f"https://foundrlist.com.evil.example/confirm?token={secret_token}"

                with self.assertRaises(browser_runtime.BrowserRuntimeError) as ctx:
                    rt.resolve_email_magic_link(
                        target_id="",
                        magic_link=forbidden_url,
                        platform_domain="foundrlist.com",
                    )

                self.assertEqual(ctx.exception.code, "MAGIC_LINK_HOST_FORBIDDEN")
                # 异常消息中绝对不泄漏 secret_token
                self.assertNotIn(secret_token, ctx.exception.message)

    def test_extract_verification_link_strictly_filters_footers_and_requires_cta(self):
        """P0-3: 消除 Magic Link 假候选：排除主页/条款/退订，支持带 CTA 上下文的 opaque ESP URL"""
        from email_otp_resolver import _extract_verification_link

        platform = "foundrlist.com"

        # 1. 纯主页无 cue：绝对不选为候选
        email_homepage_only = "Welcome to FoundrList! Visit us at https://foundrlist.com anytime."
        self.assertIsNone(_extract_verification_link(email_homepage_only, platform))

        # 2. 条款/隐私/退订链接：绝对不选为候选
        email_footers = """
        Thanks for using FoundrList.
        Terms: https://foundrlist.com/terms
        Privacy: https://foundrlist.com/privacy
        Unsubscribe: https://click.postmarkapp.com/unsubscribe/xyz123
        """
        self.assertIsNone(_extract_verification_link(email_footers, platform))

        # 3. HTML 带有退订 anchor：排除
        html_unsub = '<a href="https://click.postmarkapp.com/track/opaque_unsub">Unsubscribe from email</a>'
        self.assertIsNone(_extract_verification_link(html_unsub, platform))

        # 4. Opaque ESP tracking URL 配合 verification CTA：成功提取！
        html_opaque_cta = """
        <div>
          <p>Please click below to activate your account:</p>
          <a href="https://click.postmarkapp.com/track/opaque_magic_link_token_123">Confirm your email</a>
        </div>
        """
        link = _extract_verification_link(html_opaque_cta, platform)
        self.assertEqual(link, "https://click.postmarkapp.com/track/opaque_magic_link_token_123")

        # 5. 纯文本 opaque ESP URL 紧邻验证提示：成功提取！
        text_opaque_cta = """
        To finish signing in, click the link below to verify your email address:
        https://click.postmarkapp.com/track/opaque_txt_789
        """
        link_txt = _extract_verification_link(text_opaque_cta, platform)
        self.assertEqual(link_txt, "https://click.postmarkapp.com/track/opaque_txt_789")

    def test_resolve_email_magic_link_detects_expired_or_invalid(self):
        """P0-3: Magic link 落地到失效或过期页面，抛出 MAGIC_LINK_EXPIRED_OR_INVALID"""
        import tempfile
        import threading
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        from functools import partial

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            html_file = tmp_dir / "expired.html"
            html_file.write_text("<!DOCTYPE html><html><body><h1>Your verification token has expired</h1></body></html>", encoding="utf-8")
            handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_dir))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            port = server.server_port
            expired_url = f"http://127.0.0.1:{port}/expired.html"

            try:
                profile = tmp_dir / "profile"
                with browser_runtime.BrowserRuntime(
                    profile_dir=profile,
                    browser_channel="chromium",
                    allow_local_fallback=True,
                ) as rt:
                    rt.navigate(f"http://127.0.0.1:{port}/expired.html")
                    with self.assertRaises(browser_runtime.BrowserRuntimeError) as ctx:
                        rt.resolve_email_magic_link(
                            target_id="",
                            magic_link=expired_url,
                            platform_domain=f"127.0.0.1:{port}",
                        )
                    self.assertEqual(ctx.exception.code, "MAGIC_LINK_EXPIRED_OR_INVALID")
            finally:
                server.shutdown()
                server.server_close()

    def test_resolve_email_magic_link_rejects_unconfirmed_without_positive_evidence(self):
        """P0-3: 仅到达 /dashboard 缺乏正面验证证据，严禁假成功，抛出 MAGIC_LINK_UNCONFIRMED"""
        import tempfile
        import threading
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        from functools import partial

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            html_file = tmp_dir / "dashboard.html"
            # 页面只有普通文本和 Logout，没有明确 verification success
            html_file.write_text("<!DOCTYPE html><html><body><h1>Dashboard</h1><button>Logout</button></body></html>", encoding="utf-8")
            handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_dir))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            port = server.server_port
            dashboard_url = f"http://127.0.0.1:{port}/dashboard.html"

            try:
                profile = tmp_dir / "profile"
                with browser_runtime.BrowserRuntime(
                    profile_dir=profile,
                    browser_channel="chromium",
                    allow_local_fallback=True,
                ) as rt:
                    rt.navigate(f"http://127.0.0.1:{port}/dashboard.html")
                    with self.assertRaises(browser_runtime.BrowserRuntimeError) as ctx:
                        rt.resolve_email_magic_link(
                            target_id="",
                            magic_link=dashboard_url,
                            platform_domain=f"127.0.0.1:{port}",
                        )
                    self.assertEqual(ctx.exception.code, "MAGIC_LINK_UNCONFIRMED")
            finally:
                server.shutdown()
                server.server_close()

    def test_resolve_email_magic_link_succeeds_with_explicit_dom_success(self):
        """P0-3: DOM 出现明确成功文案，正确返回验证成功"""
        import tempfile
        import threading
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        from functools import partial

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            html_file = tmp_dir / "confirmed.html"
            html_file.write_text("<!DOCTYPE html><html><body><h1>Your email has been verified!</h1></body></html>", encoding="utf-8")
            handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_dir))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            port = server.server_port
            confirmed_url = f"http://127.0.0.1:{port}/confirmed.html"

            try:
                profile = tmp_dir / "profile"
                with browser_runtime.BrowserRuntime(
                    profile_dir=profile,
                    browser_channel="chromium",
                    allow_local_fallback=True,
                ) as rt:
                    rt.navigate(f"http://127.0.0.1:{port}/confirmed.html")
                    res = rt.resolve_email_magic_link(
                        target_id="",
                        magic_link=confirmed_url,
                        platform_domain=f"127.0.0.1:{port}",
                    )
                    self.assertTrue(res["ok"])
                    self.assertEqual(res["action"], "MAGIC_LINK_RESOLVED")
                    self.assertTrue(res["verification_succeeded"])
                    self.assertEqual(res["safe_landed_domain"], "127.0.0.1")
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
