"""Provider-verified identities for the user's existing local workspace.

Google and GitHub use loopback OAuth with PKCE; hosted email/password accounts
use Supabase Auth. GitHub retains a device-flow fallback for client-ID-only
installations. Only identity metadata lives in the OS credential store, never
passwords or provider tokens. These identities do not authorize the local API or
partition the workspace. Stable provider IDs, not emails, identify them.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import threading
import time
import webbrowser
from urllib.parse import urlencode, urlsplit

import httpx

from agent.config import get_settings
from agent.contracts.accounts import Account, AccountProvider, AccountStatus, DEFAULT_RETURN_URL, EmailSignUpResult, SignInFlow, SignInRequest


GOOGLE_CALLBACK = "http://127.0.0.1:8000/api/accounts/callback/google"
GITHUB_CALLBACK = "http://127.0.0.1:8000/api/accounts/callback/github"
EMAIL_CALLBACK = "http://127.0.0.1:8000/api/accounts/callback/email"


class AccountError(Exception):
    pass


class AccountService:
    def __init__(self, *, keyring=None, transport=None, clock=time.monotonic, opener=webbrowser.open):
        if keyring is None:
            import keyring as system_keyring
            keyring = system_keyring
        self.keyring = keyring
        self.transport = transport
        self.clock = clock
        self.opener = opener
        self.lock = threading.RLock()
        self.flows: dict[str, dict] = {}

    def _load(self) -> dict:
        try:
            raw = self.keyring.get_password("vellum.accounts", "identities-v1")
            data = json.loads(raw) if raw else {"accounts": [], "active_account_id": None}
            accounts = [Account.model_validate(value).model_dump() for value in data["accounts"]]
            active = data.get("active_account_id")
            if active and not any(a["id"] == active for a in accounts):
                raise ValueError("Invalid active account")
            logged_out = data.get("logged_out", False)
            if type(logged_out) is not bool:
                raise ValueError("Invalid logout state")
            return {"accounts": accounts, "active_account_id": active, "logged_out": logged_out}
        except Exception as exc:
            raise AccountError("Account storage is unavailable. Unlock the system credential store and retry, or continue locally.") from exc

    def _save(self, data: dict) -> None:
        try:
            self.keyring.set_password("vellum.accounts", "identities-v1", json.dumps(data))
        except Exception as exc:
            raise AccountError("Could not save the account in the system credential store. Retry or continue locally.") from exc

    def status(self) -> AccountStatus:
        with self.lock:
            available = True
            try:
                data = self._load()
            except AccountError:
                data = {"accounts": [], "active_account_id": None}
                available = False
            settings = get_settings()
            providers = []
            for provider, label, configured in (
                ("google", "Google", bool(settings.account_google_client_id and settings.account_google_client_secret)),
                ("github", "GitHub", bool(settings.account_github_client_id)),
            ):
                reason = "" if configured else f"{label} sign-in has not been configured for this installation."
                if not available:
                    reason = "Unlock the system credential store to sign in."
                method = "device" if provider == "github" and not getattr(settings, "account_github_client_secret", "") else "redirect"
                providers.append(AccountProvider(id=provider, name=label, available=configured and available, reason=reason, method=method))
            try:
                self._email_config()
                email_ready, email_reason = available, "" if available else "Unlock the system credential store to sign in."
            except AccountError:
                email_ready, email_reason = False, "Email sign-in is not available yet. You can sign in with Google or GitHub, or continue as guest."
            return AccountStatus(**data, providers=providers, storage_available=available,
                                 email_auth_available=email_ready, email_auth_reason=email_reason)

    def _email_config(self) -> tuple[str, str]:
        settings = get_settings()
        url = getattr(settings, "account_supabase_url", "").strip().rstrip("/")
        key = getattr(settings, "account_supabase_publishable_key", "").strip()
        parsed = urlsplit(url)
        # Passwords go only to the configured hosted Supabase project over HTTPS.
        if (parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".supabase.co")
                or parsed.netloc != parsed.hostname or parsed.path or parsed.query or parsed.fragment):
            raise AccountError("The email account service has not been configured.")
        public_key = key.startswith("sb_publishable_")
        if not public_key and key.count(".") == 2:
            try:
                payload = key.split(".")[1]
                public_key = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("role") == "anon"
            except (ValueError, UnicodeError, AttributeError):
                public_key = False
        if not public_key:
            raise AccountError("The email account service requires a publishable key.")
        return url, key

    def _email_http(self, method: str, path: str, *, token: str = "", **kwargs) -> dict:
        url, key = self._email_config()
        headers = {"apikey": key, "Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        try:
            with httpx.Client(transport=self.transport, timeout=20, follow_redirects=False) as client:
                response = client.request(method, url + "/auth/v1/" + path, headers=headers, **kwargs)
                if response.is_error:
                    try:
                        error_code = response.json().get("error_code", "")
                    except (ValueError, AttributeError):
                        error_code = ""
                    messages = {
                        "email_address_not_authorized": "Verification email cannot be delivered to this address yet. Try Google or GitHub, or continue as guest.",
                        "over_email_send_rate_limit": "Too many verification emails were requested. Wait a while and try again.",
                        "weak_password": "Choose a stronger password and try again.",
                        "signup_disabled": "Account creation is not available right now. You can continue as guest.",
                    }
                    if error_code in messages:
                        raise AccountError(messages[error_code])
                if response.status_code == 429:
                    raise AccountError("Too many attempts. Wait a moment and try again.")
                if response.status_code in {400, 401, 403, 422}:
                    raise AccountError("Check your email and password. If you just signed up, confirm your email before signing in.")
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or data.get("error"):
                    raise ValueError("Invalid account response")
                return data
        except (httpx.HTTPError, ValueError) as exc:
            # Provider bodies and submitted passwords never become API errors.
            raise AccountError("The email account service could not be reached. Try again.") from exc

    @staticmethod
    def _email_credentials(email: str, password: str, *, signup: bool = False) -> str:
        email = email.strip().lower()
        if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise AccountError("Enter a valid email address.")
        if not password or len(password) > 1024 or (signup and len(password) < 8):
            raise AccountError("Use a password with at least 8 characters." if signup else "Enter your password.")
        return email

    def _remember(self, account: Account):
        data = self._load()
        saved = [a for a in data["accounts"] if a["id"] != account.id]
        if len(saved) >= 12:
            raise AccountError("You can save up to 12 accounts on this device. Remove an account before adding another.")
        self._save({"accounts": saved + [account.model_dump()], "active_account_id": account.id, "logged_out": False})

    def _complete_email(self, token: str):
        user = self._email_http("GET", "user", token=token)
        if not user.get("id") or not user.get("email") or not user.get("email_confirmed_at"):
            raise AccountError("Confirm your email before signing in.")
        project, _ = self._email_config()
        subject = project + ":" + str(user["id"])
        email = str(user["email"])
        self._remember(Account(id="email:" + hashlib.sha256(subject.encode()).hexdigest()[:32], provider="email",
                               display_name=email.split("@")[0][:120], email=email[:320]))

    def email_sign_in(self, email: str, password: str) -> AccountStatus:
        with self.lock:
            email = self._email_credentials(email, password)
            self._load()
            data = self._email_http("POST", "token", params={"grant_type": "password"}, json={"email": email, "password": password})
            if not data.get("access_token"):
                raise AccountError("The email account service did not complete sign-in. Try again.")
            self._complete_email(data["access_token"])
            self._cancel_pending()
            return self.status()

    def email_sign_up(self, email: str, password: str, return_url: str = DEFAULT_RETURN_URL) -> EmailSignUpResult:
        with self.lock:
            email = self._email_credentials(email, password, signup=True)
            return_url = SignInRequest(provider="google", return_url=return_url).return_url
            self._load()
            self.flows = {k: v for k, v in self.flows.items() if v["expires_at"] > self.clock()}
            if len(self.flows) >= 8:
                raise AccountError("Too many sign-in attempts. Cancel an existing attempt and try again.")
            flow_id, state, verifier = (secrets.token_urlsafe(32) for _ in range(3))
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            data = self._email_http("POST", "signup", params={"redirect_to": EMAIL_CALLBACK + "?" + urlencode({"state": state})},
                                    json={"email": email, "password": password, "code_challenge": challenge, "code_challenge_method": "s256"})
            if data.get("access_token"):
                self._complete_email(data["access_token"])
                self._cancel_pending()
                return EmailSignUpResult(status="complete", message="Account created.")
            flow = dict(provider="email", method="redirect", status="pending", state=state, verifier=verifier,
                        authorization_url="", user_code="", interval=3, browser_opened=False,
                        message="Check your email and confirm your account to continue.", return_url=return_url,
                        expires_at=self.clock() + 3600)
            self.flows[flow_id] = flow
            return EmailSignUpResult(status="confirmation_required", message=flow["message"], flow=self._view(flow_id, flow))

    def _http(self, method: str, url: str, **kwargs):
        try:
            with httpx.Client(transport=self.transport, timeout=20, follow_redirects=False) as client:
                response = client.request(method, url, **kwargs)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Never expose authorization codes, tokens, HTTP bodies, or query strings.
            raise AccountError("The sign-in provider could not be reached. Check your connection and try again.") from exc

    def _view(self, flow_id: str, flow: dict) -> SignInFlow:
        return SignInFlow(flow_id=flow_id, **{key: flow[key] for key in (
            "provider", "status", "authorization_url", "user_code", "interval", "browser_opened", "message", "method"
        )})

    def start(self, provider: str, return_url: str = DEFAULT_RETURN_URL, open_browser: bool = True) -> SignInFlow:
        # Validate here too; callback query parameters never choose a redirect destination.
        return_url = SignInRequest(provider=provider, return_url=return_url).return_url
        with self.lock:
            status = self.status()
            readiness = next((p for p in status.providers if p.id == provider), None)
            if not readiness or not readiness.available:
                raise AccountError(readiness.reason if readiness else "Unsupported sign-in provider.")
            self.flows = {k: v for k, v in self.flows.items() if v["expires_at"] > self.clock()}
            if len(self.flows) >= 8:
                raise AccountError("Too many sign-in attempts. Cancel an existing attempt or try again in a few minutes.")
            settings = get_settings()
            flow_id = secrets.token_urlsafe(32)
            flow = dict(provider=provider, status="pending", authorization_url="", user_code="", interval=2,
                        browser_opened=False, message="", expires_at=self.clock() + 600, next_poll=0,
                        method=readiness.method, return_url=return_url)
            if readiness.method == "redirect":
                verifier = secrets.token_urlsafe(64)
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
                google = provider == "google"
                flow.update(state=secrets.token_urlsafe(32), verifier=verifier,
                            client_id=settings.account_google_client_id if google else settings.account_github_client_id)
                params = dict(client_id=flow["client_id"], redirect_uri=GOOGLE_CALLBACK if google else GITHUB_CALLBACK,
                              response_type="code", scope="openid email profile" if google else "read:user user:email",
                              state=flow["state"], code_challenge=challenge, code_challenge_method="S256", prompt="select_account")
                if not google:
                    params["allow_signup"] = "true"
                endpoint = "https://accounts.google.com/o/oauth2/v2/auth" if google else "https://github.com/login/oauth/authorize"
                flow["authorization_url"] = endpoint + "?" + urlencode(params)
            else:
                data = self._http("POST", "https://github.com/login/device/code", headers={"Accept": "application/json"},
                                  data={"client_id": settings.account_github_client_id, "scope": "read:user user:email"})
                if not data.get("device_code") or not data.get("user_code"):
                    raise AccountError("GitHub device sign-in is unavailable. Enable device flow in the Vellum OAuth app registration.")
                flow.update(device_code=data["device_code"], user_code=str(data["user_code"]),
                            client_id=settings.account_github_client_id, authorization_url="https://github.com/login/device",
                            interval=max(5, int(data.get("interval", 5))),
                            expires_at=self.clock() + min(900, int(data.get("expires_in", 900))))
                flow["next_poll"] = self.clock() + flow["interval"]
            self.flows[flow_id] = flow
            try:
                if open_browser:
                    flow["browser_opened"] = bool(self.opener(flow["authorization_url"]))
            except Exception:
                pass
            return self._view(flow_id, flow)

    def _flow(self, flow_id: str) -> dict:
        flow = self.flows.get(flow_id)
        if not flow:
            raise AccountError("This sign-in attempt no longer exists. Start again.")
        if flow["status"] == "pending" and self.clock() >= flow["expires_at"]:
            flow.update(status="expired", message="Sign-in expired. Start again.")
            self._clear_secrets(flow)
        return flow

    @staticmethod
    def _clear_secrets(flow: dict):
        for key in ("state", "verifier", "device_code"):
            flow.pop(key, None)

    def _complete(self, flow: dict, token: str):
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if flow["provider"] == "google":
            profile = self._http("GET", "https://openidconnect.googleapis.com/v1/userinfo", headers=headers)
            if not profile.get("sub") or profile.get("email_verified") is not True or not profile.get("email"):
                raise AccountError("Google did not return a verified email address. Choose another account.")
            subject, email = str(profile["sub"]), str(profile["email"])
            name, username = profile.get("name") or email, ""
        else:
            profile = self._http("GET", "https://api.github.com/user", headers=headers)
            if not isinstance(profile.get("id"), int) or not profile.get("login"):
                raise AccountError("GitHub did not return a valid account. Try signing in again.")
            emails = self._http("GET", "https://api.github.com/user/emails", headers=headers)
            verified = [e for e in emails if e.get("verified") is True and e.get("email")]
            verified.sort(key=lambda e: not e.get("primary"))
            email = str(verified[0]["email"]) if verified else ""
            subject, username = str(profile["id"]), str(profile["login"])
            name = profile.get("name") or username
        account = Account(id=flow["provider"] + ":" + hashlib.sha256(subject.encode()).hexdigest()[:32],
                          provider=flow["provider"], display_name=str(name)[:120], username=username[:120], email=email[:320])
        self._remember(account)
        flow.update(status="complete", message="Signed in. You can return to Vellum.")
        self._clear_secrets(flow)

    def google_callback(self, state: str, code: str, error: str) -> bool:
        return self.complete_callback("google", state, code, error)[0]

    def complete_callback(self, provider: str, state: str, code: str, error: str) -> tuple[bool, str]:
        with self.lock:
            match = next(((k, v) for k, v in self.flows.items()
                          if v["provider"] == provider and v.get("state") and secrets.compare_digest(v["state"], state)), None)
            if not match:
                return False, DEFAULT_RETURN_URL
            flow_id, _ = match
            flow = self._flow(flow_id)
            if flow["status"] != "pending":
                return False, flow["return_url"]
            # Consume before exchange: callbacks, including failures, are single-use.
            flow.pop("state", None)
            try:
                if error or not code:
                    raise AccountError("Sign-in was cancelled or denied. You can try again.")
                if provider == "email":
                    tokens = self._email_http("POST", "token", params={"grant_type": "pkce"}, json={"auth_code": code, "code_verifier": flow["verifier"]})
                    if not tokens.get("access_token"):
                        raise AccountError("Email confirmation did not complete. Try signing in with your email and password.")
                    self._complete_email(tokens["access_token"])
                    flow.update(status="complete", message="Email confirmed. Your account is ready.")
                    return True, flow["return_url"]
                google = provider == "google"
                settings = get_settings()
                endpoint = "https://oauth2.googleapis.com/token" if google else "https://github.com/login/oauth/access_token"
                tokens = self._http("POST", endpoint, headers={"Accept": "application/json"}, data=dict(
                    client_id=flow["client_id"], client_secret=settings.account_google_client_secret if google else settings.account_github_client_secret,
                    code=code, code_verifier=flow["verifier"], redirect_uri=GOOGLE_CALLBACK if google else GITHUB_CALLBACK,
                    grant_type="authorization_code"))
                if tokens.get("error") or not tokens.get("access_token"):
                    raise AccountError("The provider did not complete sign-in. Try again.")
                self._complete(flow, tokens["access_token"])
            except AccountError as exc:
                flow.update(status="failed", message=str(exc))
            finally:
                self._clear_secrets(flow)
            return flow["status"] == "complete", flow["return_url"]

    def poll(self, flow_id: str) -> SignInFlow:
        with self.lock:
            flow = self._flow(flow_id)
            if flow["status"] == "pending" and flow["method"] == "device" and self.clock() >= flow["next_poll"]:
                flow["next_poll"] = self.clock() + flow["interval"]
                try:
                    tokens = self._http("POST", "https://github.com/login/oauth/access_token", headers={"Accept": "application/json"}, data=dict(
                        client_id=flow["client_id"], device_code=flow["device_code"], grant_type="urn:ietf:params:oauth:grant-type:device_code"))
                    error = tokens.get("error")
                    if error == "slow_down":
                        flow["interval"] += 5
                        flow["next_poll"] = self.clock() + flow["interval"]
                    elif error == "authorization_pending":
                        pass
                    elif error or not tokens.get("access_token"):
                        raise AccountError("GitHub sign-in was denied or expired. Start again.")
                    else:
                        self._complete(flow, tokens["access_token"])
                except AccountError as exc:
                    flow.update(status="failed", message=str(exc))
                    self._clear_secrets(flow)
            return self._view(flow_id, flow)

    def cancel(self, flow_id: str) -> SignInFlow:
        with self.lock:
            flow = self._flow(flow_id)
            if flow["status"] == "pending":
                flow.update(status="cancelled", message="Sign-in cancelled.")
                self._clear_secrets(flow)
            return self._view(flow_id, flow)

    def select(self, account_id: str) -> AccountStatus:
        with self.lock:
            data = self._load()
            if not any(a["id"] == account_id for a in data["accounts"]):
                raise AccountError("This account is no longer saved. Sign in again.")
            self._cancel_pending()
            self._save({**data, "active_account_id": account_id, "logged_out": False})
            return self.status()

    def _cancel_pending(self):
        for flow_id in list(self.flows):
            self.cancel(flow_id)

    def sign_out(self, account_id: str) -> AccountStatus:
        with self.lock:
            data = self._load()
            self._cancel_pending()
            accounts = [a for a in data["accounts"] if a["id"] != account_id]
            active = None if account_id == data["active_account_id"] else data["active_account_id"]
            self._save({**data, "accounts": accounts, "active_account_id": active})
            return self.status()

    def logout(self) -> AccountStatus:
        with self.lock:
            data = self._load()
            self._cancel_pending()
            self._save({**data, "active_account_id": None, "logged_out": True})
            return self.status()

    def continue_local(self) -> AccountStatus:
        with self.lock:
            data = self._load()
            self._save({**data, "active_account_id": None, "logged_out": False})
            return self.status()
