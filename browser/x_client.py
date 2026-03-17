"""Playwright browser manager for X. Uses persistent Chrome profile."""

import asyncio
import hashlib
import hmac
import struct
import sys
import time
import base64
from playwright.async_api import async_playwright, BrowserContext, Page


def _generate_totp(secret: str, period: int = 30, digits: int = 6) -> str:
    """Generate a TOTP code from a base32-encoded secret."""
    secret_bytes = base64.b32decode(secret.upper().replace(" ", ""))
    counter = int(time.time()) // period
    counter_bytes = struct.pack(">Q", counter)
    hmac_hash = hmac.new(secret_bytes, counter_bytes, hashlib.sha1).digest()
    offset = hmac_hash[-1] & 0x0F
    truncated = struct.unpack(">I", hmac_hash[offset:offset + 4])[0] & 0x7FFFFFFF
    code = truncated % (10 ** digits)
    return str(code).zfill(digits)


def _chrome_profile_is_locked(profile_path: str) -> bool:
    """Check if a Chrome profile directory is locked by another process."""
    import os
    if sys.platform == "win32":
        lock_file = os.path.join(profile_path, "lockfile")
        if os.path.exists(lock_file):
            try:
                os.rename(lock_file, lock_file)
                return False
            except OSError:
                return True
        return False
    else:
        return os.path.exists(os.path.join(profile_path, "SingletonLock"))


class XClient:
    def __init__(
        self,
        chrome_profile_path: str,
        headless: bool = False,
        profile_directory: str = "",
    ):
        self.chrome_profile_path = chrome_profile_path
        self.headless = headless
        self.profile_directory = profile_directory
        self._playwright = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._log_fn = None

    def set_log_fn(self, fn):
        self._log_fn = fn

    def _log(self, msg: str):
        if self._log_fn:
            self._log_fn(msg)

    async def start(self) -> Page:
        if self._context is not None:
            self._log("Browser already running, reusing existing session.")
            return self._page

        if _chrome_profile_is_locked(self.chrome_profile_path):
            self._log(
                "WARNING: Chrome profile appears locked. "
                "If launch fails, close Chrome tabs using this profile and retry."
            )

        args = ["--disable-blink-features=AutomationControlled"]
        if self.profile_directory:
            args.append(f"--profile-directory={self.profile_directory}")

        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.chrome_profile_path,
            channel="chrome",
            headless=self.headless,
            viewport={"width": 1280, "height": 900},
            args=args,
        )
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()
        return self._page

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    async def navigate(self, url: str, wait_ms: int = 3000):
        await self.page.goto(url, wait_until="domcontentloaded")
        await self.page.wait_for_timeout(wait_ms)

    async def is_logged_in(self) -> bool:
        """Check if user is logged into X by looking for the compose button."""
        await self.navigate("https://x.com/home")
        try:
            await self.page.wait_for_selector(
                'a[href="/compose/post"], [data-testid="SideNav_NewTweet_Button"]',
                timeout=8000,
            )
            return True
        except Exception:
            return False

    async def login(self, username: str, password: str, totp_secret: str = "") -> bool:
        """Log into X with username, password, and optional TOTP 2FA."""
        self._log("Navigating to X login...")
        await self.page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded")
        await self.page.wait_for_timeout(3000)

        # Step 1: Enter username
        self._log("Entering username...")
        try:
            username_input = self.page.locator('input[autocomplete="username"], input[name="text"]').first
            await username_input.wait_for(timeout=10000)
            await username_input.click()
            await username_input.fill(username)
            await self.page.wait_for_timeout(500)

            next_btn = self.page.locator('button:has-text("Next"), [role="button"]:has-text("Next")').first
            await next_btn.click()
            await self.page.wait_for_timeout(2000)
        except Exception as e:
            self._log(f"Failed at username step: {e}")
            return False

        # Step 1b: Handle unusual activity / confirmation challenge
        try:
            challenge_input = self.page.locator('input[data-testid="ocfEnterTextTextInput"]')
            if await challenge_input.count() > 0 and await challenge_input.first.is_visible():
                self._log("Confirmation challenge detected, entering username again...")
                await challenge_input.first.fill(username)
                await self.page.wait_for_timeout(500)
                next_btn = self.page.locator('button[data-testid="ocfEnterTextNextButton"], button:has-text("Next")').first
                await next_btn.click()
                await self.page.wait_for_timeout(2000)
        except Exception:
            pass

        # Step 2: Enter password
        self._log("Entering password...")
        try:
            password_input = self.page.locator('input[name="password"], input[type="password"]').first
            await password_input.wait_for(timeout=10000)
            await password_input.click()
            await password_input.fill(password)
            await self.page.wait_for_timeout(500)

            login_btn = self.page.locator('button[data-testid="LoginForm_Login_Button"], button:has-text("Log in")').first
            await login_btn.click()
            await self.page.wait_for_timeout(3000)
        except Exception as e:
            self._log(f"Failed at password step: {e}")
            return False

        # Step 3: Handle 2FA if needed
        if totp_secret:
            try:
                totp_input = self.page.locator('input[data-testid="ocfEnterTextTextInput"], input[name="text"]')
                if await totp_input.count() > 0 and await totp_input.first.is_visible():
                    self._log("2FA prompt detected, entering TOTP code...")
                    code = _generate_totp(totp_secret)
                    self._log(f"Generated TOTP code: {code}")
                    await totp_input.first.fill(code)
                    await self.page.wait_for_timeout(500)

                    next_btn = self.page.locator(
                        'button[data-testid="ocfEnterTextNextButton"], '
                        'button:has-text("Next"), '
                        'button:has-text("Verify")'
                    ).first
                    await next_btn.click()
                    await self.page.wait_for_timeout(3000)
            except Exception as e:
                self._log(f"2FA step issue: {e}")

        # Verify login succeeded
        try:
            await self.page.wait_for_selector(
                'a[href="/compose/post"], [data-testid="SideNav_NewTweet_Button"]',
                timeout=10000,
            )
            self._log("Login successful.")
            return True
        except Exception:
            self._log("Login may have failed. Check browser window.")
            return False

    async def stop(self):
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._playwright = None
