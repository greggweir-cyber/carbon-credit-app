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

# PDF Generator (updated for soil carbon)
def generate_pdf_report(area_ha, species_mix, final_credits, soil_credits=0):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "🌍 Carbon Credit Estimation Report", ln=True, align="C")
    pdf.ln(10)
    
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 10, f"Date: {datetime.now().strftime('%Y-%m-%d')}", ln=True)
    pdf.cell(0, 10, f"Project Area: {area_ha} hectares", ln=True)
    
    total_credits = final_credits + soil_credits
    pdf.cell(0, 10, f"Estimated Net Carbon Credits (40 years): {total_credits:,.0f} tonnes CO₂e", ln=True)
    pdf.cell(0, 8, f"  - Biomass: {final_credits:,.0f} tonnes CO₂e", ln=True)
    pdf.cell(0, 8, f"  - Soil: {soil_credits:,.0f} tonnes CO₂e", ln=True)
    pdf.ln(10)
    
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Species Mix", ln=True)
    pdf.set_font("Arial", "", 12)
    for spec in species_mix:
        pdf.cell(0, 8, f"- {spec['common_name']} ({spec['species_name']}): {spec['pct']}% ({spec['density']} trees/ha)", ln=True)
    pdf.ln(10)
    
    pdf.set_font("Arial", "I", 10)
    pdf.cell(0, 10, "Note: This is a feasibility estimate. Actual carbon credits require validation per Verra VM0042.", ln=True)
    
    return pdf.output(dest='S').encode('latin-1')

st.set_page_config(page_title="Carbon Credit Estimator", layout="wide")
st.title("🌍 Reforestation Carbon Credit Estimator (40-Year Verra Compliant)")

# Load species data
@st.cache_data
def load_species_data():
    df = pd.read_csv("allometric_equations.csv")
    return df

try:
    species_df = load_species_data()
except Exception as e:
    st.error(f"Error loading species data: {e}")
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
    with st.spinner("Simulating 40-year growth (biomass + soil)..."):
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
            
            # Run simulation
            sim = CarbonCreditSimulator("allometric_equations.csv")
            results = sim.simulate_project(
                area_ha=area_ha,
                species_mix=species_mix,
                project_years=project_years,
                annual_mortality=mortality
            )
            final = results[-1]
            
            # Extract biomass and soil credits
            biomass_credits = final['co2e_net_t'] - final.get('soil_co2e_t', 0)
            soil_credits = final.get('soil_co2e_t', 0) * len(results)  # Total soil
            total_credits = biomass_credits + soil_credits
            
            st.success(f"✅ Estimated Net Carbon Credits: **{total_credits:,.0f} tonnes CO₂e**")
            st.caption(f"🌳 Biomass: {biomass_credits:,.0f} | 🌱 Soil: {soil_credits:,.0f}")
            
            # Chart
            years = [r['year'] for r in results]
            total_credits_yearly = [r['co2e_net_t'] for r in results]
            chart_data = {"Year": years, "Net CO₂e (tonnes)": total_credits_yearly}
            st.line_chart(chart_data, x="Year", y="Net CO₂e (tonnes)")
            
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
            pdf_bytes = generate_pdf_report(area_ha, species_mix, biomass_credits, soil_credits)
            st.download_button(
                label="📥 Download PDF Report",
                data=pdf_bytes,
                file_name="carbon_credit_report.pdf",
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