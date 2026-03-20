import streamlit as st
import folium
from streamlit_folium import st_folium
import os, sys
import pandas as pd
import numpy as np
from datetime import datetime
from fpdf import FPDF

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from carbon_simulator import CarbonCreditSimulator, UPLIFT_CITATIONS

RSR_CITATION = "IPCC 2019 Refinement Vol.4 Ch.4 Table 4.4"

# TerraPod technology uplifts — ISB/EAD/ICBA trial, Abu Dhabi, Nov 2024
# Reference: EAD/EQS/2024/1935 — Completion of Trial on ISB Technology
TERRAPOD_CITATION = (
    "ISB/EAD/ICBA Pre-Optimisation Phase (POP) Trial, Abu Dhabi, Nov 2024. "
    "Ref: EAD/EQS/2024/1935. Certified by Environment Agency Abu Dhabi."
)
TERRAPOD_UPLIFTS = {
    "seedball_outdoor": {
        "label"         : "TerraPod (outdoor deployment)",
        "germination"   : 0.82,    # 82% vs 6% traditional outdoor
        "survival_yr1"  : 0.92,    # 92% 60-day survival rate
        "annual_mortality_mult": 0.40,  # ~60% reduction in ongoing mortality
        "water_saving"  : 0.80,    # 80% less water than traditional
        "dbh_growth_mult": 1.20,   # estimated +20% DBH growth from biocarbon soil
    },
    "seedball_greenhouse": {
        "label"         : "TerraPod (greenhouse + outdoor)",
        "germination"   : 0.90,
        "survival_yr1"  : 0.93,
        "annual_mortality_mult": 0.35,
        "water_saving"  : 0.83,
        "dbh_growth_mult": 1.25,
    },
}

st.set_page_config(
    page_title="VCS Reforestation Carbon Estimator",
    page_icon="🌳",
    layout="wide",
)

def get_ecoregion(lat, lon):
    """
    Estimate WWF ecoregion from lat/lon.
    Checks specific biome polygons before falling back to latitude bands.
    Covers: deserts, mangroves, dry broadleaf, montane, flooded, mediterranean,
            tropical moist, tropical grasslands, temperate, boreal.
    """
    abs_lat = abs(lat)

    # ── 1. MANGROVES — coastal tropical/subtropical (check first) ──────────────
    # Only flag as mangrove if very close to coast (rough heuristic: low elevation
    # proxy = within known mangrove latitude bands near coastlines)
    # Key mangrove regions worldwide
    # Known mangrove hotspot bounding boxes (tighter zones = more coastal)
    mangrove_hotspots = [
        (4, 6, -3, 2),        # Ghana / Benin coast (tight coastal strip)
        (-1, 4, 8, 12),       # Cameroon / Niger Delta
        (-10, -5, 13, 16),    # Angola coast
        (-18, -14, 35, 40),   # Mozambique coast
        (20, 24, 88, 92),     # Sundarbans (Bangladesh/India)
        (10, 14, 99, 103),    # Thailand / Myanmar coast
        (1, 2, 103, 105),     # Singapore coast (tight)
        (-8, -4, 114, 118),   # Java / Borneo coast
        (-20, -16, -40, -38), # Brazil coast (Bahia)
        (8, 12, -85, -82),    # Costa Rica / Panama coast
        (10, 14, -87, -83),   # Honduras / Nicaragua coast
        (-22, -18, 115, 118), # NW Australia coast
    ]
    for lat_min, lat_max, lon_min, lon_max in mangrove_hotspots:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return "mangroves"

    # ── 2. FLOODED GRASSLANDS — specific regions ───────────────────────────────
    flooded_zones = [
        (-20, -15, 18, 26),   # Okavango / Zambezi floodplains
        (-18, -12, 26, 34),   # Bangweulu / Kafue flats
        (8, 14, 13, 17),      # Lake Chad basin
        (-20, -10, -65, -55), # Pantanal (Brazil/Bolivia)
        (25, 30, 85, 92),     # Brahmaputra floodplain
    ]
    for lat_min, lat_max, lon_min, lon_max in flooded_zones:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return "flooded grasslands and savannas"

    # ── 3. MONTANE GRASSLANDS ──────────────────────────────────────────────────
    montane_zones = [
        (-5, 5, 32, 37),      # East African highlands (Kenya, Uganda, Tanzania)
        (5, 15, 35, 42),      # Ethiopian highlands
        (-25, -10, -75, -65), # Andes highlands
        (25, 35, 80, 100),    # Himalayan foothills
        (-45, -35, -75, -65), # Patagonian Andes
    ]
    for lat_min, lat_max, lon_min, lon_max in montane_zones:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return "montane grasslands and shrublands"

    # ── 4. DESERTS & XERIC SHRUBLANDS ─────────────────────────────────────────
    desert_zones = [
        (12, 38, 32, 65),     # Arabian Peninsula / Middle East
        (15, 35, -18, 40),    # Sahara / North Africa
        (25, 45, 50, 70),     # Iranian / Central Asian deserts
        (-35, -15, 115, 145), # Australian outback
        (-45, -15, -75, -65), # Atacama / Patagonian desert
        (35, 50, 80, 120),    # Gobi / Central Asian steppe
        (25, 40, -120, -100), # Southwest USA (Mojave, Sonoran)
        (20, 30, -18, 20),    # Sahel transition
    ]
    for lat_min, lat_max, lon_min, lon_max in desert_zones:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return "deserts and xeric shrublands"

    # ── 5. TROPICAL DRY BROADLEAF ─────────────────────────────────────────────
    dry_broadleaf_zones = [
        (10, 25, 68, 88),     # Indian subcontinent dry zone
        (5, 18, -18, 15),     # West African dry zone (Guinea savanna)
        (-20, -5, 28, 38),    # East African dry broadleaf (Zambia, Mozambique, not Okavango)
        (-25, -10, -55, -40), # Brazilian dry forest (Caatinga)
        (8, 20, -90, -75),    # Central American dry forest
    ]
    for lat_min, lat_max, lon_min, lon_max in dry_broadleaf_zones:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return "tropical and subtropical dry broadleaf forests"

    # ── 6. BOREAL / TAIGA ─────────────────────────────────────────────────────
    if abs_lat > 60:
        return "boreal forests/taiga"
    if 55 <= abs_lat <= 60:
        if 60 <= lon <= 180 or -180 <= lon <= -90:
            return "boreal forests/taiga"

    # ── 7. TROPICAL MOIST & GRASSLANDS ────────────────────────────────────────
    if abs_lat <= 23.5:
        # African savanna / grassland belt
        if -20 <= lon <= 50 and 5 <= lat <= 20:
            return "tropical and subtropical grasslands"
        # South American cerrado / savanna
        if -65 <= lon <= -40 and -20 <= lat <= -5:
            return "tropical and subtropical grasslands"
        # SE Asia moist
        if 90 <= lon <= 180 and -10 <= lat <= 20:
            return "tropical and subtropical moist broadleaf forests"
        # Amazon / Congo / SE Asia default
        return "tropical and subtropical moist broadleaf forests"

    # ── 8. MEDITERRANEAN ──────────────────────────────────────────────────────
    if -10 <= lon <= 40 and 30 <= lat <= 45:
        return "mediterranean forests"
    if -125 <= lon <= -115 and 30 <= lat <= 40:
        return "mediterranean forests"
    if 115 <= lon <= 155 and -40 <= lat <= -30:
        return "mediterranean forests"
    if -75 <= lon <= -68 and -40 <= lat <= -30:   # central Chile
        return "mediterranean forests"

    # ── 9. TEMPERATE ──────────────────────────────────────────────────────────
    if 23.5 < abs_lat <= 60:
        if abs_lat >= 50 and (60 <= lon <= 180 or -180 <= lon <= -90):
            return "boreal forests/taiga"
        return "temperate broadleaf and mixed forests"

    return "temperate broadleaf and mixed forests"

