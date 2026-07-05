from __future__ import annotations

import re
import uuid
from urllib.parse import urlencode, urlparse, urlunparse


_INDUSTRY_DEFAULTS: dict[str, dict[str, list[str]]] = {
    "roofing": {
        "headlines": [
            "Local Roofing Experts You Can Trust",
            "Quality Roof Repairs & Replacements",
            "Protect Your Home with a New Roof",
            "Affordable Roofing Services Near You",
            "Licensed Roofing Contractors",
        ],
        "descriptions": [
            "Get a free estimate from licensed roofing pros. Quality work, guaranteed.",
            "Storm damage? Leaks? We fix it all. Free inspections available today.",
            "Affordable roof repairs and replacements. Family-owned & trusted.",
            "From shingle to metal roofing, we do it all. Call for your free quote.",
        ],
        "usps": ["Free Estimate", "Free Inspection", "Licensed & Insured"],
    },
    "plumbing": {
        "headlines": [
            "Emergency Plumbing Services 24/7",
            "Trusted Local Plumbers Near You",
            "Fast & Reliable Plumbing Repairs",
            "Stop Leaks Before They Cause Damage",
            "Licensed Plumbing Contractors",
        ],
        "descriptions": [
            "Clogged drain? Burst pipe? Call our expert plumbers for fast service.",
            "24/7 emergency plumbing. Licensed pros arrive fast. Free estimates.",
            "From faucet repairs to water heater installation. Quality work guaranteed.",
            "Don't let a small leak become a big problem. Call us today.",
        ],
        "usps": ["24/7 Emergency Service", "Free Estimate", "Licensed & Insured"],
    },
    "hvac": {
        "headlines": [
            "Heating & AC Services You Can Trust",
            "Stay Comfortable All Year Long",
            "Expert HVAC Installation & Repair",
            "Beat the Heat with Professional AC Service",
            "Local HVAC Contractors Near You",
        ],
        "descriptions": [
            "Is your AC struggling? Schedule a tune-up today. Licensed HVAC techs.",
            "From furnaces to heat pumps, we service it all. Free estimates.",
            "Don't sweat it — call the HVAC pros. Fast, reliable service.",
            "Heating repairs, AC installation, and everything in between.",
        ],
        "usps": ["Free Estimate", "Same-Day Service", "Licensed & Insured"],
    },
    "electrical": {
        "headlines": [
            "Licensed Electricians You Can Count On",
            "Electrical Repairs & Installations",
            "Safe & Reliable Electrical Services",
            "Panel Upgrades & Wiring Experts",
            "Local Electrical Contractors",
        ],
        "descriptions": [
            "Flickering lights? Outlets not working? Call our licensed electricians.",
            "From panel upgrades to whole-home wiring. Safety first, always.",
            "Need a new ceiling fan or outlet? We handle it all. Free estimates.",
            "Don't DIY electricity — trust the pros. Licensed & insured.",
        ],
        "usps": ["Licensed & Insured", "Free Estimate", "Same-Day Service"],
    },
    "construction": {
        "headlines": [
            "General Contractors for Your Dream Home",
            "Custom Construction & Remodeling",
            "From Foundation to Finish",
            "Quality Construction Services Near You",
            "Build with the Best Contractors",
        ],
        "descriptions": [
            "Turning your vision into reality. Custom homes, additions & more.",
            "Experienced general contractors for residential & commercial projects.",
            "From concept to completion — we build it all. Free consultations.",
            "Quality craftsmanship on every project. Licensed & insured.",
        ],
        "usps": ["Free Consultation", "Licensed & Insured", "Quality Guaranteed"],
    },
    "landscaping": {
        "headlines": [
            "Transform Your Outdoor Space Today",
            "Professional Landscaping & Design",
            "Lawn Care & Hardscaping Experts",
            "Beautiful Yards Start Here",
            "Local Landscaping Services Near You",
        ],
        "descriptions": [
            "From lawn maintenance to complete landscape design. Free quotes.",
            "Make your neighbors jealous. Professional landscaping at fair prices.",
            "Patios, walkways, sod, and more. Your dream yard awaits.",
            "Curb appeal starts with great landscaping. Call us today.",
        ],
        "usps": ["Free Estimate", "Licensed & Insured", "Quality Guaranteed"],
    },
    "solar": {
        "headlines": [
            "Go Solar — Save on Energy Bills",
            "Solar Panel Installation Experts",
            "Power Your Home with Clean Energy",
            "Affordable Solar Solutions Near You",
            "Local Solar Installers You Can Trust",
        ],
        "descriptions": [
            "Reduce your electric bill with professional solar panel installation.",
            "Federal tax credits available. Go solar for as little as $0 down.",
            "Energy independence starts at home. Get your free solar quote today.",
            "Expert solar design and installation. Save money & the planet.",
        ],
        "usps": ["Free Quote", "$0 Down Options", "Licensed Installers"],
    },
    "painting": {
        "headlines": [
            "Transform Your Home with Fresh Paint",
            "Interior & Exterior Painting Pros",
            "Professional Painters Near You",
            "Quality Painting at Affordable Prices",
            "Local Painting Contractors",
        ],
        "descriptions": [
            "Give your home a fresh look. Interior and exterior painting services.",
            "From accent walls to whole-house repaints. Free color consultation.",
            "Professional painters who show up on time and leave it spotless.",
            "Boost your home's value with a professional paint job.",
        ],
        "usps": ["Free Estimate", "Licensed & Insured", "Quality Guaranteed"],
    },
    "windows": {
        "headlines": [
            "Energy-Efficient Window Replacement",
            "Beautiful New Windows for Your Home",
            "Window Installation Experts Near You",
            "Save Energy with New Windows",
            "Local Window Replacement Contractors",
        ],
        "descriptions": [
            "Lower your energy bills with premium replacement windows. Free quote.",
            "Cracked or drafty windows? Upgrade today and feel the difference.",
            "Professional window installation. Energy Star certified products.",
            "Enhance your home's comfort and value with new windows.",
        ],
        "usps": ["Free Estimate", "Energy Star Certified", "Lifetime Warranty"],
    },
    "kitchen & bath": {
        "headlines": [
            "Dream Kitchen & Bath Renovations",
            "Transform Your Kitchen or Bathroom",
            "Custom Remodeling Experts Near You",
            "From Old to Stunning — Kitchen & Bath",
            "Local Kitchen & Bath Contractors",
        ],
        "descriptions": [
            "Turn your kitchen into the heart of the home. Custom designs & builds.",
            "Luxury bathrooms at affordable prices. Free design consultation.",
            "Cabinet refacing, countertops, tile — we do it all.",
            "Your dream kitchen or bath is just a call away. Free estimates.",
        ],
        "usps": ["Free Design Consultation", "Licensed & Insured", "Quality Guaranteed"],
    },
    "fencing": {
        "headlines": [
            "Privacy & Security Fencing Experts",
            "Custom Fence Installation Near You",
            "Quality Fencing at Fair Prices",
            "Enhance Your Property with a New Fence",
            "Local Fence Contractors",
        ],
        "descriptions": [
            "Wood, vinyl, chain link, and more. Professional fence installation.",
            "Need more privacy? We build beautiful, durable fences. Free quotes.",
            "Secure your property with quality fencing. Licensed & insured.",
            "From garden fences to pool safety fences. We do it all.",
        ],
        "usps": ["Free Estimate", "Licensed & Insured", "Quality Guaranteed"],
    },
    "concrete": {
        "headlines": [
            "Concrete Driveways & Patios Experts",
            "Quality Concrete Work for Your Home",
            "Stamped Concrete & Pavers Near You",
            "Durable Concrete Solutions",
            "Local Concrete Contractors",
        ],
        "descriptions": [
            "Driveways, patios, walkways, and foundations. Expert concrete work.",
            "Stamped or stained concrete that looks like stone for less.",
            "Cracked driveway? We'll make it look brand new. Free estimates.",
            "Durable, beautiful concrete from experienced contractors.",
        ],
        "usps": ["Free Estimate", "Licensed & Insured", "Quality Guaranteed"],
    },
    "cleaning": {
        "headlines": [
            "Professional Cleaning Services",
            "Sparkling Clean Homes & Offices",
            "Trusted Local Cleaning Company",
            "Let Us Do the Dirty Work",
            "Affordable Cleaning Services Near You",
        ],
        "descriptions": [
            "Deep cleaning, move-out cleaning, regular maintenance. We do it all.",
            "Your home deserves a professional clean. Eco-friendly products used.",
            "Residential and commercial cleaning. Licensed, bonded & insured.",
            "Sit back and relax while we make your space spotless.",
        ],
        "usps": ["Eco-Friendly Products", "Licensed & Insured", "Satisfaction Guaranteed"],
    },
    "pest control": {
        "headlines": [
            "Pest Control Experts Near You",
            "Get Rid of Pests for Good",
            "Safe & Effective Pest Elimination",
            "Protect Your Home from Pests",
            "Local Pest Control Services",
        ],
        "descriptions": [
            "Ants, roaches, termites, rodents — we eliminate them all. Free inspection.",
            "Safe for kids and pets. Effective pest control with guaranteed results.",
            "Don't let pests take over your home. Call us for fast relief.",
            "Seasonal pest prevention plans available. Protect your home year-round.",
        ],
        "usps": ["Free Inspection", "Pet Safe", "Satisfaction Guaranteed"],
    },
    "moving": {
        "headlines": [
            "Stress-Free Moving Services",
            "Local & Long-Distance Moving Experts",
            "Professional Movers You Can Trust",
            "Pack, Load, Move — We Handle It All",
            "Affordable Moving Company Near You",
        ],
        "descriptions": [
            "From packing to unpacking, our movers handle everything with care.",
            "Local moves, long-distance, and commercial. Free moving quotes.",
            "Don't lift a finger. Professional movers who treat your belongings like gold.",
            "Moving made easy. Transparent pricing, no hidden fees.",
        ],
        "usps": ["Free Quote", "Licensed & Insured", "No Hidden Fees"],
    },
    "real estate": {
        "headlines": [
            "Top Real Estate Agents Near You",
            "Buy or Sell with Confidence",
            "Your Dream Home Awaits",
            "Local Real Estate Experts",
            "Sell Your Home for Top Dollar",
        ],
        "descriptions": [
            "Expert real estate agents ready to help you buy or sell your home.",
            "Get the best price for your home. Free market analysis available.",
            "First-time buyer? We'll guide you every step of the way.",
            "Your local real estate experts. Proven results, happy clients.",
        ],
        "usps": ["Free Market Analysis", "Proven Results", "Client Satisfaction"],
    },
    "church": {
        "headlines": [
            "Find Your Spiritual Home",
            "Worship With Our Community",
            "All Are Welcome Here",
            "A Place for Faith & Fellowship",
            "Join Us This Sunday",
        ],
        "descriptions": [
            "Find community, purpose, and faith. All are welcome to worship with us.",
            "A welcoming congregation for you and your family. Join us this Sunday.",
            "Faith-based community serving [location]. Everyone is welcome.",
            "Discover a place where you belong. Youth programs, worship & more.",
        ],
        "usps": ["All Are Welcome", "Family-Friendly", "Community Focused"],
    },
}

