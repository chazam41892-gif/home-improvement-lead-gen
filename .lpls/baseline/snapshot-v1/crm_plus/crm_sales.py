"""CRM & Sales integrations — 50 manifests."""
from __future__ import annotations

from leviathantalon_catalog.integrations.base import AuthScheme, manifest, IntegrationManifest
from typing import List


def _bearer(env: str) -> AuthScheme:
    return AuthScheme(kind="bearer", env_var=env)

def _header(env: str, hdr: str) -> AuthScheme:
    return AuthScheme(kind="header", env_var=env, header_name=hdr)

def _basic(env: str) -> AuthScheme:
    return AuthScheme(kind="basic", env_var=env)

def _query(env: str, qname: str = "api_key") -> AuthScheme:
    return AuthScheme(kind="query", env_var=env, query_name=qname)

def _oauth2(cid: str, csec: str, auth_url: str, tok_url: str, scopes: list) -> AuthScheme:
    return AuthScheme(
        kind="oauth2",
        oauth2_client_id_env=cid,
        oauth2_client_secret_env=csec,
        oauth2_authorize_url=auth_url,
        oauth2_token_url=tok_url,
        oauth2_scopes=scopes,
    )


# ── 1. Salesforce ──────────────────────────────────────────────────────────
_salesforce = manifest(
    "salesforce",
    "https://your-instance.salesforce.com/services/data/v59.0",
    display="Salesforce",
    category="crm_sales",
    auth=_oauth2(
        "SALESFORCE_CLIENT_ID", "SALESFORCE_CLIENT_SECRET",
        "https://login.salesforce.com/services/oauth2/authorize",
        "https://login.salesforce.com/services/oauth2/token",
        ["api", "refresh_token"],
    ),
    actions={
        "query_records": ("GET", "/query", ["q"], [], "Run SOQL query"),
        "create_lead": ("POST", "/sobjects/Lead", [], ["FirstName", "LastName", "Company", "Email"], "Create a Lead"),
        "update_opportunity": ("PATCH", "/sobjects/Opportunity/{id}", [], ["StageName", "Amount", "CloseDate"], "Update Opportunity"),
    },
    docs_url="https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/",
)

# ── 2. HubSpot ─────────────────────────────────────────────────────────────
_hubspot = manifest(
    "hubspot",
    "https://api.hubapi.com",
    display="HubSpot",
    category="crm_sales",
    auth=_bearer("HUBSPOT_ACCESS_TOKEN"),
    actions={
        "create_contact": ("POST", "/crm/v3/objects/contacts", [], ["email", "firstname", "lastname", "phone"], "Create CRM contact"),
        "search_contacts": ("POST", "/crm/v3/objects/contacts/search", [], ["filterGroups", "properties", "limit"], "Search contacts"),
        "create_deal": ("POST", "/crm/v3/objects/deals", [], ["dealname", "dealstage", "amount", "pipeline"], "Create a deal"),
    },
    docs_url="https://developers.hubspot.com/docs/api/crm/contacts",
)

# ── 3. Pipedrive ───────────────────────────────────────────────────────────
_pipedrive = manifest(
    "pipedrive",
    "https://api.pipedrive.com/v1",
    display="Pipedrive",
    category="crm_sales",
    auth=_query("PIPEDRIVE_API_TOKEN", "api_token"),
    actions={
        "get_persons": ("GET", "/persons", ["start", "limit", "filter_id"], [], "List persons"),
        "add_deal": ("POST", "/deals", [], ["title", "value", "currency", "person_id", "stage_id"], "Add a deal"),
        "add_activity": ("POST", "/activities", [], ["subject", "type", "due_date", "deal_id", "person_id"], "Log an activity"),
    },
    docs_url="https://developers.pipedrive.com/docs/api/v1",
)

# ── 4. Close.io ────────────────────────────────────────────────────────────
_close_io = manifest(
    "close_io",
    "https://api.close.com/api/v1",
    display="Close CRM",
    category="crm_sales",
    auth=_basic("CLOSE_API_KEY"),
    actions={
        "list_leads": ("GET", "/lead", ["query", "_limit", "_skip"], [], "Search/list leads"),
        "create_lead": ("POST", "/lead", [], ["name", "contacts", "status_id"], "Create a lead"),
        "create_task": ("POST", "/task", [], ["lead_id", "text", "due_date", "assigned_to"], "Create a task"),
    },
    docs_url="https://developer.close.com/",
)

# ── 5. Freshsales ──────────────────────────────────────────────────────────
_freshsales = manifest(
    "freshsales",
    "https://your-domain.myfreshworks.com/crm/sales/api",
    display="Freshsales",
    category="crm_sales",
    auth=_header("FRESHSALES_API_KEY", "Authorization"),
    actions={
        "list_contacts": ("GET", "/contacts/view/all", ["page", "per_page"], [], "List all contacts"),
        "create_contact": ("POST", "/contacts", [], ["first_name", "last_name", "email", "work_number"], "Create contact"),
        "create_deal": ("POST", "/deals", [], ["name", "deal_stage_id", "amount", "owner_id"], "Create deal"),
    },
    docs_url="https://developers.freshworks.com/crm/api/",
)

