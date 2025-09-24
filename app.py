import streamlit as st
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from carbon_simulator import CarbonCreditSimulator

st.set_page_config(page_title="Carbon Credit Estimator", layout="wide")
st.title("🌍 Reforestation Carbon Credit Estimator (40-Year Verra Compliant)")

st.sidebar.header("Project Details")
area_ha = st.sidebar.number_input("Area (hectares)", min_value=1, value=100)
project_years = st.sidebar.slider("Project Duration (years)", 20, 60, 40)

st.sidebar.subheader("Species Mix")
species1 = st.sidebar.selectbox("Species", [
    "Tectona grandis",
    "Acacia mearnsii",
    "Eucalyptus grandis",
    "Pinus sylvestris"
])
density = st.sidebar.number_input("Trees per hectare", 500, 2000, 1100)

region = "tropical" if species1 in ["Tectona grandis", "Acacia mearnsii", "Eucalyptus grandis"] else "temperate"
mortality = st.sidebar.number_input("Annual Mortality (%)", 0, 20, 4) / 100.0

if st.sidebar.button("Calculate Carbon Credits"):
    with st.spinner("Simulating 40-year growth..."):
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
else:
    st.info("👈 Enter your project details in the sidebar and click **Calculate**")