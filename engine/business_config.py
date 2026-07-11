from __future__ import annotations


_CLOSE_RATE_ESTIMATE = 4.0
_APPROX_CVR = 0.1


class BusinessConfig:
    def __init__(self) -> None:
        self.avg_job_size: float = 8500.0
        self.gross_margin: float = 0.35
        self.lead_cost_ceiling: float = 85.0
        self.monthly_ad_budget: float = 2000.0
        self.target_roas: float = 4.0
        self.business_name: str = "Our Business"
        self.business_phone: str = ""
        self.business_email: str = ""

    def get_config(self) -> dict:
        return {
            "avg_job_size": self.avg_job_size,
            "gross_margin": self.gross_margin,
            "lead_cost_ceiling": self.lead_cost_ceiling,
            "monthly_ad_budget": self.monthly_ad_budget,
            "target_roas": self.target_roas,
            "business_name": self.business_name,
            "business_phone": self.business_phone,
            "business_email": self.business_email,
        }

    def update_config(self, updates: dict) -> dict:
        known = {
            "avg_job_size": float,
            "gross_margin": float,
            "lead_cost_ceiling": float,
            "monthly_ad_budget": float,
            "target_roas": float,
            "business_name": str,
            "business_phone": str,
            "business_email": str,
        }
        for key, value in updates.items():
            if key in known:
                expected = known[key]
                try:
                    if expected in (int, float):
                        value = expected(value)
                        if expected == float and value < 0:
                            raise ValueError(f"{key} must be non-negative")
                except (TypeError, ValueError):
                    raise ValueError(f"Invalid value for {key}: expected {expected.__name__}")
                setattr(self, key, value)
        return self.get_config()

    def get_metrics(self) -> dict:
        avg_profit_per_job = self.avg_job_size * self.gross_margin
        leads_needed_per_job = _CLOSE_RATE_ESTIMATE
        cost_per_acquired_customer = self.lead_cost_ceiling * leads_needed_per_job
        max_cost_per_click = self.lead_cost_ceiling * _APPROX_CVR
        break_even_leads = (
            self.monthly_ad_budget / self.lead_cost_ceiling
            if self.lead_cost_ceiling > 0
            else 0
        )

        return {
            "avg_job_size": self.avg_job_size,
            "gross_margin": self.gross_margin,
            "avg_profit_per_job": avg_profit_per_job,
            "lead_cost_ceiling": self.lead_cost_ceiling,
            "monthly_ad_budget": self.monthly_ad_budget,
            "leads_needed_per_job": leads_needed_per_job,
            "cost_per_acquired_customer": cost_per_acquired_customer,
            "target_roas": self.target_roas,
            "max_cost_per_click": max_cost_per_click,
            "break_even_leads": break_even_leads,
        }

    def evaluate_lead(self, trade_avg_job_value: float, trade_cpl_ceiling: float, lead_score: float = 50) -> dict:
        """Return an economic verdict for a lead given the business model and trade economics."""
        if trade_avg_job_value <= 0 or trade_cpl_ceiling <= 0 or self.gross_margin <= 0 or self.lead_cost_ceiling <= 0:
            return {
                "verdict": "invalid",
                "error": "Trade economics or business config missing required positive values",
                "lead_score": lead_score,
            }

        effective_job_value = max(trade_avg_job_value, self.avg_job_size)
        profit_per_job = effective_job_value * self.gross_margin
        # Better leads reduce the effective number of leads needed to close
        close_rate_adjustment = max(0.5, min(4.0, 4.0 - (lead_score / 100) * 2.0))
        effective_cpl = min(trade_cpl_ceiling, self.lead_cost_ceiling)
        cost_to_acquire = effective_cpl * close_rate_adjustment
        roas = profit_per_job / cost_to_acquire if cost_to_acquire > 0 else 0
        max_cost_per_click = self.lead_cost_ceiling * _APPROX_CVR
        max_bid = min(effective_cpl * _APPROX_CVR, max_cost_per_click)

        verdict = "reject"
        if roas >= self.target_roas and effective_cpl <= self.lead_cost_ceiling:
            verdict = "pursue"
        elif roas >= 1.0 and effective_cpl <= self.lead_cost_ceiling * 1.25:
            verdict = "test"

        return {
            "verdict": verdict,
            "trade_avg_job_value": trade_avg_job_value,
            "business_avg_job_size": self.avg_job_size,
            "profit_per_job": round(profit_per_job, 2),
            "effective_cpl": round(effective_cpl, 2),
            "cost_to_acquire": round(cost_to_acquire, 2),
            "roas": round(roas, 2),
            "target_roas": self.target_roas,
            "max_bid": round(max_bid, 2),
            "lead_score": lead_score,
        }
