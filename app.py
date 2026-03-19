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

@st.cache_resource
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

# ── Regional benchmarks for Low / Medium / High estimates ────────────────────────
REGIONAL_BENCHMARKS = {
    "tropical and subtropical moist broadleaf forests": {
        "low"   : {"species": "Terminalia superba",      "common": "Afara",               "density": 800,  "region": "tropical"},
        "medium": {"species": "Cedrela odorata",         "common": "Spanish Cedar",        "density": 1000, "region": "tropical"},
        "high"  : {"species": "Acacia mangium",          "common": "Mangium",              "density": 1200, "region": "tropical"},
    },
    "tropical and subtropical dry broadleaf forests": {
        "low"   : {"species": "Colophospermum mopane",   "common": "Mopane",               "density": 800,  "region": "dry_tropical"},
        "medium": {"species": "Tectona grandis",         "common": "Teak",                 "density": 1000, "region": "dry_tropical"},
        "high"  : {"species": "Gmelina arborea",         "common": "Gmelina",              "density": 1200, "region": "tropical"},
    },
    "tropical and subtropical grasslands": {
        "low"   : {"species": "Acacia senegal",          "common": "Gum Arabic",           "density": 600,  "region": "tropical_grassland"},
        "medium": {"species": "Vitellaria paradoxa",     "common": "Shea Tree",            "density": 800,  "region": "tropical_grassland"},
        "high"  : {"species": "Parkia biglobosa",        "common": "Locust Bean",          "density": 1000, "region": "tropical_grassland"},
    },
    "deserts and xeric shrublands": {
        "low"   : {"species": "Haloxylon persicum",      "common": "White Saxaul",         "density": 600,  "region": "desert"},
        "medium": {"species": "Acacia tortilis",         "common": "Umbrella Thorn",       "density": 800,  "region": "desert"},
        "high"  : {"species": "Prosopis cineraria",      "common": "Ghaf Tree",            "density": 1000, "region": "desert"},
    },
    "mediterranean forests": {
        "low"   : {"species": "Quercus ilex",            "common": "Holm Oak",             "density": 800,  "region": "mediterranean"},
        "medium": {"species": "Pinus halepensis",        "common": "Aleppo Pine",          "density": 1000, "region": "mediterranean"},
        "high"  : {"species": "Cedrus atlantica",        "common": "Atlas Cedar",          "density": 1100, "region": "mediterranean"},
    },
    "temperate broadleaf and mixed forests": {
        "low"   : {"species": "Quercus robur",           "common": "English Oak",          "density": 800,  "region": "temperate"},
        "medium": {"species": "Fagus sylvatica",         "common": "European Beech",       "density": 1000, "region": "temperate"},
        "high"  : {"species": "Populus nigra",           "common": "Black Poplar",         "density": 1200, "region": "temperate"},
    },
    "boreal forests/taiga": {
        "low"   : {"species": "Abies balsamea",          "common": "Balsam Fir",           "density": 800,  "region": "boreal"},
        "medium": {"species": "Picea abies",             "common": "Norway Spruce",        "density": 1000, "region": "boreal"},
        "high"  : {"species": "Pinus sylvestris",        "common": "Scots Pine",           "density": 1200, "region": "boreal"},
    },
    "mangroves": {
        "low"   : {"species": "Ceriops tagal",           "common": "Spurred Mangrove",     "density": 1000, "region": "mangrove"},
        "medium": {"species": "Avicennia marina",        "common": "Grey Mangrove",        "density": 1200, "region": "mangrove"},
        "high"  : {"species": "Rhizophora mangle",       "common": "Red Mangrove",         "density": 1500, "region": "mangrove"},
    },
    "montane grasslands and shrublands": {
        "low"   : {"species": "Polylepis australis",     "common": "Queñoa",               "density": 800,  "region": "montane"},
        "medium": {"species": "Alnus acuminata",         "common": "Andean Alder",         "density": 1000, "region": "montane"},
        "high"  : {"species": "Juniperus procera",       "common": "African Pencil Cedar", "density": 1100, "region": "montane"},
    },
    "flooded grasslands and savannas": {
        "low"   : {"species": "Salix alba",              "common": "White Willow",         "density": 800,  "region": "flooded"},
        "medium": {"species": "Eucalyptus camaldulensis","common": "River Red Gum",        "density": 1000, "region": "flooded"},
        "high"  : {"species": "Populus nigra",           "common": "Black Poplar",         "density": 1200, "region": "flooded"},
    },
}

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

