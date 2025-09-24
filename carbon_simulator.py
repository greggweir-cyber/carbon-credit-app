import pandas as pd
import numpy as np

# Constants
CARBON_FRACTION = 0.47
CO2E_FACTOR = 3.67
ROOT_SHOOT_RATIO = 0.20
VERRA_BUFFER = 0.20  # 20% non-permanence buffer

class CarbonCreditSimulator:
    def __init__(self, data_path="allometric_equations.csv"):
        self.equations_df = pd.read_csv(data_path)
        self.coeff_cache = {}
        self._build_coeff_cache()

    def _build_coeff_cache(self):
        """Pre-load coefficients for fast lookup."""
        for _, row in self.equations_df.iterrows():
            key = (row['species_name'], row['region'])
            self.coeff_cache[key] = {
                'a': row['a'],
                'b': row['b'],
                'wood_density': row['wood_density'] if pd.notna(row['wood_density']) else 0.5
            }

    def get_coeffs(self, species, region):
        """Get allometric coefficients; fallback to generic if missing."""
        key = (species, region)
        if key in self.coeff_cache:
            return self.coeff_cache[key]
        # Try same species in any region
        for (sp, reg), coeffs in self.coeff_cache.items():
            if sp == species:
                return coeffs
        # Fallback: use Chave et al. 2014 tropical default
        return {'a': 0.0673, 'b': 2.3230, 'wood_density': 0.5}

    def calculate_agb_kg(self, dbh_cm, species, region):
        """Calculate Above-Ground Biomass (kg) for one tree."""
        coeffs = self.get_coeffs(species, region)
        agb = coeffs['a'] * (dbh_cm ** coeffs['b'])
        return max(agb, 0.01)  # Avoid zero

    def estimate_soil_carbon(self, area_ha, region, project_years=40):
        """Estimate additional soil carbon sequestration (tonnes CO2e) over project life."""
        # IPCC 2019 default soil organic carbon stocks (tonnes C / ha)
        soc_defaults = {
            "tropical": 75,
            "temperate": 100,
            "boreal": 150
        }
        initial_soc_t = area_ha * soc_defaults.get(region, 75)
        # Conservative 10% increase in SOC over 40 years (reforestation effect)
        delta_soc_t = initial_soc_t * 0.10
        # Convert to CO2e
        soil_co2e_t = delta_soc_t * CO2E_FACTOR
        return soil_co2e_t

    def simulate_project(
        self,
        area_ha,
        species_mix,  # List of dicts with 'species_name', 'region', 'pct', 'density'
        project_years=40,
        annual_mortality=0.04,
        thinning_schedule=None
    ):
        if thinning_schedule is None:
            thinning_schedule = []

        yearly_results = []
        current_trees = {}
        total_initial_trees = 0

        # Setup initial stand
        for mix in species_mix:
            species = mix['species_name']
            region = mix['region']
            density = mix['density']
            pct = mix['pct'] / 100.0
            trees = int(area_ha * density * pct)
            current_trees[species] = {
                'count': trees,
                'dbh_cm': np.full(trees, 1.0),
                'region': region
            }
            total_initial_trees += trees

        thin_dict = {t['year']: t['pct_remove']/100.0 for t in thinning_schedule}

        # Simulation loop
        for year in range(1, project_years + 1):
            total_biomass = 0.0

            for species, data in current_trees.items():
                if data['count'] <= 0:
                    continue

                # Apply mortality
                survivors = int(data['count'] * (1 - annual_mortality))
                if survivors <= 0:
                    data['count'] = 0
                    data['dbh_cm'] = np.array([])
                    continue

                # Keep largest trees (simulate competition)
                if len(data['dbh_cm']) > survivors:
                    data['dbh_cm'] = np.sort(data['dbh_cm'])[-survivors:]
                data['count'] = survivors

                # Apply thinning
                if year in thin_dict:
                    remove_frac = thin_dict[year]
                    keep_count = int(survivors * (1 - remove_frac))
                    if keep_count > 0:
                        data['dbh_cm'] = np.sort(data['dbh_cm'])[-keep_count:]
                        data['count'] = keep_count
                    else:
                        data['count'] = 0
                        data['dbh_cm'] = np.array([])

                # Grow trees
                growth_mm = self._get_dbh_growth_mm(species, data['region'])
                data['dbh_cm'] += growth_mm / 10.0

                # Calculate biomass
                agb_total = sum(
                    self.calculate_agb_kg(dbh, species, data['region'])
                    for dbh in data['dbh_cm']
                )
                total_biomass += agb_total * (1 + ROOT_SHOOT_RATIO)

            # Carbon accounting (biomass only)
            carbon_t = (total_biomass / 1000) * CARBON_FRACTION
            co2e_gross_t = carbon_t * CO2E_FACTOR
            co2e_net_t = co2e_gross_t * (1 - VERRA_BUFFER)

yearly_results.append({
    'year': year,
    'trees_total': sum(d['count'] for d in current_trees.values()),
    'biomass_t': total_biomass / 1000,
    'carbon_t': carbon_t,
    'co2e_gross_t': co2e_gross_t,          # ✅ Keep gross
    'co2e_net_t': co2e_gross_t,            # Will apply buffer later
    'soil_co2e_gross_t': 0                 # Will add soil gross later
})

        # Add soil carbon (distributed evenly over project life)
# After simulation loop, add soil GROSS (no buffer)
if species_mix:
    region = species_mix[0]['region']
    soil_co2e_total_gross = self.estimate_soil_carbon(area_ha, region, project_years)
    annual_soil_gross = soil_co2e_total_gross / project_years
    for yr in yearly_results:
        yr['soil_co2e_gross_t'] = annual_soil_gross
        yr['total_gross_t'] = yr['co2e_gross_t'] + annual_soil_gross

return yearly_results  # Returns GROSS values only    def _get_dbh_growth_mm(self, species, region):
        """Get DBH growth rate (mm/year) based on species and region."""
        # Fast-growing tropical species
        tropical_fast = [
            "Acacia mangium", "Eucalyptus grandis", "Gmelina arborea",
            "Paulownia tomentosa", "Leucaena leucocephala"
        ]
        if region == "tropical":
            return 20.0 if species in tropical_fast else 12.0
        elif region == "temperate":
            return 8.0
        else:  # boreal
            return 5.0