# ── 6. Zoho CRM ────────────────────────────────────────────────────────────
_zoho_crm = manifest(
    "zoho_crm",
    "https://www.zohoapis.com/crm/v5",
    display="Zoho CRM",
    category="crm_sales",
    auth=_oauth2(
        "ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET",
        "https://accounts.zoho.com/oauth/v2/auth",
        "https://accounts.zoho.com/oauth/v2/token",
        ["ZohoCRM.modules.ALL"],
    ),
    actions={
        "get_leads": ("GET", "/Leads", ["fields", "page", "per_page"], [], "Retrieve leads"),
        "create_lead": ("POST", "/Leads", [], ["Last_Name", "Company", "Email", "Phone"], "Create a lead"),
        "search_records": ("GET", "/Contacts/search", ["criteria", "fields"], [], "Search contacts by criteria"),
    },
    docs_url="https://www.zoho.com/crm/developer/docs/api/v5/",
)

# ── 7. Insightly ───────────────────────────────────────────────────────────
_insightly = manifest(
    "insightly",
    "https://api.insightly.com/v3.1",
    display="Insightly",
    category="crm_sales",
    auth=_basic("INSIGHTLY_API_KEY"),
    actions={
        "get_contacts": ("GET", "/Contacts", ["top", "skip", "orderby", "filter"], [], "List contacts"),
        "create_contact": ("POST", "/Contacts", [], ["FIRST_NAME", "LAST_NAME", "EMAIL_ADDRESS"], "Create contact"),
        "create_opportunity": ("POST", "/Opportunities", [], ["OPPORTUNITY_NAME", "OPPORTUNITY_STATE", "RESPONSIBLE_USER_ID"], "Create opportunity"),
    },
    docs_url="https://api.insightly.com/v3.1/Help",
)

# ── 8. Copper CRM ──────────────────────────────────────────────────────────
_copper_crm = manifest(
    "copper_crm",
    "https://api.copper.com/developer_api/v1",
    display="Copper CRM",
    category="crm_sales",
    auth=_header("COPPER_API_KEY", "X-PW-AccessToken"),
    actions={
        "search_people": ("POST", "/people/search", [], ["name", "emails", "page_size"], "Search people records"),
        "create_person": ("POST", "/people", [], ["name", "emails", "phone_numbers", "company_id"], "Create a person"),
        "create_opportunity": ("POST", "/opportunities", [], ["name", "primary_contact_id", "pipeline_id", "pipeline_stage_id"], "Create opportunity"),
    },
    docs_url="https://developer.copper.com/",
)

# ── 9. Nimble CRM ──────────────────────────────────────────────────────────
_nimble_crm = manifest(
    "nimble_crm",
    "https://api.nimble.com/api/v1",
    display="Nimble CRM",
    category="crm_sales",
    auth=_bearer("NIMBLE_ACCESS_TOKEN"),
    actions={
        "list_contacts": ("GET", "/contacts", ["limit", "offset", "sort"], [], "List contacts"),
        "create_contact": ("POST", "/contact", [], ["first_name", "last_name", "email", "phone"], "Create contact"),
        "add_note": ("POST", "/activities/note", [], ["note", "contact_ids", "subject"], "Add a note to contacts"),
    },
    docs_url="https://nimble.readthedocs.io/en/latest/",
)

# ── 10. Capsule CRM ────────────────────────────────────────────────────────
_capsule_crm = manifest(
    "capsule_crm",
    "https://api.capsulecrm.com/api/v2",
    display="Capsule CRM",
    category="crm_sales",
    auth=_bearer("CAPSULE_API_TOKEN"),
    actions={
        "list_parties": ("GET", "/parties", ["q", "page", "perPage"], [], "Search parties (people/orgs)"),
        "create_person": ("POST", "/parties", [], ["type", "firstName", "lastName", "emailAddresses"], "Create a person"),
        "create_opportunity": ("POST", "/opportunities", [], ["name", "party", "milestone", "value"], "Create an opportunity"),
    },
    docs_url="https://developer.capsulecrm.com/v2/",
)

# ── 11. Apptivo ────────────────────────────────────────────────────────────
_apptivo = manifest(
    "apptivo",
    "https://api.apptivo.com/app/dao",
    display="Apptivo",
    category="crm_sales",
    auth=_query("APPTIVO_API_KEY", "apiKey"),
    actions={
        "get_leads": ("GET", "/leads/byApiKey", ["num_rows", "start"], [], "List leads"),
        "create_lead": ("POST", "/leads/create", [], ["firstName", "lastName", "email", "phone"], "Create a lead"),
        "create_opportunity": ("POST", "/opportunities/create", [], ["opportunityName", "accountId", "stage"], "Create opportunity"),
    },
    docs_url="https://apptivo.com/api/",
)

