/**
 * Lead Gen Pro — Embeddable Lead Capture Widget
 *
 * Drop this script onto any website or landing page to capture leads directly
 * into the Leviathan Growth portal:
 *
 *   <script src="https://growth.leviathansi.xyz/static/widgets/lead-capture.js"
 *           data-business="Your Business"
 *           data-industry="roofing"
 *           data-primary="#6366f1"></script>
 *
 * The widget injects a mobile-friendly form, submits to /api/capture/lead,
 * and tracks UTM parameters automatically.
 */
(function () {
  'use strict';

  var script = document.currentScript || (function () {
    var scripts = document.getElementsByTagName('script');
    return scripts[scripts.length - 1];
  })();

  var config = {
    business: script.getAttribute('data-business') || 'Our Business',
    industry: script.getAttribute('data-industry') || 'home improvement',
    primary: script.getAttribute('data-primary') || '#6366f1',
    apiUrl: script.getAttribute('data-api') || '/api/capture/lead',
    source: script.getAttribute('data-source') || 'embedded_widget',
  };

  function getUtmParams() {
    var params = new URLSearchParams(window.location.search);
    return {
      utm_source: params.get('utm_source') || '',
      utm_medium: params.get('utm_medium') || 'widget',
      utm_campaign: params.get('utm_campaign') || '',
    };
  }

  function injectStyles() {
    var css = `
      .lgpw-root {
        all: initial;
        display: block;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: #0a0a0f;
        color: #e2e8f0;
        border-radius: 12px;
        padding: 24px;
        max-width: 420px;
        margin: 0 auto;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
      }
      .lgpw-root * { box-sizing: border-box; margin: 0; padding: 0; }
      .lgpw-header { font-size: 13px; font-weight: 600; color: ${config.primary}; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 6px; }
      .lgpw-title { font-size: 22px; font-weight: 700; color: #f1f5f9; margin-bottom: 18px; }
      .lgpw-field { margin-bottom: 14px; }
      .lgpw-field label { display: block; font-size: 12px; font-weight: 500; color: #94a3b8; margin-bottom: 5px; }
      .lgpw-field input,
      .lgpw-field textarea {
        width: 100%;
        padding: 10px 12px;
        background: #13131e;
        border: 1px solid #1e1e2e;
        border-radius: 8px;
        color: #e2e8f0;
        font-size: 14px;
        outline: none;
      }
      .lgpw-field input:focus,
      .lgpw-field textarea:focus { border-color: ${config.primary}; }
      .lgpw-field input::placeholder,
      .lgpw-field textarea::placeholder { color: #475569; }
      .lgpw-submit { width: 100%; padding: 12px; background: ${config.primary}; color: #fff; font-size: 15px; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; }
      .lgpw-submit:hover { opacity: 0.92; }
      .lgpw-submit:disabled { opacity: 0.5; cursor: not-allowed; }
      .lgpw-confirmation { display: none; background: #13131e; border: 1px solid #1e1e2e; border-radius: 8px; padding: 20px; margin-top: 16px; text-align: center; }
      .lgpw-confirmation.show { display: block; }
      .lgpw-confirmation h3 { color: ${config.primary}; margin-bottom: 6px; }
      .lgpw-confirmation p { color: #94a3b8; font-size: 13px; }
      .lgpw-error { color: #ef4444; font-size: 12px; margin-top: 8px; display: none; }
      .lgpw-error.show { display: block; }
      @media (max-width: 480px) { .lgpw-root { padding: 18px; border-radius: 0; } }
    `;
    var style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);
  }

  function renderWidget() {
    var container = document.createElement('div');
    container.className = 'lgpw-root';
    container.innerHTML = `
      <div class="lgpw-header">${escapeHtml(config.business)}</div>
      <div class="lgpw-title">Request Your Free Estimate</div>
      <form id="lgpw-form">
        <div class="lgpw-field">
          <label for="lgpw-name">Full Name</label>
          <input type="text" id="lgpw-name" name="name" placeholder="Your name" required />
        </div>
        <div class="lgpw-field">
          <label for="lgpw-email">Email</label>
          <input type="email" id="lgpw-email" name="email" placeholder="you@example.com" />
        </div>
        <div class="lgpw-field">
          <label for="lgpw-phone">Phone *</label>
          <input type="tel" id="lgpw-phone" name="phone" placeholder="(555) 123-4567" required />
        </div>
        <div class="lgpw-field">
          <label for="lgpw-address">Project Address</label>
          <input type="text" id="lgpw-address" name="address" placeholder="123 Main St, City, State" />
        </div>
        <div class="lgpw-field">
          <label for="lgpw-project">Project Description</label>
          <textarea id="lgpw-project" name="project_description" rows="3" placeholder="Tell us about your project"></textarea>
        </div>
        <button type="submit" class="lgpw-submit" id="lgpw-submit">Get Started</button>
        <div class="lgpw-error" id="lgpw-error"></div>
      </form>
      <div class="lgpw-confirmation" id="lgpw-confirmation">
        <h3>Request Received</h3>
        <p>We'll be in touch within minutes.</p>
      </div>
    `;
    script.parentNode.insertBefore(container, script.nextSibling);

    var form = container.querySelector('#lgpw-form');
    var btn = container.querySelector('#lgpw-submit');
    var errorEl = container.querySelector('#lgpw-error');
    var confirmEl = container.querySelector('#lgpw-confirmation');

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      errorEl.classList.remove('show');
      confirmEl.classList.remove('show');
      btn.disabled = true;
      btn.textContent = 'Sending...';

      var payload = {
        name: document.getElementById('lgpw-name').value.trim(),
        email: document.getElementById('lgpw-email').value.trim(),
        phone: document.getElementById('lgpw-phone').value.trim(),
        address: document.getElementById('lgpw-address').value.trim(),
        project_description: document.getElementById('lgpw-project').value.trim(),
        source: config.source,
        industry: config.industry,
      };
      Object.assign(payload, getUtmParams());

      fetch(config.apiUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
        .then(function (r) { return r.json(); })
        .then(function (result) {
          if (result.ok) {
            confirmEl.classList.add('show');
            form.reset();
          } else {
            errorEl.textContent = result.error || 'Something went wrong.';
            errorEl.classList.add('show');
          }
        })
        .catch(function () {
          errorEl.textContent = 'Network error. Please try again.';
          errorEl.classList.add('show');
        })
        .finally(function () {
          btn.disabled = false;
          btn.textContent = 'Get Started';
        });
    });
  }

  function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      injectStyles();
      renderWidget();
    });
  } else {
    injectStyles();
    renderWidget();
  }
})();
