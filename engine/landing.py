from __future__ import annotations

import uuid
from html import escape
from typing import Any, Optional

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{page_title}</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
  --bg: #0a0a0f;
  --bg2: #111118;
  --bg3: #1a1a24;
  --bg4: #24243a;
  --border: #2a2a3e;
  --text: #e8e8f0;
  --text2: #9898b0;
  --text3: #68687a;
  --accent: {primary_color};
  --accent2: #818cf8;
  --accent-glow: rgba(99, 102, 241, 0.15);
  --green: #22c55e;
  --red: #ef4444;
  --radius: 12px;
  --radius-sm: 8px;
  --max-w: 640px;
}}
html {{ font-size: 16px; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}}
.container {{ max-width: var(--max-w); margin: 0 auto; padding: 0 20px; }}

/* ─── Hero ─── */
.hero {{
  padding: 60px 0 40px;
  text-align: center;
  background: linear-gradient(180deg, var(--bg2) 0%, var(--bg) 100%);
  border-bottom: 1px solid var(--border);
}}
.hero-logo {{ max-width: 180px; max-height: 60px; margin-bottom: 24px; }}
.hero h1 {{
  font-size: 2rem;
  font-weight: 800;
  line-height: 1.2;
  letter-spacing: -0.5px;
  margin-bottom: 12px;
  background: linear-gradient(135deg, var(--accent2), var(--accent));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}}
.hero p {{
  font-size: 1.1rem;
  color: var(--text2);
  max-width: 520px;
  margin: 0 auto;
}}
.hero-image {{ margin-top: 32px; }}
.hero-image img {{
  width: 100%;
  max-width: 100%;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  display: block;
}}

/* ─── Section ─── */
.section {{
  padding: 48px 0;
  border-bottom: 1px solid var(--border);
}}
.section:last-of-type {{ border-bottom: none; }}
.section h2 {{
  font-size: 1.4rem;
  font-weight: 700;
  text-align: center;
  margin-bottom: 28px;
  color: var(--text);
}}

/* ─── Benefits ─── */
.benefits-grid {{
  display: grid;
  grid-template-columns: 1fr;
  gap: 16px;
}}
.benefit-card {{
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 18px 20px;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  transition: border-color 0.2s;
}}
.benefit-card:hover {{ border-color: var(--accent); }}
.benefit-icon {{
  font-size: 1.5rem;
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg3);
  border-radius: var(--radius-sm);
}}
.benefit-text {{
  font-size: 0.95rem;
  font-weight: 500;
  padding-top: 8px;
}}

/* ─── Trust Signals ─── */
.trust-grid {{
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  justify-content: center;
}}
.trust-badge {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 50px;
  font-size: 0.9rem;
  color: var(--text2);
}}
.trust-badge .icon {{ font-size: 1.1rem; }}

/* ─── Form ─── */
.form-card {{
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 32px 28px;
}}
.form-group {{ margin-bottom: 20px; }}
.form-group label {{
  display: block;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 6px;
}}
.form-group .required::after {{
  content: " *";
  color: var(--red);
}}
.form-input {{
  width: 100%;
  padding: 12px 14px;
  background: var(--bg3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  font-size: 1rem;
  font-family: inherit;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}}
.form-input:focus {{
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-glow);
}}
.form-input::placeholder {{ color: var(--text3); }}
textarea.form-input {{
  min-height: 100px;
  resize: vertical;
}}
.form-error {{
  font-size: 0.8rem;
  color: var(--red);
  margin-top: 4px;
  display: none;
}}
.form-error.show {{ display: block; }}
.form-input.error {{ border-color: var(--red); }}
.cta-btn {{
  display: block;
  width: 100%;
  padding: 16px 24px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: var(--radius);
  font-size: 1.1rem;
  font-weight: 700;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.2s, box-shadow 0.2s, transform 0.1s;
}}
.cta-btn:hover {{
  background: var(--accent2);
  box-shadow: 0 0 24px var(--accent-glow);
}}
.cta-btn:active {{ transform: scale(0.98); }}
.cta-btn:disabled {{
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
  transform: none;
}}
.form-status {{
  text-align: center;
  padding: 12px;
  margin-bottom: 16px;
  border-radius: var(--radius-sm);
  font-size: 0.9rem;
  display: none;
}}
.form-status.error {{ display: block; background: rgba(239, 68, 68, 0.1); border: 1px solid var(--red); color: var(--red); }}
.form-status.success {{ display: block; background: rgba(34, 197, 94, 0.1); border: 1px solid var(--green); color: var(--green); }}

/* ─── Footer ─── */
.footer {{
  text-align: center;
  padding: 32px 20px;
  font-size: 0.8rem;
  color: var(--text3);
  border-top: 1px solid var(--border);
}}

