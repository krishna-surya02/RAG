"""The words of the synthetic policy wordings and endorsement sets.

Split from corpus_gen.py so the generator reads as a generator. Everything a
coverage question turns on -- the exclusions schedules, the flood
endorsements, the sub-limit schedules -- is written out by hand below. The
rest (definitions, per-peril conditions, the general and claims conditions)
is real-shaped boilerplate expanded from short specs, because a 60-page
wording is mostly boilerplate, and that boilerplate is exactly what crowds a
retriever in production.

Two flood endorsements carry the brief's point:

  HFL-23 (2023 set)  legal register. Excludes river/sea "Inundation", but gives
                     back "Pluvial accumulation" (rainfall surface water) up to
                     a sub-limit, after a $2,500 flood deductible.
  HFL-25 (2025 set)  plain English, written the way adjusters search ("flood
                     damage", "surface water from heavy rain"). Excludes all
                     of it unless Flood Plus is on the schedule.

So a search for "surface water from heavy rain" embeds closer to HFL-25 than
to HFL-23 -- which is how a 2024 loss ends up read against 2025 wording.
"""

# --- Household base wording (HH-PW) -------------------------------------------

HH_TITLE = "Household Policy Wording"

HH_FRONT = [
    ("About this policy", [
        "This policy wording, your schedule and any endorsements shown on your schedule form the contract of insurance between you and us. Please read them together. Your schedule tells you which sections you have chosen, the sums insured, the deductibles that apply and which endorsement set is attached to the current period of insurance.",
        "We will insure you against the loss, damage or liability described in this wording which happens during the period of insurance, provided you have paid the premium and kept to the terms and conditions. Words shown in bold type have the meanings given in the Definitions section.",
        "Endorsements change the cover in this wording. Where an endorsement and this wording say different things, the endorsement applies. The endorsement set that applies to a loss is the set attached to the period of insurance in which the loss happened, as shown on the schedule for that period.",
    ]),
    ("How to make a claim", [
        "Tell us as soon as possible about any incident that may lead to a claim. You can report a claim by telephone or online at any time. We will give you a claim reference, which you should quote in all correspondence.",
        "An adjuster will review your claim against the wording, schedule and endorsements in force on the date of the loss. Nothing said by our claims handlers or any automated service is a decision on your claim until it is confirmed in writing by an adjuster.",
    ]),
    ("Cancellation rights", [
        "You may cancel this policy within 14 days of receiving your documents or the start of the period of insurance, whichever is later, and we will refund the premium in full provided no claim has been made.",
        "After the cooling-off period you may cancel at any time by contacting us. We will refund the premium for the unexpired part of the period of insurance, less an administration charge of $35, provided no claim has been made in the current period.",
        "We may cancel this policy by giving you 14 days' notice in writing where there is a valid reason, such as non-payment of premium, a change in risk we cannot insure, or suspected fraud. If we cancel, cover ends at 00:01 on the date shown in our notice, and losses after that time are not insured.",
    ]),
    ("Complaints", [
        "We aim to provide a high standard of service. If you are not satisfied, please contact our customer relations team, quoting your policy number. We will acknowledge your complaint within five working days and aim to resolve it within eight weeks.",
        "If you remain dissatisfied, you may be able to refer your complaint to the insurance ombudsman or the regulator in your state. Making a complaint does not affect your legal rights.",
    ]),
]

HH_DEFINITIONS = [
    ("Accidental damage", "Sudden, unexpected and visible damage which has not been caused on purpose and which happens at a single identifiable time."),
    ("Bodily injury", "Physical injury to a person, including death or illness resulting from that injury."),
    ("Buildings", "The home, its fixtures and fittings, permanently installed swimming pools, tennis courts, drives, patios and terraces, walls, gates and fences, and domestic outbuildings, all within the premises."),
    ("Contents", "Household goods and personal property belonging to you or for which you are legally responsible, kept in the home, but not motor vehicles, caravans, trailers, watercraft, livestock, or any part of the buildings."),
    ("Deductible", "The amount you must pay towards each claim. The deductible is deducted from the assessed loss before any sub-limit or sum insured is applied. A deductible is not a sub-limit and does not reduce the sub-limit."),
    ("Endorsement", "A document that changes the cover provided by this wording. Endorsements are issued in sets; the set attached to a period of insurance is shown on the schedule for that period."),
    ("Endorsement set", "The group of endorsements, identified by a set reference and version, attached to a period of insurance at its start or renewal. The 2023 set (HEND-2023) attaches to periods starting on or after 1 April 2023 and before 1 April 2025. The 2025 set (HEND-2025) attaches to periods starting on or after 1 April 2025."),
    ("Escape of water", "Water suddenly escaping from a fixed water installation, domestic appliance, water tank, waterbed or aquarium within the home."),
    ("Excess", "See Deductible."),
    ("Fixed water installation", "Pipes, tanks, radiators, boilers and similar equipment permanently connected to the water supply or heating system of the home."),
    ("Heave", "Upward movement of the ground beneath the buildings as a result of the soil expanding."),
    ("Home", "The private dwelling at the address shown on the schedule, together with its garages and outbuildings, used for domestic purposes only."),
    ("Landslip", "Downward movement of sloping ground."),
    ("Money", "Current coins and bank notes, postal and money orders, gift tokens and pre-paid cards, held for social or domestic purposes."),
    ("Period of insurance", "The period shown on the schedule for which we have accepted your premium. Each renewal begins a new period of insurance with its own schedule and endorsement set."),
    ("Personal possessions", "Clothing, jewellery, watches, and other items normally worn or carried by you, which belong to you or for which you are legally responsible."),
    ("Policy limit", "The most we will pay for any one claim under a section, as shown on the schedule or in the limits table that forms part of this policy. A policy limit is distinct from both the deductible and any sub-limit."),
    ("Premises", "The home and the land belonging to it, shown on the title deeds, at the address shown on the schedule."),
    ("Schedule", "The document that gives details of you, the home, the sections in force, the sums insured, the deductibles, the endorsement set and the period of insurance."),
    ("Settlement", "Movement of the buildings caused by the compaction of the ground beneath them under their own weight, normally within ten years of construction."),
    ("Storm", "A period of violent weather with wind speeds of at least 55 miles per hour, or torrential rainfall of at least 25 millimetres per hour, or snow to a depth of at least 30 centimetres, or hail of such intensity that it causes damage to hard surfaces."),
    ("Sub-limit", "A limit within a section that caps what we pay for a particular type of loss, regardless of the policy limit for that section. Sub-limits are shown in the endorsement set's schedule of sub-limits. The deductible is applied first and does not erode the sub-limit."),
    ("Subsidence", "Downward movement of the ground beneath the buildings, other than by settlement."),
    ("Sum insured", "The amount shown on the schedule as the most we will pay under the relevant section."),
    ("Terrorism", "Any act of any person or organisation involving the causing or threatening of harm, or putting the public in fear, for political, religious, ideological or similar purposes."),
    ("Unoccupied", "Not lived in by you or a member of your family for more than 60 consecutive days."),
    ("Valuables", "Jewellery, watches, items of gold, silver and other precious metals, furs, pictures, works of art and collections of stamps, coins or medals."),
    ("We, us, our", "The insurer named on the schedule."),
    ("You, your", "The person or persons named on the schedule as policyholder and members of their family who normally live in the home."),
    ("Wear and tear", "Gradual deterioration through age or use, including rust, corrosion, rot and the gradual effects of light, weather and pollution."),
]