# ── 12. Bitrix24 ───────────────────────────────────────────────────────────
_bitrix24 = manifest(
    "bitrix24",
    "https://your-domain.bitrix24.com/rest/1",
    display="Bitrix24",
    category="crm_sales",
    auth=_query("BITRIX24_WEBHOOK_SECRET", "auth"),
    actions={
        "crm_contact_list": ("GET", "/crm.contact.list", ["filter", "select", "start"], [], "List CRM contacts"),
        "crm_contact_add": ("POST", "/crm.contact.add", [], ["fields"], "Add CRM contact"),
        "crm_deal_add": ("POST", "/crm.deal.add", [], ["fields"], "Add CRM deal"),
    },
    docs_url="https://training.bitrix24.com/rest_help/crm/",
)

# ── 13. Streak CRM ─────────────────────────────────────────────────────────
_streak_crm = manifest(
    "streak_crm",
    "https://www.streak.com/api/v2",
    display="Streak CRM",
    category="crm_sales",
    auth=_basic("STREAK_API_KEY"),
    actions={
        "list_pipelines": ("GET", "/pipelines", [], [], "List all pipelines"),
        "create_box": ("POST", "/pipelines/{pipelineKey}/boxes", [], ["name", "stageKey"], "Create a box (deal)"),
        "list_contacts": ("GET", "/contacts", ["page", "limit"], [], "List contacts"),
    },
    docs_url="https://streak.readme.io/reference/",
)

# ── 14. Salesflare ─────────────────────────────────────────────────────────
_salesflare = manifest(
    "salesflare",
    "https://api.salesflare.com",
    display="Salesflare",
    category="crm_sales",
    auth=_header("SALESFLARE_API_KEY", "Authorization"),
    actions={
        "list_accounts": ("GET", "/accounts", ["type", "limit", "offset"], [], "List accounts"),
        "create_contact": ("POST", "/contacts", [], ["email", "firstname", "lastname", "phone"], "Create contact"),
        "create_opportunity": ("POST", "/opportunities", [], ["name", "account_id", "pipeline_id", "stage_id"], "Create opportunity"),
    },
    docs_url="https://api.salesflare.com/docs",
)

# ── 15. EngageBay ──────────────────────────────────────────────────────────
_engagebay = manifest(
    "engagebay",
    "https://app.engagebay.com/dev",
    display="EngageBay",
    category="crm_sales",
    auth=_header("ENGAGEBAY_API_KEY", "Authorization"),
    actions={
        "list_contacts": ("GET", "/panel/contacts", ["page", "limit", "sort"], [], "List contacts"),
        "create_contact": ("POST", "/panel/subscribers/subscriber", [], ["email", "name", "phone"], "Create subscriber/contact"),
        "create_deal": ("POST", "/panel/deals", [], ["name", "amount", "milestone", "owner_id"], "Create a deal"),
    },
    docs_url="https://help.engagebay.com/article/51-crm-api",
)

# ── 16. Agile CRM ──────────────────────────────────────────────────────────
_agile_crm = manifest(
    "agile_crm",
    "https://your-domain.agilecrm.com/dev",
    display="Agile CRM",
    category="crm_sales",
    auth=_basic("AGILECRM_API_KEY"),
    actions={
        "get_contacts": ("GET", "/api/contacts", ["page_size", "cursor"], [], "List contacts"),
        "create_contact": ("POST", "/api/contacts", [], ["first_name", "last_name", "email", "phone"], "Create contact"),
        "create_deal": ("POST", "/api/opportunity", [], ["name", "expected_value", "milestone", "probability"], "Create a deal"),
    },
    docs_url="https://github.com/agilecrm/rest-api",
)

# ── 17. ActiveCampaign CRM ─────────────────────────────────────────────────
_activecampaign_crm = manifest(
    "activecampaign_crm",
    "https://your-account.api-us1.com/api/3",
    display="ActiveCampaign CRM",
    category="crm_sales",
    auth=_header("ACTIVECAMPAIGN_API_KEY", "Api-Token"),
    actions={
        "list_contacts": ("GET", "/contacts", ["limit", "offset", "email"], [], "List/search contacts"),
        "create_contact": ("POST", "/contacts", [], ["email", "firstName", "lastName", "phone"], "Create contact"),
        "create_deal": ("POST", "/deals", [], ["title", "value", "currency", "owner", "group"], "Create CRM deal"),
    },
    docs_url="https://developers.activecampaign.com/reference/",
)

# ── 18. Keap / Infusionsoft ────────────────────────────────────────────────
_keap_infusionsoft = manifest(
    "keap_infusionsoft",
    "https://api.infusionsoft.com/crm/rest/v1",
    display="Keap / Infusionsoft",
    category="crm_sales",
    auth=_oauth2(
        "KEAP_CLIENT_ID", "KEAP_CLIENT_SECRET",
        "https://signin.infusionsoft.com/app/oauth/authorize",
        "https://api.infusionsoft.com/token",
        ["full"],
    ),
    actions={
        "list_contacts": ("GET", "/contacts", ["limit", "offset", "order"], [], "List contacts"),
        "create_contact": ("POST", "/contacts", [], ["email_addresses", "given_name", "family_name", "phone_numbers"], "Create contact"),
        "create_opportunity": ("POST", "/opportunities", [], ["title", "contact", "stage", "estimated_close_date"], "Create opportunity"),
    },
    docs_url="https://developer.infusionsoft.com/docs/rest/",
)