_FACEBOOK_HEADLINES: dict[str, list[str]] = {
    "roofing": [
        "Your Roof Protects Everything You Love",
        "Don't Wait Until It Leaks",
        "Peace of Mind Starts at the Top",
    ],
    "plumbing": [
        "A Tiny Drip Can Become a Flood",
        "Hot Showers. Working Drains. Happy Home.",
        "Don't Let Plumbing Problems Ruin Your Day",
    ],
    "hvac": [
        "Your Family Deserves Perfect Comfort",
        "Too Hot? Too Cold? We've Got You.",
        "Breathe Easy with Expert HVAC Service",
    ],
    "electrical": [
        "Safety Starts with Good Wiring",
        "Don't Get Left in the Dark",
        "Power Your Home Safely",
    ],
    "construction": [
        "Build Something Beautiful",
        "Your Dream Home Is Closer Than You Think",
        "From Blueprint to Reality",
    ],
    "landscaping": [
        "Your Yard, Only Better",
        "Imagine Morning Coffee in Paradise",
        "Curb Appeal That Turns Heads",
    ],
    "solar": [
        "Harness the Power of the Sun",
        "Lower Bills. Cleaner Planet. Smart Choice.",
        "Energy Freedom Starts Today",
    ],
    "painting": [
        "A Fresh Coat Changes Everything",
        "Your Home Deserves a Makeover",
        "Color Your World Beautiful",
    ],
    "windows": [
        "See the World Through New Windows",
        "Let the Light In",
        "Drafty Windows? We've Got the Solution.",
    ],
    "kitchen & bath": [
        "The Heart of Your Home Deserves Love",
        "Luxury Baths Don't Have to Cost a Fortune",
        "Cook, Laugh, Live — In a Kitchen You Love",
    ],
    "fencing": [
        "Good Fences Make Good Neighbors",
        "Your Private Oasis Awaits",
        "Define Your Space Beautifully",
    ],
    "concrete": [
        "A Driveway That Welcomes You Home",
        "Solid Foundations for Beautiful Spaces",
        "Curb Appeal from the Ground Up",
    ],
    "cleaning": [
        "Come Home to a Sparkling Clean Space",
        "You Work Hard — Let Us Clean",
        "A Clean Home Is a Happy Home",
    ],
    "pest control": [
        "Sleep Tight, No Bugs Tonight",
        "Your Home Should Be Yours Alone",
        "Uninvited Guests? We'll Show Them Out.",
    ],
    "moving": [
        "Starting Fresh? We'll Carry the Load.",
        "Moving Doesn't Have to Be Stressful",
        "Your New Chapter Starts Here",
    ],
    "real estate": [
        "Find the Place You'll Call Home",
        "Your Dream Home Is Out There",
        "Sell Smart. Buy Happy. Live Well.",
    ],
    "church": [
        "You Are Not Alone — You Belong Here",
        "Faith, Hope & Community Await You",
        "Find Your People. Find Your Purpose.",
    ],
}

