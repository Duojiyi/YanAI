from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from threading import RLock

from services.config import config


_CODE_TTL_SECONDS = 10 * 60
_SEND_COOLDOWN_SECONDS = 60
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class VerificationRecord:
    code_hash: str
    expires_at: float
    sent_at: float
    attempts: int = 0


_lock = RLock()
_codes: dict[str, VerificationRecord] = {}


def normalize_email(value: object) -> str:
    return str(value or "").strip().lower()


def split_email(email: str) -> tuple[str, str]:
    normalized = normalize_email(email)
    if normalized.count("@") != 1 or not _EMAIL_RE.match(normalized):
        raise ValueError("email is invalid")
    local, domain = normalized.rsplit("@", 1)
    if not local or not domain:
        raise ValueError("email is invalid")
    return local, domain


def _domain_matches(domain: str, pattern: str) -> bool:
    if not pattern:
        return False
    if pattern.startswith("*."):
        suffix = pattern[2:]
        return domain.endswith(f".{suffix}") and domain != suffix
    return domain == pattern


def validate_registration_email(email: str) -> str:
    normalized = normalize_email(email)
    local, domain = split_email(normalized)

    if config.email_alias_restriction_enabled:
        if "+" in local:
            raise ValueError("email aliases are not allowed")
        if domain in {"gmail.com", "googlemail.com"} and "." in local:
            raise ValueError("gmail dot aliases are not allowed")

    if config.email_domain_whitelist_enabled:
        allowed = config.email_domain_whitelist
        if not allowed:
            raise ValueError("email domain whitelist is empty")
        if not any(_domain_matches(domain, item) for item in allowed):
            raise ValueError("email domain is not allowed")

    return normalized


def _code_hash(email: str, code: str) -> str:
    secret = config.auth_key or "registration-email-code"
    message = f"{normalize_email(email)}:{str(code or '').strip()}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _force_auth_login(client: smtplib.SMTP, username: str, password: str) -> None:
    code, response = client.docmd("AUTH", "LOGIN")
    if code != 334:
        raise smtplib.SMTPAuthenticationError(code, response)
    code, response = client.docmd(base64.b64encode(username.encode("utf-8")).decode("ascii"))
    if code != 334:
        raise smtplib.SMTPAuthenticationError(code, response)
    code, response = client.docmd(base64.b64encode(password.encode("utf-8")).decode("ascii"))
    if code != 235:
        raise smtplib.SMTPAuthenticationError(code, response)


def _send_email(receiver: str, subject: str, html: str) -> None:
    host = config.smtp_host
    port = config.smtp_port
    username = config.smtp_username
    password = config.smtp_password
    sender = config.smtp_from_email
    if not host or not sender:
        raise ValueError("SMTP is not configured")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = receiver
    message.set_content("Your verification code is included in the HTML email.")
    message.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    if config.smtp_use_ssl or port == 465:
        client: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=15, context=context)
    else:
        client = smtplib.SMTP(host, port, timeout=15)

    try:
        client.ehlo()
        if not (config.smtp_use_ssl or port == 465) and config.smtp_use_starttls:
            client.starttls(context=context)
            client.ehlo()
        if username or password:
            if config.smtp_force_auth_login:
                _force_auth_login(client, username, password)
            else:
                client.login(username, password)
        client.send_message(message)
    finally:
        try:
            client.quit()
        except Exception:
            client.close()


def send_registration_verification_code(email: str) -> None:
    normalized = validate_registration_email(email)
    now = time.time()
    with _lock:
        record = _codes.get(normalized)
        if record and now - record.sent_at < _SEND_COOLDOWN_SECONDS:
            wait_seconds = int(_SEND_COOLDOWN_SECONDS - (now - record.sent_at))
            raise ValueError(f"please wait {wait_seconds}s before requesting another code")

    code = f"{secrets.randbelow(1_000_000):06d}"
    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.7;color:#1c1917">
      <h2 style="margin:0 0 12px">颜AI 邮箱验证码</h2>
      <p>你正在注册颜AI账号，本次验证码为：</p>
      <p style="font-size:28px;font-weight:700;letter-spacing:6px;margin:18px 0">{code}</p>
      <p>验证码 10 分钟内有效。如果不是你本人操作，可以忽略这封邮件。</p>
    </div>
    """.strip()
    _send_email(normalized, "颜AI 邮箱验证码", html)

    with _lock:
        _codes[normalized] = VerificationRecord(
            code_hash=_code_hash(normalized, code),
            expires_at=now + _CODE_TTL_SECONDS,
            sent_at=now,
        )


def verify_registration_code(email: str, code: str) -> None:
    normalized = validate_registration_email(email)
    candidate = str(code or "").strip()
    if not candidate:
        raise ValueError("verification code is required")
    now = time.time()
    with _lock:
        record = _codes.get(normalized)
        if not record:
            raise ValueError("verification code is invalid or expired")
        if record.expires_at < now:
            _codes.pop(normalized, None)
            raise ValueError("verification code is invalid or expired")
        if record.attempts >= 5:
            _codes.pop(normalized, None)
            raise ValueError("verification code has too many failed attempts")
        if not hmac.compare_digest(record.code_hash, _code_hash(normalized, candidate)):
            record.attempts += 1
            raise ValueError("verification code is invalid or expired")
        _codes.pop(normalized, None)


def clear_verification_codes() -> None:
    with _lock:
        _codes.clear()