# ── 19. Less Annoying CRM ──────────────────────────────────────────────────
_less_annoying_crm = manifest(
    "less_annoying_crm",
    "https://api.lessannoyingcrm.com/v1",
    display="Less Annoying CRM",
    category="crm_sales",
    auth=_header("LACRM_API_TOKEN", "Authorization"),
    actions={
        "get_contact": ("GET", "/Contact/{ContactId}", [], [], "Get a contact by ID"),
        "create_contact": ("POST", "/Contact", [], ["FirstName", "LastName", "Email", "Phone"], "Create contact"),
        "create_pipeline_item": ("POST", "/Pipeline", [], ["ContactId", "PipelineId", "StatusId", "Note"], "Add contact to a pipeline"),
    },
    docs_url="https://www.lessannoyingcrm.com/help/topic/api/",
)

# ── 20. Nutshell CRM ───────────────────────────────────────────────────────
_nutshell_crm = manifest(
    "nutshell_crm",
    "https://app.nutshell.com/api/v1/json",
    display="Nutshell CRM",
    category="crm_sales",
    auth=_basic("NUTSHELL_API_KEY"),
    actions={
        "find_contacts": ("POST", "/findContacts", [], ["query", "limit", "page"], "Search contacts"),
        "new_contact": ("POST", "/newContact", [], ["name", "email", "phone"], "Create a contact"),
        "new_lead": ("POST", "/newLead", [], ["contacts", "accounts", "market", "assignee"], "Create a lead/deal"),
    },
    docs_url="https://developers.nutshell.com/",
)

# ── 21. Pipeliner CRM ──────────────────────────────────────────────────────
_pipeliner_crm = manifest(
    "pipeliner_crm",
    "https://eu-central.pipelinersales.com/api/v100",
    display="Pipeliner CRM",
    category="crm_sales",
    auth=_basic("PIPELINER_API_KEY"),
    actions={
        "list_contacts": ("GET", "/rest/{spaceId}/entities/Contacts", ["limit", "offset", "filter"], [], "List contacts"),
        "create_contact": ("POST", "/rest/{spaceId}/entities/Contacts", [], ["first_name", "last_name", "email1"], "Create contact"),
        "create_opportunity": ("POST", "/rest/{spaceId}/entities/Opportunities", [], ["name", "pipeline_id", "step_id", "value"], "Create opportunity"),
    },
    docs_url="https://pipelinersales.github.io/pipeliner-api-docs/",
)

# ── 22. Salesloft ──────────────────────────────────────────────────────────
_salesloft = manifest(
    "salesloft",
    "https://api.salesloft.com/v2",
    display="Salesloft",
    category="crm_sales",
    auth=_bearer("SALESLOFT_ACCESS_TOKEN"),
    actions={
        "list_people": ("GET", "/people", ["per_page", "page", "email_addresses"], [], "List people (prospects)"),
        "create_person": ("POST", "/people", [], ["email_address", "first_name", "last_name", "phone"], "Create a person"),
        "create_cadence_membership": ("POST", "/cadence_memberships", [], ["person_id", "cadence_id", "user_id"], "Enroll person in cadence"),
    },
    docs_url="https://developers.salesloft.com/api.html",
)

# ── 23. Outreach.io ────────────────────────────────────────────────────────
_outreach_io = manifest(
    "outreach_io",
    "https://api.outreach.io/api/v2",
    display="Outreach",
    category="crm_sales",
    auth=_bearer("OUTREACH_ACCESS_TOKEN"),
    actions={
        "list_prospects": ("GET", "/prospects", ["filter[emails]", "page[size]", "page[number]"], [], "List prospects"),
        "create_prospect": ("POST", "/prospects", [], ["emails", "firstName", "lastName", "phones"], "Create prospect"),
        "create_sequence_state": ("POST", "/sequenceStates", [], ["prospect_id", "sequence_id", "mailboxId"], "Enroll in sequence"),
    },
    docs_url="https://developers.outreach.io/api/",
)

# ── 24. Apollo.io ──────────────────────────────────────────────────────────
_apollo_io = manifest(
    "apollo_io",
    "https://api.apollo.io/v1",
    display="Apollo.io",
    category="crm_sales",
    auth=_header("APOLLO_API_KEY", "Cache-Control"),
    actions={
        "people_search": ("POST", "/mixed_people/search", [], ["q_keywords", "person_titles", "contact_email_status", "page"], "Search people"),
        "enrich_person": ("POST", "/people/match", [], ["first_name", "last_name", "organization_name", "email"], "Enrich a person record"),
        "create_contact": ("POST", "/contacts", [], ["first_name", "last_name", "email", "organization_name"], "Create a contact"),
    },
    docs_url="https://apolloio.github.io/apollo-api-docs/",
)