# (ref suffix, peril, covered text, list of "not covered" items)
HH_BUILDINGS_PERILS = [
    ("1.1", "Fire, lightning, explosion and earthquake", "Loss or damage to the buildings caused by fire, smoke, lightning, explosion or earthquake.",
     ["damage caused by smoke from gradual emission or from fireplaces used for their intended purpose", "scorching, melting or warping unless accompanied by flames", "damage while the home is unoccupied, where the fire was started deliberately"]),
    ("1.2", "Aircraft and falling objects", "Loss or damage to the buildings caused by aircraft or other flying devices, or items dropped from them.",
     ["damage caused by drones operated by you or a member of your family"]),
    ("1.3", "Riot, civil commotion and malicious acts", "Loss or damage to the buildings caused by riot, civil commotion, strikes, labour or political disturbances, or by malicious people.",
     ["damage caused by you, your family, or people lawfully in the home", "damage while the home is unoccupied", "damage caused by tenants or paying guests"]),
    ("1.4", "Impact", "Loss or damage to the buildings caused by impact by any vehicle, animal or falling tree or branch.",
     ["damage caused by pets or animals owned by you", "damage to gates and fences caused by vehicles driven by you", "the cost of removing fallen trees which have not damaged the buildings"]),
    ("1.5", "Storm", "Loss or damage to the buildings caused by storm, as defined. We will not consider a claim for storm unless there is evidence of a storm in your area on or around the date of the loss.",
     ["damage to gates, fences and hedges (see Exclusion HX-9)", "damage caused by rising groundwater (see Exclusion HX-17)", "damage which happens gradually, or is attributable to wear and tear", "water entering the home at ground level from outside -- this is governed by the flood endorsement in the endorsement set attached to the period of insurance (see Exclusion HX-3)"]),
    ("1.6", "Flood", "Cover for flood, inundation and surface water is not provided by this wording. It is provided, limited or excluded only by the flood endorsement within the endorsement set attached to the period of insurance in which the loss happened. See Exclusion HX-3.",
     ["any flood loss not given back by the flood endorsement in the applicable endorsement set"]),
    ("1.7", "Escape of water", "Loss or damage to the buildings caused by escape of water from any fixed water installation, domestic appliance, water tank, waterbed or aquarium, including the cost of removing and replacing any part of the buildings necessary to find the source of the escape (see Extension 1.14 Trace and access).",
     ["the cost of repairing the installation or appliance from which the water escaped, unless the damage was caused by frost", "damage caused by continuous or repeated seepage or leakage over a period of time (see Exclusion HX-1)", "damage caused by failure or lack of grouting or sealant", "damage while the home is unoccupied", "the deductible shown in the limits table for escape of water"]),
    ("1.8", "Escape of oil", "Loss or damage to the buildings caused by oil escaping from a fixed oil-fired heating installation.",
     ["damage caused by gradual leakage", "the cost of the oil lost"]),
    ("1.9", "Frost", "Loss or damage to the fixed water and heating installations caused by frost.",
     ["damage to installations in outbuildings or garages that are not heated", "damage while the home is unoccupied unless the heating was maintained at a minimum of 12 degrees Celsius (see Exclusion HX-8)"]),
    ("1.10", "Theft or attempted theft", "Loss or damage to the buildings caused by theft or attempted theft.",
     ["theft while the home is unoccupied", "theft by you, your family, or anyone lawfully in the home", "theft from any part of the home let to tenants or paying guests unless there was forcible and violent entry (see Exclusion HX-15)"]),
    ("1.11", "Subsidence, heave and landslip", "Loss or damage to the buildings caused by subsidence or heave of the site on which the buildings stand, or landslip.",
     ["damage to patios, terraces, drives, paths, walls, gates and fences unless the home is damaged at the same time by the same cause", "damage caused by settlement or by new structures bedding down (see Exclusion HX-4)", "damage caused by coastal or river erosion", "the subsidence deductible shown in the limits table"]),
    ("1.12", "Breakage of aerials and satellite dishes", "Loss or damage to the buildings caused by breakage or collapse of television or radio receiving aerials, satellite dishes and their fittings and masts.",
     ["damage to the aerial or dish itself"]),
    ("1.13", "Accidental damage to underground services", "Accidental damage to underground pipes, cables and drains which serve the home and which you are legally responsible for.",
     ["damage caused by wear and tear or gradual deterioration", "damage caused by tree roots growing over time"]),
    ("1.14", "Trace and access", "Following escape of water or oil, the cost of finding the source and repairing walls, floors or ceilings removed or damaged to find it, up to $5,000 in any period of insurance.",
     ["the cost of repairing the source of the escape itself"]),
    ("1.15", "Alternative accommodation", "If the home cannot be lived in because of damage insured under this section, the reasonable cost of comparable alternative accommodation for you and your pets, up to 20% of the buildings sum insured.",
     ["costs you would have paid if the damage had not happened", "costs after the home is fit to live in again"]),
]