_LSA_DESCRIPTIONS: dict[str, str] = {
    "roofing": "Professional roofing services in {location}. Licensed & insured roof repairs and installations. Free estimates available.",
    "plumbing": "Expert plumbing services in {location}. Fast, reliable repairs. Licensed plumbers. Call today.",
    "hvac": "Heating and AC services in {location}. Professional HVAC repair and installation. Licensed technicians.",
    "electrical": "Licensed electricians serving {location}. Safe, reliable electrical services for your home. Free estimates.",
    "construction": "General contractors in {location} for custom builds and renovations. Quality craftsmanship. Free consultations.",
    "landscaping": "Landscaping services in {location}. Lawn care, hardscaping, and design. Free quotes. Licensed & insured.",
    "solar": "Solar panel installation in {location}. Save on energy with professional solar. Free quotes available.",
    "painting": "Professional painters in {location}. Interior and exterior painting. Free estimates. Licensed & insured.",
    "windows": "Window replacement in {location}. Energy-efficient windows. Professional installation. Free quotes.",
    "kitchen & bath": "Kitchen and bath remodeling in {location}. Custom designs. Licensed contractors. Free consultations.",
    "fencing": "Fence installation in {location}. Wood, vinyl, and more. Free estimates. Licensed & insured.",
    "concrete": "Concrete services in {location}. Driveways, patios, foundations. Quality work. Free estimates.",
    "cleaning": "Professional cleaning services in {location}. Residential and commercial. Licensed & insured.",
    "pest control": "Pest control in {location}. Safe, effective pest elimination. Free inspections. Pet friendly.",
    "moving": "Moving services in {location}. Local and long-distance. Licensed & insured. Free quotes.",
    "real estate": "Real estate agents in {location}. Buy or sell with trusted local experts. Free market analysis.",
    "church": "Faith community in {location}. All are welcome to worship and fellowship with us.",
}