# ── 25. ZoomInfo ───────────────────────────────────────────────────────────
_zoominfo = manifest(
    "zoominfo",
    "https://api.zoominfo.com",
    display="ZoomInfo",
    category="crm_sales",
    auth=_bearer("ZOOMINFO_ACCESS_TOKEN"),
    actions={
        "search_contacts": ("POST", "/search/contact", [], ["matchPersonInput", "outputFields", "rpp"], "Search B2B contacts"),
        "search_companies": ("POST", "/search/company", [], ["matchCompanyInput", "outputFields", "rpp"], "Search companies"),
        "enrich_contact": ("POST", "/enrich/contact", [], ["matchPersonInput", "outputFields"], "Enrich a contact record"),
    },
    docs_url="https://api-docs.zoominfo.com/",
)

# ── 26. Lusha ──────────────────────────────────────────────────────────────
_lusha = manifest(
    "lusha",
    "https://api.lusha.com",
    display="Lusha",
    category="crm_sales",
    auth=_header("LUSHA_API_KEY", "api_key"),
    actions={
        "find_person": ("GET", "/person", ["firstName", "lastName", "company", "domain"], [], "Find contact info for a person"),
        "find_company": ("GET", "/company", ["domain"], [], "Look up company data"),
        "bulk_enrich": ("POST", "/bulk/person", [], ["contacts"], "Bulk enrich person list"),
    },
    docs_url="https://www.lusha.com/docs/",
)

# ── 27. Hunter.io ──────────────────────────────────────────────────────────
_hunter_io = manifest(
    "hunter_io",
    "https://api.hunter.io/v2",
    display="Hunter.io",
    category="crm_sales",
    auth=_query("HUNTER_API_KEY", "api_key"),
    actions={
        "domain_search": ("GET", "/domain-search", ["domain", "limit", "offset", "type"], [], "Find email addresses for a domain"),
        "email_finder": ("GET", "/email-finder", ["domain", "first_name", "last_name"], [], "Find a person's email"),
        "email_verifier": ("GET", "/email-verifier", ["email"], [], "Verify an email address"),
    },
    docs_url="https://hunter.io/api-documentation/v2",
)

# ── 28. Clearbit ───────────────────────────────────────────────────────────
_clearbit = manifest(
    "clearbit",
    "https://person.clearbit.com/v2",
    display="Clearbit",
    category="crm_sales",
    auth=_bearer("CLEARBIT_API_KEY"),
    actions={
        "enrich_person": ("GET", "/people/find", ["email"], [], "Enrich a person by email"),
        "enrich_company": ("GET", "/companies/find", ["domain"], [], "Enrich a company by domain"),
        "reveal_ip": ("GET", "/companies/find", ["ip"], [], "Identify company from IP address"),
    },
    docs_url="https://dashboard.clearbit.com/docs",
)

# ── 29. RocketReach ────────────────────────────────────────────────────────
_rocketreach = manifest(
    "rocketreach",
    "https://api.rocketreach.co/v2",
    display="RocketReach",
    category="crm_sales",
    auth=_header("ROCKETREACH_API_KEY", "Api-Key"),
    actions={
        "lookup_person": ("GET", "/api/lookupProfile", ["linkedin_url", "name", "current_employer"], [], "Look up a profile"),
        "search_people": ("POST", "/api/search", [], ["query", "page", "page_size"], "Search people"),
        "bulk_lookup": ("POST", "/api/bulk_lookup", [], ["ids"], "Bulk look up profiles"),
    },
    docs_url="https://rocketreach.co/api",
)

# ── 30. Crunchbase API ─────────────────────────────────────────────────────
_crunchbase_api = manifest(
    "crunchbase_api",
    "https://api.crunchbase.com/api/v4",
    display="Crunchbase",
    category="crm_sales",
    auth=_query("CRUNCHBASE_API_KEY", "user_key"),
    actions={
        "search_organizations": ("POST", "/searches/organizations", [], ["field_ids", "predicate", "limit"], "Search organizations"),
        "get_organization": ("GET", "/entities/organizations/{entity_id}", ["field_ids"], [], "Get organization details"),
        "search_people": ("POST", "/searches/people", [], ["field_ids", "predicate", "limit"], "Search people"),
    },
    docs_url="https://data.crunchbase.com/docs",
)

# ── 31. PhantomBuster ──────────────────────────────────────────────────────
_phantombuster = manifest(
    "phantombuster",
    "https://api.phantombuster.com/api/v2",
    display="PhantomBuster",
    category="crm_sales",
    auth=_header("PHANTOMBUSTER_API_KEY", "X-Phantombuster-Key"),
    actions={
        "list_agents": ("GET", "/agents/fetch-all", [], [], "List all automation agents"),
        "launch_agent": ("POST", "/agents/launch", [], ["id", "argument"], "Launch a PhantomBuster agent"),
        "fetch_output": ("GET", "/agents/fetch-output", ["id"], [], "Fetch the latest output of an agent"),
    },
    docs_url="https://hub.phantombuster.com/reference/",
)

