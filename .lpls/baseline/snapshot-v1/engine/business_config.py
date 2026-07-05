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
            "avg_job_size",
            "gross_margin",
            "lead_cost_ceiling",
            "monthly_ad_budget",
            "target_roas",
            "business_name",
            "business_phone",
            "business_email",
        }
        for key, value in updates.items():
            if key in known:
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