HH_CONTENTS_ITEMS = [
    ("2.1", "Insured perils for contents", "Loss or damage to contents in the home caused by any of the perils listed in Section 1 (1.1 to 1.11), subject to the same exclusions and conditions as apply to those perils.",
     ["loss or damage to contents in the open, other than as provided by Extension 2.4", "flood loss to contents not given back by the flood endorsement in the applicable endorsement set"]),
    ("2.2", "Theft of contents", "Theft or attempted theft of contents from the home. Where the home is left unattended, cover is limited to theft following forcible and violent entry or exit.",
     ["theft of money above $500", "theft from unattended vehicles", "theft from communal areas of a building containing flats"]),
    ("2.3", "Valuables limit", "The most we will pay for valuables is shown in the schedule of sub-limits in the endorsement set attached to the period of insurance. Any single item worth more than $2,500 must be specified on the schedule.",
     ["any single unspecified valuable above $2,500"]),
    ("2.4", "Contents in the garden", "Loss or damage to contents in the open but within the premises, caused by any insured peril other than storm or flood, up to $1,000.",
     ["plants, trees and shrubs, other than as provided by Extension 2.7"]),
    ("2.5", "Frozen food", "Loss of or damage to food in a freezer caused by a rise or fall in temperature, up to $750.",
     ["deliberate disconnection of the power supply by the electricity provider"]),
    ("2.6", "Students' belongings", "Contents belonging to a member of your family who is a full-time student, while temporarily living away from home, up to $5,000.",
     ["theft unless there was forcible and violent entry"]),
    ("2.7", "Garden plants", "Loss or damage to plants, trees and shrubs in the garden caused by fire, lightning, explosion, theft or malicious acts, up to $1,000 in total and $250 for any one item.",
     ["damage caused by storm, frost, drought or animals"]),
    ("2.8", "Visitors' belongings", "Loss or damage to the personal belongings of visitors while in the home, caused by an insured peril, up to $1,000.",
     ["visitors' money or valuables"]),
    ("2.9", "Replacement locks", "The cost of replacing keys and locks to external doors and windows, a safe or an alarm if the keys are lost or stolen, up to $750.",
     []),
    ("2.10", "Money and credit cards", "Theft of money and loss arising from fraudulent use of credit cards following theft, up to $500.",
     ["loss where the card issuer has not been notified within 24 hours of discovery"]),
]

HH_LIABILITY_ITEMS = [
    ("3.1", "Liability as occupier", "We will pay amounts you become legally liable to pay as damages for bodily injury to any person, or loss of or damage to property, caused by an accident in or around the home during the period of insurance, up to the liability limit shown in the limits table, plus legal costs agreed by us. Any claim involving bodily injury is referred to an adjuster and must not be settled or admitted without our written consent.",
     ["bodily injury to you or your family", "liability arising from any business, trade or profession", "liability arising from owning or using motor vehicles, caravans or watercraft", "liability you have accepted under a contract"]),
    ("3.2", "Liability as owner of the buildings", "We will pay amounts you become legally liable to pay as owner of the buildings for bodily injury or property damage caused by an accident at the premises.",
     ["liability covered under Section 3.1"]),
    ("3.3", "Defective Premises Act liability", "Liability arising from any home you previously owned and occupied, for seven years after you sold it, provided you do not have other insurance for it.",
     ["the cost of repairing any defect"]),
    ("3.4", "Employers' liability for domestic staff", "Amounts you become legally liable to pay for bodily injury to people employed by you to work in the home, up to $5,000,000.",
     ["people employed in any business"]),
]

HH_PERSONAL_ITEMS = [
    ("4.1", "Personal possessions away from home", "Loss or damage to personal possessions anywhere in the world, if this section is shown on the schedule, up to the sum insured.",
     ["theft from unattended vehicles unless locked out of sight in a boot", "sports equipment while in use", "items sent by post or courier"]),
    ("4.2", "Pedal cycles", "Loss or damage to pedal cycles, if shown on the schedule, up to $1,000 per cycle.",
     ["theft unless locked to an immovable object or in a locked building", "damage to tyres unless the cycle is damaged at the same time"]),
]

