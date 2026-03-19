import streamlit as st
import folium
from streamlit_folium import st_folium
import os, sys, json
import pandas as pd
import numpy as np
from datetime import datetime
from fpdf import FPDF

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from carbon_simulator import CarbonCreditSimulator, UPLIFT_CITATIONS, RSR_CITATION

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="VCS Reforestation Carbon Estimator",
    page_icon="🌳",
    layout="wide",
)

# ── Ecoregion detection ────────────────────────────────────────────────────────
def get_ecoregion(lat, lon):
    if -23.5 <= lat <= 23.5:
        if -60 <= lon <= 150:
            return "tropical and subtropical moist broadleaf forests"
        elif -20 <= lon <= 50 or 110 <= lon <= 150:
            return "tropical and subtropical grasslands"
        else:
            return "deserts and xeric shrublands"
    elif 23.5 < abs(lat) <= 66.5:
        if -10 <= lon <= 40:
            return "temperate broadleaf and mixed forests"
        elif 60 <= lon <= 180 or -180 <= lon <= -50:
            return "boreal forests/taiga"
        else:
            return "temperate broadleaf and mixed forests"
    else:
        return "boreal forests/taiga"

def eco_to_region(eco):
    eco = eco.lower()
    if "boreal" in eco or "taiga" in eco:
        return "boreal"
    elif "temperate" in eco:
        return "temperate"
    elif "montane" in eco or "alpine" in eco:
        return "temperate"
    return "tropical"

# ── Data loading ───────────────────────────────────────────────────────────────
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

# ── PDF report ─────────────────────────────────────────────────────────────────
def generate_pdf_report(area_ha, species_mix, gross_credits, buffer_pct,
                         soil_gross, management, audit_trail, project_years):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Header
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "VCS Reforestation Carbon Credit Report", ln=True, align="C")
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 6, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Methodology: Verra AR-ACM0003", ln=True, align="C")
    pdf.ln(4)

    # Summary
    net_credits   = gross_credits * (1 - buffer_pct / 100.0)
    buffer_amount = gross_credits * buffer_pct / 100.0

    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "Carbon Credit Summary", ln=True)
    pdf.set_font("Arial", "", 11)
    pdf.cell(0, 7, f"Project area:                {area_ha:,.0f} ha", ln=True)
    pdf.cell(0, 7, f"Crediting period:            {project_years} years", ln=True)
    pdf.cell(0, 7, f"Gross sequestration:         {gross_credits:,.0f} tCO2e", ln=True)
    pdf.cell(0, 7, f"  - Biomass:                 {gross_credits - soil_gross:,.0f} tCO2e", ln=True)
    pdf.cell(0, 7, f"  - Soil:                    {soil_gross:,.0f} tCO2e", ln=True)
    pdf.cell(0, 7, f"Buffer pool ({buffer_pct}%):          {buffer_amount:,.0f} tCO2e", ln=True)
    pdf.cell(0, 7, f"Net issuable VCUs:           {net_credits:,.0f} tCO2e", ln=True)
    pdf.ln(3)

    # Management practices
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "Management Practices & Uplifts", ln=True)
    pdf.set_font("Arial", "", 10)
    if management.get("irrigation"):
        pdf.cell(0, 6, f"  Irrigation:  +15% DBH growth  [{UPLIFT_CITATIONS['irrigation']}]", ln=True)
    if management.get("nutrients"):
        pdf.cell(0, 6, f"  Nutrients:   +10% DBH growth  [{UPLIFT_CITATIONS['nutrients']}]", ln=True)
    if management.get("biochar"):
        pdf.cell(0, 6, f"  Biochar:     +10% growth, +5 tC/ha soil  [{UPLIFT_CITATIONS['biochar']}]", ln=True)
    if not any([management.get("irrigation"), management.get("nutrients"), management.get("biochar")]):
        pdf.cell(0, 6, "  No management uplifts applied (conservative baseline)", ln=True)
    pdf.ln(3)

    # Species mix
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "Species Mix", ln=True)
    pdf.set_font("Arial", "", 10)
    for spec in species_mix:
        eq_info = audit_trail.get("species_equations", {}).get(spec["species_name"], {})
        tier    = eq_info.get("tier", "Unknown")
        cite    = eq_info.get("citation", "")[:60]
        pdf.cell(0, 6, f"  {spec['common_name']} ({spec['species_name']}): "
                        f"{spec['pct']}%  |  {spec['density']} stems/ha  |  {tier}", ln=True)
        if cite:
            pdf.set_font("Arial", "I", 8)
            pdf.cell(0, 5, f"    Citation: {cite}", ln=True)
            pdf.set_font("Arial", "", 10)
    pdf.ln(3)

    # Key constants
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "VCS-Required Constants & Assumptions", ln=True)
    pdf.set_font("Arial", "", 10)
    constants = [
        ("Carbon fraction (CF)",        "0.47",    "IPCC 2006 Table 4.3"),
        ("CO2e conversion factor",       "3.67",    "Molecular weight C:CO2"),
        ("RSR tropical",                 "0.235",   RSR_CITATION),
        ("RSR temperate",                "0.192",   RSR_CITATION),
        ("RSR boreal",                   "0.390",   RSR_CITATION),
        ("Uncertainty discount",         "20%",     "VCS Uncertainty & Variance Policy v4"),
        ("Equation database",            "GlobAllomeTree + allometric_equations.csv", "Peer-reviewed"),
    ]
    for label, value, citation in constants:
        pdf.cell(0, 6, f"  {label}: {value}  [{citation}]", ln=True)
    pdf.ln(3)

    # Audit trail
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
        pdf.cell(0, 5, f"  {key}: {str(val)[:90]}", ln=True)

    pdf.ln(5)
    pdf.set_font("Arial", "I", 8)
    pdf.cell(0, 5, "This is a feasibility estimate. Actual VCUs require Verra validation and verification.", ln=True)

    return bytes(pdf.output(dest="S"))

