"""
EmailTemplateRenderer — fetches Jinja2 templates from S3 and renders HTML emails.
"""

import logging
import re
from typing import Dict, Any, Optional

import boto3
import jinja2

from vital_chatwoot_bridge.email.models import EmailTemplatesConfig

logger = logging.getLogger(__name__)


class EmailTemplateRenderer:
    """Renders Jinja2 email templates fetched from S3."""

    def __init__(
        self,
        config: EmailTemplatesConfig,
        aws_access_key_id: str = "",
        aws_secret_access_key: str = "",
    ):
        self.config = config
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
        self.defaults: Dict[str, str] = dict(config.defaults)

        # Inject asset_base_url into defaults so all templates can use it
        if config.asset_base_url:
            self.defaults["asset_base_url"] = config.asset_base_url

        self.env = jinja2.Environment(
            autoescape=jinja2.select_autoescape(["html"]),
        )

        # Fetch all templates from S3 into memory at init
        self._template_cache: Dict[str, jinja2.Template] = {}
        self._load_templates_from_s3()

    def _load_templates_from_s3(self) -> None:
        """Fetch all configured templates from S3 and compile them."""
        boto_kwargs: Dict[str, Any] = {"region_name": self.config.s3_region}
        if self._aws_access_key_id and self._aws_secret_access_key:
            boto_kwargs["aws_access_key_id"] = self._aws_access_key_id
            boto_kwargs["aws_secret_access_key"] = self._aws_secret_access_key
        s3 = boto3.client("s3", **boto_kwargs)

        for name, tpl_def in self.config.templates.items():
            try:
                resp = s3.get_object(
                    Bucket=self.config.s3_bucket,
                    Key=tpl_def.s3_key,
                )
                html = resp["Body"].read().decode("utf-8")
                self._template_cache[name] = self.env.from_string(html)
                logger.info(
                    f"📧 Loaded email template '{name}' from "
                    f"s3://{self.config.s3_bucket}/{tpl_def.s3_key}"
                )
            except Exception as e:
                logger.error(f"❌ Failed to load email template '{name}' from S3: {e}")
                raise

        logger.info(f"📧 {len(self._template_cache)} email template(s) loaded")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def template_names(self) -> list:
        """Return list of available template names."""
        return list(self._template_cache.keys())

    def render(self, template_name: str, template_vars: Dict[str, Any]) -> str:
        """Render a named template with the given variables.

        Args:
            template_name: Registered template name.
            template_vars: Caller-provided variables (override defaults).

        Returns:
            Rendered HTML string.

        Raises:
            KeyError: If template_name is not registered.
        """
        template = self._template_cache.get(template_name)
        if not template:
            raise KeyError(f"Unknown email template: {template_name}")

        # Merge: defaults < caller vars (caller wins)
        merged = {**self.defaults, **template_vars}
        return template.render(**merged)

    def render_subject(
        self, template_name: str, template_vars: Dict[str, Any]
    ) -> str:
        """Render the subject line for a named template.

        Falls back to an explicit ``subject`` key in *template_vars* when the
        template definition has no ``subject_default``.
        """
        tpl_def = self.config.templates.get(template_name)
        if not tpl_def or not tpl_def.subject_default:
            return template_vars.get("subject", "")

        merged = {**self.defaults, **template_vars}
        subject_tpl = self.env.from_string(tpl_def.subject_default)
        return subject_tpl.render(**merged)

    @staticmethod
    def extract_body_content(html: str) -> str:
        """Extract inner content of <body> from a full HTML document.

        Chatwoot wraps outgoing emails in its own layout (base.liquid) which
        already provides <!DOCTYPE>, <html>, <head>, <body>.  Embedding a
        second full document inside that layout breaks email clients.

        This method returns only the content *inside* <body>...</body> so it
        can be safely inserted into Chatwoot's layout.  If no <body> tag is
        found the original string is returned unchanged.
        """
        match = re.search(
            r"<body[^>]*>(.*)</body>", html, re.DOTALL | re.IGNORECASE
        )
        return match.group(1).strip() if match else html

    def reload(self) -> None:
        """Re-fetch all templates from S3. Useful for runtime refresh."""
        self._template_cache.clear()
        self._load_templates_from_s3()


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_renderer: Optional[EmailTemplateRenderer] = None


def init_renderer(
    config: EmailTemplatesConfig,
    aws_access_key_id: str = "",
    aws_secret_access_key: str = "",
) -> EmailTemplateRenderer:
    """Initialise the global renderer (called once at startup)."""
    global _renderer
    _renderer = EmailTemplateRenderer(
        config,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )
    return _renderer


def get_renderer() -> Optional[EmailTemplateRenderer]:
    """Return the global renderer, or None if templates are not configured."""
    return _renderer
