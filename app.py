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

st.set_page_config(
    page_title="VCS Reforestation Carbon Estimator",
    page_icon="🌳",
    layout="wide",
)

def get_ecoregion(lat, lon):
    """
    Estimate WWF ecoregion from lat/lon.
    Uses known desert/arid bounding boxes first, then latitude bands.
    """
    # --- Known desert / arid regions (check first before latitude bands) ---
    # Arabian Peninsula / Middle East deserts
    if 12 <= lat <= 38 and 32 <= lon <= 65:
        return "deserts and xeric shrublands"
    # Sahara / North Africa
    if 15 <= lat <= 35 and -18 <= lon <= 40:
        return "deserts and xeric shrublands"
    # Iranian / Central Asian deserts
    if 25 <= lat <= 45 and 50 <= lon <= 70:
        return "deserts and xeric shrublands"
    # Australian outback
    if -35 <= lat <= -15 and 115 <= lon <= 145:
        return "deserts and xeric shrublands"
    # Atacama / Patagonian
    if -45 <= lat <= -15 and -75 <= lon <= -65:
        return "deserts and xeric shrublands"
    # Gobi / Central Asian steppe
    if 35 <= lat <= 50 and 80 <= lon <= 120:
        return "deserts and xeric shrublands"
    # Southwest USA deserts
    if 25 <= lat <= 40 and -120 <= lon <= -100:
        return "deserts and xeric shrublands"

    # --- Mangroves (coastal tropics) ---
    # (handled by species selection, not auto-detected here)

    # --- Latitude-based biome bands ---
    abs_lat = abs(lat)

    # Boreal / Arctic
    if abs_lat > 60:
        return "boreal forests/taiga"

    # Tropical band
    if abs_lat <= 23.5:
        # African savanna belt
        if -20 <= lon <= 50 and 5 <= lat <= 20:
            return "tropical and subtropical grasslands"
        # SE Asia / Pacific islands
        if 90 <= lon <= 180 and -10 <= lat <= 20:
            return "tropical and subtropical moist broadleaf forests"
        # Amazon / Central Africa / SE Asia moist
        return "tropical and subtropical moist broadleaf forests"

    # Sub-tropical / temperate band (23.5 - 60)
    if 23.5 < abs_lat <= 40:
        # Mediterranean climates
        if (-10 <= lon <= 40 and 30 <= lat <= 45):  # Mediterranean basin
            return "mediterranean forests"
        if (-125 <= lon <= -115 and 30 <= lat <= 40):  # California
            return "mediterranean forests"
        if (115 <= lon <= 155 and -40 <= lat <= -30):  # SW Australia
            return "mediterranean forests"
        # East Asia / Eastern USA temperate
        return "temperate broadleaf and mixed forests"

    # 40-60 degrees
    if 40 < abs_lat <= 60:
        # Continental interiors -> boreal tendency
        if 60 <= lon <= 180 or -180 <= lon <= -90:
            return "boreal forests/taiga"
        return "temperate broadleaf and mixed forests"

    return "temperate broadleaf and mixed forests"

def eco_to_region(eco):
    eco = eco.lower()
    if "boreal" in eco or "taiga" in eco:
        return "boreal"
    elif "temperate" in eco or "montane" in eco:
        return "temperate"
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

@st.cache_data
def load_species_data():
    return pd.read_csv("allometric_equations.csv")

@st.cache_data
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
    st.sidebar.warning("No native species with allometric data for this ecoregion. Showing all regional species.")
    filtered_list = full_list or ["Tectona grandis (Tectona grandis)"]

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

            results      = sim.simulate_project(
                area_ha=area_ha, species_mix=species_mix,
                project_years=project_years, annual_mortality=mortality,
                management=management,
            )
            gross_biomass = sum(r["co2e_gross_t"] for r in results)
            gross_soil    = sum(r["soil_co2e_gross_t"] for r in results)
            gross_total   = gross_biomass + gross_soil
            buffer_held   = gross_total * (buffer_pct / 100.0)
            net_total     = gross_total * (1 - buffer_pct / 100.0)
            net_vcs       = net_total * 0.80

            audit = sim.get_audit_trail(
                species_mix, management, area_ha, project_years, mortality, buffer_pct
            )

            st.success(f"Net VCUs (buffer + 20% uncertainty discount): **{net_vcs:,.0f} tCO2e**")

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Gross tCO2e",       f"{gross_total:,.0f}")
            col2.metric("Buffer held",        f"{buffer_held:,.0f}")
            col3.metric("Net pre-discount",   f"{net_total:,.0f}")
            col4.metric("VCS net (-20%)",     f"{net_vcs:,.0f}")

            if active_uplifts:
                st.info(f"Management uplifts: {' | '.join(active_uplifts)}")

            st.subheader("Cumulative Carbon Accumulation")
            years, cum_gross, cum_net = [], [], []
            running = 0
            for r in results:
                running += r["co2e_gross_t"] + r["soil_co2e_gross_t"]
                years.append(r["year"])
                cum_gross.append(running)
                cum_net.append(running * (1 - buffer_pct/100) * 0.80)

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
                st.write(f"**RSR ({detected_region}):** {audit['rsr_values'].get(detected_region, 0.235)} - {RSR_CITATION}")
                st.write(f"**Uncertainty discount:** 20% - VCS Uncertainty & Variance Policy v4")
                st.write(f"**Buffer pool:** {buffer_pct}% - user selected (VCS min 10%)")
                if use_irrigation: st.write(f"**Irrigation:** {UPLIFT_CITATIONS['irrigation']}")
                if use_biochar:    st.write(f"**Biochar:** {UPLIFT_CITATIONS['biochar']}")
                if use_nutrients:  st.write(f"**Nutrients:** {UPLIFT_CITATIONS['nutrients']}")

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