# ── App ────────────────────────────────────────────────────────────────────────
st.title("🌳 VCS Reforestation Carbon Credit Estimator")
st.caption("Verra AR-ACM0003 · GlobAllomeTree equations · IPCC 2019 RSR · VVB-defensible audit trail")

# Load data
try:
    species_df   = load_species_data()
    native_df    = load_native_species()
    sim          = load_simulator()
except Exception as e:
    st.error(f"Error loading data: {e}")
    st.stop()

# ── Session state ──────────────────────────────────────────────────────────────
if "lat" not in st.session_state:
    st.session_state.lat      = -3.4653
    st.session_state.lon      = -62.2153
    st.session_state.ecoregion = "tropical and subtropical moist broadleaf forests"

# ── Map ────────────────────────────────────────────────────────────────────────
st.subheader("📍 Project Location")
m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=4)
folium.Marker(
    [st.session_state.lat, st.session_state.lon],
    popup="Project Location",
    icon=folium.Icon(color="green"),
).add_to(m)
map_data = st_folium(m, width=700, height=300)

if map_data and map_data.get("last_clicked"):
    st.session_state.lat      = map_data["last_clicked"]["lat"]
    st.session_state.lon      = map_data["last_clicked"]["lng"]
    st.session_state.ecoregion = get_ecoregion(
        st.session_state.lat, st.session_state.lon
    )

# ── Sidebar ────────────────────────────────────────────────────────────────────
st.sidebar.header("⚙️ Project Parameters")

# Ecoregion display
st.sidebar.info(f"📍 Detected ecoregion:\n**{st.session_state.ecoregion.title()}**")
detected_region = eco_to_region(st.session_state.ecoregion)

# Project details
area_ha       = st.sidebar.number_input("Project area (ha)", min_value=1, value=100)
project_years = st.sidebar.slider("Crediting period (years)", 20, 60, 40)
mortality     = st.sidebar.number_input("Annual mortality (%)", 0, 20, 4) / 100.0
buffer_pct    = st.sidebar.slider("Buffer pool (%)", 10, 30, 20,
                                   help="VCS minimum 10%. Withheld from issuable VCUs.")

# ── Management practices ───────────────────────────────────────────────────────
st.sidebar.subheader("🌱 Management Practices")
st.sidebar.caption("Fixed uplifts per peer-reviewed literature (VVB-defensible)")