def eco_to_region(eco):
    """Map WWF ecoregion name to allometric_equations.csv region value."""
    eco = eco.lower()
    if "boreal" in eco or "taiga" in eco:                return "boreal"
    elif "temperate" in eco:                              return "temperate"
    elif "mediterranean" in eco:                         return "mediterranean"
    elif "desert" in eco or "xeric" in eco:              return "desert"
    elif "montane" in eco or "alpine" in eco:            return "montane"
    elif "dry broadleaf" in eco:                         return "dry_tropical"
    elif "flooded" in eco:                               return "flooded"
    elif "grassland" in eco or "savanna" in eco:         return "tropical_grassland"
    elif "mangrove" in eco:                              return "mangrove"
    return "tropical"

def pdf_safe(text):
    """Strip non-latin-1 chars so fpdf helvetica does not crash."""
    replacements = {
        '\u2014': '-', '\u2013': '-', '\u2012': '-',
        '\u2018': "'", '\u2019': "'",
        '\u201c': '"', '\u201d': '"',
        '\u2026': '...', '\u00a0': ' ',
    }
    t = str(text)
    for bad, good in replacements.items():
        t = t.replace(bad, good)
    return t.encode('latin-1', errors='replace').decode('latin-1')

@st.cache_data(ttl=0)
def load_species_data():
    return pd.read_csv("allometric_equations.csv")

@st.cache_data(ttl=0)
def load_native_species():
    df = pd.read_csv("native_species.csv")
    df["ecoregion"] = df["ecoregion"].str.strip().str.lower()
    return df

@st.cache_resource(ttl=0)
def load_simulator():
    return CarbonCreditSimulator(
        data_path="allometric_equations.csv",
        globallometree_path="globallometree_usable.json",
    )

def generate_pdf_report(area_ha, species_mix, gross_credits, buffer_pct,
                         soil_gross, management, audit_trail, project_years):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "VCS Reforestation Carbon Credit Report", ln=True, align="C")
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 6, pdf_safe(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Methodology: Verra AR-ACM0003"), ln=True, align="C")
    pdf.ln(4)

    net_credits   = gross_credits * (1 - buffer_pct / 100.0)
    buffer_amount = gross_credits * buffer_pct / 100.0

    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "Carbon Credit Summary", ln=True)
    pdf.set_font("Arial", "", 11)
    pdf.cell(0, 7, pdf_safe(f"Project area:          {area_ha:,.0f} ha"), ln=True)
    pdf.cell(0, 7, pdf_safe(f"Crediting period:      {project_years} years"), ln=True)
    pdf.cell(0, 7, pdf_safe(f"Gross sequestration:   {gross_credits:,.0f} tCO2e"), ln=True)
    pdf.cell(0, 7, pdf_safe(f"  - Biomass:           {gross_credits - soil_gross:,.0f} tCO2e"), ln=True)
    pdf.cell(0, 7, pdf_safe(f"  - Soil:              {soil_gross:,.0f} tCO2e"), ln=True)
    pdf.cell(0, 7, pdf_safe(f"Buffer pool ({buffer_pct}%):     {buffer_amount:,.0f} tCO2e"), ln=True)
    pdf.cell(0, 7, pdf_safe(f"Net issuable VCUs:     {net_credits:,.0f} tCO2e"), ln=True)
    pdf.cell(0, 7, pdf_safe(f"VCS net (-20% disc.):  {net_credits * 0.8:,.0f} tCO2e"), ln=True)
    pdf.ln(3)

    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "Management Practices", ln=True)
    pdf.set_font("Arial", "", 10)
    if management.get("irrigation"):
        pdf.cell(0, 6, pdf_safe("  Irrigation: +15% DBH growth  [IPCC 2019 Vol.4 Ch.2 s2.3.2]"), ln=True)
    if management.get("nutrients"):
        pdf.cell(0, 6, pdf_safe("  Nutrients:  +10% DBH growth  [IPCC 2019]"), ln=True)
    if management.get("biochar"):
        pdf.cell(0, 6, pdf_safe("  Biochar:    +10% growth, +5 tC/ha soil  [Jeffery et al. 2017]"), ln=True)
    if not any([management.get("irrigation"), management.get("nutrients"), management.get("biochar")]):
        pdf.cell(0, 6, "No management uplifts applied (conservative baseline)", ln=True)
    pdf.ln(3)

    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "Species Mix & Equation Sources", ln=True)
    pdf.set_font("Arial", "", 10)
    for spec in species_mix:
        eq_info = audit_trail.get("species_equations", {}).get(spec["species_name"], {})
        tier    = eq_info.get("tier", "Unknown")
        cite    = pdf_safe(eq_info.get("citation", "")[:70])
        pdf.cell(0, 6, pdf_safe(
            f"  {spec['common_name']} ({spec['species_name']}): "
            f"{spec['pct']}%  |  {spec['density']} stems/ha  |  {tier}"
        ), ln=True)
        if cite:
            pdf.set_font("Arial", "I", 8)
            pdf.cell(0, 5, f"    Cite: {cite}", ln=True)
            pdf.set_font("Arial", "", 10)
    pdf.ln(3)

    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "VCS-Required Constants", ln=True)
    pdf.set_font("Arial", "", 10)
    constants = [
        ("Carbon fraction",    "0.47",  "IPCC 2006 Table 4.3"),
        ("CO2e factor",        "3.67",  "Molecular weight C:CO2"),
        ("AGB",                "Species-specific allometric equations", "GlobAllomeTree / project dataset"),
        ("BGB included",       "Yes - Total biomass = AGB x (1 + RSR)", "VCS AR-ACM0003 required carbon pool"),
        ("RSR tropical",       "0.235", "IPCC 2019 Table 4.4"),
        ("RSR temperate",      "0.192", "IPCC 2019 Table 4.4"),
        ("RSR boreal",         "0.390", "IPCC 2019 Table 4.4"),
        ("Uncertainty disc.",  "20%",   "VCS Uncertainty & Variance Policy v4"),
        ("Equation database",  "GlobAllomeTree + allometric_equations.csv", "Peer-reviewed"),
    ]
    for label, value, citation in constants:
        pdf.cell(0, 6, pdf_safe(f"  {label}: {value}  [{citation}]"), ln=True)
    pdf.ln(3)

    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "VVB Audit Trail", ln=True)
    pdf.set_font("Arial", "", 9)
    for key, val in audit_trail.items():
        if key in ("species_equations", "management_uplifts"):
            continue
        if isinstance(val, list):
            val = "; ".join(val)
        elif isinstance(val, dict):
            val = str(val)
        pdf.cell(0, 5, pdf_safe(f"  {key}: {str(val)[:90]}"), ln=True)

    pdf.ln(5)
    pdf.set_font("Arial", "I", 8)
    pdf.cell(0, 5, "Feasibility estimate only. VCUs require Verra validation and verification.", ln=True)

    return bytes(pdf.output(dest="S"))


# ── App ────────────────────────────────────────────────────────────────────────
st.title("🌳 VCS Reforestation Carbon Credit Estimator")
st.caption("Verra AR-ACM0003  |  GlobAllomeTree equations  |  IPCC 2019 RSR  |  VVB-defensible audit trail")

try:
    species_df = load_species_data()
    native_df  = load_native_species()
    sim        = load_simulator()