# ── 32. Snov.io ────────────────────────────────────────────────────────────
_snov_io = manifest(
    "snov_io",
    "https://api.snov.io",
    display="Snov.io",
    category="crm_sales",
    auth=_bearer("SNOV_ACCESS_TOKEN"),
    actions={
        "get_domain_prospects": ("POST", "/v1/get-domain-emails-with-info", [], ["domain", "type", "limit", "lastId"], "Find prospects from a domain"),
        "add_prospect": ("POST", "/v1/add-prospect-to-list", [], ["emails", "listId"], "Add prospect to a list"),
        "verify_email": ("POST", "/v1/get-emails-verification-status", [], ["emails"], "Verify email deliverability"),
    },
    docs_url="https://snov.io/api",
)

# ── 33. AnyMailFinder ──────────────────────────────────────────────────────
_anymailfinder = manifest(
    "anymailfinder",
    "https://api.anymailfinder.com/v5.0",
    display="AnyMailFinder",
    category="crm_sales",
    auth=_bearer("ANYMAILFINDER_API_KEY"),
    actions={
        "find_email": ("POST", "/search/email.json", [], ["full_name", "domain"], "Find email from name + domain"),
        "bulk_find": ("POST", "/search/bulk.json", [], ["searches"], "Submit bulk email find job"),
        "get_bulk_result": ("GET", "/bulk/{bulk_search_id}.json", [], [], "Retrieve bulk job results"),
    },
    docs_url="https://anymailfinder.com/api-docs",
)

# ── 34. FindThatLead ───────────────────────────────────────────────────────
_findthatlead = manifest(
    "findthatlead",
    "https://api.findthatlead.com/v1",
    display="FindThatLead",
    category="crm_sales",
    auth=_query("FINDTHATLEAD_API_KEY", "apikey"),
    actions={
        "find_email": ("GET", "/email-search", ["firstname", "lastname", "domain"], [], "Find email for a person"),
        "domain_search": ("GET", "/domain-search", ["domain"], [], "Find emails for a domain"),
        "verify_email": ("GET", "/verify", ["email"], [], "Verify an email address"),
    },
    docs_url="https://findthatlead.com/api-docs",
)

# ── 35. LeadIQ ─────────────────────────────────────────────────────────────
_leadiq = manifest(
    "leadiq",
    "https://api.leadiq.com",
    display="LeadIQ",
    category="crm_sales",
    auth=_bearer("LEADIQ_API_KEY"),
    actions={
        "find_contact": ("POST", "/graphql", [], ["query", "variables"], "GraphQL: find contact by LinkedIn URL"),
        "enrich_contact": ("POST", "/graphql", [], ["query", "variables"], "GraphQL: enrich contact details"),
        "push_to_crm": ("POST", "/graphql", [], ["query", "variables"], "GraphQL: push enriched contact to CRM"),
    },
    docs_url="https://developers.leadiq.com/",
)

# ── 36. Cognism ────────────────────────────────────────────────────────────
_cognism = manifest(
    "cognism",
    "https://api.cognism.com/v1",
    display="Cognism",
    category="crm_sales",
    auth=_bearer("COGNISM_API_KEY"),
    actions={
        "search_contacts": ("POST", "/contacts/search", [], ["filter", "fields", "limit", "offset"], "Search B2B contacts"),
        "get_contact": ("GET", "/contacts/{id}", ["fields"], [], "Get a contact by ID"),
        "export_contacts": ("POST", "/contacts/export", [], ["ids", "crmType"], "Export contacts to CRM"),
    },
    docs_url="https://developer.cognism.com/",
)

# ── 37. Lead411 ────────────────────────────────────────────────────────────
_lead411 = manifest(
    "lead411",
    "https://api.lead411.com/v1",
    display="Lead411",
    category="crm_sales",
    auth=_header("LEAD411_API_KEY", "X-Auth-Token"),
    actions={
        "search_people": ("GET", "/people", ["first_name", "last_name", "company", "title", "limit"], [], "Search people"),
        "search_companies": ("GET", "/companies", ["name", "industry", "state", "employees_min", "limit"], [], "Search companies"),
        "get_person": ("GET", "/people/{id}", [], [], "Get person detail by ID"),
    },
    docs_url="https://www.lead411.com/api-documentation/",
)

# ── 38. AeroLeads ──────────────────────────────────────────────────────────
_aeroleads = manifest(
    "aeroleads",
    "https://aeroleads.com/api",
    display="AeroLeads",
    category="crm_sales",
    auth=_query("AEROLEADS_API_KEY", "api_key"),
    actions={
        "get_prospects": ("GET", "/prospects", ["page"], [], "List prospect data"),
        "add_prospect": ("POST", "/prospects", [], ["name", "email", "company", "phone"], "Add a prospect"),
        "delete_prospect": ("DELETE", "/prospects/{id}", [], [], "Delete a prospect"),
    },
    docs_url="https://aeroleads.com/api-documentation/",
)