col1, col2 = st.sidebar.columns(2)
water_limited    = col1.checkbox("Water-limited site?")
use_irrigation   = col1.checkbox(
    "✅ Irrigation (+15%)",
    disabled=not water_limited,
    help=UPLIFT_CITATIONS["irrigation"],
)
nutrient_poor    = col2.checkbox("Nutrient-poor soil?")
use_nutrients    = col2.checkbox(
    "✅ Nutrients (+10%)",
    disabled=not nutrient_poor,
    help=UPLIFT_CITATIONS["nutrients"],
)
use_biochar      = st.sidebar.checkbox(
    "✅ Biochar (+10% growth, +5 tC/ha soil)",
    help=UPLIFT_CITATIONS["biochar"],
)
use_weed_control = st.sidebar.checkbox("✅ Weed/invasive control", value=True,
                                        help="+5% survival rate")
use_fencing      = st.sidebar.checkbox("✅ Fencing/exclosure",
                                        help="+7% survival rate")

# Show uplift summary
active_uplifts = []
if use_irrigation: active_uplifts.append("Irrigation +15%")
if use_nutrients:  active_uplifts.append("Nutrients +10%")
if use_biochar:    active_uplifts.append("Biochar +10% / +5 tC/ha soil")
if active_uplifts:
    st.sidebar.success(f"Active uplifts: {', '.join(active_uplifts)}")
else:
    st.sidebar.info("No growth uplifts applied (conservative)")

management = {
    "irrigation"   : use_irrigation,
    "nutrients"    : use_nutrients,
    "biochar"      : use_biochar,
    "weed_control" : use_weed_control,
    "fencing"      : use_fencing,
}

# ── Species selection ──────────────────────────────────────────────────────────
st.sidebar.subheader("🌿 Region & Species")

# Filter native species for this ecoregion
ecoregion_key   = st.session_state.ecoregion.lower().strip()
native_species  = native_df[native_df["ecoregion"] == ecoregion_key]["species_name"].tolist()

# Build display list with common names
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
    st.sidebar.warning("⚠️ No native species with allometric data for this ecoregion. Showing all regional species.")
    filtered_list = full_list or ["Tectona grandis (Tectona grandis)"]

species_options = filtered_list

# Species mix builder
if "species_list" not in st.session_state:
    st.session_state.species_list = [
        {"display": species_options[0], "pct": 100, "density": 1100}
    ]

for i, spec in enumerate(st.session_state.species_list):
    cols = st.sidebar.columns([3, 1, 1])
    spec["display"] = cols[0].selectbox(
        f"Species {i+1}", species_options,
        index=min(i, len(species_options)-1),
        key=f"sp_{i}",
    )
    spec["pct"]     = cols[1].number_input(
        f"% {i+1}", 0, 100, spec["pct"], key=f"pct_{i}"
    )
    spec["density"] = cols[2].number_input(
        f"Dens {i+1}", 100, 5000, spec["density"], key=f"den_{i}"
    )

c1, c2 = st.sidebar.columns(2)
if c1.button("➕ Add species"):
    if len(st.session_state.species_list) < 5:
        st.session_state.species_list.append(
            {"display": species_options[0], "pct": 0, "density": 1100}
        )
if c2.button("➖ Remove last"):
    if len(st.session_state.species_list) > 1:
        st.session_state.species_list.pop()

total_pct = sum(s["pct"] for s in st.session_state.species_list)
if total_pct != 100:
    st.sidebar.warning(f"⚠️ Species mix = {total_pct}%. Must equal 100%.")