except Exception as e:
    st.error(f"Error loading data: {e}")
    st.stop()

if "lat" not in st.session_state:
    st.session_state.lat       = -3.4653
    st.session_state.lon       = -62.2153
    st.session_state.ecoregion = "tropical and subtropical moist broadleaf forests"

st.subheader("📍 Project Location")
m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=4)
folium.Marker(
    [st.session_state.lat, st.session_state.lon],
    popup="Project Location",
    icon=folium.Icon(color="green"),
).add_to(m)
map_data = st_folium(m, width=700, height=300)

if map_data and map_data.get("last_clicked"):
    st.session_state.lat       = map_data["last_clicked"]["lat"]
    st.session_state.lon       = map_data["last_clicked"]["lng"]
    st.session_state.ecoregion = get_ecoregion(st.session_state.lat, st.session_state.lon)

# ── Country-specific data panel ───────────────────────────────────────────────
COUNTRY_DATA = {
    "morocco": {"country": "Morocco", "country_code": "MA", "source": {"title": "Flore Endémique du Maroc — Sélection pour reforestation et renaturation", "author": "Pr. Abdelkader Taleb", "institution": "IAV Hassan II, Rabat", "year": 2026, "publisher": "Atelier Jardins", "reference": "Taleb, A. (2026). Flore Endémique du Maroc: Sélection pour reforestation et renaturation. Atelier Jardins S.A.S.", "based_on": "Flore pratique du Maroc, Fennane & al. (1999-2015)"}, "geographic_zones": {"Ms": "Maroc saharien", "As": "Atlas saharien", "AA": "Anti-Atlas", "HA": "Haut Atlas", "MA": "Moyen Atlas", "Mam": "Maroc atlantique moyen", "Man": "Maroc atlantique nord", "Op": "Plateaux du Maroc oriental", "Om": "Monts du Maroc oriental", "LM": "Littoral de la Méditerranée", "R": "Rif"}, "ecoregion_mapping": {"mediterranean forests": ["R", "MA", "HA", "Man", "LM", "Mam"], "deserts and xeric shrublands": ["Ms", "AA", "As"], "montane grasslands and shrublands": ["HA", "MA", "AA"], "temperate broadleaf and mixed forests": ["MA", "R", "HA"]}, "species": {"Quercus rotundifolia": {"common_fr": "Chêne vert", "common_en": "Holm Oak", "family": "Fagaceae", "endemic": false, "height_m": [5, 20], "width_m": [5, 12], "growth_rate": "slow", "dbh_growth_mm_yr": 5.5, "drought_resistance": "very_high", "salinity_tolerance": "low", "zones": ["all except Ms and Op"], "planting_density_m": "6x6", "stems_per_ha": 278, "water_need": "very_low", "associated_species": ["Pistacia lentiscus", "Arbutus unedo", "Pistacia atlantica"], "rooting": "deep_taproot", "soil": "poor calcareous", "uses": ["timber", "edible_acorn", "ornamental"], "carbon_notes": "Long-lived, high wood density, major carbon store in Moroccan forests"}, "Quercus suber": {"common_fr": "Chêne-liège", "common_en": "Cork Oak", "family": "Fagaceae", "endemic": false, "height_m": [6, 20], "width_m": [5, 12], "growth_rate": "slow_moderate", "dbh_growth_mm_yr": 7.0, "drought_resistance": "high", "salinity_tolerance": "low", "zones": ["LM", "R", "HA", "MA", "Man", "Om"], "planting_density_m": "7x7", "stems_per_ha": 204, "water_need": "moderate", "associated_species": ["Erica arborea", "Cistus ladanifer", "Arbutus unedo"], "rooting": "very_deep_taproot", "soil": "acidic poor (calcifuge)", "uses": ["cork", "timber", "edible_acorn"], "carbon_notes": "High commercial value, cork harvest does not kill tree, ideal for CCB projects"}, "Tetraclinis articulata": {"common_fr": "Thuya de Barbarie", "common_en": "Barbary Thuja", "family": "Cupressaceae", "endemic": true, "height_m": [6, 15], "width_m": [3, 6], "growth_rate": "slow", "dbh_growth_mm_yr": 5.5, "drought_resistance": "very_high", "salinity_tolerance": "low", "zones": ["AA", "HA", "MA", "Mam", "Man", "Op", "Om", "LM", "R"], "planting_density_m": "4x4", "stems_per_ha": 625, "water_need": "very_low", "associated_species": ["Juniperus phoenicea", "Pistacia atlantica", "Pistacia lentiscus"], "rooting": "deep_taproot", "soil": "calcareous poor", "uses": ["timber", "resin"], "carbon_notes": "Endemic to Morocco/Algeria. Key species for Moroccan dry forest restoration. High density planting possible."}, "Pistacia atlantica": {"common_fr": "Pistachier de l'Atlas", "common_en": "Atlas Pistachio", "family": "Anacardiaceae", "endemic": false, "height_m": [5, 20], "width_m": [5, 10], "growth_rate": "slow", "dbh_growth_mm_yr": 5.5, "drought_resistance": "very_high", "salinity_tolerance": "low", "zones": ["all Morocco"], "planting_density_m": "6x6", "stems_per_ha": 278, "water_need": "very_low", "associated_species": ["Juniperus phoenicea", "Tetraclinis articulata"], "rooting": "very_deep_taproot", "soil": "poor calcareous", "uses": ["edible_fruit", "timber", "ornamental"], "carbon_notes": "Extremely long-lived (1000+ years). Deep taproot. Nationwide distribution makes it ideal anchor species."}, "Cupressus atlantica": {"common_fr": "Cyprès de l'Atlas", "common_en": "Atlas Cypress", "family": "Cupressaceae", "endemic": true, "height_m": [10, 20], "width_m": [3, 6], "growth_rate": "slow_moderate", "dbh_growth_mm_yr": 7.0, "drought_resistance": "high", "salinity_tolerance": "low", "zones": ["HA"], "planting_density_m": "5x5", "stems_per_ha": 400, "water_need": "low", "associated_species": ["Juniperus phoenicea", "Tetraclinis articulata"], "rooting": "deep_taproot", "soil": "varied, not calcaire", "uses": ["timber", "windbreak"], "carbon_notes": "Critically endangered endemic. Reforestation projects in High Atlas eligible for biodiversity co-benefits (CCB)."}, "Sideroxylon spinosum": {"common_fr": "Arganier", "common_en": "Argan Tree", "family": "Sapotaceae", "endemic": true, "height_m": [3, 10], "width_m": [3, 7], "growth_rate": "slow", "dbh_growth_mm_yr": 5.5, "drought_resistance": "extreme", "salinity_tolerance": "low", "zones": ["Ms", "AA", "HA", "Mam", "LM"], "planting_density_m": "8x8", "stems_per_ha": 156, "water_need": "low", "associated_species": ["Ziziphus lotus", "Euphorbia resinifera"], "rooting": "exceptional_deep_5_10m", "soil": "arid calcareous", "uses": ["edible_oil", "cosmetic", "timber"], "carbon_notes": "UNESCO Biosphere Reserve species. Root system 5-10m depth documented. Exceptional drought tolerance. Strong co-benefit case for CCB."}, "Olea europaea subsp. oleaster": {"common_fr": "Olivier sauvage", "common_en": "Wild Olive", "family": "Oleaceae", "endemic": false, "height_m": [3, 10], "width_m": [3, 6], "growth_rate": "slow", "dbh_growth_mm_yr": 5.5, "drought_resistance": "very_high", "salinity_tolerance": "low", "zones": ["all except Saharan zones"], "planting_density_m": "6x6", "stems_per_ha": 278, "water_need": "very_low", "associated_species": ["Quercus ilex", "Pistacia lentiscus"], "rooting": "deep_taproot", "soil": "poor calcareous", "uses": ["rootstock_cultivated_olive", "timber", "ornamental"], "carbon_notes": "Extremely long-lived. Used as rootstock for cultivated olive. High cultural/biodiversity value in Morocco."}, "Juniperus phoenicea": {"common_fr": "Genévrier de Phénicie", "common_en": "Phoenician Juniper", "family": "Cupressaceae", "endemic": false, "height_m": [2, 8], "width_m": [2, 5], "growth_rate": "slow", "dbh_growth_mm_yr": 5.5, "drought_resistance": "very_high", "salinity_tolerance": "high", "zones": ["As", "AA", "HA", "MA", "Mam", "Man", "Om", "LM", "R"], "planting_density_m": "4x4", "stems_per_ha": 625, "water_need": "very_low", "associated_species": ["Pistacia lentiscus", "Pinus halepensis", "Tetraclinis articulata"], "rooting": "deep_taproot_lateral", "soil": "calcareous rocky", "uses": ["stabilisation", "timber", "windbreak"], "carbon_notes": "Excellent pioneer species for degraded land. Nationwide distribution. Supports soil stabilisation before climax species establish."}, "Argyrocytisus battandieri": {"common_fr": "Genêt de Battandier", "common_en": "Moroccan Broom", "family": "Fabaceae", "endemic": true, "height_m": [2, 4], "width_m": [2, 3], "growth_rate": "moderate", "dbh_growth_mm_yr": 8.5, "drought_resistance": "high", "salinity_tolerance": "none", "zones": ["MA", "R"], "planting_density_m": "2x2", "stems_per_ha": 2500, "water_need": "low", "nitrogen_fixing": true, "associated_species": ["Tetraclinis articulata", "Juniperus phoenicea"], "rooting": "deep_taproot", "soil": "sandy calcareous", "uses": ["ornamental", "melliferous"], "carbon_notes": "Endemic nitrogen-fixer. Improves soil for companion species. Key understorey component in Moroccan mixed forest restoration."}, "Pistacia lentiscus": {"common_fr": "Lentisque", "common_en": "Lentisk/Mastic", "family": "Anacardiaceae", "endemic": false, "height_m": [1, 5], "width_m": [2, 5], "growth_rate": "slow_moderate", "dbh_growth_mm_yr": 7.0, "drought_resistance": "very_high", "salinity_tolerance": "very_high", "zones": ["As", "AA", "HA", "MA", "Mam", "Man", "Om", "LM", "R"], "planting_density_m": "2x2", "stems_per_ha": 2500, "water_need": "low", "associated_species": ["Olea europaea", "Cistus monspeliensis", "Quercus ilex"], "rooting": "deep_taproot", "soil": "calcareous rocky poor", "uses": ["resin_mastic", "timber", "melliferous"], "carbon_notes": "Extremely salt and drought tolerant. Important understorey species. High planting density adds significant shrub-layer carbon."}}, "recommended_mixes": {"northern_morocco_rif": {"label": "Rif / Northern Atlantic (R, Man, LM)", "description": "Mixed oak-myrtle-lentisk forest typical of northern Morocco", "species_mix": [{"species": "Quercus suber", "pct": 30, "role": "canopy"}, {"species": "Quercus rotundifolia", "pct": 20, "role": "canopy"}, {"species": "Arbutus unedo", "pct": 15, "role": "sub-canopy"}, {"species": "Pistacia lentiscus", "pct": 20, "role": "understorey"}, {"species": "Myrtus communis", "pct": 15, "role": "understorey"}], "density_stems_ha": 800}, "atlas_mountains": {"label": "Middle/High Atlas (MA, HA)", "description": "Thuya-juniper-pistachio forest of the Atlas", "species_mix": [{"species": "Tetraclinis articulata", "pct": 35, "role": "canopy"}, {"species": "Juniperus phoenicea", "pct": 25, "role": "canopy"}, {"species": "Pistacia atlantica", "pct": 20, "role": "canopy"}, {"species": "Argyrocytisus battandieri", "pct": 20, "role": "understorey_N-fix"}], "density_stems_ha": 700}, "argan_zone": {"label": "Argan Zone (Souss, AA, SW Morocco)", "description": "Argan-euphorbia-ziziphus arid woodland", "species_mix": [{"species": "Sideroxylon spinosum", "pct": 50, "role": "canopy"}, {"species": "Pistacia atlantica", "pct": 25, "role": "canopy"}, {"species": "Olea europaea subsp. oleaster", "pct": 25, "role": "canopy"}], "density_stems_ha": 300}, "nationwide_pioneer": {"label": "Pioneer mix (degraded land, any zone)", "description": "Fast-establishing native mix for degraded/eroded land", "species_mix": [{"species": "Juniperus phoenicea", "pct": 30, "role": "pioneer"}, {"species": "Pistacia lentiscus", "pct": 30, "role": "pioneer"}, {"species": "Tetraclinis articulata", "pct": 25, "role": "canopy"}, {"species": "Argyrocytisus battandieri", "pct": 15, "role": "N-fixer"}], "density_stems_ha": 900}}, "biodiversity_notes": {"endemic_count": 6, "endemic_species": ["Cupressus atlantica", "Tetraclinis articulata", "Sideroxylon spinosum", "Argyrocytisus battandieri", "Chamaecytisus mollis", "Euphorbia resinifera"], "ccb_relevance": "Morocco has 6 endemic tree/shrub species in this study eligible for CCB biodiversity co-benefits", "iucn_notes": "Cupressus atlantica is critically endangered. Sideroxylon spinosum (Argan) is a UNESCO Biosphere Reserve species.", "pollinator_value": "15 of 16 species are melliferous — strong co-benefit case for pollinator habitat"}}
}

