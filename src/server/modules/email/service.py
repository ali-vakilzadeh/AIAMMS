"""Email Module - Transactional email with SMTP and API provider adapters."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Dict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

from core.module_base import ModuleBase, ModuleContext, HealthStatus
from core.health import HealthReport
from core.settings import module_settings
from core.logger import get_logger
from core.utils import utcnow


logger = get_logger("email")


@dataclass
class RenderedEmail:
    """Result of email template rendering."""
    subject: str
    html: str
    text: str


class EmailProvider(ABC):
    """Abstract base class for email providers."""
    
    @abstractmethod
    async def send(self, to: str, subject: str, html: str, text: str) -> bool:
        """Send an email. Returns True on success."""
        pass
    
    @abstractmethod
    async def health_check(self) -> HealthReport:
        """Check provider health."""
        pass


class SMTPProvider(EmailProvider):
    """SMTP email provider."""
    
    def __init__(self, host: str, port: int, username: str, password: str, from_addr: str, use_tls: bool = True):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.use_tls = use_tls
        logger.info(f"SMTP provider initialized: {host}:{port}")
    
    async def send(self, to: str, subject: str, html: str, text: str) -> bool:
        """Send email via SMTP with retry."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = self.from_addr
                msg["To"] = to
                
                msg.attach(MIMEText(text, "plain"))
                msg.attach(MIMEText(html, "html"))
                
                if self.use_tls:
                    server = smtplib.SMTP(self.host, self.port)
                    server.starttls()
                else:
                    server = smtplib.SMTP_SSL(self.host, self.port)
                
                if self.username:
                    server.login(self.username, self.password)
                
                server.sendmail(self.from_addr, [to], msg.as_string())
                server.quit()
                
                # Redact address except domain
                domain = to.split("@")[-1] if "@" in to else "***"
                logger.info(f"Email sent to ***@{domain}")
                return True
                
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Failed to send email after {max_retries} attempts: {e}")
                    return False
                wait_time = 2 ** attempt
                logger.warning(f"SMTP send attempt {attempt + 1} failed, retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
        
        return False
    
    async def health_check(self) -> HealthReport:
        ts = utcnow()
        try:
            # Try to connect and handshake
            if self.use_tls:
                server = smtplib.SMTP(self.host, self.port)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self.host, self.port)
            
            if self.username:
                server.login(self.username, self.password)
            
            server.quit()
            
            return HealthReport(
                module="email",
                status=HealthStatus.OK,
                checks=[{"name": "smtp_handshake", "status": "OK", "detail": "SMTP connection OK"}],
                ts=ts,
            )
        except Exception as e:
            return HealthReport(
                module="email",
                status=HealthStatus.UNAVAILABLE,
                checks=[{"name": "smtp_handshake", "status": "UNAVAILABLE", "detail": str(e)}],
                ts=ts,
            )