# The household exclusions schedule. HX-3 hands flood to the endorsement set.
HH_EXCLUSIONS = [
    ("HX-1", "Wear and tear and gradual deterioration", "We do not cover loss or damage caused by wear and tear, gradual deterioration, or anything that happens gradually, including continuous or repeated seepage or leakage of water over a period of time, rot, rust, corrosion, mildew, or the action of light or atmosphere. This exclusion applies whether or not the deterioration was visible before the loss."),
    ("HX-2", "Defective design, materials and workmanship", "We do not cover the cost of putting right faulty or defective design, specification, materials or workmanship. We will cover resulting damage that is otherwise insured."),
    ("HX-3", "Flood, inundation and surface water", "Flood, inundation and surface water are governed solely by the flood endorsement in the endorsement set attached to the period of insurance in which the loss happened. Where that endorsement does not give cover, the loss is not insured under any section of this wording. The 2023 set's flood endorsement is HFL-23; the 2025 set's is HFL-25. The two are not interchangeable: the endorsement to apply is the one on the schedule for the period in which the loss date falls."),
    ("HX-4", "Settlement and new structures", "We do not cover loss or damage caused by settlement, shrinkage, or new structures bedding down, or by the normal movement of a building within ten years of construction."),
    ("HX-5", "Mould and fungus", "We do not cover loss or damage caused by mould, fungus or wet rot, except where it results directly from an escape of water that is itself insured, in which case cover is limited to the mould sub-limit in the endorsement set's schedule of sub-limits."),
    ("HX-6", "Pollution and contamination", "We do not cover loss or damage caused by pollution or contamination, unless caused by a sudden, identifiable, unintended and unexpected incident during the period of insurance."),
    ("HX-7", "Vermin and insects", "We do not cover loss or damage caused by insects, vermin, rodents, birds, or by any animal owned by or in the care of you or your family, other than as provided by Accidental Damage Extension HAD where it is attached."),
    ("HX-8", "Frost in unheated premises", "We do not cover frost damage to fixed water installations while the home is unoccupied unless the heating system was maintained at a minimum of 12 degrees Celsius day and night, or the water supply was turned off and the system drained."),
    ("HX-9", "Storm damage to gates, fences and hedges", "We do not cover loss or damage to gates, hedges and fences caused by storm, wind, rain, hail, snow or frost, or by flood in any form."),
    ("HX-10", "Deliberate acts", "We do not cover loss or damage deliberately caused by you, your family, or anyone acting on your behalf or with your knowledge."),
    ("HX-11", "War and terrorism", "We do not cover loss, damage, cost or liability caused by war, invasion, act of foreign enemy, hostilities, civil war, rebellion, revolution, insurrection, military or usurped power, or by terrorism."),
    ("HX-12", "Nuclear and radioactive contamination", "We do not cover loss, damage, cost or liability caused by ionising radiation or contamination by radioactivity from any nuclear fuel or nuclear waste, or the radioactive, toxic or explosive properties of any nuclear assembly."),
    ("HX-13", "Sonic bangs", "We do not cover loss or damage caused by pressure waves from aircraft or other flying devices travelling at or above the speed of sound."),
    ("HX-14", "Business use", "We do not cover loss, damage or liability arising from any trade, profession or business carried on at the home, other than clerical work, unless Home Business Endorsement HBU is attached and shown on the schedule."),
    ("HX-15", "Theft from let property", "We do not cover theft or attempted theft from any part of the home let or sub-let to tenants, lodgers or paying guests, unless there was forcible and violent entry or exit."),
    ("HX-16", "Electronic data and cyber events", "We do not cover loss or damage to any computer, electronic equipment or data caused by any computer virus, hacking, or the failure of any equipment to correctly recognise a date."),
    ("HX-17", "Groundwater and water table", "We do not cover loss or damage caused by water rising from the water table or groundwater percolating through floors or basement walls, whether or not following rainfall. This exclusion applies in addition to, and is not overridden by, any flood endorsement."),
    ("HX-18", "Pets", "We do not cover loss or damage caused by chewing, scratching, tearing or fouling by pets or domestic animals."),
    ("HX-19", "Unoccupancy", "We do not cover loss or damage caused by escape of water, escape of oil, theft, attempted theft, or malicious acts while the home is unoccupied, unless you have told us and we have agreed in writing."),
    ("HX-20", "Indirect loss", "We do not cover any loss or expense that is not directly caused by the event that led to your claim, such as loss of earnings, time taken to prepare a claim, or reduction in market value after repair."),
]

GENERAL_CONDITIONS = [
    ("Taking care", "You must take all reasonable steps to prevent loss, damage or injury and to keep the buildings and contents in a good state of repair."),
    ("Changes you must tell us about", "You must tell us as soon as possible about any change in circumstances that may affect the cover, including a change of address, building work, the home becoming unoccupied, or anyone living at the home being convicted of a criminal offence."),
    ("Other insurance", "If any loss, damage or liability covered by this policy is also covered by another policy, we will pay only our proportionate share."),
    ("Fraud", "If you or anyone acting on your behalf makes a fraudulent claim, we will not pay the claim, we may cancel the policy from the date of the fraudulent act, and we may recover any sums already paid."),
    ("Sums insured", "You must make sure the sums insured are adequate. If the buildings sum insured is less than the full cost of rebuilding, we may reduce any claim payment in proportion to the under-insurance."),
    ("Index-linking", "Sums insured are adjusted monthly in line with a recognised building cost or retail price index. We do not charge for this during the period of insurance, but renewal premiums are based on the adjusted sums insured."),
    ("Security", "Where your schedule requires approved locks or an alarm, they must be in use when the home is left unattended. If they are not, we will not pay for theft or attempted theft."),
    ("Unoccupancy", "If the home is to be unoccupied for more than 60 consecutive days, you must tell us before the 60th day. We may apply restrictions or extra conditions."),
    ("Building works", "You must tell us before starting any building work costing more than $25,000 or requiring planning permission or structural alteration."),
    ("Rights of third parties", "No one other than you and us has any right to enforce any term of this policy."),
    ("Law applying", "This policy is governed by the law of the state in which the home is situated, unless agreed otherwise in writing."),
    ("Sanctions", "We will not provide any cover or pay any claim to the extent that doing so would expose us to any sanction, prohibition or restriction under United Nations resolutions or the trade or economic sanctions, laws or regulations of any jurisdiction."),
    ("Premium payment", "If you pay by instalments and miss a payment, we will write to you. If the payment is not made within 14 days, we may cancel the policy, and cover will end on the date in our cancellation notice."),
    ("Renewal", "At each renewal we will send you a new schedule. A renewal begins a new period of insurance and may attach a different endorsement set. The endorsement set on a schedule applies to losses in that period only."),
    ("Data protection", "We use the information you give us to administer your policy and claims, to prevent fraud, and to meet our legal and regulatory obligations. Claim information may be shared with adjusters, loss assessors and service providers acting for us."),
    ("Interest", "We will not pay interest on any claim payment unless required by law."),
]