def detect_country(lat, lon):
    """Rough bounding box detection for country-specific data."""
    if 27.5 <= lat <= 35.9 and -13.2 <= lon <= -1.0:
        return "morocco"
    return None

detected_country = detect_country(st.session_state.lat, st.session_state.lon)

if detected_country and detected_country in COUNTRY_DATA:
    cd = COUNTRY_DATA[detected_country]
    with st.expander(f"📚 Site-Specific Data — {cd['country']} ({cd['source']['author']}, {cd['source']['year']})", expanded=True):
        src = cd["source"]
        st.info(
            f"**{src['title']}**  \n"
            f"{src['author']} · {src['institution']} · {src['year']}  \n"
            f"*{src['reference']}*"
        )

        col1, col2, col3 = st.columns(3)
        col1.metric("Native species documented", len(cd["species"]))
        col2.metric("Endemic species", cd["biodiversity_notes"]["endemic_count"])
        col3.metric("Melliferous species", "15/16")

        st.caption(cd["biodiversity_notes"]["ccb_relevance"])

        # Recommended species mixes
        st.subheader("Recommended Native Species Mixes")
        mix_names = list(cd["recommended_mixes"].keys())
        selected_mix_key = st.selectbox(
            "Select mix for your project zone",
            options=mix_names,
            format_func=lambda k: cd["recommended_mixes"][k]["label"],
            key="morocco_mix"
        )
        selected_mix = cd["recommended_mixes"][selected_mix_key]
        st.caption(selected_mix["description"])
        st.caption(f"Recommended density: {selected_mix['density_stems_ha']} stems/ha")

        mix_rows = []
        for item in selected_mix["species_mix"]:
            sp_data = cd["species"].get(item["species"], {})
            mix_rows.append({
                "Species": item["species"],
                "Common name": sp_data.get("common_en", ""),
                "Mix %": f"{item['pct']}%",
                "Role": item["role"],
                "Growth": sp_data.get("growth_rate", ""),
                "Drought": sp_data.get("drought_resistance", ""),
                "Endemic": "🌿" if sp_data.get("endemic") else "",
            })
        import pandas as pd
        st.table(pd.DataFrame(mix_rows))

        # Endemic species highlight
        st.subheader("Endemic & High-Value Species")
        for sp_name, sp_data in cd["species"].items():
            if sp_data.get("endemic") or sp_name in ["Sideroxylon spinosum", "Pistacia atlantica"]:
                with st.container():
                    c1, c2 = st.columns([1, 3])
                    c1.markdown(f"**{sp_data['common_en']}**  \n*{sp_name}*  \n{'🌿 Endemic' if sp_data.get('endemic') else ''}")
                    c2.markdown(
                        f"Height: {sp_data['height_m'][0]}-{sp_data['height_m'][1]}m · "
                        f"Growth: {sp_data['growth_rate']} · "
                        f"Drought: {sp_data['drought_resistance']}  \n"
                        f"{sp_data.get('carbon_notes','')}"
                    )

        st.caption(f"Source: {src['based_on']}")
    st.divider()

