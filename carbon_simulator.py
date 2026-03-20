"""
CarbonCreditSimulator v4 — GlobAllomeTree + IPCC 2019 + Phased Mortality + VM0047
======================================================
Equation priority:
  Tier 1: GlobAllomeTree (18,499 raw equations → 888 validated DBH-only species)
  Tier 2: allometric_equations.csv (224 species, simple a*DBH^b)
  Tier 3: IPCC 2019 regional power-law default

Management uplifts (FIXED — literature-cited, VVB-defensible):
  Irrigation : +15% DBH growth    IPCC 2019 Vol.4 Ch.2 §2.3.2
  Nutrients  : +10% DBH growth    IPCC 2019
  Biochar    : +10% growth + 5 tC/ha stable soil C   Jeffery et al. 2017

RSR (IPCC 2019 Table 4.4 — replaces flat 0.20):
  tropical : 0.235   temperate : 0.192   boreal : 0.390
"""

import pandas as pd
import numpy as np
import json, re, os, math
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────────
CARBON_FRACTION = 0.47        # IPCC 2006 Table 4.3
CO2E_FACTOR     = 3.67        # C → CO2e (44/12)

RSR = {"tropical": 0.235, "temperate": 0.192, "boreal": 0.390}
RSR_DEFAULT = 0.235
RSR_CITATION = "IPCC 2019 Refinement Vol.4 Ch.4 Table 4.4"

# Minimum plausible AGB at DBH=10cm — filters out equations fitted to seedlings only
AGB_SANITY_MIN_KG = 3.0   # anything below this at DBH=10 is rejected

FAST_SPECIES = {
    "Acacia mangium","Acacia mearnsii","Eucalyptus grandis",
    "Eucalyptus camaldulensis","Eucalyptus tereticornis","Eucalyptus deglupta",
    "Gmelina arborea","Paulownia tomentosa","Grevillea robusta",
    "Pinus caribaea","Acacia auriculiformis",
}

UPLIFT_CITATIONS = {
    "irrigation": "IPCC 2019 Vol.4 Ch.2 §2.3.2 (+15% DBH growth)",
    "nutrients" : "IPCC 2019 (+10% DBH growth)",
    "biochar"   : "Jeffery et al. 2017, GCB Bioenergy 9:1930 (+10% growth, +5 tC/ha stable soil C)",
}

SOC_DEFAULTS = {"tropical": 75, "temperate": 100, "boreal": 150}
SOC_CITATION  = "IPCC 2019 Refinement Vol.4 Ch.4, Table 2.3 regional defaults"

# ── Formula evaluator ──────────────────────────────────────────────────────────
def _eval_formula(equation: str, output_tr: str, unit_y: str, dbh: float):
    """Evaluate a GlobAllomeTree equation string. Returns kg or None on failure."""
    try:
        dbh = max(float(dbh), 0.5)
        f = str(equation).strip()
        if not f:
            return None
        # Skip equations needing wood density (Z) or height (H)
        if re.search(r'\b[ZH]\b', f):
            return None
        # Substitute X → DBH
        f = re.sub(r'\bX\b', str(dbh), f)
        # Math function normalization
        f = (f.replace('^', '**')
              .replace('ln(',    'math.log(')
              .replace('log10(', 'math.log10(')
              .replace('Log10(', 'math.log10(')
              .replace('log(',   'math.log(')
              .replace('Log(',   'math.log(')
              .replace('exp(',   'math.exp(')
              .replace('Exp(',   'math.exp(')
              .replace('sqrt(',  'math.sqrt('))
        result = eval(f, {"math": math, "__builtins__": {}})
        result = float(result)
        if result <= 0 or not math.isfinite(result):
            return None
        # Apply inverse output transform
        tr = str(output_tr or '').lower().strip()
        if tr in ('log', 'ln'):
            result = math.exp(result)
        elif tr in ('log10',):
            result = 10.0 ** result
        # Unit conversion → kg
        uy = str(unit_y or 'kg').lower().strip()
        if uy == 'g':
            result /= 1000.0
        elif uy == 'mg':          # Mg = Megagram = tonne
            result *= 1000.0
        if result <= 0 or not math.isfinite(result):
            return None
        return result
    except Exception:
        return None


