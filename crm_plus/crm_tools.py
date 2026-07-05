"""
CRMTools — Customer Relationship Management for Metanoia Unlimited
CRM+ Integration for lead management, sales tracking, customer support
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import json

logger = logging.getLogger("talon.crm")


class CRMTools:
    """
    CRM+ System for Metanoia Unlimited LLC
    Complete customer lifecycle management
    """
    
    def __init__(self, db_path: str = "./data/crm"):
        self.db_path = db_path
        self.leads = []
        self.customers = []
        self.interactions = []
        self.opportunities = []
        
    async def create_lead(self, name: str, email: str, source: str, 
                         phone: Optional[str] = None, company: Optional[str] = None) -> Dict:
        """Create a new lead"""
        lead = {
            'id': f"LEAD-{len(self.leads)+1:05d}",
            'name': name,
            'email': email,
            'phone': phone,
            'company': company,
            'source': source,
            'status': 'new',
            'score': 0,
            'created_at': datetime.now().isoformat(),
            'last_contact': None,
            'notes': []
        }
        self.leads.append(lead)
        logger.info(f"Created lead: {name} ({email})")
        return {'success': True, 'lead': lead}
    
    async def qualify_lead(self, lead_id: str, score: int, status: str) -> Dict:
        """Qualify a lead with scoring"""
        for lead in self.leads:
            if lead['id'] == lead_id:
                lead['score'] = score
                lead['status'] = status
                if score >= 70:
                    lead['status'] = 'qualified'
                return {'success': True, 'lead': lead}
        return {'success': False, 'error': 'Lead not found'}
    
    async def convert_to_customer(self, lead_id: str, deal_value: float = 0.0) -> Dict:
        """Convert qualified lead to customer"""
        for lead in self.leads:
            if lead['id'] == lead_id:
                if lead['status'] != 'qualified':
                    return {'success': False, 'error': 'Lead not qualified'}
                
                customer = {
                    'id': f"CUST-{len(self.customers)+1:05d}",
                    'lead_id': lead_id,
                    'name': lead['name'],
                    'email': lead['email'],
                    'phone': lead['phone'],
                    'company': lead['company'],
                    'deal_value': deal_value,
                    'status': 'active',
                    'lifetime_value': deal_value,
                    'created_at': datetime.now().isoformat(),
                    'last_purchase': datetime.now().isoformat(),
                    'support_tickets': [],
                    'communication_history': []
                }
                self.customers.append(customer)
                lead['status'] = 'converted'
                logger.info(f"Converted lead to customer: {customer['name']}")
                return {'success': True, 'customer': customer}
        return {'success': False, 'error': 'Lead not found'}
    
    async def log_interaction(self, contact_id: str, contact_type: str,
                             interaction_type: str, notes: str,
                             outcome: Optional[str] = None) -> Dict:
        """Log customer/lead interaction"""
        interaction = {
            'id': f"INT-{len(self.interactions)+1:06d}",
            'contact_id': contact_id,
            'contact_type': contact_type,  # 'lead' or 'customer'
            'type': interaction_type,  # 'email', 'call', 'meeting', 'demo'
            'notes': notes,
            'outcome': outcome,
            'timestamp': datetime.now().isoformat()
        }
        self.interactions.append(interaction)
        
        # Update last contact
        for lead in self.leads:
            if lead['id'] == contact_id:
                lead['last_contact'] = interaction['timestamp']
                lead['notes'].append(notes)
                break
        
        return {'success': True, 'interaction': interaction}
    
    async def create_opportunity(self, customer_id: str, name: str,
                                  value: float, stage: str = 'prospecting') -> Dict:
        """Create sales opportunity"""
        opportunity = {
            'id': f"OPP-{len(self.opportunities)+1:05d}",
            'customer_id': customer_id,
            'name': name,
            'value': value,
            'stage': stage,  # 'prospecting', 'qualification', 'proposal', 'negotiation', 'closed_won', 'closed_lost'
            'probability': self._stage_probability(stage),
            'expected_close': None,
            'created_at': datetime.now().isoformat(),
            'activities': []
        }
        self.opportunities.append(opportunity)
        return {'success': True, 'opportunity': opportunity}
    
    def _stage_probability(self, stage: str) -> int:
        """Get probability for stage"""
        probabilities = {
            'prospecting': 10,
            'qualification': 25,
            'proposal': 50,
            'negotiation': 75,
            'closed_won': 100,
            'closed_lost': 0
        }
        return probabilities.get(stage, 10)
    
    async def update_opportunity_stage(self, opp_id: str, new_stage: str) -> Dict:
        """Update opportunity stage"""
        for opp in self.opportunities:
            if opp['id'] == opp_id:
                opp['stage'] = new_stage
                opp['probability'] = self._stage_probability(new_stage)
                if new_stage == 'closed_won':
                    await self._process_win(opp)
                return {'success': True, 'opportunity': opp}
        return {'success': False, 'error': 'Opportunity not found'}
    
    async def _process_win(self, opportunity: Dict):
        """Process won opportunity"""
        # Update customer lifetime value
        for customer in self.customers:
            if customer['id'] == opportunity['customer_id']:
                customer['lifetime_value'] += opportunity['value']
                customer['last_purchase'] = datetime.now().isoformat()
                logger.info(f"Deal won: ${opportunity['value']} from {customer['name']}")
                break
    
    async def get_pipeline(self) -> Dict:
        """Get sales pipeline overview"""
        pipeline = {}
        total_value = 0
        weighted_value = 0
        
        for opp in self.opportunities:
            stage = opp['stage']
            if stage not in pipeline:
                pipeline[stage] = {'count': 0, 'value': 0}
            pipeline[stage]['count'] += 1
            pipeline[stage]['value'] += opp['value']
            total_value += opp['value']
            weighted_value += opp['value'] * (opp['probability'] / 100)
        
        return {
            'success': True,
            'pipeline': pipeline,
            'total_value': total_value,
            'weighted_value': weighted_value,
            'active_opportunities': len([o for o in self.opportunities if o['stage'] not in ['closed_won', 'closed_lost']])
        }
    
    async def get_dashboard(self) -> Dict:
        """Get CRM dashboard metrics"""
        active_leads = len([l for l in self.leads if l['status'] == 'new'])
        qualified_leads = len([l for l in self.leads if l['status'] == 'qualified'])
        customers = len(self.customers)
        total_revenue = sum(c['lifetime_value'] for c in self.customers)
        
        return {
            'success': True,
            'metrics': {
                'active_leads': active_leads,
                'qualified_leads': qualified_leads,
                'customers': customers,
                'total_revenue': total_revenue,
                'opportunities': len(self.opportunities),
                'interactions_today': len([i for i in self.interactions 
                                          if i['timestamp'].startswith(datetime.now().strftime('%Y-%m-%d'))])
            }
        }
    
    async def ai_lead_scoring(self, lead_id: str) -> Dict:
        """AI-powered lead scoring"""
        for lead in self.leads:
            if lead['id'] == lead_id:
                # Simple scoring algorithm (replace with ML model)
                score = 0
                if lead['email']:
                    score += 20
                if lead['phone']:
                    score += 15
                if lead['company']:
                    score += 25
                if lead['source'] in ['referral', 'organic']:
                    score += 20
                
                lead['score'] = min(100, score)
                
                # Auto-qualify high scores
                if lead['score'] >= 70:
                    lead['status'] = 'qualified'
                
                return {'success': True, 'lead': lead, 'score': lead['score']}
        return {'success': False, 'error': 'Lead not found'}
    
    async def export_data(self, format: str = 'json') -> Dict:
        """Export CRM data"""
        data = {
            'leads': self.leads,
            'customers': self.customers,
            'interactions': self.interactions,
            'opportunities': self.opportunities,
            'exported_at': datetime.now().isoformat()
        }
        
        if format == 'json':
            export_path = f"./exports/crm_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            Path(export_path).parent.mkdir(parents=True, exist_ok=True)
            with open(export_path, 'w') as f:
                json.dump(data, f, indent=2)
            return {'success': True, 'path': export_path}
        
        return {'success': True, 'data': data}