st.sidebar.header("Project Parameters")
st.sidebar.info(f"Ecoregion detected:\n**{st.session_state.ecoregion.title()}**")
detected_region = eco_to_region(st.session_state.ecoregion)

area_ha       = st.sidebar.number_input("Project area (ha)", min_value=1, value=100)
project_years = st.sidebar.slider("Crediting period (years)", 20, 60, 40)
mortality     = st.sidebar.number_input("Annual mortality (%)", 0, 20, 4) / 100.0
buffer_pct    = st.sidebar.slider("Buffer pool (%)", 10, 30, 20,
                                   help="VCS minimum 10%")

st.sidebar.subheader("Management Practices")
st.sidebar.caption("Fixed uplifts per peer-reviewed literature")

col1, col2 = st.sidebar.columns(2)
water_limited  = col1.checkbox("Water-limited?")
use_irrigation = col1.checkbox("Irrigation (+15%)", disabled=not water_limited,
                                help="IPCC 2019 Vol.4 Ch.2 s2.3.2")
nutrient_poor  = col2.checkbox("Nutrient-poor?")
use_nutrients  = col2.checkbox("Nutrients (+10%)", disabled=not nutrient_poor,
                                help="IPCC 2019")
use_biochar      = st.sidebar.checkbox("Biochar (+10% growth, +5 tC/ha soil)",
                                        help="Jeffery et al. 2017")
use_weed_control = st.sidebar.checkbox("Weed/invasive control", value=True)
use_fencing      = st.sidebar.checkbox("Fencing/exclosure")

st.sidebar.subheader("Managed Restoration Protocol")
st.sidebar.caption("ISB intensive management — documented protocols")
use_managed_restoration = st.sidebar.checkbox(
    "Intensive managed restoration",
    value=True,
    help=(
        "Applies phased mortality model based on ISB protocol:\n"
        "Yrs 1-2: 0% net mortality (immediate replanting)\n"
        "Yrs 3-4: 0.5% mortality (irrigation weaning)\n"
        "Yrs 5+:  1.5% mortality (established trees, MRV continues)\n"
        "Requires: soil preparation per hole, drip irrigation with moisture sensors, "
        "drone/satellite MRV, immediate dead-tree replacement."
    )
)
if use_managed_restoration:
    st.sidebar.success(
        "Active: 0% → 0.5% → 1.5% phased mortality\n"
        "Irrigation weaned off at Year 4\n"
        "Continuous drone & satellite MRV (40yr)"
    )
    mrvdiscount = 10  # continuous MRV justifies 10% vs 20%
else:
    mrvdiscount = 20

st.sidebar.subheader("TerraPod Technology")
st.sidebar.caption("ISB planting technology — EAD/ICBA certified trial, UAE Nov 2024")
terrapod_option = st.sidebar.selectbox(
    "Deployment method",
    options=["None (standard planting)",
             "TerraPod (outdoor)",
             "TerraPod (greenhouse + outdoor)"],
    index=1,
)
terrapod_key = {
    "None (standard planting)"        : None,
    "TerraPod (outdoor)"              : "seedball_outdoor",
    "TerraPod (greenhouse + outdoor)" : "seedball_greenhouse",
}[terrapod_option]
st.session_state["terrapod_key_for_benchmark"] = terrapod_key or "seedball_outdoor"

if terrapod_key:
    tp = TERRAPOD_UPLIFTS[terrapod_key]
    st.sidebar.info(
        f"**{tp['label']}**\n\n"
        f"- Germination: {tp['germination']*100:.0f}%\n"
        f"- Year-1 survival: {tp['survival_yr1']*100:.0f}%\n"
        f"- Water saving: {tp['water_saving']*100:.0f}%\n"
        f"- Growth uplift: +{(tp['dbh_growth_mult']-1)*100:.0f}% DBH\n"
        f"- Mortality reduction: {(1-tp['annual_mortality_mult'])*100:.0f}%\n\n"
        f"*Cite: {TERRAPOD_CITATION[:80]}...*"
    )

active_uplifts = []
if use_irrigation: active_uplifts.append("Irrigation +15%")
if use_nutrients:  active_uplifts.append("Nutrients +10%")
if use_biochar:    active_uplifts.append("Biochar +10%/+5 tC/ha")
if active_uplifts:
    st.sidebar.success(f"Active: {', '.join(active_uplifts)}")

management = {
    "irrigation"  : use_irrigation,
    "nutrients"   : use_nutrients,
    "biochar"     : use_biochar,
    "weed_control": use_weed_control,
    "fencing"     : use_fencing,
    "terrapod"    : terrapod_key,
}

st.sidebar.subheader("Species")
ecoregion_key  = st.session_state.ecoregion.lower().strip()
native_species = native_df[native_df["ecoregion"] == ecoregion_key]["species_name"].tolist()

species_by_region = {}
for region_val in species_df["region"].dropna().unique():
    rdf = species_df[species_df["region"] == region_val]
    display = []
    for _, row in rdf.iterrows():
        common = row.get("common_name", row["species_name"])
        if pd.isna(common): common = row["species_name"]
        display.append(f"{common} ({row['species_name']})")
    species_by_region[region_val] = sorted(set(display))

full_list     = species_by_region.get(detected_region, [])
filtered_list = []
for disp in full_list:
    try:
        sp_name = disp.split("(")[1].rstrip(")")
        if sp_name in native_species:
            filtered_list.append(disp)
    except:
        continue

if not filtered_list:
    st.sidebar.warning(
        f"No native species with allometric data found for **{st.session_state.ecoregion.title()}**. "
        "Showing all regional species — note these may not be confirmed native to your exact location. "
        "Consider uploading a custom species CSV with locally verified native species."
    )
    filtered_list = full_list or ["Tectona grandis (Tectona grandis)"]
else:
    st.sidebar.success(
        f"Showing {len(filtered_list)} confirmed native species for {st.session_state.ecoregion.title()}."
    )

species_options = filtered_list

if "species_list" not in st.session_state:
    st.session_state.species_list = [{"display": species_options[0], "pct": 100, "density": 1100}]

for i, spec in enumerate(st.session_state.species_list):
    cols = st.sidebar.columns([3, 1, 1])
    spec["display"]  = cols[0].selectbox(f"Species {i+1}", species_options,
                                          index=min(i, len(species_options)-1), key=f"sp_{i}")
    spec["pct"]      = cols[1].number_input(f"% {i+1}", 0, 100, spec["pct"], key=f"pct_{i}")
    spec["density"]  = cols[2].number_input(f"Dens {i+1}", 100, 5000, spec["density"], key=f"den_{i}")

