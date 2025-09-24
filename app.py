import streamlit as st
import folium
from streamlit_folium import st_folium
import os
import sys

# Add current dir to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from carbon_simulator import CarbonCreditSimulator

st.set_page_config(page_title="Carbon Credit Estimator", layout="wide")
st.title("🌍 Reforestation Carbon Credit Estimator (40-Year Verra Compliant)")

# Default location (start over Amazon)
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

# Capture click
map_data = st_folium(m, width=700, height=300)

# Update location if clicked
if map_data and map_data["last_clicked"]:
    st.session_state.lat = map_data["last_clicked"]["lat"]
    st.session_state.lon = map_data["last_clicked"]["lng"]

# Auto-detect region from latitude (simplified)
lat = st.session_state.lat
if -23.5 <= lat <= 23.5:
    auto_region = "tropical"
elif 23.5 < lat <= 66.5 or -66.5 <= lat < -23.5:
    auto_region = "temperate"
else:
    auto_region = "boreal"

st.sidebar.write(f"🌍 Auto-detected region: **{auto_region.title()}**")

# Sidebar inputs
st.sidebar.header("Project Details")
area_ha = st.sidebar.number_input("Area (hectares)", min_value=1, value=100)
project_years = st.sidebar.slider("Project Duration (years)", 20, 60, 40)

species1 = st.sidebar.selectbox("Species", [
    "Tectona grandis",
    "Acacia mearnsii",
    "Eucalyptus grandis",
    "Pinus sylvestris"
])
density = st.sidebar.number_input("Trees per hectare", 500, 2000, 1100)

# Override region if needed
region = st.sidebar.selectbox("Region (override auto-detect)", 
                             ["tropical", "temperate", "boreal"], 
                             index=0 if auto_region=="tropical" else 1)

mortality = st.sidebar.number_input("Annual Mortality (%)", 0, 20, 4) / 100.0

if st.sidebar.button("Calculate Carbon Credits"):
    with st.spinner("Simulating 40-year growth..."):
        try:
            sim = CarbonCreditSimulator("allometric_equations.csv")
            results = sim.simulate_project(
                area_ha=area_ha,
                species_mix=[{"species": species1, "region": region, "pct": 100, "density": density}],
                project_years=project_years,
                annual_mortality=mortality
            )
            final = results[-1]
            st.success(f"✅ Estimated Net Carbon Credits: **{final['co2e_net_t']:,.0f} tonnes CO₂e**")
            
            years = [r['year'] for r in results]
            credits = [r['co2e_net_t'] for r in results]
            chart_data = {"Year": years, "Net CO₂e (tonnes)": credits}
            st.line_chart(chart_data, x="Year", y="Net CO₂e (tonnes)")
            
        except Exception as e:
            st.error(f"Error: {str(e)}")
else:
    st.info("👈 Click on the map to set your project location, then click **Calculate**")