CLAIMS_CONDITIONS = [
    ("Notification", "You must tell us as soon as reasonably possible about any event that may lead to a claim, and in any event within 30 days. Theft, attempted theft, and malicious acts must be reported to the police within 24 hours."),
    ("Preventing further damage", "You must take all reasonable steps to prevent further loss or damage, including arranging emergency repairs. We will pay the reasonable cost of emergency repairs as part of an insured claim."),
    ("Evidence", "You must provide, at your own expense, any reasonable evidence we ask for, including receipts, valuations, photographs, estimates, and a written account of the incident."),
    ("Admission of liability", "You must not admit liability or offer or agree to settle any claim against you without our written permission."),
    ("Our rights", "We may take over and conduct in your name the defence or settlement of any claim, and pursue any claim for our own benefit against any other person."),
    ("Inspection", "We may appoint an adjuster or loss assessor to inspect the damage. You must give them reasonable access to the home and the damaged property."),
    ("Settlement of buildings claims", "We will pay the cost of repair or rebuilding to a standard equivalent to new, less the deductible, provided the work is carried out without unreasonable delay. If the work is not carried out, we will pay the reduction in market value, up to the cost of repair."),
    ("Settlement of contents claims", "We will replace or repair damaged contents as new, less the deductible, except clothing and household linen, for which we will deduct an amount for wear and tear."),
    ("Matching items", "We will not pay for replacing undamaged items forming part of a pair, set, suite or carpet where the damage is restricted to a clearly identifiable area."),
    ("Applying deductibles and sub-limits", "For each claim we first assess the loss, then deduct the applicable deductible, and then apply any applicable sub-limit and finally the policy limit. Where a section or endorsement sets its own deductible, that deductible applies in place of the standard deductible, not in addition to it."),
    ("Wording in force", "Every claim is assessed against this wording and the endorsement set shown on the schedule for the period of insurance in which the loss date falls. A later or earlier endorsement set does not apply to that loss, even where its wording is clearer."),
    ("Referral to an adjuster", "Coverage decisions are made only by an authorised adjuster. Any automated or assisted triage provides information only and does not accept or decline a claim."),
]

# --- Household endorsement sets ----------------------------------------------

HEND_2023 = {
    "title": "Household Endorsement Set 2023",
    "set_id": "HEND-2023",
    "intro": "This endorsement set attaches to household periods of insurance starting on or after 1 April 2023 and before 1 April 2025. It forms part of the policy only for a period of insurance whose schedule shows HEND-2023. Each endorsement below is version v2023.1.",
    "endorsements": [
        ("HFL-23", "Flood Endorsement (Inundation and Pluvial Accumulation)", [
            ("§1", "Definitions", "For the purposes of this endorsement: \"Inundation\" means the covering of normally dry land by water escaping from the normal confines of any natural or artificial watercourse, lake, reservoir, canal or dam, or by the sea or tidal water, including storm surge. \"Pluvial accumulation\" means water arising from precipitation which accumulates upon or flows across the surface of the ground before entering a drainage system or watercourse, and which enters the Home at or above ground level."),
            ("§2.1", "Exclusion of Inundation", "The Insurer shall not be liable in respect of loss or damage to the Buildings or Contents caused by or arising from Inundation, howsoever occurring, including where Inundation is concurrent with, follows, or is aggravated by storm or windstorm."),
            ("§2.2", "Pluvial accumulation: limited indemnity", "Notwithstanding Exclusion HX-3 of the Policy Wording, loss or damage to the Buildings or Contents caused directly by Pluvial accumulation entering the Home is indemnified, subject always to the Pluvial Accumulation Sub-limit stated in Endorsement HSL-23 and to the Flood Deductible stated in §2.3. This §2.2 does not apply where the Home is situated within a designated flood zone declared to the Insurer at inception of the period of insurance, nor to water entering by percolation from the water table, which remains excluded by HX-17."),
            ("§2.3", "Flood Deductible", "Each and every claim under §2.2 is subject to a Flood Deductible of $2,500, which applies in place of, and not in addition to, the Buildings or Contents deductible. The Flood Deductible is deducted from the assessed loss before the Pluvial Accumulation Sub-limit is applied, and does not erode that Sub-limit."),
            ("§3", "Conditions", "The Insured shall notify the Insurer of any loss under this endorsement within 30 days, shall take all reasonable measures to remove water and dry the Buildings, and shall retain damaged items for inspection where reasonably practicable."),
        ]),
        ("HAD-23", "Accidental Damage Extension", [
            ("§1", "Cover", "Where shown on the schedule, the Buildings and Contents sections are extended to include accidental damage, subject to the accidental damage deductible in the limits table."),
            ("§2", "Exclusions", "This extension does not cover damage caused by pets, by wear and tear, by any process of cleaning, dyeing or repair, or by electrical or mechanical breakdown."),
        ]),
        ("HBU-23", "Home Business Endorsement", [
            ("§1", "Cover", "Where shown on the schedule, Exclusion HX-14 does not apply to clerical business use of the Home, and business equipment is insured as Contents up to $10,000."),
        ]),
        ("HSL-23", "Schedule of Sub-limits 2023", [
            ("§1", "Sub-limits", "The following sub-limits apply to periods of insurance carrying HEND-2023: Pluvial Accumulation Sub-limit (HFL-23 §2.2): $15,000 per event. Mould sub-limit (HX-5): $10,000 per period of insurance. Valuables (Extension 2.3): $10,000 in total. Trace and access (Extension 1.14): $5,000. Each sub-limit applies after the applicable deductible has been deducted and is separate from the policy limit."),
        ]),
    ],
}

