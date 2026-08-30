import hashlib
from datetime import date
from enum import Enum

from beanie import Document, Link

from app.models.meeting import MeetingTranscript


class IndustryBucket(str, Enum):
    retail_ecommerce = "retail_ecommerce"
    health_medical = "health_medical"
    food_beverage = "food_beverage"
    education = "education"
    professional_b2b_services = "professional_b2b_services"
    logistics_distribution = "logistics_distribution"
    real_estate_construction = "real_estate_construction"
    hospitality_tourism = "hospitality_tourism"
    manufacturing_industrial = "manufacturing_industrial"
    finance_insurance = "finance_insurance"
    technology_software = "technology_software"
    beauty_wellness = "beauty_wellness"
    nonprofit = "nonprofit"
    agriculture = "agriculture"
    other = "other"


class BusinessModel(str, Enum):
    b2c = "b2c"
    b2b = "b2b"
    b2b2c = "b2b2c"
    nonprofit_donor_facing = "nonprofit_donor_facing"
    unclear = "unclear"


class BusinessSize(str, Enum):
    solo_micro = "solo_micro"
    small = "small"
    medium = "medium"
    large = "large"
    unclear = "unclear"


class InquiryVolume(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    very_high = "very_high"
    unclear = "unclear"


class DiscoveryChannel(str, Enum):
    linkedin = "linkedin"
    google_search_ads = "google_search_ads"
    peer_referral = "peer_referral"
    industry_event_conference = "industry_event_conference"
    webinar = "webinar"
    podcast = "podcast"
    social_media = "social_media"
    blog_magazine_article = "blog_magazine_article"
    word_of_mouth_group = "word_of_mouth_group"
    email_marketing = "email_marketing"
    other = "other"
    unclear = "unclear"


class Channel(str, Enum):
    whatsapp = "whatsapp"
    phone_calls = "phone_calls"
    email = "email"
    instagram = "instagram"
    facebook = "facebook"
    in_person_only = "in_person_only"
    website_form = "website_form"
    other = "other"
    unclear = "unclear"


class ClientNeed(str, Enum):
    multi_channel_support = "multi_channel_support"
    appointment_scheduling = "appointment_scheduling"
    crm_erp_pos_lms_integration = "crm_erp_pos_lms_integration"
    order_shipment_inventory_tracking = "order_shipment_inventory_tracking"
    extended_24_7_availability = "extended_24_7_availability"
    multi_language_support = "multi_language_support"
    human_escalation = "human_escalation"
    lead_qualification_sales_pipeline = "lead_qualification_sales_pipeline"
    business_knowledge = "business_knowledge"
    brand_tone_alignment = "brand_tone_alignment"
    quote_pricing_calculation = "quote_pricing_calculation"
    data_privacy_compliance = "data_privacy_compliance"
    emergency_urgent_triage = "emergency_urgent_triage"
    personalized_recommendations = "personalized_recommendations"
    other = "other"


class RegulatoryFlag(str, Enum):
    health_data = "health_data"
    financial_fiscal_data = "financial_fiscal_data"
    minors_student_data = "minors_student_data"
    none_apparent = "none_apparent"
    other = "other"


class PainPointUrgency(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    unclear = "unclear"


class EnhancedTranscript(Document):
    id: str
    meeting: Link[MeetingTranscript]
    # LLM-inferred classification
    sector: IndustryBucket
    sub_sector: str
    business_model: BusinessModel
    business_size: BusinessSize
    inquiry_volume: InquiryVolume
    discovery_channel: DiscoveryChannel
    current_channels: list[Channel]
    client_needs: list[ClientNeed]
    regulatory_flag: RegulatoryFlag
    pain_point_urgency: PainPointUrgency
    # Denormalized from the source MeetingTranscript at enrichment time. Both are
    # immutable source-of-truth fields (never LLM-inferred, never edited), so
    # copying them here lets every dashboard aggregation read a single collection
    # with no join. See app/aggregation/rows.py.
    closed: bool
    salesperson: str

    class Settings:
        name = "enhanced_transcripts"


def enrichment_key(name: str, email: str, phone_number: str, meeting_date: date) -> str:
    """Idempotency key for a (client, meeting) pair — used as EnhancedTranscript._id."""
    raw = "|".join(
        [name.strip().lower(), email.strip().lower(), phone_number.strip(), meeting_date.isoformat()]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