c1, c2 = st.sidebar.columns(2)
if c1.button("+ Add"):
    if len(st.session_state.species_list) < 5:
        st.session_state.species_list.append({"display": species_options[0], "pct": 0, "density": 1100})
if c2.button("- Remove"):
    if len(st.session_state.species_list) > 1:
        st.session_state.species_list.pop()

total_pct = sum(s["pct"] for s in st.session_state.species_list)
if total_pct != 100:
    st.sidebar.warning(f"Mix = {total_pct}%. Must equal 100%.")

# ── Regional estimate summary card (pre-computed mixed forest averages) ──────
REGIONAL_BENCHMARKS_PRECOMPUTED = {
    "boreal forests/taiga": {
        "low_gross": 16899,
        "medium_gross": 38562,
        "high_gross": 70696,
        "low_species": [
            "Larix occidentalis",
            "Picea sitchensis",
            "Pinus contorta",
            "Picea glauca",
            "Picea mariana"
        ],
        "high_species": [
            "Betula papyrifera",
            "Populus tremuloides",
            "Abies lasiocarpa",
            "Betula pendula",
            "Picea abies"
        ],
        "all_species": [
            "Larix occidentalis",
            "Picea sitchensis",
            "Pinus contorta",
            "Picea glauca",
            "Picea mariana",
            "Larix decidua",
            "Larix kaempferi",
            "Larix laricina",
            "Larix sibirica",
            "Abies balsamea",
            "Pinus banksiana",
            "Betula papyrifera",
            "Populus tremuloides",
            "Abies lasiocarpa",
            "Betula pendula",
            "Picea abies"
        ],
        "n_species": 16,
        "density": 1000,
        "region": "boreal"
    },
    "deserts and xeric shrublands": {
        "low_gross": 4600,
        "medium_gross": 10599,
        "high_gross": 15483,
        "low_species": [
            "Balanites aegyptiaca",
            "Acacia ehrenbergiana",
            "Acacia tortilis",
            "Ziziphus mauritiana",
            "Ziziphus spina-christi"
        ],
        "high_species": [
            "Retama raetam",
            "Haloxylon ammodendron",
            "Prosopis cineraria",
            "Prosopis juliflora",
            "Acacia nilotica"
        ],
        "all_species": [
            "Balanites aegyptiaca",
            "Acacia ehrenbergiana",
            "Acacia tortilis",
            "Ziziphus mauritiana",
            "Ziziphus spina-christi",
            "Faidherbia albida",
            "Maerua crassifolia",
            "Calligonum comosum",
            "Tamarix aphylla",
            "Haloxylon persicum",
            "Retama raetam",
            "Haloxylon ammodendron",
            "Prosopis cineraria",
            "Prosopis juliflora",
            "Acacia nilotica"
        ],
        "n_species": 15,
        "density": 700,
        "region": "desert"
    },
    "flooded grasslands and savannas": {
        "low_gross": 65697,
        "medium_gross": 108121,
        "high_gross": 186773,
        "low_species": [
            "Populus nigra"
        ],
        "high_species": [
            "Melaleuca argentea"
        ],
        "all_species": [
            "Populus nigra",
            "Acacia stenophylla",
            "Melaleuca argentea"
        ],
        "n_species": 3,
        "density": 900,
        "region": "flooded"
    },
    "mangroves": {
        "low_gross": 36908,
        "medium_gross": 96083,
        "high_gross": 143915,
        "low_species": [
            "Sonneratia alba"
        ],
        "high_species": [
            "Ceriops tagal"
        ],
        "all_species": [
            "Sonneratia alba",
            "Avicennia germinans",
            "Bruguiera gymnorrhiza",
            "Ceriops tagal"
        ],
        "n_species": 4,
        "density": 1200,
        "region": "mangrove"
    },
    "mediterranean forests": {
        "low_gross": 16881,
        "medium_gross": 66797,
        "high_gross": 131997,
        "low_species": [
            "Fraxinus ornus",
            "Juniperus thurifera",
            "Pinus halepensis",
            "Pinus pinea",
            "Pinus pinaster"
        ],
        "high_species": [
            "Quercus ilex",
            "Quercus pubescens",
            "Quercus suber",
            "Cedrus atlantica",
            "Cedrus libani"
        ],
        "all_species": [
            "Fraxinus ornus",
            "Juniperus thurifera",
            "Pinus halepensis",
            "Pinus pinea",
            "Pinus pinaster",
            "Ceratonia siliqua",
            "Pistacia lentiscus",
            "Arbutus unedo",
            "Abies pinsapo",
            "Quercus cerris",
            "Quercus faginea",
            "Quercus ilex",
            "Quercus pubescens",
            "Quercus suber",
            "Cedrus atlantica",
            "Cedrus libani"
        ],
        "n_species": 16,
        "density": 900,
        "region": "mediterranean"
    },
    "montane grasslands and shrublands": {
        "low_gross": 9417,
        "medium_gross": 16047,
        "high_gross": 20831,
        "low_species": [
            "Prunus africana",
            "Alnus acuminata",
            "Rhododendron arboreum",
            "Juniperus procera",
            "Olea europaea subsp. cuspidata"
        ],
        "high_species": [
            "Gynoxys caracasana",
            "Polylepis racemosa",
            "Hypericum lanceolatum",
            "Erica arborea",
            "Abies spectabilis"
        ],
        "all_species": [
            "Prunus africana",
            "Alnus acuminata",
            "Rhododendron arboreum",
            "Juniperus procera",
            "Olea europaea subsp. cuspidata",
            "Podocarpus glomeratus",
            "Hagenia abyssinica",
            "Rapanea melanophloeos",
            "Polylepis australis",
            "Escallonia resinosa",
            "Gynoxys caracasana",
            "Polylepis racemosa",
            "Hypericum lanceolatum",
            "Erica arborea",
            "Abies spectabilis"
        ],
        "n_species": 15,
        "density": 900,
        "region": "montane"
    },
    "temperate broadleaf and mixed forests": {
        "low_gross": 26874,
        "medium_gross": 66100,
        "high_gross": 117981,
        "low_species": [
            "Castanea sativa",
            "Juglans nigra",
            "Prunus avium",
            "Prunus serotina",
            "Alnus incana",
            "Juglans regia",
            "Platanus occidentalis",
            "Liquidambar styraciflua"
        ],
        "high_species": [
            "Tilia cordata",
            "Ulmus glabra",
            "Ulmus laevis",
            "Fraxinus excelsior",
            "Quercus petraea",
            "Quercus robur",
            "Fagus sylvatica",
            "Robinia pseudoacacia"
        ],
        "all_species": [
            "Castanea sativa",
            "Juglans nigra",
            "Prunus avium",
            "Prunus serotina",
            "Alnus incana",
            "Juglans regia",
            "Platanus occidentalis",
            "Liquidambar styraciflua",
            "Platanus orientalis",
            "Celtis australis",
            "Celtis occidentalis",
            "Salix alba",
            "Corylus avellana",
            "Magnolia grandiflora",
            "Salix fragilis",
            "Alnus glutinosa",
            "Tilia cordata",
            "Ulmus glabra",
            "Ulmus laevis",
            "Fraxinus excelsior",
            "Quercus petraea",
            "Quercus robur",
            "Fagus sylvatica",
            "Robinia pseudoacacia"
        ],
        "n_species": 24,
        "density": 1000,
        "region": "temperate"
    },
    "tropical and subtropical dry broadleaf forests": {
        "low_gross": 21916,
        "medium_gross": 79294,
        "high_gross": 149665,
        "low_species": [
            "Acacia catechu",
            "Brachystegia spiciformis"
        ],
        "high_species": [
            "Afzelia quanzensis",
            "Terminalia arjuna"
        ],
        "all_species": [
            "Acacia catechu",
            "Brachystegia spiciformis",
            "Julbernardia paniculata",
            "Colophospermum mopane",
            "Pterocarpus angolensis",
            "Terminalia sericea",
            "Afzelia quanzensis",
            "Terminalia arjuna"
        ],
        "n_species": 8,
        "density": 900,
        "region": "dry_tropical"
    },
    "tropical and subtropical grasslands": {
        "low_gross": 5186,
        "medium_gross": 34874,
        "high_gross": 63540,
        "low_species": [
            "Acacia senegal"
        ],
        "high_species": [
            "Combretum molle"
        ],
        "all_species": [
            "Acacia senegal",
            "Terminalia macroptera",
            "Sclerocarya birrea",
            "Vitellaria paradoxa",
            "Combretum molle"
        ],
        "n_species": 5,
        "density": 700,
        "region": "tropical_grassland"
    },
    "tropical and subtropical moist broadleaf forests": {
        "low_gross": 66234,
        "medium_gross": 153834,
        "high_gross": 262139,
        "low_species": [
            "Dalbergia latifolia",
            "Dalbergia melanoxylon",
            "Dalbergia sissoo",
            "Albizia adianthifolia",
            "Cordia alliodora",
            "Nephelium lappaceum",
            "Archidendron pauciflorum",
            "Dipterocarpus indicus",
            "Dipterocarpus alatus",
            "Spathodea campanulata",
            "Vitex doniana",
            "Acacia mearnsii",
            "Moringa oleifera",
            "Anadenanthera colubrina",
            "Brownea macrophylla",
            "Schinus molle",
            "Mimusops elengi",
            "Buchenavia tetraphylla",
            "Dracontomelon dao",
            "Milicia excelsa"
        ],
        "high_species": [
            "Guarea guidonia",
            "Hymenaea courbaril",
            "Inga edulis",
            "Inga feuilleei",
            "Tabebuia rosea",
            "Dipterocarpus costatus",
            "Dipterocarpus grandiflorus",
            "Dipterocarpus turbinatus",
            "Elaeocarpus angustifolius",
            "Araucaria cunninghamii",
            "Araucaria heterophylla",
            "Araucaria hunsteinii",
            "Nauclea diderrichii",
            "Terminalia superba",
            "Cedrela odorata",
            "Paulownia tomentosa",
            "Gmelina arborea",
            "Grevillea robusta",
            "Tectona grandis",
            "Terminalia ivorensis"
        ],
        "all_species": [
            "Dalbergia latifolia",
            "Dalbergia melanoxylon",
            "Dalbergia sissoo",
            "Albizia adianthifolia",
            "Cordia alliodora",
            "Nephelium lappaceum",
            "Archidendron pauciflorum",
            "Dipterocarpus indicus",
            "Dipterocarpus alatus",
            "Spathodea campanulata",
            "Vitex doniana",
            "Acacia mearnsii",
            "Moringa oleifera",
            "Anadenanthera colubrina",
            "Brownea macrophylla",
            "Schinus molle",
            "Mimusops elengi",
            "Buchenavia tetraphylla",
            "Dracontomelon dao",
            "Milicia excelsa",
            "Toona ciliata",
            "Lovoa trichilioides",
            "Triplochiton scleroxylon",
            "Jacaranda mimosifolia",
            "Lophira alata",
            "Manilkara zapota",
            "Manilkara bidentata",
            "Manilkara huberi",
            "Khaya anthotheca",
            "Khaya ivorensis",
            "Khaya senegalensis",
            "Agathis australis",
            "Swietenia macrophylla",
            "Swietenia mahagoni",
            "Shorea robusta",
            "Brosimum alicastrum",
            "Cordia dichotoma",
            "Cordia myxa",
            "Enterolobium cyclocarpum",
            "Eugenia uniflora",
            "Guarea guidonia",
            "Hymenaea courbaril",
            "Inga edulis",
            "Inga feuilleei",
            "Tabebuia rosea",
            "Dipterocarpus costatus",
            "Dipterocarpus grandiflorus",
            "Dipterocarpus turbinatus",
            "Elaeocarpus angustifolius",
            "Araucaria cunninghamii",
            "Araucaria heterophylla",
            "Araucaria hunsteinii",
            "Nauclea diderrichii",
            "Terminalia superba",
            "Cedrela odorata",
            "Paulownia tomentosa",
            "Gmelina arborea",
            "Grevillea robusta",
            "Tectona grandis",
            "Terminalia ivorensis"
        ],
        "n_species": 60,
        "density": 1100,
        "region": "tropical"
    }
}

