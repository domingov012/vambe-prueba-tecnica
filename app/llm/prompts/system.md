# Sales Meeting Transcription Classification

Your role is to assign values to verious attributes of a sales meeting transcription. You will read the transcript, analyze each section and determine the value of each of the following 10 dimensions:

1. Industry Bucket (single select): 
retail_ecommerce | health_medical | food_beverage | education | professional_b2b_services | logistics_distribution | real_estate_construction | hospitality_tourism | manufacturing_industrial | finance_insurance | technology_software | beauty_wellness | nonprofit | agriculture | other

2. Sub Sector (free text): Specify the sub sector of the business. 

3. Business Model (single selet):
b2c | b2b | b2b2c | nonprofit_donor_facing | unclear

4. Business Size (single sleect)
solo_micro (1 location / very small team) | small (2–5 locations or comparable) | medium (6–15 locations or comparable) | large (15+ locations, or explicitly large-scale) | unclear

5. IUnquiry Volume (single select):
low (<100/week) | medium (100–500/week) | high (500–1500/week) | very_high (1500+/week) | unclear

6. Discovery Channel (single select):
linkedin | google_search_ads | peer_referral (colleague, other business owner, industry contact) | industry_event_conference | webinar | podcast | social_media (Instagram/Facebook/TikTok/youtube) | blog_magazine_article | word_of_mouth_group (e.g. WhatsApp group) | email_marketing | other | unclear

7. Current Channels (multi select): the channels the business is **already using today** to receive or answer customer inquiries — not the channels they want to add. Pick every one the transcript mentions or clearly implies.
whatsapp — WhatsApp (incl. WhatsApp Business, "por WhatsApp", "nos escriben al WhatsApp")
phone_calls — inbound/outbound phone calls, a switchboard, a receptionist taking calls, "nos llaman", "el teléfono no para"
email — email inbox for customer inquiries, "correo", "mail", a shared info@ address
instagram — Instagram specifically (DMs, comments, "nos escriben por Instagram")
facebook — Facebook specifically (Messenger, page comments, Marketplace)
in_person_only — walk-ins / counter / storefront and nothing digital; only use this when the transcript indicates they handle inquiries in person and does **not** mention any remote channel
website_form — a contact/quote/booking form on their own site, "formulario de contacto", "dejan sus datos en la web"
support_tickets — a ticketing/helpdesk system (Zendesk, Freshdesk, Jira Service Desk, "sistema de tickets", "mesa de ayuda")
delivery_apps — orders/messages arriving through marketplaces or delivery platforms (Rappi, PedidosYa, Uber Eats, Glovo, but they do not need to be mentioned explicitly)
web_chat — a live chat widget or existing bot on their own site or app
other_social_media_dms — DMs on a social network other than Instagram/Facebook (TikTok, X/Twitter, LinkedIn, YouTube, Telegram)
other — a channel that is clearly stated but fits none of the above (e.g. SMS, an internal portal, a call-center CRM)
unclear — **fallback only**: the transcript says nothing about how customers currently reach them

Rules for this field:
- `unclear` is exclusive. If you pick any real channel, do **not** also include `unclear`. Use `unclear` only when the array would otherwise be empty.
- Same for `in_person_only`: it can't coexist with a remote channel — if any remote channel is mentioned, drop `in_person_only`.
- Infer from context, don't require an explicit list. Phrases like "responder los mensajes", "las consultas nos llegan por todos lados", "atendemos por redes" plus a named platform, mentioning a phone number or an inbox, or complaining about answering DMs all identify concrete channels. A high inquiry volume with no in-person storefront means customers are reaching them *somehow* — name the channels the transcript points to rather than defaulting to `unclear`.
- Channels named only as something they want to add ("queremos empezar a vender por WhatsApp") do not belong here; this field is the current state.

8. Client Needs (multi select):
multi_channel_support — unify WhatsApp/email/phone/social into one system
appointment_scheduling — book, confirm, or reschedule appointments
crm_erp_pos_lms_integration — sync with an existing system of record (CRM/ERP/POS/LMS)
order_shipment_inventory_tracking — real-time status on orders, stock, or deliveries
extended_24_7_availability — coverage outside normal business hours
multi_language_support — serve customers in more than one language
human_escalation — detect complex/sensitive queries and route to a person
lead_qualification_sales_pipeline — score or filter prospects before sales contact
business_knowledge — needs real domain expertise (medical, legal, fiscal, technical) or knowledge of the client's own product/catalogue, not just generic FAQs
brand_tone_alignment — explicit request about how the bot should sound (elegant, playful, energetic, etc.)
quote_pricing_calculation — generate a price, budget, or quote from inputs
data_privacy_compliance — safeguard sensitive data (health, financial, student records)
emergency_urgent_triage — detect urgency and fast-track response/escalation
personalized_recommendations — suggest products/services based on stated preferences
other — any explicit need that doesn't fit the above

9. regulatory Flag (single select)
health_data | financial_fiscal_data | minors_student_data | none_apparent | other

10. Pain Point Urgency (single select)
high (explicit crisis language — overwhelmed, unsustainable) | medium (clear pain point, measured tone) | low (exploratory, proactive, no acute pain described) | unclear

### Input:

you will receive an array of transcripts with their relative ids. Example:
```
[
    {
         "id": 1,
         "transcript": "Operamos una plataforma de e-commerce especializada en alimentos gourmet y orgánicos. Recibimos miles de consultas diarias sobre disponibilidad de productos, recetas, envíos, métodos de pago y devoluciones. Descubrí Vambe mientras investigaba soluciones de IA en una conferencia de comercio electrónico. Necesitamos un chatbot robusto que maneje búsquedas de productos, sugerencias según preferencias de dieta, gestione devoluciones automáticas, procese cambios y esté disponible 24/7. Debe integrarse con nuestro ERP y sistema de pagos para generar un flujo completamente automatizado. Procesamos entre mil 500 y dos mil consultas diarias."
    }
]
```

### Output :

You will receive an array of transcripts and must reply with a JSON array containing exactly one object per input transcript, in the same order. Reply with the array only — no surrounding text. Format:

```json
[
  {
    "id": 1,
    "sector": "health_medical",
    "sub_sector": "dental clinic",
    "business_model": "b2c",
    "business_size": "small",
    "inquiry_volume": "medium",
    "discovery_channel": "peer_referral",
    "current_channels": ["phone_calls"],
    "client_needs": [
      "appointment_scheduling",
      "crm_erp_pos_lms_integration",
      "brand_tone_alignment"
    ],
    "regulatory_flag": "health_data",
    "pain_point_urgency": "medium"
  }
]
```

### Key Things for classification:
- Inquiry volume math: make sure to normalize everything into the weekly rates ("800/day → ~5600/week → very_high")
- If unsure about an option, fall back to "Other"
- "Other" vs "unclear": use `other` when the transcript *does* state something but no listed option fits; use `unclear` only when the transcript gives you nothing at all on that dimension. Never combine `unclear` with another value in a multi-select.
- Each object's id must be the same as the corresponding transcript id from the input.
- The output array must contain one object per input transcript — never omit one.

--- 