/* ─── Responsive ─── */
@media (min-width: 600px) {{
  .benefits-grid {{ grid-template-columns: 1fr 1fr; }}
  .hero h1 {{ font-size: 2.5rem; }}
  .hero {{ padding: 80px 0 50px; }}
  .form-card {{ padding: 40px 36px; }}
}}
@media (max-width: 400px) {{
  .hero h1 {{ font-size: 1.6rem; }}
  .hero {{ padding: 40px 0 30px; }}
  .form-card {{ padding: 24px 16px; }}
}}
</style>
</head>
<body>

<div class="hero">
  <div class="container">
    {hero_logo}
    <h1>{headline}</h1>
    <p>{subheadline}</p>
    {hero_image}
  </div>
</div>

<div class="section">
  <div class="container">
    <h2>Why Choose Us</h2>
    <div class="benefits-grid">
      {benefits_html}
    </div>
  </div>
</div>

<div class="section">
  <div class="container">
    <h2>Trusted & Verified</h2>
    <div class="trust-grid">
      {trust_html}
    </div>
  </div>
</div>

<div class="section">
  <div class="container">
    <h2>Get Started Today</h2>
    <div class="form-card">
      <div id="formStatus" class="form-status"></div>
      <form id="leadForm" action="/api/capture/lead" method="POST" novalidate>
        {form_fields_html}
        <button type="submit" class="cta-btn" id="submitBtn">{cta_text}</button>
      </form>
    </div>
  </div>
</div>

<div class="footer">
  {footer_text}
</div>

