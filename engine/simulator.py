from __future__ import annotations

import random
import math
from typing import Dict, Any
from engine.trades.trades import get_trade_config

class CampaignSimulator:
    """
    Simulates B2B marketing campaign ROI and performance metrics
    using default trade configs, seasonal triggers, and budget constraints.
    """

    def project_roi(self, trade_id: str, location: str, daily_budget: float) -> dict:
        config = get_trade_config(trade_id)
        if not config:
            raise ValueError(f"Unknown trade: {trade_id}")

        avg_job_value = config.get("avg_job_value", 5000.0)
        cpl_ceiling = config.get("lead_cpl_ceiling", 100.0)
        base_conv_rate = config.get("conversion_rate", 0.05)
        seasons = config.get("seasons", [])

        # 1. Location-based density multiplier (based on string hashing for stability)
        loc_hash = sum(ord(c) for c in location)
        loc_mult = 0.8 + ((loc_hash % 50) / 100.0) # range 0.8 to 1.3

        # 2. Seasonality modifier (checks current month)
        from datetime import datetime
        current_month = datetime.now().strftime("%B").lower()
        season_mult = 1.0
        if seasons:
            is_peak = any(current_month in s.lower() or s.lower() in current_month for s in seasons)
            season_mult = 1.25 if is_peak else 0.85

        # 3. Compute cost-per-lead (CPL) and spend
        budget_scale = 1.0 + (math.log(max(1.0, daily_budget / 50.0)) * 0.15) if daily_budget > 50 else 1.0
        projected_cpl = round(cpl_ceiling * loc_mult * budget_scale, 2)
        
        monthly_spend = daily_budget * 30
        simulated_leads = int(monthly_spend / max(10.0, projected_cpl))

        # 4. Run daily stochastic simulation for 30 days
        total_leads = 0
        total_conversions = 0
        daily_log = []

        daily_lead_rate = (daily_budget / projected_cpl) if projected_cpl > 0 else 0
        rng = random.Random(loc_hash + int(daily_budget))

        for day in range(1, 31):
            daily_leads = int(rng.gauss(daily_lead_rate, math.sqrt(max(1.0, daily_lead_rate))))
            daily_leads = max(0, daily_leads)
            
            day_conv_rate = base_conv_rate * season_mult * rng.uniform(0.9, 1.1)
            conversions = 0
            for _ in range(daily_leads):
                if rng.random() < day_conv_rate:
                    conversions += 1
            
            total_leads += daily_leads
            total_conversions += conversions
            daily_log.append({
                "day": day,
                "leads": daily_leads,
                "conversions": conversions,
                "revenue": round(conversions * avg_job_value, 2)
            })

        gross_revenue = round(total_conversions * avg_job_value, 2)
        net_profit = round(gross_revenue - monthly_spend, 2)
        roi_pct = round((net_profit / monthly_spend) * 100, 2) if monthly_spend > 0 else 0.0

        return {
            "ok": True,
            "trade": trade_id,
            "location": location,
            "monthly_spend": round(monthly_spend, 2),
            "projected_cpl": projected_cpl,
            "total_leads": total_leads,
            "total_conversions": total_conversions,
            "gross_revenue": gross_revenue,
            "net_profit": net_profit,
            "roi_percentage": roi_pct,
            "daily_log": daily_log
        }
