import streamlit as st
import folium
from streamlit_folium import st_folium
import os
import sys
import pandas as pd
from datetime import datetime
from fpdf import FPDF

# Add current dir to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from carbon_simulator import CarbonCreditSimulator

# PDF Generator (VM0047 compliant, with management practices)
def generate_pdf_report(area_ha, species_mix, gross_credits, buffer_pct, soil_gross, management):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "Carbon Credit Estimation Report", ln=True, align="C")
    pdf.ln(10)
    
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 10, f"Date: {datetime.now().strftime('%Y-%m-%d')}", ln=True)
    pdf.cell(0, 10, f"Project Area: {area_ha} hectares", ln=True)
    pdf.cell(0, 10, f"Methodology: Verra VM0047 (2023)", ln=True)
    pdf.ln(5)
    
    net_credits = gross_credits * (1 - buffer_pct / 100.0)
    buffer_amount = gross_credits * (buffer_pct / 100.0)
    
    pdf.cell(0, 10, f"Gross Carbon Sequestration (40 years): {gross_credits:,.0f} tonnes CO2e", ln=True)
    pdf.cell(0, 8, f"  - Biomass: {gross_credits - soil_gross:,.0f} tonnes CO2e", ln=True)
    pdf.cell(0, 8, f"  - Soil: {soil_gross:,.0f} tonnes CO2e", ln=True)
    pdf.ln(5)
    
    pdf.cell(0, 10, f"Buffer Pool ({buffer_pct}%): {buffer_amount:,.0f} tonnes CO2e", ln=True)
    pdf.cell(0, 10, f"Net Issuable Credits: {net_credits:,.0f} tonnes CO2e", ln=True)
    pdf.ln(10)
    
    # Management practices
    if any(management.values()):
        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, "Management Practices", ln=True)
        pdf.set_font("Arial", "", 12)
        if management.get("irrigation"):
            pdf.cell(0, 8, "- Irrigation (+15% growth)", ln=True)
        if management.get("nutrients"):
            pdf.cell(0, 8, "- Fertilizers (+10% growth)", ln=True)
        if management.get("biochar"):
            pdf.cell(0, 8, "- Biochar (+10% growth, +5 tC/ha soil carbon)", ln=True)
        pdf.ln(5)
    
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Species Mix", ln=True)
    pdf.set_font("Arial", "", 12)
    for spec in species_mix:
        pdf.cell(0, 8, f"- {spec['common_name']} ({spec['species_name']}): {spec['pct']}% ({spec['density']} trees/ha)", ln=True)
    pdf.ln(10)
    
    pdf.set_font("Arial", "I", 10)
    pdf.cell(0, 10, "Note: This is a feasibility estimate per Verra VM0047. Actual carbon credits require validation.", ln=True)
    
    return bytes(pdf.output(dest='S'))

st.set_page_config(page_title="Carbon Credit Estimator", layout="wide")
st.title("🌍 Reforestation Carbon Credit Estimator (Verra VM0047)")

# Load species data
@st.cache_data
def load_species_data():
    df = pd.read_csv("allometric_equations.csv")
    return df

try:
    species_df = load_species_data()
except Exception as e:
    st.error(f"Error loading species  {e}")
    st.stop()

# Group species by region with common names
species_by_region = {}
for region in species_df['region'].dropna().unique():
    region_df = species_df[species_df['region'] == region]
    display_names = []
    for _, row in region_df.iterrows():
        common = row['common_name'] if pd.notna(row['common_name']) else row['species_name']
        display_names.append(f"{common} ({row['species_name']})")
    species_by_region[region] = sorted(list(set(display_names)))

regions = sorted(species_by_region.keys())

# Default location
if "lat" not in st.session_state:
    st.session_state.lat = -3.4653
    st.session_state.lon = -62.2153

# Map
st.subheader("📍 Select Project Location")
m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=4)
folium.Marker(
    [st.session_state.lat, st.session_state.lon],
    popup="Project Location",
    icon=folium.Icon(color="green")
).add_to(m)

map_data = st_folium(m, width=700, height=300)
if map_data and map_data["last_clicked"]:
    st.session_state.lat = map_data["last_clicked"]["lat"]
    st.session_state.lon = map_data["last_clicked"]["lng"]

# Auto-detect region from latitude
lat = st.session_state.lat
if -23.5 <= lat <= 23.5:
    auto_region = "tropical"
elif 23.5 < lat <= 66.5 or -66.5 <= lat < -23.5:
    auto_region = "temperate"
else:
    auto_region = "boreal"

# Sidebar inputs
st.sidebar.header("Project Details")
area_ha = st.sidebar.number_input("Area (hectares)", min_value=1, value=100)
project_years = st.sidebar.slider("Project Duration (years)", 20, 60, 40)
mortality = st.sidebar.number_input("Annual Mortality (%)", 0, 20, 4) / 100.0

# Buffer pool slider (VM0047: 10-20%)
buffer_pct = st.sidebar.slider("Buffer Pool (%)", 10, 20, 20)
buffer_fraction = buffer_pct / 100.0

# Management Practices (VM0047 Section 0.4)
st.sidebar.subheader("Management Practices")
col1, col2 = st.sidebar.columns(2)

# Irrigation (only if water-limited)
water_limited = col1.checkbox("Water-limited site?")
use_irrigation = col1.checkbox("✅ Use irrigation", disabled=not water_limited)

# Nutrients (only if nutrient-poor)
nutrient_poor = col2.checkbox("Nutrient-poor soil?")
use_nutrients = col2.checkbox("✅ Use fertilizers", disabled=not nutrient_poor)

# Biochar (always allowed)
use_biochar = st.sidebar.checkbox("✅ Apply biochar (5 t/ha)")

