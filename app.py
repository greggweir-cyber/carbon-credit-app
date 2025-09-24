
import streamlit as st
import folium
from streamlit_folium import st_folium
import os
import sys
import pandas as pd

# Add current dir to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from carbon_simulator import CarbonCreditSimulator

st.set_page_config(page_title="Carbon Credit Estimator", layout="wide")
st.title("🌍 Reforestation Carbon Credit Estimator (40-Year Verra Compliant)")

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

# Auto-detect region
lat = st.session_state.lat
if -23.5 <= lat <= 23.5:
    auto_region = "tropical"
elif 23.5 < lat <= 66.5 or -66.5 <= lat < -23.5:
    auto_region = "temperate"
else:
    auto_region = "boreal"

st.sidebar.write(f"🌍 Auto-detected region: **{auto_region.title()}**")

# Project inputs
st.sidebar.header("Project Details")
area_ha = st.sidebar.number_input("Area (hectares)", min_value=1, value=100)
project_years = st.sidebar.slider("Project Duration (years)", 20, 60, 40)
mortality = st.sidebar.number_input("Annual Mortality (%)", 0, 20, 4) / 100.0

# Species input
st.sidebar.subheader("Species Mix")
region = st.sidebar.selectbox("Region (override)", 
                             ["tropical", "temperate", "boreal"], 
                             index=0 if auto_region=="tropical" else 1)

# Available species by region
species_options = {
    "tropical": ["Tectona grandis", "Acacia mearnsii", "Eucalyptus grandis"],
    "temperate": ["Pinus sylvestris", "Quercus robur", "Fagus sylvatica"],
    "boreal": ["Picea abies", "Pinus sylvestris", "Betula pendula"]
}

# Initialize session state for species list
if "species_list" not in st.session_state:
    st.session_state.species_list = [
        {"species": species_options[region][0], "pct": 100, "density": 1100}
    ]

# Display species rows
for i, spec in enumerate(st.session_state.species_list):
    cols = st.sidebar.columns([2, 1, 1])
    spec["species"] = cols[0].selectbox(
        f"Species {i+1}", 
        species_options[region],
        index=species_options[region].index(spec["species"]) if spec["species"] in species_options[region] else 0,
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
    if len(st.session_state.species_list) < 5:  # Max 5 species
        st.session_state.species_list.append({
            "species": species_options[region][0], 
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
    with st.spinner("Simulating 40-year growth..."):
        try:
            # Prepare species mix
            species_mix = []
            for spec in st.session_state.species_list:
                if spec["pct"] > 0:
                    species_mix.append({
                        "species": spec["species"],
                        "region": region,
                        "pct": spec["pct"],
                        "density": spec["density"]
                    })
            
            sim = CarbonCreditSimulator("allometric_equations.csv")
            results = sim.simulate_project(
                area_ha=area_ha,
                species_mix=species_mix,
                project_years=project_years,
                annual_mortality=mortality
            )
            final = results[-1]
            st.success(f"✅ Estimated Net Carbon Credits: **{final['co2e_net_t']:,.0f} tonnes CO₂e**")
            
            # Chart
            years = [r['year'] for r in results]
            credits = [r['co2e_net_t'] for r in results]
            chart_data = {"Year": years, "Net CO₂e (tonnes)": credits}
            st.line_chart(chart_data, x="Year", y="Net CO₂e (tonnes)")
            
            # Show species mix
            st.subheader("Your Species Mix")
            mix_df = pd.DataFrame([
                {"Species": s["species"], "Percentage": f"{s['pct']}%", "Density": s["density"]}
                for s in species_mix
            ])
            st.table(mix_df)
            
        except Exception as e:
            st.error(f"Error: {str(e)}")
else:
    if total_pct != 100:
        st.info("👈 Adjust species percentages to total 100%, then click **Calculate**")
    else:
        st.info("👈 Click **Calculate Carbon Credits** to run simulation")