HEND_2025 = {
    "title": "Household Endorsement Set 2025",
    "set_id": "HEND-2025",
    "intro": "This endorsement set applies to household periods of insurance starting on or after 1 April 2025. It is part of your policy only for a period of insurance whose schedule shows HEND-2025. Each endorsement below is version v2025.1.",
    "endorsements": [
        ("HFL-25", "Flood, Surface Water and Storm Surge Endorsement", [
            ("§1", "What we mean by flood", "In this endorsement, flood means water from any source outside your home that covers normally dry ground. Flood includes rivers and streams bursting their banks, the sea and storm surge, and surface water from heavy rain or rainfall that collects on the ground or runs off roads, gardens and fields into your home. Flood damage from heavy rain is flood, even if no river or sea is involved."),
            ("§2.1", "Flood damage is not insured", "We do not insure loss or damage caused by flood, including surface water from heavy rainfall, rising rivers and storm surge, unless Flood Plus is shown on your schedule. This applies to your buildings and your contents, and whether or not a storm happened at the same time."),
            ("§2.2", "Flood Plus (optional)", "If your schedule shows Flood Plus, we insure flood damage to your buildings and contents up to the Flood Plus sub-limit in the 2025 Schedule of Sub-limits (HSL-25), after the flood deductible in §2.3. Flood Plus is not available where your home is in a designated flood zone."),
            ("§2.3", "Flood deductible", "Each flood claim under Flood Plus has a flood deductible of $5,000. It replaces your standard buildings or contents deductible, and it is taken off the assessed loss before the Flood Plus sub-limit is applied."),
            ("§3", "What you must do", "Tell us about flood damage within 30 days, move valuables upstairs if a flood warning is issued, and keep damaged items for our adjuster to inspect where you can."),
        ]),
        ("HAD-25", "Accidental Damage Extension", [
            ("§1", "Cover", "If your schedule shows accidental damage, your buildings and contents are also insured for accidental damage, after the accidental damage deductible in the limits table."),
            ("§2", "What is not insured", "Damage by pets, wear and tear, cleaning or repair, or electrical or mechanical breakdown."),
        ]),
        ("HBU-25", "Home Business Endorsement", [
            ("§1", "Cover", "If your schedule shows home business cover, Exclusion HX-14 does not apply to office work at home, and business equipment is insured as contents up to $15,000."),
        ]),
        ("HSL-25", "Schedule of Sub-limits 2025", [
            ("§1", "Sub-limits", "These sub-limits apply to periods of insurance carrying HEND-2025: Flood Plus sub-limit (HFL-25 §2.2): $25,000 per event. Mould sub-limit (HX-5): $7,500 per period of insurance. Valuables (Extension 2.3): $12,500 in total. Trace and access (Extension 1.14): $5,000. Each sub-limit applies after the deductible and is separate from the policy limit."),
        ]),
    ],
}

# --- Motor base wording (MT-PW) ----------------------------------------------

MT_TITLE = "Motor Policy Wording"

MT_FRONT = [
    ("About this policy", [
        "This policy wording, your schedule, your certificate of motor insurance and any endorsements shown on your schedule form your contract with us. Your schedule shows your level of cover (Comprehensive, or Third Party Fire and Theft), the drivers insured, the permitted use of the vehicle, the deductibles, and which endorsement set is attached to the current period of insurance.",
        "The endorsement set that applies to a loss is the set attached to the period of insurance in which the loss happened. Endorsements change this wording, and where they differ, the endorsement applies.",
    ]),
    ("Making a claim", [
        "Report any accident, theft or damage to us as soon as possible, and in any case within 7 days. Do not admit fault or offer payment to anyone involved.",
        "An adjuster will assess your claim against the wording and endorsements in force on the date of the loss. Information given by claims handlers or any automated service is not a decision on your claim.",
    ]),
    ("Cancellation", [
        "You may cancel within 14 days of receiving your documents for a full refund if no claim has been made. After that you may cancel at any time and receive a proportionate refund less an administration charge of $35, provided no claim has been made in the current period.",
        "We may cancel by giving 7 days' notice for a valid reason, including non-payment, a change in risk we cannot insure, or misrepresentation. Cover ends at the time stated in our notice.",
    ]),
]

MT_DEFINITIONS = [
    ("Comprehensive cover", "The level of cover that includes Sections 1 to 6 of this wording."),
    ("Third Party Fire and Theft (TPFT)", "The level of cover that includes Sections 1 and 2 only. TPFT does not include loss of or damage to your own vehicle other than by fire or theft."),
    ("Deductible", "The amount you must pay towards each claim, deducted from the assessed loss before any sub-limit or limit is applied. Different deductibles apply to different sections, as shown in the limits table."),
    ("Market value", "The cost of replacing your vehicle with one of the same make, model, age, mileage and condition immediately before the loss."),
    ("Insured driver", "Any person shown on your certificate of motor insurance as entitled to drive, who holds a valid licence for the vehicle and is not disqualified."),
    ("Your vehicle", "The motor vehicle shown on your schedule, including its standard accessories and spare parts."),
    ("Permitted use", "The purposes for which your vehicle may be used, as shown on your certificate of motor insurance."),
    ("Period of insurance", "The period shown on your schedule. Each renewal starts a new period of insurance, with its own schedule and endorsement set."),
    ("Endorsement set", "The group of endorsements attached to a period of insurance at its start or renewal. MEND-2023 attaches to periods starting on or after 1 April 2023 and before 1 April 2025; MEND-2025 to periods starting on or after 1 April 2025."),
    ("Sub-limit", "A cap on what we pay for a particular type of loss within a section, separate from the deductible and the policy limit."),
    ("Policy limit", "The most we will pay under a section for any one claim, shown in the limits table."),
    ("Total loss", "Where the cost of repair is more than 60% of the market value, or the vehicle is stolen and not recovered within 21 days."),
    ("Windscreen", "The windscreen, windows and sunroof glass of your vehicle, and the bodywork scratching resulting solely from their breakage."),
    ("Bodily injury", "Physical injury to a person, including death or illness resulting from that injury."),
    ("Accessories", "Parts or products specifically designed to be fitted to your vehicle, including in-car entertainment and navigation equipment permanently fitted."),
    ("Keys", "Keys, key cards, fobs and any other device used to unlock or start your vehicle."),
    ("Official flood warning", "A flood warning issued by a national or local government weather or environment agency for the area in which the vehicle is located."),
]

