"""Which subject a source series belongs to, decided once and in one place.

The health slice (VisText-Health) is selected by this function, so the split is a written rule
rather than a judgement made by hand. Boundary cases are decided explicitly: pharmaceutical
*revenue* is industry finance, not a health measurement; healthcare *prices* are a
health-system measurement and count as health.

`domain(title)` returns one of:

    health      a measurement of disease, care, mortality, health expenditure or the health
                workforce -- something a public-health or clinical analyst would report
    life_sci    biology or the life sciences outside human health (agriculture, environment,
                species)
    other       everything else

Deliberately excluded from `health`: pharmaceutical and biotech company revenue, health
*insurance* market share, and medical-device *sales* -- those are measurements of firms, not
of health. They are listed explicitly rather than left to fall through, so the decision is
visible when the list is read.
"""
import re

_HEALTH = (
    # disease and its burden
    r'covid|coronavirus|sars|influenza|\bflu\b|measles|polio|dengue|ebola|malaria|cholera|'
    r'tubercul|hepatitis|hiv|aids|zika|outbreak|epidemic|pandemic|infect|virus|viral|'
    r'disease|cancer|tumou?r|carcinom|leukaem|diabet|asthma|stroke|cardiac|cardiovascular|'
    r'obes|dementia|alzheimer|malnutri|anaemi|anemia|'
    # who is affected, and how badly
    r'mortal|death rate|deaths|fatalit|morbidit|incidence|prevalence|case fatality|'
    r'\bcases\b|infections|hospitali[sz]|hospital|\bicu\b|intensive care|patient|inpatient|'
    r'outpatient|admission|'
    # care, prevention and the system that delivers them
    r'vaccin|immuni[sz]|screening|diagnos|treatment|therap|surgery|surgical|operation|'
    r'transplant|dialysis|angioplast|bypass|caesarean|'
    r'health care|healthcare|health system|health expenditure|health spending|'
    r'medical|medicine|clinic|physician|\bdoctor|\bnurse|midwi|dentist|pharmacist|'
    # population health outcomes
    r'life expectancy|infant mortality|birth rate|fertility rate|maternal|'
    r'smok|tobacco|alcohol consumption|drug use|opioid|overdose|suicide|mental health|'
    r'depression|obesity|body mass'
)

_LIFE_SCI = (
    r'\bspecies\b|biodiversit|wildlife|forest|deforest|fisher|aquacultur|crop|harvest|'
    r'livestock|cattle|poultry|agricultur|organic farming|\bgenome|genetic|biotech'
)

# Measurements of firms and markets that happen to sit in a health sector. Checked FIRST.
_NOT_HEALTH = (
    r'pharmaceutical (compan|firm|manufactur|market|industry|revenue|sales)|'
    r'generic pharmaceutical|drug compan|biotech compan|'
    r'health insurance (market|compan|provider)|'
    r'revenue of|sales of medical|medical device (market|sales|revenue)|'
    r'market share|share price|stock|'
    # Deal flow and capital in a health sector is a measurement of finance, not of health.
    r'mergers and acquisitions|transaction value|deal value|venture capital|'
    r'investment in|funding (round|raised)|market size|market value'
)


# A temporal qualifier is not the measured quantity. "Consumer preferred channels of brand
# communication DURING THE CORONAVIRUS PANDEMIC" is a marketing series that says "coronavirus";
# counting it as health would put a survey of advertising channels in the health slice.
_WHEN = (r'\b(?:during|amid|amidst|throughout|since|before|after|following|prior to)\b'
         r'[^,;]{0,60}?\b(?:pandemic|outbreak|crisis|epidemic|lockdown|quarantine)\b')


def domain(title):
    t = ' '.join(title.lower().split())
    t = re.sub(_WHEN, ' ', t)
    if re.search(_NOT_HEALTH, t):
        return 'other'
    if re.search(_HEALTH, t):
        return 'health'
    if re.search(_LIFE_SCI, t):
        return 'life_sci'
    return 'other'