_CTA_DEFAULTS: list[str] = [
    "Get Free Estimate",
    "Call Now",
    "Get a Quote",
    "Book Online",
    "Contact Us Today",
    "Schedule Now",
    "Learn More",
    "Get Started",
]


class AdCopyGenerator:
    def __init__(self) -> None:
        pass

    def generate_ad_copy(
        self,
        industry: str,
        location: str = "",
        usp: str = "",
        platform: str = "google",
        count: int = 3,
    ) -> list[dict]:
        industry = industry.lower().strip()
        data = _INDUSTRY_DEFAULTS.get(industry)
        if data is None:
            data = {
                "headlines": [f"Professional {industry.title()} Services"],
                "descriptions": [
                    f"Expert {industry} services near you. Quality work, guaranteed."
                ],
                "usps": ["Free Estimate", "Licensed & Insured", "Quality Guaranteed"],
            }

        usp_pool = [usp] if usp else data["usps"]
        ctas = _CTA_DEFAULTS[:]

        results: list[dict] = []
        for i in range(count):
            headline_idx = i % len(data["headlines"])
            desc_idx = i % len(data["descriptions"])
            usp_idx = i % len(usp_pool)
            cta_idx = i % len(ctas)

            headline = data["headlines"][headline_idx]
            description = data["descriptions"][desc_idx]
            cta = ctas[cta_idx]
            selected_usp = usp_pool[usp_idx]

            if platform == "google":
                headline = self._make_google_headline(headline, industry, location)
                description = self._make_description(
                    description, location, selected_usp
                )

            elif platform == "facebook":
                fb_list = _FACEBOOK_HEADLINES.get(industry, data["headlines"])
                headline = fb_list[i % len(fb_list)]
                if location:
                    headline = f"{headline} — Serving {location}"
                description = self._make_description(
                    data["descriptions"][desc_idx], location, selected_usp
                )

            elif platform == "lsa":
                lsa_template = _LSA_DESCRIPTIONS.get(
                    industry,
                    f"Professional {industry} services in {{{{location}}}}. Free estimates.",
                )
                description = lsa_template.format(location=location or "your area")
                headline = f"{industry.title()} in {location or 'Your Area'}"
                cta = "Call Now"

            headline = headline[:30]
            description = description[:90]

            results.append(
                {
                    "headline": headline,
                    "description": description,
                    "cta": cta,
                    "platform": platform,
                }
            )

        return results

    @staticmethod
    def _make_google_headline(
        headline: str, industry: str, location: str
    ) -> str:
        loc = location or "Near You"
        variants = [
            f"{loc} {industry.title()} Experts",
            f"Best {industry.title()} in {loc}",
            f"{headline}",
            f"{industry.title()} Services {loc}",
        ]
        return variants[hash(headline) % len(variants)]

    @staticmethod
    def _make_description(
        description: str, location: str, usp: str
    ) -> str:
        result = description
        if location and "{location}" not in result:
            result = result.replace("near you", f"in {location}").replace(
                "Near You", f"in {location}"
            )
            if "near you" not in result.lower():
                result = f"{result.strip('. ')} in {location}."
        if usp and usp not in result:
            result = f"{result.strip('. ')} {usp}."
        return result

    def generate_keywords(self, industry: str, location: str = "") -> dict:
        industry = industry.lower().strip()
        base = industry
        loc = location
        loc_prefix = f"{loc} " if loc else ""
        loc_suffix = f" in {loc}" if loc else ""

        service_terms = [
            f"{base} services",
            f"{base} contractor",
            f"{base} company",
            f"{base} repair",
            f"{base} installation",
            f"emergency {base}",
            f"residential {base}",
            f"commercial {base}",
        ]

        problem_terms = {
            "roofing": ["roof leak repair", "storm damage roof", "missing shingles"],
            "plumbing": ["clogged drain", "burst pipe repair", "water heater leak"],
            "hvac": ["ac not cooling", "furnace repair", "no heat"],
            "electrical": ["flickering lights", "breaker keeps tripping", "outlet not working"],
            "construction": ["home addition", "basement finishing", "room addition"],
            "landscaping": ["overgrown yard", "dead lawn", "landscape design"],
            "solar": ["high electric bill", "solar panel cost", "go solar"],
            "painting": ["peeling paint", "interior painting", "exterior painting"],
            "windows": ["drafty windows", "window replacement cost", "double pane windows"],
            "kitchen & bath": ["kitchen remodel", "bathroom renovation", "cabinet refacing"],
            "fencing": ["privacy fence", "fence repair", "pool fence"],
            "concrete": ["cracked driveway", "concrete patio", "stamped concrete"],
            "cleaning": ["deep cleaning", "move out cleaning", "house cleaning"],
            "pest control": ["termite treatment", "rodent removal", "ant exterminator"],
            "moving": ["local movers", "long distance moving", "apartment moving"],
            "real estate": ["homes for sale", "sell my home", "real estate agent"],
            "church": ["church near me", "places of worship", "Sunday service"],
        }

        problems = problem_terms.get(base, [f"{base} near me", f"best {base}", f"affordable {base}"])

        broad: list[str] = []
        phrase: list[str] = []
        exact: list[str] = []
        negative: list[str] = ["diy", "how to", "jobs", "salary", "training", "course", "free"]

        for term in service_terms:
            broad.append(f"{loc_prefix}{term}")
            phrase.append(f'"{loc_prefix}{term}"')
            exact.append(f"[{loc_prefix}{term}]")

        for prob in problems:
            broad.append(f"{loc_prefix}{prob}")
            phrase.append(f'"{loc_prefix}{prob}"')

        broad.append(f"{loc_prefix}{base} near me")
        broad.append(f"best {loc_prefix}{base}")
        broad.append(f"affordable {loc_prefix}{base}")

        if loc:
            broad.append(f"best {base} {loc}")
            broad.append(f"{base} near {loc.split(',')[0].strip()}")

        phrase.append(f'"{loc_prefix}{base} near me"')
        phrase.append(f'"best {loc_prefix}{base} contractor"')
        exact.append(f"[{loc_prefix}{base} company]")
        exact.append(f"[{loc_prefix}{base} services]")

        negative_formatted = [f"-{kw}" for kw in negative]

        return {
            "broad": broad[:10],
            "phrase": phrase[:10],
            "exact": exact[:8],
            "negative": negative_formatted[:8],
        }

    @staticmethod
    def generate_pixel_html(pixel_type: str, tracking_id: str) -> str:
        pixel_type = pixel_type.lower().strip()

        if pixel_type == "google_ads":
            return (
                "<script async "
                'src="https://www.googletagmanager.com/gtag/js?id='
                f"{tracking_id}"
                '"></script>\n'
                "<script>\n"
                "  window.dataLayer = window.dataLayer || [];\n"
                '  function gtag(){dataLayer.push(arguments);}\n'
                f"  gtag('js', new Date());\n"
                f"  gtag('config', '{tracking_id}');\n"
                "</script>"
            )

        if pixel_type == "facebook_pixel":
            return (
                "<script>\n"
                "  !function(f,b,e,v,n,t,s)\n"
                "  {if(f.fbq)return;n=f.fbq=function(){n.callMethod?\n"
                "  n.callMethod.apply(n,arguments):n.queue.push(arguments)};\n"
                "  if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';\n"
                '  n.queue=[];t=b.createElement(e);t.async=!0;\n'
                "  t.src=v;s=b.getElementsByTagName(e)[0];\n"
                "  s.parentNode.insertBefore(t,s)}(window, document,'script',\n"
                "  'https://connect.facebook.net/en_US/fbevents.js');\n"
                f"  fbq('init', '{tracking_id}');\n"
                "  fbq('track', 'PageView');\n"
                "</script>\n"
                '<noscript><img height="1" width="1" style="display:none" '
                'src="https://www.facebook.com/tr?id='
                f"{tracking_id}"
                '&ev=PageView&noscript=1"'
                "/></noscript>"
            )

        if pixel_type == "linkedin_insight":
            return (
                "<script type=\"text/javascript\">\n"
                "  _linkedin_partner_id = \"" + tracking_id + "\";\n"
                "  window._linkedin_data_partner_ids = window._linkedin_data_partner_ids || [];\n"
                "  window._linkedin_data_partner_ids.push(_linkedin_partner_id);\n"
                "</script>\n"
                "<script type=\"text/javascript\">\n"
                "(function(l) {\n"
                "if (!l){window.lintrk = function(a,b){window.lintrk.q.push([a,b])};\n"
                "window.lintrk.q=[]}\n"
                "var s = document.getElementsByTagName('script')[0];\n"
                "var b = document.createElement('script');\n"
                "b.type = 'text/javascript';b.async = true;\n"
                "b.src = 'https://snap.licdn.com/li.lms-analytics/insight.min.js';\n"
                "s.parentNode.insertBefore(b, s);})(window.lintrk);\n"
                "</script>\n"
                '<noscript>\n'
                '<img height="1" width="1" style="display:none;" alt="" '
                'src="https://px.ads.linkedin.com/collect/?pid='
                f"{tracking_id}"
                '&fmt=gif" />\n'
                "</noscript>"
            )

        raise ValueError(f"Unsupported pixel type: {pixel_type}")

    @staticmethod
    def inject_pixels(landing_page_html: str, pixels: list[dict]) -> str:
        head_close = "</head>"
        head_pixels = ""

        for px in pixels:
            snippet = AdCopyGenerator.generate_pixel_html(
                px["type"], px["tracking_id"]
            )
            head_pixels += snippet + "\n"

        modified = landing_page_html.replace(
            head_close, head_pixels + "\n" + head_close
        )

        conversion_scripts = ""
        for px in pixels:
            ptype = px["type"].lower().strip()
            tid = px["tracking_id"]

            if ptype == "google_ads":
                conversion_scripts += (
                    f"\n                gtag('event', 'conversion', "
                    f"{{'send_to': '{tid}/lead'}});"
                )
            elif ptype == "facebook_pixel":
                conversion_scripts += (
                    f"\n                fbq('track', 'Lead');"
                )
            elif ptype == "linkedin_insight":
                conversion_scripts += (
                    f"\n                window.lintrk('track', {{'conversion_id': {tid}}});"
                )

        if conversion_scripts:
            success_redirect = re.search(
                r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]",
                modified,
            )
            if success_redirect:
                original_redirect = success_redirect.group(0)
                replacement = (
                    original_redirect.rstrip(";")
                    + conversion_scripts
                    + ";"
                )
                modified = modified.replace(original_redirect, replacement)

        return modified

    @staticmethod
    def generate_utm_url(
        base_url: str,
        source: str,
        medium: str = "cpc",
        campaign: str = "",
        content: str = "",
    ) -> str:
        parsed = urlparse(base_url)
        params = {"utm_source": source, "utm_medium": medium}
        if campaign:
            params["utm_campaign"] = campaign
        if content:
            params["utm_content"] = content

        existing_query = parsed.query
        if existing_query:
            existing_pairs = existing_query.split("&")
            existing_dict = {}
            for pair in existing_pairs:
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    existing_dict[k] = v
            existing_dict.update(params)
            new_query = urlencode(existing_dict)
        else:
            new_query = urlencode(params)

        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment,
            )
        )
