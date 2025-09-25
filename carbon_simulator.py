import pandas as pd
import numpy as np

# Constants
CARBON_FRACTION = 0.47
CO2E_FACTOR = 3.67
ROOT_SHOOT_RATIO = 0.20

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
        """Estimate GROSS natural soil carbon sequestration (tonnes CO2e)."""
        soc_defaults = {
            "tropical": 75,
            "temperate": 100,
            "boreal": 150
        }
        initial_soc_t = area_ha * soc_defaults.get(region, 75)
        delta_soc_t = initial_soc_t * 0.10  # 10% increase
        return delta_soc_t * CO2E_FACTOR

    def simulate_project(
        self,
        area_ha,
        species_mix,
        project_years=40,
        annual_mortality=0.04,
        thinning_schedule=None,
        management=None
    ):
        if management is None:
            management = {"irrigation": False, "nutrients": False, "biochar": False}
        if thinning_schedule is None:
            thinning_schedule = []

        yearly_results = []
        current_trees = {}
        total_initial_trees = 0

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

                # Grow trees with management uplift
                growth_mm = self._get_dbh_growth_mm(species, data['region'], management)
                data['dbh_cm'] += growth_mm / 10.0

                agb_total = sum(
                    self.calculate_agb_kg(dbh, species, data['region'])
                    for dbh in data['dbh_cm']
                )
                total_biomass += agb_total * (1 + ROOT_SHOOT_RATIO)

            carbon_t = (total_biomass / 1000) * CARBON_FRACTION
            co2e_gross_t = carbon_t * CO2E_FACTOR

            yearly_results.append({
                'year': year,
                'trees_total': sum(d['count'] for d in current_trees.values()),
                'biomass_t': total_biomass / 1000,
                'carbon_t': carbon_t,
                'co2e_gross_t': co2e_gross_t,
                'soil_co2e_gross_t': 0
            })

        # Add soil carbon (natural + biochar)
        if species_mix:
            region = species_mix[0]['region']
            natural_soil = self.estimate_soil_carbon(area_ha, region, project_years)
            biochar_soil = 0
            if management.get("biochar"):
                # Jeffery et al. 2017: 5 tC/ha stable biochar
                biochar_soil = area_ha * 5 * CO2E_FACTOR
            total_soil_gross = natural_soil + biochar_soil
            annual_soil_gross = total_soil_gross / project_years

            for yr in yearly_results:
                yr['soil_co2e_gross_t'] = annual_soil_gross

        return yearly_results

    def _get_dbh_growth_mm(self, species, region, management):
        """Get DBH growth with management uplift."""
        tropical_fast = ["Acacia mangium", "Eucalyptus grandis", "Gmelina arborea"]
        if region == "tropical":
            base_growth = 20.0 if species in tropical_fast else 12.0
        elif region == "temperate":
            base_growth = 8.0
        else:
            base_growth = 5.0
        
        # Apply conservative uplifts (IPCC 2019, Jeffery et al. 2017)
        uplift = 1.0
        if management.get("irrigation"):
            uplift *= 1.15  # +15%
        if management.get("nutrients"):
            uplift *= 1.10  # +10%
        if management.get("biochar"):
            uplift *= 1.10  # +10% (growth boost)
        
        return base_growth * uplift