# Region selection
st.sidebar.subheader("Region & Species")
region_options = regions if regions else ["tropical", "temperate", "boreal"]
default_region_index = region_options.index(auto_region) if auto_region in region_options else 0
selected_region = st.sidebar.selectbox("Region (auto-detected)", region_options, index=default_region_index)

# Species options for selected region
species_options = species_by_region.get(selected_region, ["Teak (Tectona grandis)"])

# Initialize species list in session state
if "species_list" not in st.session_state:
    st.session_state.species_list = [
        {"display": species_options[0], "pct": 100, "density": 1100}
    ]

# Display species rows
for i, spec in enumerate(st.session_state.species_list):
    cols = st.sidebar.columns([3, 1, 1])
    spec["display"] = cols[0].selectbox(
        f"Species {i+1}",
        species_options,
        index=species_options.index(spec["display"]) if spec["display"] in species_options else 0,
        key=f"species_{i}"
    )
    spec["pct"] = cols[1].number_input(
        f"% {i+1}",
        min_value=0, max_value=100,
        value=spec["pct"],
        key=f"pct_{i}"
    )
    spec["density"] = cols[2].number_input(
        f"Density {i+1}",
        min_value=100, max_value=5000,
        value=spec["density"],
        key=f"density_{i}"
    )

# Add/remove buttons
col1, col2 = st.sidebar.columns(2)
if col1.button("➕ Add Species"):
    if len(st.session_state.species_list) < 5:
        st.session_state.species_list.append({
            "display": species_options[0],
            "pct": 0,
            "density": 1100
        })
if col2.button("➖ Remove Last"):
    if len(st.session_state.species_list) > 1:
        st.session_state.species_list.pop()

# Validate total percentage
total_pct = sum(spec["pct"] for spec in st.session_state.species_list)
if total_pct != 100:
    st.sidebar.warning(f"⚠️ Total: {total_pct}%. Must equal 100%!")

# Calculate button
if st.sidebar.button("Calculate Carbon Credits") and total_pct == 100:
    with st.spinner("Simulating 40-year growth (VM0047 compliant)..."):
        try:
            # Parse display names
            species_mix = []
            for spec in st.session_state.species_list:
                if spec["pct"] > 0:
                    display = spec["display"]
                    if "(" in display and ")" in display:
                        common_name = display.split(" (")[0]
                        species_name = display.split(" (")[1].rstrip(")")
                    else:
                        species_name = display
                        common_name = display
                    species_mix.append({
                        "species_name": species_name,
                        "common_name": common_name,
                        "region": selected_region,
                        "pct": spec["pct"],
                        "density": spec["density"]
                    })
            
            # Build management dict
            management = {
                "irrigation": use_irrigation,
                "nutrients": use_nutrients,
                "biochar": use_biochar
            }
            
            # Run simulation (returns GROSS values)
            sim = CarbonCreditSimulator("allometric_equations.csv")
            results = sim.simulate_project(
                area_ha=area_ha,
                species_mix=species_mix,
                project_years=project_years,
                annual_mortality=mortality,
                management=management
            )
            final = results[-1]
            
            # Calculate totals
            gross_biomass = final['co2e_gross_t']
            gross_soil = final.get('soil_co2e_gross_t', 0) * len(results)
            gross_total = gross_biomass + gross_soil
            net_total = gross_total * (1 - buffer_fraction)
            buffer_held = gross_total * buffer_fraction
            
            # Display results
            st.success(f"✅ Net Issuable Credits: **{net_total:,.0f} tonnes CO₂e**")
            st.caption(f"📊 Gross Sequestration: {gross_total:,.0f} tonnes CO₂e")
            st.progress(int(buffer_pct), f"Buffer Pool: {buffer_pct}% ({buffer_held:,.0f} tonnes held)")
            
            # Management uplift summary
            uplift_msg = []
            if use_irrigation: uplift_msg.append("Irrigation (+15%)")
            if use_nutrients: uplift_msg.append("Nutrients (+10%)")
            if use_biochar: uplift_msg.append("Biochar (+10% growth, +5 tC/ha soil)")
            if uplift_msg:
                st.info(f"🌱 Management uplift: {', '.join(uplift_msg)}")
            
            # Chart
            years = [r['year'] for r in results]
            gross_series = [r['co2e_gross_t'] + r.get('soil_co2e_gross_t', 0) for r in results]
            net_series = [g * (1 - buffer_fraction) for g in gross_series]
            chart_data = pd.DataFrame({
                "Year": years,
                "Gross CO2e": gross_series,
                "Net CO2e": net_series
            })
            st.line_chart(chart_data, x="Year", y=["Gross CO2e", "Net CO2e"])
            
            # Species mix table
            st.subheader("Your Species Mix")
            mix_df = pd.DataFrame([
                {
                    "Species": f"{s['common_name']} ({s['species_name']})",
                    "Percentage": f"{s['pct']}%",
                    "Density": s["density"]
                }
                for s in species_mix
            ])
            st.table(mix_df)
            
            # PDF Download
            pdf_bytes = generate_pdf_report(area_ha, species_mix, gross_total, buffer_pct, gross_soil, management)
            st.download_button(
                label="📥 Download VM0047 Report (PDF)",
                data=pdf_bytes,
                file_name="carbon_credit_vm0047_report.pdf",
                mime="application/pdf"
            )
            
        except Exception as e:
            st.error(f"Simulation error: {str(e)}")
            st.code(str(e))
else:
    if total_pct != 100:
        st.info("👈 Adjust species percentages to total 100%, then click **Calculate**")
    else:
        st.info("👈 Click **Calculate Carbon Credits** to run simulation")