# ── Regional estimate summary card ───────────────────────────────────────────
eco_key    = st.session_state.ecoregion.lower().strip()
benchmarks = REGIONAL_BENCHMARKS.get(eco_key)
if benchmarks:
    try:
        tp_key  = terrapod_key or "seedball_outdoor"
        tp      = TERRAPOD_UPLIFTS.get(tp_key, {})
        tp_mort = tp.get("annual_mortality_mult", 1.0)
        tp_grow = tp.get("dbh_growth_mult", 1.0)
        tp_label= tp.get("label", "Standard planting")
        mgmt_bm = {
            "terrapod_growth_mult": tp_grow,
            "irrigation": use_irrigation,
            "nutrients" : use_nutrients,
            "biochar"   : use_biochar,
        }
        bm_results = {}
        for tier in ("low", "medium", "high"):
            bm  = benchmarks[tier]
            mix = [{"species_name": bm["species"], "common_name": bm["common"],
                    "region": bm["region"], "pct": 100, "density": bm["density"]}]
            r   = sim.simulate_project(
                area_ha=area_ha, species_mix=mix,
                project_years=project_years,
                annual_mortality=0.04 * tp_mort,
                management=mgmt_bm,
            )
            gross = r[-1]["co2e_gross_t"] + sum(x["soil_co2e_gross_t"] for x in r)
            net   = gross * (1 - buffer_pct / 100)
            bm_results[tier] = {"gross": gross, "net": net, "species": bm["common"]}

        st.subheader(f"📊 Regional Estimate — {st.session_state.ecoregion.title()}")
        st.caption(
            f"{area_ha:,} ha · {project_years} yr · {tp_label} · "
            f"Representative species for this ecoregion"
        )
        c1, c2, c3 = st.columns(3)
        for col, tier, icon in [(c1,"low","🟡"),(c2,"medium","🟠"),(c3,"high","🟢")]:
            d = bm_results[tier]
            col.metric(
                f"{icon} {tier.title()} — {d['species']}",
                f"{d['net']:,.0f} tCO₂e net",
                f"Gross: {d['gross']:,.0f}",
            )
        st.caption("Select specific species in the sidebar to refine this estimate ↑")
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
            )
            # Carbon stock at END of crediting period (not sum of annual stocks)
            final         = results[-1]
            gross_biomass = final["co2e_gross_t"]
            gross_soil    = sum(r["soil_co2e_gross_t"] for r in results)  # soil IS cumulative annual
            gross_total   = gross_biomass + gross_soil
            buffer_held   = gross_total * (buffer_pct / 100.0)
            net_total     = gross_total * (1 - buffer_pct / 100.0)
            net_vcs       = net_total  # 20% uncertainty discount available but not applied here

            audit = sim.get_audit_trail(
                species_mix, management, area_ha, project_years, mortality, buffer_pct
            )

            st.success(f"Estimated Net VCUs (after {buffer_pct}% buffer): **{net_vcs:,.0f} tCO2e**")

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Gross tCO2e",        f"{gross_total:,.0f}")
            col2.metric("Buffer held",         f"{buffer_held:,.0f}")
            col3.metric("Net VCUs (est.)",     f"{net_total:,.0f}")
            col4.metric("Net after buffer",    f"{net_vcs:,.0f}")

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
                st.write(f"**Uncertainty discount:** 20% available per VCS Uncertainty & Variance Policy v4 (not applied to estimates shown)")
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