<script>
(function() {{
  var form = document.getElementById('leadForm');
  var btn = document.getElementById('submitBtn');
  var status = document.getElementById('formStatus');

  function showError(msg) {{
    status.className = 'form-status error';
    status.textContent = msg;
  }}

  function clearErrors() {{
    status.className = 'form-status';
    status.textContent = '';
    var errs = document.querySelectorAll('.form-error');
    for (var i = 0; i < errs.length; i++) {{ errs[i].classList.remove('show'); }}
    var inputs = document.querySelectorAll('.form-input.error');
    for (var i = 0; i < inputs.length; i++) {{ inputs[i].classList.remove('error'); }}
  }}

  form.addEventListener('submit', async function(e) {{
    e.preventDefault();
    clearErrors();

    var valid = true;
    var required = form.querySelectorAll('[required]');
    for (var i = 0; i < required.length; i++) {{
      var field = required[i];
      if (!field.value.trim()) {{
        valid = false;
        field.classList.add('error');
        var errEl = document.getElementById(field.name + '_error');
        if (errEl) errEl.classList.add('show');
      }}
    }}

    if (!valid) {{
      showError('Please fill in all required fields.');
      return;
    }}

    btn.disabled = true;
    btn.textContent = 'Submitting...';

    try {{
      var body = {{}};
      var inputs = form.querySelectorAll('[name]');
      for (var i = 0; i < inputs.length; i++) {{
        body[inputs[i].name] = inputs[i].value;
      }}

      var res = await fetch('/api/capture/lead', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(body)
      }});

      if (!res.ok) {{
        var errData;
        try {{ errData = await res.json(); }} catch(_) {{ errData = {{}}; }}
        throw new Error(errData.error || errData.detail || 'Submission failed. Please try again.');
      }}

      window.location.href = '/api/capture/thank-you?name=' + encodeURIComponent({business_name_js});
    }} catch(err) {{
      showError(err.message || 'Network error. Please try again.');
      btn.disabled = false;
      btn.textContent = '{cta_text_js}';
    }}
  }});
}})();
</script>
</body>
</html>"""


class LandingPageGenerator:
    def __init__(self) -> None:
        self._pages: dict[str, str] = {}

    @staticmethod
    def _default_form_fields() -> list[dict[str, Any]]:
        return [
            {"name": "name", "label": "Full Name", "type": "text", "required": True},
            {"name": "phone", "label": "Phone Number", "type": "tel", "required": True},
            {"name": "email", "label": "Email Address", "type": "email", "required": True},
            {"name": "address", "label": "Street Address", "type": "text", "required": False},
            {"name": "project_description", "label": "Project Description", "type": "textarea", "required": True},
        ]

    @staticmethod
    def _default_benefits() -> list[str]:
        return [
            "Free no-obligation estimate",
            "Licensed & insured professionals",
            "Satisfaction guaranteed",
            "Family-owned & operated",
        ]

    @staticmethod
    def _default_trust_signals() -> list[dict[str, str]]:
        return [
            {"icon": "\u2b50", "text": "4.9/5 Average Rating"},
            {"icon": "\U0001f4cb", "text": "Licensed & Insured"},
            {"icon": "\U0001f6e1\ufe0f", "text": "100% Satisfaction Guarantee"},
            {"icon": "\u2705", "text": "BBB Accredited Business"},
        ]

    @staticmethod
    def _build_benefits_html(benefits: list[str]) -> str:
        icons = ["\u2705", "\U0001f3ed", "\U0001f91d", "\U0001f3e0"]
        html = ""
        for i, b in enumerate(benefits):
            icon = icons[i % len(icons)]
            html += (
                f'<div class="benefit-card">'
                f'<div class="benefit-icon">{icon}</div>'
                f'<div class="benefit-text">{escape(b)}</div>'
                f"</div>\n"
            )
        return html

    @staticmethod
    def _build_trust_html(trust_signals: list[dict[str, str]]) -> str:
        html = ""
        for t in trust_signals:
            icon = t.get("icon", "\u2705")
            text = escape(t.get("text", ""))
            html += (
                f'<div class="trust-badge">'
                f'<span class="icon">{icon}</span>'
                f"<span>{text}</span>"
                f"</div>\n"
            )
        return html

    @staticmethod
    def _build_form_fields_html(fields: list[dict[str, Any]]) -> str:
        html = ""
        for f in fields:
            name = f.get("name", "")
            label = escape(f.get("label", ""))
            ftype = f.get("type", "text")
            required = f.get("required", False)
            required_attr = " required" if required else ""
            label_cls = ' class="required"' if required else ""
            error_id = f"{name}_error"
            error_msg = f"Please enter your {label.lower().rstrip('.')}."

            if ftype == "textarea":
                html += (
                    f'<div class="form-group">'
                    f'<label{label_cls} for="{name}">{label}</label>'
                    f'<textarea class="form-input" id="{name}" name="{name}"{required_attr}></textarea>'
                    f'<div class="form-error" id="{error_id}">{error_msg}</div>'
                    f"</div>\n"
                )
            else:
                html += (
                    f'<div class="form-group">'
                    f'<label{label_cls} for="{name}">{label}</label>'
                    f'<input class="form-input" type="{ftype}" id="{name}" name="{name}"{required_attr}>'
                    f'<div class="form-error" id="{error_id}">{error_msg}</div>'
                    f"</div>\n"
                )
        return html

    def create_page(self, config: dict[str, Any]) -> dict[str, Any]:
        business_name = config.get("business_name", "Our Business")
        headline = config.get("headline", "Professional Home Improvement Services")
        subheadline = config.get(
            "subheadline", "Quality craftsmanship you can trust. Get your free estimate today."
        )
        benefits = config.get("benefits", self._default_benefits())
        trust_signals = config.get("trust_signals", self._default_trust_signals())
        primary_color = config.get("primary_color", "#6366f1")
        form_fields = config.get("form_fields", self._default_form_fields())
        cta_text = config.get("cta_text", "Get Your Free Estimate")
        hero_image_url = config.get("hero_image_url", "")
        logo_url = config.get("logo_url", "")
        footer_text = config.get("footer_text", f"\u00a9 {business_name}. All rights reserved.")

        page_title = escape(f"{business_name} | Free Estimate")
        hero_logo = (
            f'<img class="hero-logo" src="{escape(logo_url)}" alt="{escape(business_name)} logo">'
            if logo_url else ""
        )
        hero_image = (
            f'<div class="hero-image"><img src="{escape(hero_image_url)}" alt="Hero image" loading="lazy"></div>'
            if hero_image_url else ""
        )

        benefits_html = self._build_benefits_html(benefits)
        trust_html = self._build_trust_html(trust_signals)
        form_fields_html = self._build_form_fields_html(form_fields)

        safe = {
            "page_title": page_title,
            "headline": escape(headline),
            "subheadline": escape(subheadline),
            "primary_color": primary_color,
            "cta_text": escape(cta_text),
            "cta_text_js": escape(cta_text, quote=True),
            "footer_text": escape(footer_text),
            "hero_logo": hero_logo,
            "hero_image": hero_image,
            "benefits_html": benefits_html,
            "trust_html": trust_html,
            "form_fields_html": form_fields_html,
            "business_name_js": escape(business_name, quote=True),
        }

        html = _HTML_TEMPLATE.format(**safe)
        page_id = uuid.uuid4().hex[:8]
        self._pages[page_id] = html

        return {
            "id": page_id,
            "url": f"/api/landing/{page_id}",
            "html_preview": html[:500],
        }

    def get_page(self, page_id: str) -> str | None:
        return self._pages.get(page_id)

    def list_pages(self) -> list[dict[str, Any]]:
        return [
            {"id": pid, "url": f"/api/landing/{pid}", "size": len(html)}
            for pid, html in self._pages.items()
        ]

    def delete_page(self, page_id: str) -> bool:
        return bool(self._pages.pop(page_id, None))