class APIProvider(EmailProvider):
    """Generic API-based email provider (SendGrid, Mailgun, etc.)."""
    
    def __init__(self, api_key: str, api_url: str, from_addr: str):
        self.api_key = api_key
        self.api_url = api_url
        self.from_addr = from_addr
        
        try:
            import httpx
            self.httpx = httpx
        except ImportError:
            raise RuntimeError("httpx not installed. Install with: pip install httpx")
        
        logger.info(f"API provider initialized: {api_url}")
    
    async def send(self, to: str, subject: str, html: str, text: str) -> bool:
        """Send email via HTTP API with retry."""
        max_retries = 3
        
        payload = {
            "from": self.from_addr,
            "to": to,
            "subject": subject,
            "html": html,
            "text": text,
        }
        
        for attempt in range(max_retries):
            try:
                async with self.httpx.AsyncClient() as client:
                    response = await client.post(
                        self.api_url,
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        timeout=30,
                    )
                    response.raise_for_status()
                    
                    domain = to.split("@")[-1] if "@" in to else "***"
                    logger.info(f"Email sent to ***@{domain}")
                    return True
                    
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Failed to send email after {max_retries} attempts: {e}")
                    return False
                wait_time = 2 ** attempt
                logger.warning(f"API send attempt {attempt + 1} failed, retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
        
        return False
    
    async def health_check(self) -> HealthReport:
        ts = utcnow()
        try:
            async with self.httpx.AsyncClient() as client:
                response = await client.get(
                    self.api_url.rstrip("/api") + "/health",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=10,
                )
                response.raise_for_status()
            
            return HealthReport(
                module="email",
                status=HealthStatus.OK,
                checks=[{"name": "api_health", "status": "OK", "detail": "API health check OK"}],
                ts=ts,
            )
        except Exception as e:
            return HealthReport(
                module="email",
                status=HealthStatus.UNAVAILABLE,
                checks=[{"name": "api_health", "status": "UNAVAILABLE", "detail": str(e)}],
                ts=ts,
            )


# Global provider instance
_provider: Optional[EmailProvider] = None


def provider() -> EmailProvider:
    """Get email provider by configuration.
    
    Selects adapter based on CMMS_EMAIL__PROVIDER (smtp|api).
    
    Returns:
        Configured EmailProvider instance
    """
    global _provider
    
    if _provider is not None:
        return _provider
    
    settings = module_settings("email")
    if settings is None:
        raise RuntimeError("Email settings not loaded")
    
    provider_type = getattr(settings, "provider", "smtp")
    from_addr = getattr(settings, "from_address", "noreply@cmms.local")
    
    if provider_type == "smtp":
        host = getattr(settings, "smtp_host", "localhost")
        port = getattr(settings, "smtp_port", 587)
        username = getattr(settings, "smtp_username", "")
        password = getattr(settings, "smtp_password", "")
        use_tls = getattr(settings, "smtp_use_tls", True)
        
        _provider = SMTPProvider(host, port, username, password, from_addr, use_tls)
        
    elif provider_type == "api":
        api_key = getattr(settings, "api_key", "")
        api_url = getattr(settings, "api_url", "")
        
        if not api_key or not api_url:
            raise ValueError("API provider requires api_key and api_url")
        
        _provider = APIProvider(api_key, api_url, from_addr)
        
    else:
        raise ValueError(f"Unknown email provider: {provider_type}")
    
    return _provider


# Built-in templates
TEMPLATES = {
    "verify_email": {
        "subject": "Verify Your Email Address",
        "html": """
        <html><body>
        <h2>Welcome!</h2>
        <p>Please verify your email address by clicking the link below:</p>
        <p><a href="{verification_link}">Verify Email</a></p>
        <p>This link expires in 24 hours.</p>
        </body></html>
        """,
        "text": """
        Welcome!
        Please verify your email address by visiting: {verification_link}
        This link expires in 24 hours.
        """,
    },
    "password_reset": {
        "subject": "Reset Your Password",
        "html": """
        <html><body>
        <h2>Password Reset Request</h2>
        <p>Click the link below to reset your password:</p>
        <p><a href="{reset_link}">Reset Password</a></p>
        <p>This link expires in 30 minutes.</p>
        <p>If you didn't request this, please ignore this email.</p>
        </body></html>
        """,
        "text": """
        Password Reset Request
        Visit this link to reset your password: {reset_link}
        This link expires in 30 minutes.
        If you didn't request this, please ignore this email.
        """,
    },
    "invitation": {
        "subject": "You've Been Invited to Join an Organization",
        "html": """
        <html><body>
        <h2>You're Invited!</h2>
        <p>{inviter_name} has invited you to join <strong>{org_name}</strong>.</p>
        <p><a href="{accept_link}">Accept Invitation</a></p>
        <p>This invitation expires in 14 days.</p>
        </body></html>
        """,
        "text": """
        You're Invited!
        {inviter_name} has invited you to join {org_name}.
        Accept the invitation at: {accept_link}
        This invitation expires in 14 days.
        """,
    },
}


def render(template: str, vars: Dict[str, str]) -> RenderedEmail:
    """Render an email template.
    
    Args:
        template: Template name (verify_email|password_reset|invitation)
        vars: Template variables
        
    Returns:
        RenderedEmail with subject, html, text
        
    Raises:
        ValueError: If template not found
    """
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template: {template}. Available: {list(TEMPLATES.keys())}")
    
    tmpl = TEMPLATES[template]
    
    return RenderedEmail(
        subject=tmpl["subject"],
        html=tmpl["html"].format(**vars),
        text=tmpl["text"].format(**vars),
    )


async def send(to: str, subject: str, html: str, text: str) -> bool:
    """Send transactional email with retry.
    
    Args:
        to: Recipient email
        subject: Email subject
        html: HTML body
        text: Plain text body
        
    Returns:
        True if sent successfully
    """
    return await provider().send(to, subject, html, text)


async def send_template(template: str, to: str, vars: Dict[str, str]) -> bool:
    """Send email using a template.
    
    Args:
        template: Template name
        to: Recipient email
        vars: Template variables
        
    Returns:
        True if sent successfully
    """
    rendered = render(template, vars)
    return await send(to, rendered.subject, rendered.html, rendered.text)


async def health_check() -> HealthReport:
    """Run email provider health check.
    
    Returns:
        HealthReport with provider status
    """
    return await provider().health_check()


class EmailService:
    """Published port for email operations."""
    
    @staticmethod
    def get_provider() -> EmailProvider:
        return provider()
    
    @staticmethod
    def render_template(template: str, vars: Dict[str, str]) -> RenderedEmail:
        return render(template, vars)
    
    @staticmethod
    async def send_email(to: str, subject: str, html: str, text: str) -> bool:
        return await send(to, subject, html, text)
    
    @staticmethod
    async def send_templated(template: str, to: str, vars: Dict[str, str]) -> bool:
        return await send_template(template, to, vars)
    
    @staticmethod
    async def check_health() -> HealthReport:
        return await health_check()


class EmailModule(ModuleBase):
    """Email module implementing ModuleBase protocol."""
    
    name = "email"
    version = "1.0.0"
    dependencies: tuple[str, ...] = ()
    optional_dependencies: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ("api", "worker", "beat", "mcp", "all-in-one")
    
    async def configure(self, settings: Any) -> None:
        """Validate email configuration."""
        logger.info("Configuring Email module")
        
    async def initialize(self, ctx: ModuleContext) -> None:
        """Initialize email provider."""
        logger.info("Initializing Email module")
        provider()  # Initialize provider
        
        # Register service port
        from core.registry import register_service
        register_service("email", EmailService(), EmailService)
        
    async def start(self) -> None:
        """Start Email module."""
        logger.info("Email module started")
        
    async def stop(self) -> None:
        """Stop Email module."""
        logger.info("Stopping Email module")
        global _provider
        _provider = None
        
    async def health(self) -> HealthReport:
        """Report email health."""
        return await health_check()