# ── Calculate button ───────────────────────────────────────────────────────────
if st.sidebar.button("🌲 Calculate Carbon Credits", type="primary") and total_pct == 100:
    with st.spinner("Running simulation…"):
        try:
            # Parse species mix
            species_mix = []
            for spec in st.session_state.species_list:
                if spec["pct"] <= 0:
                    continue
                disp = spec["display"]
                if "(" in disp and ")" in disp:
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

            # Run simulation
            results  = sim.simulate_project(
                area_ha=area_ha,
                species_mix=species_mix,
                project_years=project_years,
                annual_mortality=mortality,
                management=management,
            )
            final         = results[-1]
            gross_biomass = sum(r["co2e_gross_t"] for r in results)
            gross_soil    = sum(r["soil_co2e_gross_t"] for r in results)
            gross_total   = gross_biomass + gross_soil
            buffer_held   = gross_total * (buffer_pct / 100.0)
            net_total     = gross_total * (1 - buffer_pct / 100.0)

            # VCS 20% uncertainty discount
            net_vcs = net_total * 0.80

            # Audit trail
            audit = sim.get_audit_trail(
                species_mix, management, area_ha, project_years,
                mortality, buffer_pct,
            )

            # ── Results display ────────────────────────────────────────────
            st.success(f"✅ Net VCUs (after buffer + 20% uncertainty): **{net_vcs:,.0f} tCO₂e**")

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Gross tCO₂e",        f"{gross_total:,.0f}")
            col2.metric("Buffer held",         f"{buffer_held:,.0f}")
            col3.metric("Net (pre-discount)",  f"{net_total:,.0f}")
            col4.metric("VCS net (−20%)",      f"{net_vcs:,.0f}")

            # Uplift info
            if active_uplifts:
                st.info(f"🌱 Management uplifts applied: {' · '.join(active_uplifts)}")

            # ── Chart ──────────────────────────────────────────────────────
            st.subheader("📈 Cumulative Carbon Accumulation")
            years         = [r["year"] for r in results]
            cum_gross     = []
            cum_net_vcs   = []
            running = 0
            for r in results:
                running += r["co2e_gross_t"] + r["soil_co2e_gross_t"]
                cum_gross.append(running)
                cum_net_vcs.append(running * (1 - buffer_pct/100) * 0.80)

            chart_df = pd.DataFrame({
                "Year"         : years,
                "Gross tCO₂e"  : cum_gross,
                "Net VCUs"     : cum_net_vcs,
            })
            st.line_chart(chart_df, x="Year", y=["Gross tCO₂e", "Net VCUs"])

            # ── Species mix table ──────────────────────────────────────────
            st.subheader("🌿 Species Mix & Equation Sources")
            mix_rows = []
            for sp in species_mix:
                eq_info = audit["species_equations"].get(sp["species_name"], {})
                mix_rows.append({
                    "Species"       : f"{sp['common_name']} ({sp['species_name']})",
                    "Mix %"         : f"{sp['pct']}%",
                    "Stems/ha"      : sp["density"],
                    "Equation tier" : eq_info.get("tier", "Unknown"),
                    "R²"            : eq_info.get("r2", "—"),
                    "N"             : eq_info.get("n", "—"),
                    "Citation"      : eq_info.get("citation", "")[:55],
                })
            st.table(pd.DataFrame(mix_rows))

            # ── Key assumptions ────────────────────────────────────────────
            with st.expander("🔍 VCS-Required Assumptions & Citations"):
                assumptions = {
                    "Carbon fraction"        : "0.47 — IPCC 2006 Table 4.3",
                    "CO₂e factor"            : "3.67 — molecular weight C:CO₂",
                    f"RSR ({detected_region})": f"{audit['rsr_values'].get(detected_region, 0.235)} — {RSR_CITATION}",
                    "Uncertainty discount"   : "20% — VCS Uncertainty & Variance Policy v4",
                    "Buffer pool"            : f"{buffer_pct}% — user selected (VCS min 10%)",
                    "Soil carbon"            : "10% of regional SOC reference — IPCC 2019",
                }
                if use_irrigation:
                    assumptions["Irrigation uplift"] = UPLIFT_CITATIONS["irrigation"]
                if use_biochar:
                    assumptions["Biochar uplift"] = UPLIFT_CITATIONS["biochar"]
                if use_nutrients:
                    assumptions["Nutrient uplift"] = UPLIFT_CITATIONS["nutrients"]
                for k, v in assumptions.items():
                    st.write(f"**{k}:** {v}")

            # ── PDF download ───────────────────────────────────────────────
            pdf_bytes = generate_pdf_report(
                area_ha, species_mix, gross_total,
                buffer_pct, gross_soil, management,
                audit, project_years,
            )
            st.download_button(
                label="📥 Download VCS Report (PDF)",
                data=pdf_bytes,
                file_name=f"vcs_carbon_report_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
            )

        except Exception as e:
            st.error(f"Simulation error: {e}")
            import traceback
            st.code(traceback.format_exc())

elif total_pct != 100:
    st.info("👈 Adjust species mix to 100%, then click **Calculate**")
else:
    st.info("👈 Configure parameters and click **Calculate Carbon Credits**")