MT_SECTIONS = [
    ("1", "Liability to third parties", [
        ("1.1", "Bodily injury and property damage", "We will insure you for amounts you are legally liable to pay for bodily injury to any person and for damage to their property arising from an accident involving your vehicle, up to the limits in the limits table. All claims involving bodily injury are referred to an adjuster.",
         ["damage to your own vehicle", "bodily injury to the driver of your vehicle", "liability arising while your vehicle is used for racing, pace-making or on a track"]),
        ("1.2", "Level of cover", "Your schedule shows whether you have Comprehensive cover or Third Party Fire and Theft. Sections 3 to 6 apply only to Comprehensive cover.",
         ["own-damage claims under Third Party Fire and Theft, other than by fire or theft"]),
        ("1.3", "Legal costs", "Legal costs incurred with our written consent in defending any claim covered under this section, including representation at an inquest or in court.",
         ["fines or penalties imposed by a court"]),
    ]),
    ("2", "Fire and theft", [
        ("2.1", "Fire", "Loss of or damage to your vehicle caused by fire, lightning or explosion.",
         ["damage caused by electrical or mechanical faults that do not result in fire"]),
        ("2.2", "Theft", "Loss of or damage to your vehicle caused by theft or attempted theft, after the theft deductible in the limits table.",
         ["theft where the keys were left in or on the vehicle (see Exclusion MX-6)", "theft by deception, including by a person posing as a buyer", "loss of fuel"]),
    ]),
    ("3", "Accidental damage (Comprehensive only)", [
        ("3.1", "Own damage", "Loss of or damage to your vehicle caused by accident, malicious damage, storm, hail or flood, after the own-damage deductible in the limits table. We will repair your vehicle or, if it is a total loss, pay the market value.",
         ["wear and tear, mechanical, electrical or computer breakdown (see Exclusion MX-4)", "damage to tyres caused by braking, punctures, cuts or bursts", "depreciation or loss of value after repair", "flood damage where the flood endorsement in the applicable endorsement set excludes it"]),
        ("3.2", "Hail damage", "Hail damage to your vehicle is insured as own damage under 3.1. Where the endorsement set includes a hail endorsement, the hail deductible in that endorsement applies instead of the own-damage deductible.",
         ["damage caused gradually by weather"]),
        ("3.3", "Flood damage", "Flood damage to your vehicle is insured, limited or excluded by the flood endorsement in the endorsement set attached to the period of insurance in which the loss happened.",
         ["flood damage not insured by the applicable flood endorsement"]),
    ]),
    ("4", "Windscreen (Comprehensive only)", [
        ("4.1", "Windscreen and windows", "Breakage of the windscreen or windows of your vehicle, after the windscreen deductible, up to the windscreen sub-limit in the limits table. A claim under this section alone does not affect your no claims discount.",
         ["replacement of glass in convertible hoods unless made of glass", "breakage caused while the vehicle is being repaired"]),
    ]),
    ("5", "Personal accident (Comprehensive only)", [
        ("5.1", "Personal accident benefit", "If you or your spouse or partner suffer accidental bodily injury while travelling in or getting into or out of your vehicle, and within three months that injury solely causes death, loss of a limb, or permanent loss of sight, we will pay the personal accident sub-limit in the limits table.",
         ["injury caused by suicide or attempted suicide", "injury to any person over 75 years of age", "injury while the driver is under the influence of alcohol or drugs"]),
    ]),
    ("6", "Medical expenses (Comprehensive only)", [
        ("6.1", "Medical expenses", "Medical expenses for each person injured while travelling in your vehicle as a result of an accident, up to the medical expenses sub-limit in the limits table.",
         ["expenses recoverable from any other source"]),
    ]),
    ("7", "Extensions", [
        ("7.1", "Courtesy car", "While your vehicle is being repaired by our approved repairer following an insured claim, a courtesy car for up to 14 days.",
         ["where your vehicle is a total loss or stolen and not recovered"]),
        ("7.2", "Personal belongings", "Loss of or damage to personal belongings in your vehicle caused by accident, fire or theft, up to $500.",
         ["money, credit cards, tickets or documents", "goods carried for business"]),
        ("7.3", "Child car seats", "Replacement of child car seats fitted in your vehicle at the time of an accident, even if there is no visible damage.",
         []),
        ("7.4", "Replacement locks", "If the keys of your vehicle are lost or stolen, the cost of replacing the keys, locks and lock transmitter, up to $1,000, after the theft deductible.",
         ["where the keys were left in or on the vehicle"]),
    ]),
]