eco_key = st.session_state.ecoregion.lower().strip()
bm_data = REGIONAL_BENCHMARKS_PRECOMPUTED.get(eco_key)
if bm_data:
    try:
        # Scale from 100ha baseline to actual area
        area_scale    = area_ha / 100.0
        # Scale from 40yr baseline to actual project years
        year_scale    = project_years / 40.0
        # Management uplift multiplier on top of TerraPod baseline
        mgmt_mult = 1.0
        if use_irrigation: mgmt_mult *= 1.15
        if use_nutrients:  mgmt_mult *= 1.10
        if use_biochar:    mgmt_mult *= 1.10
        # TerraPod vs no TerraPod
        tp      = TERRAPOD_UPLIFTS.get(terrapod_key or "seedball_outdoor", {})
        tp_grow = tp.get("dbh_growth_mult", 1.20)
        tp_mort = tp.get("annual_mortality_mult", 0.40)
        # TerraPod baseline already baked into pre-computed numbers
        # Additional management on top
        total_mult = mgmt_mult * area_scale * year_scale

        low_net    = bm_data["low_gross"]    * total_mult * (1 - buffer_pct/100)
        medium_net = bm_data["medium_gross"] * total_mult * (1 - buffer_pct/100)
        high_net   = bm_data["high_gross"]   * total_mult * (1 - buffer_pct/100)
        low_gross    = bm_data["low_gross"]    * total_mult
        medium_gross = bm_data["medium_gross"] * total_mult
        high_gross   = bm_data["high_gross"]   * total_mult

        n_sp = bm_data["n_species"]
        tp_label = tp.get("label", "Standard planting")

        st.subheader(f"📊 Mixed Forest Estimate — {st.session_state.ecoregion.title()}")
        st.caption(
            f"{area_ha:,} ha · {project_years} yr · {tp_label} · "
            f"Based on {n_sp} native species mix for this ecoregion · "
            f"{bm_data['density']:,} stems/ha"
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("🟡 Low estimate",    f"{low_net:,.0f} tCO₂e net",    f"Gross: {low_gross:,.0f}")
        c2.metric("🟠 Medium estimate", f"{medium_net:,.0f} tCO₂e net", f"Gross: {medium_gross:,.0f}")
        c3.metric("🟢 High estimate",   f"{high_net:,.0f} tCO₂e net",   f"Gross: {high_gross:,.0f}")
        st.caption(
            f"Low = average of slowest-growing native species mix · "
            f"Medium = full native species mix average · "
            f"High = average of fastest-growing native species mix · "
            f"Select specific species below to refine ↓"
        )
        st.divider()
    except Exception as _e:
        st.caption(f"Regional estimate unavailable: {_e}")

if st.sidebar.button("Calculate Carbon Credits", type="primary") and total_pct == 100:
    with st.spinner("Simulating..."):
        try:
            species_mix = []
            for spec in st.session_state.species_list:
                if spec["pct"] <= 0:
                    continue
                disp = spec["display"]
                if "(" in disp:
                    common_name  = disp.split(" (")[0]
                    species_name = disp.split(" (")[1].rstrip(")")
                else:
                    species_name = common_name = disp
                species_mix.append({
                    "species_name": species_name,
                    "common_name" : common_name,
                    "region"      : detected_region,
                    "pct"         : spec["pct"],
                    "density"     : spec["density"],
                })

            # Apply TerraPod uplifts if selected
            effective_mortality = mortality
            terrapod_info = None
            if terrapod_key:
                tp = TERRAPOD_UPLIFTS[terrapod_key]
                effective_mortality = mortality * tp["annual_mortality_mult"]
                # Apply growth uplift via management
                management["terrapod_growth_mult"] = tp["dbh_growth_mult"]
                terrapod_info = tp

            results      = sim.simulate_project(
                area_ha=area_ha, species_mix=species_mix,
                project_years=project_years, annual_mortality=effective_mortality,
                management=management,
                managed_restoration=use_managed_restoration,
            )
            # Carbon stock at END of crediting period (not sum of annual stocks)
            final         = results[-1]
            gross_biomass = final["co2e_gross_t"]
            gross_soil    = sum(r["soil_co2e_gross_t"] for r in results)  # soil IS cumulative annual
            gross_total   = gross_biomass + gross_soil
            buffer_held   = gross_total * (buffer_pct / 100.0)
            net_total     = gross_total * (1 - buffer_pct / 100.0)
            net_vcs       = net_total * (1 - mrvdiscount / 100.0)

            audit = sim.get_audit_trail(
                species_mix, management, area_ha, project_years, mortality, buffer_pct
            )

            st.success(f"Estimated Net VCUs (after {buffer_pct}% buffer + {mrvdiscount}% MRV discount): **{net_vcs:,.0f} tCO2e**")

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Gross tCO2e",              f"{gross_total:,.0f}")
            col2.metric("Buffer held",               f"{buffer_held:,.0f}")
            col3.metric("Net (pre-discount)",         f"{net_total:,.0f}")
            col4.metric(f"Net VCUs (-{mrvdiscount}% MRV)", f"{net_vcs:,.0f}")

            if active_uplifts:
                st.info(f"Management uplifts: {' | '.join(active_uplifts)}")
            if terrapod_info:
                st.success(
                    f"**TerraPod Technology Applied:** {terrapod_info['label']} | "
                    f"Mortality reduced {(1-terrapod_info['annual_mortality_mult'])*100:.0f}% | "
                    f"Growth +{(terrapod_info['dbh_growth_mult']-1)*100:.0f}% | "
                    f"Water saving {terrapod_info['water_saving']*100:.0f}% | "
                    f"*Cite: EAD/EQS/2024/1935*"
                )

            st.subheader("Cumulative Carbon Accumulation")
            # Chart: biomass stock at each year + cumulative soil
            years, cum_gross, cum_net = [], [], []
            cumulative_soil = 0
            for r in results:
                cumulative_soil += r["soil_co2e_gross_t"]
                total_stock = r["co2e_gross_t"] + cumulative_soil
                years.append(r["year"])
                cum_gross.append(round(total_stock, 0))
                cum_net.append(round(total_stock * (1 - buffer_pct/100), 0))

            chart_df = pd.DataFrame({"Year": years, "Gross tCO2e": cum_gross, "Net VCUs": cum_net})
            st.line_chart(chart_df, x="Year", y=["Gross tCO2e", "Net VCUs"])

            st.subheader("Species Mix & Equation Sources")
            mix_rows = []
            for sp in species_mix:
                eq_info = audit["species_equations"].get(sp["species_name"], {})
                mix_rows.append({
                    "Species"      : f"{sp['common_name']} ({sp['species_name']})",
                    "Mix %"        : f"{sp['pct']}%",
                    "Stems/ha"     : sp["density"],
                    "Equation tier": eq_info.get("tier", "Unknown"),
                    "R2"           : eq_info.get("r2", "-"),
                    "N"            : eq_info.get("n", "-"),
                    "Citation"     : eq_info.get("citation", "")[:55],
                })
            st.table(pd.DataFrame(mix_rows))

            with st.expander("VCS Assumptions & Citations"):
                st.write(f"**Carbon fraction:** 0.47 - IPCC 2006 Table 4.3")
                st.write(f"**CO2e factor:** 3.67 - molecular weight C:CO2")
                rsr_val = audit['rsr_values'].get(detected_region, 0.235)
                st.write(f"**Above-ground biomass (AGB):** Calculated from species-specific allometric equations (Biomass = f(DBH))")
                st.write(f"**Below-ground biomass (BGB):** Included via root-to-shoot ratio (RSR) - Total biomass = AGB x (1 + RSR)")
                st.write(f"**RSR ({detected_region}):** {rsr_val} - {RSR_CITATION}")
                st.write(f"**BGB carbon pool:** Fully accounted for in all sequestration estimates per VCS AR-ACM0003 requirements")
                st.write(f"**Uncertainty discount:** {mrvdiscount}% applied — " +
                             ("continuous drone/satellite MRV justifies 10% per VCS Uncertainty Policy v4" 
                              if use_managed_restoration else 
                              "standard 20% per VCS Uncertainty & Variance Policy v4"))
                if use_managed_restoration:
                    st.write("**Managed restoration protocol:**")
                    st.write("- Yrs 1-2: 0% net mortality — immediate replanting, 100% survival maintained")
                    st.write("- Yrs 3-4: 0.5% mortality — irrigation weaning, TerraPod transition")
                    st.write("- Yrs 5+:  1.5% mortality — established native forest, MRV only")
                    st.write("- Continuous drone & satellite MRV for full 40-year crediting period")
                    st.write("- Cite: ISB managed restoration protocol / EAD/EQS/2024/1935")
                st.write(f"**Buffer pool:** {buffer_pct}% - user selected (VCS min 10%)")
                if use_irrigation: st.write(f"**Irrigation:** {UPLIFT_CITATIONS['irrigation']}")
                if use_biochar:    st.write(f"**Biochar:** {UPLIFT_CITATIONS['biochar']}")
                if use_nutrients:  st.write(f"**Nutrients:** {UPLIFT_CITATIONS['nutrients']}")
                if terrapod_key:
                    tp = TERRAPOD_UPLIFTS[terrapod_key]
                    st.write(f"**TerraPod ({tp['label']}):** Germination {tp['germination']*100:.0f}%, "
                             f"Year-1 survival {tp['survival_yr1']*100:.0f}%, "
                             f"Mortality -{(1-tp['annual_mortality_mult'])*100:.0f}%, "
                             f"Growth +{(tp['dbh_growth_mult']-1)*100:.0f}%")
                    st.write(f"**TerraPod citation:** {TERRAPOD_CITATION}")

            pdf_bytes = generate_pdf_report(
                area_ha, species_mix, gross_total, buffer_pct,
                gross_soil, management, audit, project_years,
            )
            st.download_button(
                label="Download VCS Report (PDF)",
                data=pdf_bytes,
                file_name=f"vcs_report_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
            )

        except Exception as e:
            st.error(f"Simulation error: {e}")
            import traceback
            st.code(traceback.format_exc())

elif total_pct != 100:
    st.info("Adjust species mix to 100%, then click Calculate.")
else:
    st.info("Configure parameters in the sidebar and click Calculate Carbon Credits.")
