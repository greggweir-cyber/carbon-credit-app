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
        self.equations_df['species_region'] = (
            self.equations_df['species_name'] + ";" + self.equations_df['region']
        )
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
        # Fallback: use Chave et al. 2014 tropical default
        return {'a': 0.0673, 'b': 2.3230, 'wood_density': 0.5}

    def calculate_agb_kg(self, dbh_cm, species, region):
        """Calculate Above-Ground Biomass (kg) for one tree."""
        coeffs = self.get_coeffs(species, region)
        agb = coeffs['a'] * (dbh_cm ** coeffs['b'])
        return max(agb, 0.01)  # Avoid zero

    def simulate_project(
        self,
        area_ha,
        species_mix,
        project_years=40,
        annual_mortality=0.04,
        thinning_schedule=None
    ):
        if thinning_schedule is None:
            thinning_schedule = []

        yearly_results = []
        current_trees = {}
        total_initial_trees = 0

        for mix in species_mix:
            species = mix['species']
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

        for year in range(1, project_years + 1):
            total_biomass = 0.0

            for species, data in current_trees.items():
                if data['count'] <= 0:
                    continue

                survivors = int(data['count'] * (1 - annual_mortality))
                if survivors <= 0:
                    data['count'] = 0
                    data['dbh_cm'] = np.array([])
                    continue

                if len(data['dbh_cm']) > survivors:
                    data['dbh_cm'] = np.sort(data['dbh_cm'])[-survivors:]
                data['count'] = survivors

                if year in thin_dict:
                    remove_frac = thin_dict[year]
                    keep_count = int(survivors * (1 - remove_frac))
                    if keep_count > 0:
                        data['dbh_cm'] = np.sort(data['dbh_cm'])[-keep_count:]
                        data['count'] = keep_count
                    else:
                        data['count'] = 0
                        data['dbh_cm'] = np.array([])

                growth_mm = self._get_dbh_growth_mm(species, data['region'])
                data['dbh_cm'] += growth_mm / 10.0

                agb_total = sum(
                    self.calculate_agb_kg(dbh, species, data['region'])
                    for dbh in data['dbh_cm']
                )
                total_biomass += agb_total * (1 + ROOT_SHOOT_RATIO)

            carbon_t = (total_biomass / 1000) * CARBON_FRACTION
            co2e_gross_t = carbon_t * CO2E_FACTOR
            co2e_net_t = co2e_gross_t * (1 - VERRA_BUFFER)

            yearly_results.append({
                'year': year,
                'trees_total': sum(d['count'] for d in current_trees.values()),
                'biomass_t': total_biomass / 1000,
                'carbon_t': carbon_t,
                'co2e_gross_t': co2e_gross_t,
                'co2e_net_t': co2e_net_t
            })

        return yearly_results

    def _get_dbh_growth_mm(self, species, region):
        tropical_fast = ["Acacia mearnsii", "Eucalyptus grandis"]
        if region == "tropical":
            return 20.0 if species in tropical_fast else 12.0
        elif region == "temperate":
            return 8.0
        else:
            return 5.0