MT_EXCLUSIONS = [
    ("MX-1", "Unlicensed and unauthorised drivers", "We do not insure any loss, damage or liability while your vehicle is being driven by anyone not shown as an insured driver on your certificate, or by anyone who does not hold a valid licence or is disqualified from driving."),
    ("MX-2", "Alcohol and drugs", "We do not insure any loss of or damage to your vehicle while it is being driven by a person whose blood or breath alcohol level exceeds the legal limit, or who is unfit through drugs, or who fails to provide a specimen when required. Liability to third parties remains insured as the law requires, and we may recover our payment from you."),
    ("MX-3", "Racing and track use", "We do not insure any loss, damage or liability while your vehicle is being used for racing, competitions, rallies, speed trials, or on a racetrack or derestricted toll road."),
    ("MX-4", "Mechanical and electrical breakdown", "We do not insure mechanical, electrical, electronic or computer breakdowns, failures or breakages, or wear and tear, or depreciation."),
    ("MX-5", "Use not permitted", "We do not insure any loss, damage or liability while your vehicle is being used for a purpose not permitted by your certificate, including hire or reward, delivery or courier work, or ride-sharing unless declared."),
    ("MX-6", "Keys left in the vehicle", "We do not insure theft or attempted theft of your vehicle, or its contents, while the keys are left in, on or in the immediate vicinity of the vehicle, or while the vehicle is left unlocked or with any window or roof open."),
    ("MX-7", "Deliberate damage", "We do not insure damage caused deliberately by you or any insured driver, or by anyone acting with your knowledge."),
    ("MX-8", "War, terrorism and nuclear", "We do not insure loss, damage or liability caused by war, terrorism, riot outside the permitted territory, or nuclear and radioactive contamination, other than as required by law."),
    ("MX-9", "Confiscation", "We do not insure loss or damage arising from confiscation, requisition or destruction of your vehicle by or under the order of any government or public authority."),
    ("MX-10", "Wrong fuel", "We do not insure damage caused by putting the wrong fuel into your vehicle, unless the misfuelling endorsement is shown on your schedule."),
    ("MX-11", "Loss of use and indirect loss", "We do not insure loss of use of your vehicle, or any indirect loss such as loss of earnings or the cost of hiring another vehicle, other than as provided by Extension 7.1."),
    ("MX-12", "Territory", "We do not insure any loss, damage or liability outside the territorial limits shown on your schedule."),
    ("MX-13", "Pollution", "We do not insure liability for pollution or contamination unless caused by a sudden, identifiable and unexpected incident."),
    ("MX-14", "Carrying passengers for payment", "We do not insure any liability while your vehicle is carrying passengers for hire or reward, other than shared fuel costs."),
    ("MX-15", "Modifications not declared", "We do not insure any loss, damage or liability if your vehicle has been modified from the manufacturer's standard specification and you have not told us about the modification."),
    ("MX-16", "Drivers' conditions", "We do not insure any loss, damage or liability if a driver has a medical condition that should have been declared to the licensing authority and was not."),
]

MEND_2023 = {
    "title": "Motor Endorsement Set 2023",
    "set_id": "MEND-2023",
    "intro": "This endorsement set attaches to motor periods of insurance starting on or after 1 April 2023 and before 1 April 2025. It forms part of the policy only for a period of insurance whose schedule shows MEND-2023. Each endorsement below is version v2023.1.",
    "endorsements": [
        ("MFL-23", "Flood and Storm Water Damage to the Vehicle", [
            ("§1", "Scope", "This endorsement governs loss of or damage to the Vehicle caused by flood, storm water, or the ingress of water from any external source."),
            ("§2.1", "Indemnity for flood damage", "Loss of or damage to the Vehicle caused by flood or storm water is indemnified under Section 3 (Accidental damage) for Comprehensive cover only, subject to the own-damage deductible stated in the limits table."),
            ("§2.2", "Deliberate entry into water", "No indemnity is provided where the Vehicle is deliberately driven into water of a depth exceeding the manufacturer's stated wading depth, or into water which a reasonable driver would have recognised as unsafe."),
        ]),
        ("MWS-23", "Windscreen Endorsement", [
            ("§1", "Windscreen deductible", "The windscreen deductible is $100 per claim, and the windscreen sub-limit is $1,500 per claim, as stated in the limits table."),
        ]),
        ("MPA-23", "Personal Accident Endorsement", [
            ("§1", "Benefit", "The personal accident sub-limit under Section 5 is $25,000 per person. The medical expenses sub-limit under Section 6 is $2,000 per person."),
        ]),
    ],
}

MEND_2025 = {
    "title": "Motor Endorsement Set 2025",
    "set_id": "MEND-2025",
    "intro": "This endorsement set applies to motor periods of insurance starting on or after 1 April 2025. It is part of your policy only for a period of insurance whose schedule shows MEND-2025. Each endorsement below is version v2025.1.",
    "endorsements": [
        ("MFL-25", "Flood Damage to Your Car", [
            ("§1", "What this covers", "This endorsement sets out when flood damage to your car is insured, including water from rivers, the sea, heavy rain and flooded roads."),
            ("§2.1", "Flood damage insured", "We insure flood damage to your car under Section 3 if you have Comprehensive cover, after the flood deductible in §2.4."),
            ("§2.2", "Car left in a flood warning area", "We do not insure flood damage if your car was left parked in an area covered by an official flood warning that was issued more than 12 hours before the flood reached your car, and it was reasonably possible to move it."),
            ("§2.3", "Driving into flood water", "We do not insure damage caused by driving your car into flood water, including flooded roads and fords."),
            ("§2.4", "Flood deductible", "The flood deductible is $1,000 per claim. It replaces your own-damage deductible for flood claims."),
        ]),
        ("MHA-25", "Hail Endorsement", [
            ("§1", "Hail deductible", "Hail damage to your car has a hail deductible of $500, which replaces your own-damage deductible for hail claims. Paintless dent repair will be used where suitable."),
        ]),
        ("MWS-25", "Windscreen Endorsement", [
            ("§1", "Windscreen deductible", "The windscreen deductible is $150 per claim and the windscreen sub-limit is $1,500 per claim, as shown in the limits table."),
        ]),
        ("MPA-25", "Personal Accident Endorsement", [
            ("§1", "Benefit", "The personal accident sub-limit under Section 5 is $25,000 per person. The medical expenses sub-limit under Section 6 is $2,500 per person."),
        ]),
    ],
}