# ── 39. Datanyze ───────────────────────────────────────────────────────────
_datanyze = manifest(
    "datanyze",
    "https://api.datanyze.com",
    display="Datanyze",
    category="crm_sales",
    auth=_bearer("DATANYZE_ACCESS_TOKEN"),
    actions={
        "get_company_technographics": ("GET", "/api/company", ["domain"], [], "Get technographic data for company"),
        "search_contacts": ("POST", "/api/contacts/search", [], ["first_name", "last_name", "company"], "Search contacts"),
        "enrich_contact": ("POST", "/api/contacts/enrich", [], ["email"], "Enrich contact with firmographic data"),
    },
    docs_url="https://developer.datanyze.com/",
)

# ── 40. NeverBounce ────────────────────────────────────────────────────────
_neverbounce = manifest(
    "neverbounce",
    "https://api.neverbounce.com/v4",
    display="NeverBounce",
    category="crm_sales",
    auth=_query("NEVERBOUNCE_API_KEY", "key"),
    actions={
        "single_check": ("GET", "/single/check", ["email", "address_info", "credits_info"], [], "Verify a single email"),
        "bulk_create": ("POST", "/jobs/create", [], ["input_location", "input", "filename"], "Create bulk verification job"),
        "bulk_results": ("GET", "/jobs/results", ["job_id", "items_per_page", "page"], [], "Retrieve bulk job results"),
    },
    docs_url="https://developers.neverbounce.com/",
)

# ── 41. Intercom ───────────────────────────────────────────────────────────
_intercom = manifest(
    "intercom",
    "https://api.intercom.io",
    display="Intercom",
    category="crm_sales",
    auth=_bearer("INTERCOM_ACCESS_TOKEN"),
    actions={
        "list_contacts": ("GET", "/contacts", ["page", "per_page"], [], "List Intercom contacts/users"),
        "create_contact": ("POST", "/contacts", [], ["email", "name", "phone", "role"], "Create a contact"),
        "create_conversation": ("POST", "/conversations", [], ["from", "body"], "Start a new conversation"),
    },
    docs_url="https://developers.intercom.com/intercom-api-reference/",
)

# ── 42. Front App ──────────────────────────────────────────────────────────
_front_app = manifest(
    "front_app",
    "https://api2.frontapp.com",
    display="Front",
    category="crm_sales",
    auth=_bearer("FRONT_ACCESS_TOKEN"),
    actions={
        "list_conversations": ("GET", "/conversations", ["q", "limit"], [], "List conversations"),
        "send_message": ("POST", "/channels/{channel_id}/messages", [], ["author_id", "subject", "body", "to"], "Send a new message"),
        "list_contacts": ("GET", "/contacts", ["limit", "page_token"], [], "List contacts"),
    },
    docs_url="https://dev.frontapp.com/docs/",
)

# ── 43. Help Scout ─────────────────────────────────────────────────────────
_helpscout = manifest(
    "helpscout",
    "https://api.helpscout.net/v2",
    display="Help Scout",
    category="crm_sales",
    auth=_bearer("HELPSCOUT_ACCESS_TOKEN"),
    actions={
        "list_conversations": ("GET", "/conversations", ["mailbox", "status", "page"], [], "List conversations"),
        "create_conversation": ("POST", "/conversations", [], ["subject", "mailboxId", "type", "customer", "threads"], "Create conversation"),
        "list_customers": ("GET", "/customers", ["firstName", "lastName", "email", "page"], [], "Search/list customers"),
    },
    docs_url="https://developer.helpscout.com/mailbox-api/",
)

# ── 44. Zendesk Sell ───────────────────────────────────────────────────────
_zendesk_sell = manifest(
    "zendesk_sell",
    "https://api.getbase.com/v2",
    display="Zendesk Sell",
    category="crm_sales",
    auth=_bearer("ZENDESK_SELL_ACCESS_TOKEN"),
    actions={
        "list_contacts": ("GET", "/contacts", ["page", "per_page", "is_organization"], [], "List contacts"),
        "create_contact": ("POST", "/contacts", [], ["first_name", "last_name", "email", "phone", "is_organization"], "Create contact"),
        "create_deal": ("POST", "/deals", [], ["name", "contact_id", "value", "stage_id"], "Create a deal"),
    },
    docs_url="https://developers.getbase.com/",
)

# ── 45. Kustomer ───────────────────────────────────────────────────────────
_kustomer = manifest(
    "kustomer",
    "https://api.kustomerapp.com/v1",
    display="Kustomer",
    category="crm_sales",
    auth=_bearer("KUSTOMER_API_KEY"),
    actions={
        "list_customers": ("GET", "/customers", ["page", "pageSize", "email"], [], "List customers"),
        "create_customer": ("POST", "/customers", [], ["name", "emails", "phones", "externalId"], "Create a customer"),
        "create_conversation": ("POST", "/conversations", [], ["customer", "channels", "subject"], "Create a conversation"),
    },
    docs_url="https://developer.kustomer.com/kustomer-api/reference/",
)