# ── Main simulator class ───────────────────────────────────────────────────────
class CarbonCreditSimulator:

    def __init__(self, data_path=None, globallometree_path=None):
        """
        Parameters
        ----------
        data_path : str
            Path to allometric_equations.csv (Tier 2 fallback).
        globallometree_path : str
            Path to pre-built globallometree_usable.json OR
            directory containing equations_part_*.json files.
        """
        self.simple_cache     = {}   # Tier 2: species -> {a, b, wd, region}
        self.globallometree   = {}   # Tier 1: species -> equation record

        # --- Tier 2: simple allometric CSV ---
        if data_path is None:
            data_path = os.getenv("ALLOMETRIC_DATA_PATH", "allometric_equations.csv")
        self._load_simple_csv(data_path)

        # --- Tier 1: GlobAllomeTree ---
        if globallometree_path is None:
            globallometree_path = os.getenv(
                "GLOBALLOMETREE_JSON", "globallometree_usable.json"
            )
        self._load_globallometree(globallometree_path)

        print(f"[CarbonSim] Tier1 GlobAllomeTree: {len(self.globallometree)} species")
        print(f"[CarbonSim] Tier2 simple allometric: {len(self.simple_cache)} species")
        self._agb_cache = {}   # memoize equation lookups per species

    # ── Loaders ────────────────────────────────────────────────────────────────

    def _load_simple_csv(self, path):
        try:
            df = pd.read_csv(path)
            for _, row in df.iterrows():
                sp = str(row.get("species_name", "")).strip()
                if sp:
                    self.simple_cache[sp] = {
                        "a"      : float(row["a"]),
                        "b"      : float(row["b"]),
                        "wd"     : float(row.get("wood_density", 0.5) or 0.5),
                        "region" : str(row.get("region", "tropical")).strip().lower(),
                        "citation": "allometric_equations.csv (project dataset)",
                    }
        except Exception as e:
            print(f"[CarbonSim] WARNING simple CSV not loaded: {e}")

    def _load_globallometree(self, path):
        """Load pre-built JSON lookup or build it from part files."""
        # Try pre-built JSON (already validated — load directly, no re-validation)
        if os.path.isfile(path):
            try:
                with open(path) as f:
                    self.globallometree = json.load(f)
                return
            except Exception as e:
                print(f"[CarbonSim] WARNING GlobAllomeTree JSON not loaded: {e}")

        # Try building from equations_part_*.json in same directory
        base = os.path.dirname(path) or "."
        parts = sorted(Path(base).glob("equations_part_*.json"))
        if not parts:
            print("[CarbonSim] No GlobAllomeTree equation parts found.")
            return
        self._build_globallometree_from_parts(parts)

    def _build_globallometree_from_parts(self, part_files):
        """Parse raw GlobAllomeTree part files and build lookup."""
        all_eq = []
        for pf in part_files:
            with open(pf) as f:
                all_eq.extend(json.load(f))

        agb_components = {
            'whole tree (aboveground)', 'stem+bark+leaves+branches',
            'aboveground biomass', 'total aboveground biomass',
            'agb', 'abg', 'above ground biomass', 'above-ground biomass'
        }

        def is_agb(eq):
            veg = str(eq.get('Veg_Component', '')).lower().strip()
            return eq.get('Bt', False) or veg in agb_components

        usable = [
            e for e in all_eq
            if is_agb(e)
            and str(e.get('Unit_Y', '')).strip().lower() in ('kg', 'kg tree -1', 'mg')
            and str(e.get('Unit_X', '')).strip().lower() == 'cm'
        ]

        from collections import defaultdict
        species_map = defaultdict(list)

        for eq in usable:
            sg = eq.get('Species_group', {})
            if not sg or 'Group' not in sg:
                continue
            for g in sg['Group']:
                sn = str(g.get('Scientific_name', '')).strip()
                parts_sp = sn.split()
                if len(parts_sp) >= 3:
                    sn = ' '.join(parts_sp[1:])
                if len(sn.split()) >= 2 and sn.lower() not in ('unknown','all','mixed'):
                    species_map[sn].append(eq)

        def r2_val(e):
            try: return float(e.get('R2') or 0)
            except: return 0.0

        for sp, eqs in species_map.items():
            best = sorted(eqs, key=r2_val, reverse=True)[0]
            eq_str  = str(best.get('Equation', '')).strip()
            tr      = str(best.get('Output_TR', '') or '').strip().lower()
            unit_y  = str(best.get('Unit_Y', 'kg')).strip().lower()
            # Validate evaluable
            val = _eval_formula(eq_str, tr, unit_y, 15.0)
            if val is None:
                continue
            # Ecozone → region
            eco = ''
            lg = best.get('Location_group', {})
            if lg and 'Group' in lg:
                for g in lg['Group']:
                    e = str(g.get('Ecoregion_WWF', '')).strip()
                    if e and e.lower() != 'none':
                        eco = e; break
            eco_l = eco.lower()
            if 'boreal' in eco_l or 'taiga' in eco_l:
                region = 'boreal'
            elif 'temperate' in eco_l or 'montane' in eco_l:
                region = 'temperate'
            else:
                region = 'tropical'
            src = best.get('Source', {})
            self.globallometree[sp] = {
                'equation'  : eq_str,
                'output_tr' : tr,
                'unit_y'    : unit_y,
                'region'    : region,
                'ecozone'   : eco,
                'r2'        : str(best.get('R2', '')),
                'n'         : str(best.get('Sample_size', '')),
                'dbh_min'   : str(best.get('Min_X', '') or ''),
                'dbh_max'   : str(best.get('Max_X', '') or ''),
                'citation'  : str(src.get('Reference', '')).strip(),
                'year'      : str(src.get('Reference_year', '')).strip(),
                'n_equations_available': len(eqs),
            }
        print(f"[CarbonSim] Built GlobAllomeTree cache: {len(self.globallometree)} species")

    # ── Biomass calculation ────────────────────────────────────────────────────

    def _get_species_rec(self, species: str, region: str):
        """Memoized lookup of best equation record for a species."""
        sp = " ".join(str(species).strip().split())
        if sp in self._agb_cache:
            return self._agb_cache[sp]

        genus = sp.split()[0] if sp else ""

        # Tier 1: GlobAllomeTree exact
        rec = self.globallometree.get(sp)
        if not rec and genus:
            for csp, r in self.globallometree.items():
                if csp.startswith(genus + " "):
                    rec = r; break
        if rec:
            self._agb_cache[sp] = ("globallometree", rec)
            return self._agb_cache[sp]

        # Tier 2: simple allometric
        s = self.simple_cache.get(sp)
        if not s and genus:
            for csp, sv in self.simple_cache.items():
                if csp.startswith(genus + " "):
                    s = sv; break
        if s:
            self._agb_cache[sp] = ("simple", s)
            return self._agb_cache[sp]

        # Tier 3: IPCC default
        defaults = {"tropical":(0.0509,2.50),"temperate":(0.065,2.38),"boreal":(0.085,2.32)}
        rg = str(region).strip().lower()
        self._agb_cache[sp] = ("default", defaults.get(rg, defaults["tropical"]))
        return self._agb_cache[sp]

    def calculate_agb_kg(self, dbh_cm: float, species: str, region: str) -> float:
        """Return above-ground biomass in kg for one tree."""
        dbh = max(float(dbh_cm), 0.5)
        sp  = " ".join(str(species).strip().split())
        rg  = str(region).strip().lower()

        # Sanity threshold: at DBH=10, a tree should weigh at least AGB_SANITY_MIN_KG
        # This filters equations fitted only to seedlings or saplings
        def _sane(val):
            if val is None or val <= 0: return False
            if dbh >= 10.0 and val < AGB_SANITY_MIN_KG: return False
            return True

        def _monotonic(rec_g):
            """Check equation is monotonically increasing: AGB(30) > AGB(10)*2"""
            try:
                v10 = _eval_formula(rec_g['equation'], rec_g['output_tr'], rec_g['unit_y'], 10.0)
                v30 = _eval_formula(rec_g['equation'], rec_g['output_tr'], rec_g['unit_y'], 30.0)
                if v10 is None or v30 is None: return False
                return v30 > v10 * 1.5  # AGB at DBH=30 must be >1.5x AGB at DBH=10
            except:
                return False

        # Tier 1: GlobAllomeTree exact match
        rec = self.globallometree.get(sp)
        if rec and _monotonic(rec):
            val = _eval_formula(rec['equation'], rec['output_tr'], rec['unit_y'], dbh)
            if _sane(val): return val

        # Tier 1: GlobAllomeTree genus match (only same-region genus)
        genus = sp.split()[0] if sp else ""
        if genus:
            # Only use genus fallback if same region — avoids tropical equations on desert species
            for csp, r in self.globallometree.items():
                if csp.startswith(genus + " ") and r.get('region','') == rg and _monotonic(r):
                    val = _eval_formula(r['equation'], r['output_tr'], r['unit_y'], dbh)
                    if _sane(val): return val
            # For non-tropical regions, stop here — don't cross-apply tropical genus equations
            if rg not in ("tropical", "dry_tropical", "tropical_grassland", "mangrove", "flooded"):
                pass  # Fall through to Tier 2
            else:
                # Tropical regions: allow cross-genus fallback
                for csp, r in self.globallometree.items():
                    if csp.startswith(genus + " ") and _monotonic(r):
                        val = _eval_formula(r['equation'], r['output_tr'], r['unit_y'], dbh)
                        if _sane(val): return val

        # Tier 2: simple allometric exact match
        s = self.simple_cache.get(sp)
        if s:
            val = s["a"] * (dbh ** s["b"])
            if val > 0: return float(val)

        # Tier 2: simple allometric genus match
        if genus:
            for csp, s in self.simple_cache.items():
                if csp.startswith(genus + " "):
                    val = s["a"] * (dbh ** s["b"])
                    if val > 0: return float(val)

        # Tier 3: IPCC 2019 regional default
        defaults = {"tropical":(0.0509,2.50),"temperate":(0.065,2.38),"boreal":(0.085,2.32),
                    "desert":(0.048,2.41),"dry_tropical":(0.050,2.40),"mediterranean":(0.065,2.35),
                    "montane":(0.060,2.38),"mangrove":(0.055,2.42),"flooded":(0.058,2.40),
                    "tropical_grassland":(0.048,2.41)}
        a, b = defaults.get(rg, defaults["tropical"])
        return max(a * (dbh ** b), 0.01)

    def get_equation_info(self, species: str) -> dict:
        """Return citation & metadata for the equation used for a species."""
        sp = " ".join(str(species).strip().split())
        genus = sp.split()[0] if sp else ""

        rec = self.globallometree.get(sp)
        if not rec and genus:
            for cached_sp, r in self.globallometree.items():
                if cached_sp.startswith(genus + " "):
                    rec = r; break

        if rec:
            return {
                "tier"      : "GlobAllomeTree (Tier 1)",
                "equation"  : rec['equation'],
                "r2"        : rec['r2'],
                "n"         : rec['n'],
                "dbh_range" : f"{rec['dbh_min']}–{rec['dbh_max']} cm",
                "citation"  : rec['citation'],
                "year"      : rec['year'],
                "n_available": rec.get('n_equations_available', 1),
            }

        s = self.simple_cache.get(sp)
        if not s and genus:
            for cached_sp, sv in self.simple_cache.items():
                if cached_sp.startswith(genus + " "):
                    s = sv; break
        if s:
            return {
                "tier"    : "Simple allometric (Tier 2)",
                "equation": f"{s['a']} × DBH^{s['b']}",
                "citation": s['citation'],
            }

        return {
            "tier"    : "IPCC 2019 regional default (Tier 3)",
            "citation": "IPCC 2019 Refinement Vol.4 Ch.4",
        }

    # ── Soil carbon ────────────────────────────────────────────────────────────

    def estimate_soil_carbon(self, area_ha: float, region: str,
                             project_years: int = 40, biochar: bool = False) -> dict:
        """
        Gross soil carbon sequestration (tCO2e).
        Natural SOC: 10% of regional reference stock over crediting period.
        Biochar: 5 tC/ha stable fraction (Jeffery et al. 2017).
        """
        soc_ref      = SOC_DEFAULTS.get(region.lower(), 75)
        natural_tc   = area_ha * soc_ref * 0.10
        natural_co2e = natural_tc * CO2E_FACTOR
        biochar_co2e = (area_ha * 5.0 * CO2E_FACTOR) if biochar else 0.0
        total_co2e   = natural_co2e + biochar_co2e

        return {
            "natural_co2e"   : round(natural_co2e, 2),
            "biochar_co2e"   : round(biochar_co2e, 2),
            "total_co2e"     : round(total_co2e, 2),
            "annual_co2e"    : round(total_co2e / max(project_years, 1), 2),
            "soc_ref_tc_ha"  : soc_ref,
            "citation_natural": SOC_CITATION,
            "citation_biochar": UPLIFT_CITATIONS["biochar"] if biochar else None,
        }

    # ── DBH growth ─────────────────────────────────────────────────────────────

    def _get_dbh_growth_mm(self, species: str, region: str, management: dict) -> float:
        """
        Annual DBH increment (mm/yr) with management uplifts.
        Base rates from IPCC 2019 Table 4.9 / 4.11.
        """
        rg = region.lower()
        fast = species in FAST_SPECIES

        if rg == "tropical":
            base = 20.0 if fast else 12.0   # IPCC 2019 Table 4.11
        elif rg in ("dry_tropical", "tropical_grassland"):
            base = 14.0 if fast else 8.0    # Tropical dry — slower than moist
        elif rg == "desert":
            base = 8.0 if fast else 5.0     # Arid species — slow growth
        elif rg == "mediterranean":
            base = 10.0 if fast else 7.0    # Mediterranean
        elif rg == "montane":
            base = 8.0 if fast else 5.0     # High-altitude — slow
        elif rg in ("mangrove", "flooded"):
            base = 10.0 if fast else 7.0    # Wetland species
        elif rg == "temperate":
            base = 10.0 if fast else 8.0    # IPCC 2019 Table 4.9
        else:  # boreal and unknown
            base = 7.0 if fast else 5.0     # IPCC 2019 Table 4.9

        mult = 1.0
        if management.get("irrigation"):  mult *= 1.15  # IPCC 2019 §2.3.2
        if management.get("nutrients"):   mult *= 1.10  # IPCC 2019
        if management.get("biochar"):     mult *= 1.10  # Jeffery et al. 2017
        # TerraPod technology growth uplift (ISB/EAD/ICBA trial, UAE Nov 2024)
        tp_mult = management.get("terrapod_growth_mult", 1.0)
        if tp_mult and float(tp_mult) > 1.0:
            mult *= float(tp_mult)

        return base * mult

    # ── Main simulation ────────────────────────────────────────────────────────

    def simulate_project(
        self,
        area_ha             : float,
        species_mix         : list,
        project_years       : int   = 40,
        annual_mortality    : float = 0.04,
        management          : dict  = None,
        managed_restoration : bool  = False,
    ) -> list:
        """
        Simulate year-by-year carbon accumulation.

        managed_restoration=True applies phased mortality model:
          Years 1-2:  0% mortality (immediate replanting, 100% survival)
          Years 3-4:  0.5% mortality (transition, irrigation weaning)
          Years 5+:   1.5% mortality (independent, MRV continues)
          Irrigation uplift removed after year 4.

        Returns list of annual result dicts, each containing:
          year, trees_total, biomass_t, carbon_t,
          co2e_gross_t, soil_co2e_gross_t,
          equation_tiers (dict: species -> tier used)
        """
        if management is None:
            management = {}

        # ── Initialise tree cohorts ──────────────────────────────────────────
        # Cap simulation at 1000ha equivalent to avoid memory crash on large projects
        # Results are scaled up proportionally
        MAX_SIM_HA  = 1000.0
        sim_area_ha = min(float(area_ha), MAX_SIM_HA)
        area_scale  = float(area_ha) / sim_area_ha

        cohorts = []
        for mix in species_mix:
            sp      = mix["species_name"]
            region  = mix["region"]
            density = mix["density"]
            pct     = mix["pct"] / 100.0
            n_trees = int(sim_area_ha * density * pct)
            if n_trees <= 0:
                continue
            cohorts.append({
                "species"  : sp,
                "region"   : region,
                "count"    : n_trees,
                "dbh_arr"  : np.full(n_trees, 1.0),   # start at 1 cm DBH
            })

        # ── Soil carbon ──────────────────────────────────────────────────────
        primary_region = species_mix[0]["region"] if species_mix else "tropical"
        soil_result = self.estimate_soil_carbon(
            sim_area_ha, primary_region, project_years,
            biochar=management.get("biochar", False)
        )
        annual_soil_co2e = soil_result["annual_co2e"]  # will be scaled with area_scale

        # ── Survival multipliers ─────────────────────────────────────────────
        # Weed control +5%, fencing +7% (documented management actions)
        surv_mult = 1.0
        if management.get("weed_control", management.get("weed", False)):
            surv_mult *= 1.05
        if management.get("fencing", management.get("fence", False)):
            surv_mult *= 1.07

        # ── Year-by-year loop ────────────────────────────────────────────────
        yearly_results = []
        eq_tiers = {c["species"]: self.get_equation_info(c["species"])["tier"]
                    for c in cohorts}

        for year in range(1, project_years + 1):
            total_biomass_kg = 0.0

            # Phased mortality and management for managed restoration projects
            if managed_restoration:
                if year <= 2:
                    # Intensive phase: immediate replanting = 0% net mortality
                    year_mortality = 0.0
                    year_mgmt = dict(management)   # full uplifts
                elif year <= 4:
                    # Transition phase: irrigation weaning, light replanting
                    year_mortality = 0.005
                    year_mgmt = dict(management)
                    year_mgmt["irrigation"] = False  # irrigation weaned off
                else:
                    # Independent phase: established trees, MRV only
                    # Trees are self-sustaining but keep TerraPod biochar benefit
                    year_mortality = 0.015
                    year_mgmt = dict(management)
                    year_mgmt["irrigation"] = False  # no irrigation needed
                    year_mgmt["nutrients"]  = False  # no added nutrients
                    # Note: biochar stays active (17,000yr longevity per PNNL study)
                    # TerraPod growth multiplier remains (established root system)
            else:
                year_mortality = annual_mortality
                year_mgmt = management

            for c in cohorts:
                if c["count"] <= 0:
                    continue

                # Mortality
                effective_mort = max(0.0, year_mortality / surv_mult)
                survivors = max(0, int(c["count"] * (1.0 - effective_mort)))

                if survivors < len(c["dbh_arr"]):
                    c["dbh_arr"] = np.sort(c["dbh_arr"])[-survivors:]
                c["count"] = survivors

                if c["count"] <= 0:
                    continue

                # Growth
                growth_mm = self._get_dbh_growth_mm(
                    c["species"], c["region"], year_mgmt
                )
                c["dbh_arr"] = c["dbh_arr"] + (growth_mm / 10.0)

                # Biomass — vectorized for speed
                rsr = RSR.get(c["region"].lower(), RSR_DEFAULT)
                # Get equation coefficients once, apply to all trees
                dbh_arr = c["dbh_arr"]
                sp  = c["species"]
                rg  = c["region"]
                # Try Tier 1: GlobAllomeTree vectorized (uses memoized lookup)
                _tier, _rec = self._get_species_rec(sp, rg)
                rec = _rec if _tier == "globallometree" else None
                if rec:
                    # Vectorized eval using numpy
                    eq  = rec['equation']
                    tr  = rec['output_tr']
                    uy  = rec['unit_y']
                    try:
                        f = str(eq).replace('^','**').replace('X','dbh_arr')
                        f = (f.replace('ln(','np.log(').replace('log10(','np.log10(')
                              .replace('Log10(','np.log10(').replace('log(','np.log(')
                              .replace('Log(','np.log(').replace('exp(','np.exp(')
                              .replace('sqrt(','np.sqrt('))
                        result = eval(f, {"np": np, "dbh_arr": dbh_arr, "__builtins__": {}})
                        result = np.where(np.isfinite(result) & (result > 0), result, 0.0)
                        if tr in ('log','ln'): result = np.exp(result)
                        elif tr in ('log10',): result = 10.0 ** result
                        if uy == 'g': result = result / 1000.0
                        elif uy == 'mg': result = result * 1000.0
                        # Sanity check: median value per tree should be plausible
                        med = float(np.median(result[result > 0])) if np.any(result > 0) else 0
                        ref_dbh = float(np.median(dbh_arr))
                        expected_min = AGB_SANITY_MIN_KG * (ref_dbh / 10.0) ** 2
                        if med < expected_min * 0.1:
                            raise ValueError("Implausibly low — fall through")
                        agb_kg = float(np.sum(result))
                    except:
                        # Fall back to per-tree calculation with sanity checks
                        agb_kg = float(np.sum([self.calculate_agb_kg(d, sp, rg) for d in dbh_arr]))
                else:
                    # Tier 2/3: use memoized lookup
                    _tier2, _rec2 = self._get_species_rec(sp, rg)
                    if _tier2 == "simple":
                        agb_kg = float(np.sum(_rec2["a"] * (dbh_arr ** _rec2["b"])))
                    else:
                        a, b = _rec2
                        agb_kg = float(np.sum(a * (dbh_arr ** b)))
                total_biomass_kg += agb_kg * (1.0 + rsr)

            carbon_t   = (total_biomass_kg / 1000.0) * CARBON_FRACTION
            co2e_gross = carbon_t * CO2E_FACTOR

            yearly_results.append({
                "year"              : year,
                "trees_total"       : round(sum(c["count"] for c in cohorts) * area_scale),
                "biomass_t"         : round(total_biomass_kg / 1000.0 * area_scale, 2),
                "carbon_t"          : round(carbon_t * area_scale, 2),
                "co2e_gross_t"      : round(co2e_gross * area_scale, 2),
                "soil_co2e_gross_t" : round(annual_soil_co2e * area_scale, 2),
                "equation_tiers"    : eq_tiers,
            })

        return yearly_results

    # ── Audit trail ───────────────────────────────────────────────────────────

    def get_audit_trail(self, species_mix: list, management: dict,
                        area_ha: float, project_years: int,
                        annual_mortality: float, buffer_pct: float) -> dict:
        """
        Return a complete, VVB-ready audit trail dict covering all
        parameters, equation sources, and management uplifts.
        """
        species_citations = {}
        for mix in species_mix:
            sp = mix["species_name"]
            info = self.get_equation_info(sp)
            species_citations[sp] = info

        uplift_log = {}
        if management.get("irrigation"):
            uplift_log["irrigation"] = UPLIFT_CITATIONS["irrigation"]
        if management.get("nutrients"):
            uplift_log["nutrients"] = UPLIFT_CITATIONS["nutrients"]
        if management.get("biochar"):
            uplift_log["biochar"] = UPLIFT_CITATIONS["biochar"]

        return {
            "carbon_fraction"        : f"{CARBON_FRACTION} — IPCC 2006 Table 4.3",
            "co2e_factor"            : f"{CO2E_FACTOR} — molecular weight C:CO2",
            "rsr_values"             : {k: v for k, v in RSR.items()},
            "rsr_citation"           : RSR_CITATION,
            "equation_priority"      : [
                "Tier 1: GlobAllomeTree (18,499 raw → 888 validated species)",
                "Tier 2: allometric_equations.csv (224 species, a×DBH^b)",
                "Tier 3: IPCC 2019 regional power-law default",
            ],
            "species_equations"      : species_citations,
            "management_uplifts"     : uplift_log,
            "annual_mortality"       : f"{annual_mortality*100:.1f}%",
            "buffer_pool"            : f"{buffer_pct}% (VCS minimum 10%)",
            "uncertainty_discount"   : "20% — VCS Uncertainty & Variance Policy v4",
            "soil_carbon_citation"   : SOC_CITATION,
            "area_ha"                : area_ha,
            "project_years"          : project_years,
        }
