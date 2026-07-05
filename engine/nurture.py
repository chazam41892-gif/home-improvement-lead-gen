from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


@dataclass
class Sequence:
    id: str
    lead_name: str
    lead_id: str
    lead_email: str
    lead_phone: str
    industry: str
    created_at: str
    actions: list
    current_step: int = 0
    completed: bool = False


_DEFAULT_SCHEDULING_CONFIG: Dict[str, Any] = {
    "slot_interval_minutes": 60,
    "business_hours_start": 9,
    "business_hours_end": 17,
    "max_per_slot": 1,
}

_TIME_SLOTS = [
    ("09:00", "9:00 AM"),
    ("10:00", "10:00 AM"),
    ("11:00", "11:00 AM"),
    ("12:00", "12:00 PM"),
    ("13:00", "1:00 PM"),
    ("14:00", "2:00 PM"),
    ("15:00", "3:00 PM"),
    ("16:00", "4:00 PM"),
]


class NurtureEngine:
    def __init__(self) -> None:
        self._sequences: Dict[str, Sequence] = {}
        self._scheduling_config: Dict[str, Any] = dict(_DEFAULT_SCHEDULING_CONFIG)
        self._appointments: List[Dict[str, Any]] = []

    # ─── Sequence CRUD ───────────────────────────────────────────────

    def create_sequence(self, lead_data: dict) -> dict:
        lead_id = lead_data.get("id", uuid.uuid4().hex[:12])
        name = lead_data.get("title", "Valued Customer")
        email = lead_data.get("email", "")
        phone = lead_data.get("phone", "")
        industry = lead_data.get("industry", "home improvement")
        business_name = lead_data.get("business_name", "Our Business")
        now = datetime.now()

        ctx = {
            "name": name,
            "lead_name": name,
            "lead_email": email,
            "lead_phone": phone,
            "phone": phone,
            "industry": industry,
            "created_at": now.isoformat(),
            "business_name": business_name,
        }

        sms_template = (
            "Hi {name}, thanks for reaching out! We received your request "
            "and will review it shortly. - {business_name}"
        ).format(**ctx)

        email_template = {
            "subject": "We're reviewing your project",
            "body": (
                "Hi {name}, just confirming we received your project details. "
                "Our team is reviewing and will reach out with a personalized "
                "proposal within 24 hours. In the meantime, feel free to call "
                "us at {phone} if you have any questions. Best, {business_name}"
            ).format(**ctx),
        }

        call_template = (
            "Reminder: Call {lead_name} at {lead_phone} \u2014 they submitted "
            "a {industry} project request {created_at}"
        ).format(**ctx)

        actions = [
            {
                "type": "sms",
                "delay_minutes": 5,
                "template": sms_template,
                "sent": False,
                "scheduled_at": "",
            },
            {
                "type": "email",
                "delay_minutes": 60,
                "template": email_template,
                "sent": False,
                "scheduled_at": "",
            },
            {
                "type": "call",
                "delay_minutes": 1440,
                "template": call_template,
                "sent": False,
                "scheduled_at": "",
            },
        ]

        sequence_id = uuid.uuid4().hex[:12]
        seq = Sequence(
            id=sequence_id,
            lead_name=name,
            lead_id=lead_id,
            lead_email=email,
            lead_phone=phone,
            industry=industry,
            created_at=now.isoformat(),
            actions=actions,
            current_step=0,
            completed=False,
        )
        self._sequences[sequence_id] = seq
        return self._sequence_to_dict(seq)

    def _sequence_to_dict(self, seq: Sequence) -> dict:
        return {
            "id": seq.id,
            "lead_name": seq.lead_name,
            "lead_id": seq.lead_id,
            "lead_email": seq.lead_email,
            "lead_phone": seq.lead_phone,
            "industry": seq.industry,
            "created_at": seq.created_at,
            "actions": seq.actions,
            "current_step": seq.current_step,
            "completed": seq.completed,
        }

    # ─── Action Processing ──────────────────────────────────────────

    def get_due_actions(self) -> List[dict]:
        due: List[dict] = []
        now = datetime.now()

        for seq in self._sequences.values():
            if seq.completed:
                continue
            if seq.current_step >= len(seq.actions):
                continue

            action = seq.actions[seq.current_step]
            if action.get("sent"):
                continue

            try:
                created = datetime.fromisoformat(seq.created_at)
            except (ValueError, TypeError):
                continue

            deadline = created + timedelta(minutes=action["delay_minutes"])
            if now >= deadline:
                due.append({
                    "sequence_id": seq.id,
                    "action_index": seq.current_step,
                    "type": action["type"],
                    "template": action["template"],
                })

        return due

    def mark_action_sent(self, sequence_id: str, action_index: int) -> bool:
        seq = self._sequences.get(sequence_id)
        if not seq:
            return False
        if action_index < 0 or action_index >= len(seq.actions):
            return False

        seq.actions[action_index]["sent"] = True
        seq.actions[action_index]["scheduled_at"] = datetime.now().isoformat()
        seq.current_step += 1

        if seq.current_step >= len(seq.actions):
            seq.completed = True

        return True

    # ─── Queries ─────────────────────────────────────────────────────

    def get_sequences(self, limit: int = 50) -> List[dict]:
        sorted_seqs = sorted(
            self._sequences.values(),
            key=lambda s: s.created_at,
            reverse=True,
        )
        return [self._sequence_to_dict(s) for s in sorted_seqs[:limit]]

    def get_sequence(self, sequence_id: str) -> Optional[dict]:
        seq = self._sequences.get(sequence_id)
        return self._sequence_to_dict(seq) if seq else None

    def delete_sequence(self, sequence_id: str) -> bool:
        if sequence_id in self._sequences:
            del self._sequences[sequence_id]
            return True
        return False

    def get_stats(self) -> dict:
        total = len(self._sequences)
        active = sum(1 for s in self._sequences.values() if not s.completed)
        completed_count = sum(1 for s in self._sequences.values() if s.completed)
        pending = 0
        for seq in self._sequences.values():
            if seq.completed:
                continue
            if seq.current_step < len(seq.actions):
                if not seq.actions[seq.current_step].get("sent"):
                    pending += 1
        return {
            "total_sequences": total,
            "active": active,
            "completed": completed_count,
            "pending_actions": pending,
        }

    # ─── Scheduling Widget ───────────────────────────────────────────

    def generate_scheduling_widget(
        self,
        business_name: str = "Our Business",
        primary_color: str = "#6366f1",
    ) -> str:
        slot_options = "".join(
            f'<option value="{val}">{label}</option>'
            for val, label in _TIME_SLOTS
        )

        return f"""<div id="nurture-scheduling-widget" class="nsw-root">
<style>
.nsw-root {{
  all: initial;
  display: block;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #0a0a0f;
  color: #e2e8f0;
  border-radius: 12px;
  padding: 32px;
  max-width: 480px;
  margin: 0 auto;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
}}
.nsw-root * {{
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}}
.nsw-header {{
  font-size: 14px;
  font-weight: 600;
  color: {primary_color};
  text-transform: uppercase;
  letter-spacing: 1.5px;
  margin-bottom: 8px;
}}
.nsw-title {{
  font-size: 24px;
  font-weight: 700;
  color: #f1f5f9;
  margin-bottom: 24px;
}}
.nsw-field {{
  margin-bottom: 16px;
}}
.nsw-field label {{
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: #94a3b8;
  margin-bottom: 6px;
}}
.nsw-field input,
.nsw-field select {{
  width: 100%;
  padding: 10px 14px;
  background: #13131e;
  border: 1px solid #1e1e2e;
  border-radius: 8px;
  color: #e2e8f0;
  font-size: 15px;
  outline: none;
  transition: border-color 0.2s;
}}
.nsw-field input:focus,
.nsw-field select:focus {{
  border-color: {primary_color};
}}
.nsw-field input::placeholder {{
  color: #475569;
}}
.nsw-submit {{
  width: 100%;
  padding: 12px;
  background: {primary_color};
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: opacity 0.2s;
  margin-top: 8px;
}}
.nsw-submit:hover {{
  opacity: 0.9;
}}
.nsw-submit:disabled {{
  opacity: 0.5;
  cursor: not-allowed;
}}
.nsw-confirmation {{
  display: none;
  background: #13131e;
  border: 1px solid #1e1e2e;
  border-radius: 8px;
  padding: 24px;
  margin-top: 20px;
  text-align: center;
}}
.nsw-confirmation.show {{
  display: block;
}}
.nsw-confirmation-icon {{
  font-size: 32px;
  margin-bottom: 8px;
}}
.nsw-confirmation h3 {{
  color: {primary_color};
  margin-bottom: 8px;
}}
.nsw-confirmation p {{
  color: #94a3b8;
  font-size: 14px;
  line-height: 1.5;
}}
.nsw-error {{
  color: #ef4444;
  font-size: 13px;
  margin-top: 8px;
  display: none;
}}
.nsw-error.show {{
  display: block;
}}
@media (max-width: 520px) {{
  .nsw-root {{
    padding: 20px;
    border-radius: 0;
  }}
}}
</style>

<div class="nsw-header">{business_name}</div>
<div class="nsw-title">Schedule Your Consultation</div>

<form id="nsw-form" onsubmit="return false;">
  <div class="nsw-field">
    <label for="nsw-date">Date</label>
    <input type="date" id="nsw-date" name="date" required />
  </div>
  <div class="nsw-field">
    <label for="nsw-time">Time</label>
    <select id="nsw-time" name="time_slot" required>
      <option value="">Select a time</option>
      {slot_options}
    </select>
  </div>
  <div class="nsw-field">
    <label for="nsw-name">Name</label>
    <input type="text" id="nsw-name" name="name" placeholder="Your full name" required />
  </div>
  <div class="nsw-field">
    <label for="nsw-phone">Phone</label>
    <input type="tel" id="nsw-phone" name="phone" placeholder="(555) 123-4567" required />
  </div>
  <div class="nsw-field">
    <label for="nsw-email">Email</label>
    <input type="email" id="nsw-email" name="email" placeholder="you@example.com" required />
  </div>
  <button type="submit" class="nsw-submit" id="nsw-submit-btn">Confirm Appointment</button>
  <div class="nsw-error" id="nsw-error"></div>
</form>

<div class="nsw-confirmation" id="nsw-confirmation">
  <div class="nsw-confirmation-icon">&#10003;</div>
  <h3>Appointment Confirmed!</h3>
  <p id="nsw-confirmation-details"></p>
</div>

<script>
(function () {{
  var form = document.getElementById('nsw-form');
  var btn = document.getElementById('nsw-submit-btn');
  var errEl = document.getElementById('nsw-error');
  var confirmEl = document.getElementById('nsw-confirmation');
  var detailsEl = document.getElementById('nsw-confirmation-details');

  var minDate = new Date();
  minDate.setDate(minDate.getDate() + 1);
  document.getElementById('nsw-date').setAttribute('min', minDate.toISOString().split('T')[0]);

  form.addEventListener('submit', function (e) {{
    e.preventDefault();
    errEl.classList.remove('show');
    confirmEl.classList.remove('show');
    btn.disabled = true;
    btn.textContent = 'Confirming...';

    var data = {{
      name: document.getElementById('nsw-name').value.trim(),
      phone: document.getElementById('nsw-phone').value.trim(),
      email: document.getElementById('nsw-email').value.trim(),
      date: document.getElementById('nsw-date').value,
      time_slot: document.getElementById('nsw-time').value,
    }};

    fetch('/api/nurture/schedule', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(data),
    }})
    .then(function (r) {{ return r.json(); }})
    .then(function (result) {{
      if (result.ok) {{
        var timeLabel = '';
        var slots = {json.dumps(dict(_TIME_SLOTS))};
        if (slots[data.time_slot]) timeLabel = slots[data.time_slot];
        detailsEl.textContent = data.name + ', your appointment on ' + data.date + ' at ' + (timeLabel || data.time_slot) + ' is confirmed.';
        confirmEl.classList.add('show');
        form.reset();
      }} else {{
        errEl.textContent = result.error || 'Something went wrong. Please try again.';
        errEl.classList.add('show');
      }}
    }})
    .catch(function () {{
      errEl.textContent = 'Network error. Please check your connection and try again.';
      errEl.classList.add('show');
    }})
    .finally(function () {{
      btn.disabled = false;
      btn.textContent = 'Confirm Appointment';
    }});
  }});
}})();
</script>
</div>"""

    # ─── Scheduling API ──────────────────────────────────────────────

    def handle_scheduling(self, data: dict) -> dict:
        name = (data.get("name") or "").strip()
        phone = (data.get("phone") or "").strip()
        email = (data.get("email") or "").strip()
        date = (data.get("date") or "").strip()
        time_slot = (data.get("time_slot") or "").strip()

        errors = []
        if not name:
            errors.append("Name is required")
        if not phone:
            errors.append("Phone is required")
        if not email:
            errors.append("Email is required")
        if not date:
            errors.append("Date is required")
        if not time_slot:
            errors.append("Time slot is required")

        if errors:
            return {"ok": False, "error": "; ".join(errors)}

        try:
            parsed = datetime.fromisoformat(date)
            if parsed.date() <= datetime.now().date():
                return {"ok": False, "error": "Date must be in the future"}
        except (ValueError, TypeError):
            return {"ok": False, "error": "Invalid date format"}

        appointment_id = uuid.uuid4().hex[:12]
        appointment = {
            "appointment_id": appointment_id,
            "name": name,
            "phone": phone,
            "email": email,
            "date": date,
            "time_slot": time_slot,
            "created_at": datetime.now().isoformat(),
        }

        self._appointments.append(appointment)

        return {
            "ok": True,
            "appointment_id": appointment_id,
            "date": date,
            "time_slot": time_slot,
        }

    def get_appointments(self, limit: int = 50) -> List[dict]:
        return sorted(
            self._appointments,
            key=lambda a: a.get("created_at", ""),
            reverse=True,
        )[:limit]