# ── 46. Gorgias ────────────────────────────────────────────────────────────
_gorgias = manifest(
    "gorgias",
    "https://your-store.gorgias.com/api",
    display="Gorgias",
    category="crm_sales",
    auth=_basic("GORGIAS_API_KEY"),
    actions={
        "list_tickets": ("GET", "/tickets", ["status", "limit", "cursor"], [], "List support tickets"),
        "create_ticket": ("POST", "/tickets", [], ["requester", "channel", "subject", "messages"], "Create a support ticket"),
        "list_customers": ("GET", "/customers", ["email", "limit"], [], "Search customers"),
    },
    docs_url="https://developers.gorgias.com/",
)

# ── 47. Re:amaze ───────────────────────────────────────────────────────────
_reamaze = manifest(
    "reamaze",
    "https://www.reamaze.io/api/v1",
    display="Re:amaze",
    category="crm_sales",
    auth=_basic("REAMAZE_API_KEY"),
    actions={
        "list_conversations": ("GET", "/conversations", ["page", "status", "channel"], [], "List conversations"),
        "create_conversation": ("POST", "/conversations", [], ["conversation", "message"], "Create a new conversation"),
        "list_contacts": ("GET", "/contacts", ["page", "q"], [], "List/search contacts"),
    },
    docs_url="https://www.reamaze.com/api",
)

# ── 48. Freshdesk ──────────────────────────────────────────────────────────
_freshdesk = manifest(
    "freshdesk",
    "https://your-domain.freshdesk.com/api/v2",
    display="Freshdesk",
    category="crm_sales",
    auth=_basic("FRESHDESK_API_KEY"),
    actions={
        "list_tickets": ("GET", "/tickets", ["page", "per_page", "order_type", "filter"], [], "List support tickets"),
        "create_ticket": ("POST", "/tickets", [], ["subject", "description", "email", "priority", "status"], "Create a ticket"),
        "list_contacts": ("GET", "/contacts", ["page", "per_page", "email"], [], "List contacts"),
    },
    docs_url="https://developers.freshdesk.com/api/",
)

# ── 49. LiveChat Inc ───────────────────────────────────────────────────────
_livechat_inc = manifest(
    "livechat_inc",
    "https://api.livechatinc.com/v3.5",
    display="LiveChat",
    category="crm_sales",
    auth=_basic("LIVECHAT_PAT"),
    actions={
        "list_chats": ("GET", "/chats", ["limit", "page_id", "sort_order"], [], "List recent chats"),
        "get_customers": ("POST", "/customers", [], ["filters", "fields", "page_id", "limit"], "List/search customers"),
        "send_event": ("POST", "/chats/{chat_id}/events", [], ["type", "text"], "Send event to a chat"),
    },
    docs_url="https://platform.text.com/docs/messaging/",
)

# ── 50. Gong.io ────────────────────────────────────────────────────────────
_gong_io = manifest(
    "gong_io",
    "https://api.gong.io/v2",
    display="Gong",
    category="crm_sales",
    auth=_basic("GONG_ACCESS_KEY"),
    actions={
        "list_calls": ("GET", "/calls", ["fromDateTime", "toDateTime", "workspaceId"], [], "List recorded calls"),
        "get_call_transcript": ("POST", "/calls/transcript", [], ["callIds"], "Retrieve transcripts for calls"),
        "list_users": ("GET", "/users", ["includeAvatars"], [], "List Gong users"),
    },
    docs_url="https://us-66496.app.gong.io/settings/api/documentation",
)


ALL_CRM_SALES_INTEGRATIONS: List[IntegrationManifest] = [
    _salesforce,
    _hubspot,
    _pipedrive,
    _close_io,
    _freshsales,
    _zoho_crm,
    _insightly,
    _copper_crm,
    _nimble_crm,
    _capsule_crm,
    _apptivo,
    _bitrix24,
    _streak_crm,
    _salesflare,
    _engagebay,
    _agile_crm,
    _activecampaign_crm,
    _keap_infusionsoft,
    _less_annoying_crm,
    _nutshell_crm,
    _pipeliner_crm,
    _salesloft,
    _outreach_io,
    _apollo_io,
    _zoominfo,
    _lusha,
    _hunter_io,
    _clearbit,
    _rocketreach,
    _crunchbase_api,
    _phantombuster,
    _snov_io,
    _anymailfinder,
    _findthatlead,
    _leadiq,
    _cognism,
    _lead411,
    _aeroleads,
    _datanyze,
    _neverbounce,
    _intercom,
    _front_app,
    _helpscout,
    _zendesk_sell,
    _kustomer,
    _gorgias,
    _reamaze,
    _freshdesk,
    _livechat_inc,
    _gong_io,
]


def register_crm_sales(bundle) -> int:
    """Register all CRM & Sales integrations into *bundle*. Returns count registered."""
    for m in ALL_CRM_SALES_INTEGRATIONS:
        bundle.register(m)
    return len(ALL_CRM_SALES_INTEGRATIONS)
