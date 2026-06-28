"""
Retirement Sacrifice Meter — Financial Engine
================================================
Pure Python. Runs client-side in the browser via Pyodide (PyScript).
No server, no backend — every number below is computed live on the
visitor's device from the inputs they enter.

All amounts in INR. Rates are annual unless noted; converted to
monthly internally for compounding math.
"""

from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def monthly_rate(annual_rate: float) -> float:
    """Simple monthly-equivalent of an annual nominal rate (r/12)."""
    return annual_rate / 12.0


def pmt(rate_m: float, n_months: int, principal: float) -> float:
    """Standard loan EMI formula (annuity payment)."""
    if n_months <= 0:
        return 0.0
    if rate_m == 0:
        return principal / n_months
    factor = (1 + rate_m) ** n_months
    return principal * rate_m * factor / (factor - 1)


def fv_of_annuity(monthly_contribution: float, rate_m: float, n_months: int) -> float:
    """Future value of a level monthly contribution stream (ordinary annuity)."""
    if n_months <= 0:
        return 0.0
    if rate_m == 0:
        return monthly_contribution * n_months
    factor = (1 + rate_m) ** n_months
    return monthly_contribution * (factor - 1) / rate_m


def fv_growing_annuity_annual(
    annual_contribution: float,
    annual_growth: float,
    annual_return: float,
    years: int,
) -> float:
    """
    Future value of a contribution that starts at `annual_contribution`
    in year 1 and grows by `annual_growth` each year, compounding at
    `annual_return`, evaluated at the END of `years`.
    Used for EPF/NPS/WeCare corpus build-up where salary (and hence
    contribution) grows year over year.
    """
    total = 0.0
    contribution = annual_contribution
    for year in range(1, years + 1):
        years_to_grow = years - year  # contribution made at year `year`, grows until `years`
        total += contribution * ((1 + annual_return) ** years_to_grow)
        contribution *= (1 + annual_growth)
    return total


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class Inputs:
    current_age: int = 28
    retirement_age: int = 60
    starting_salary: float = 2_000_000          # annual CTC, INR
    salary_growth: float = 0.08                  # annual %, decimal
    basic_pct: float = 0.40                       # Basic as % of CTC

    epf_rate: float = 0.24                        # employee+employer combined, % of Basic
    epf_return: float = 0.0815                    # annual

    nps_voluntary_pct: float = 0.05                # employee voluntary %, of Basic
    nps_employer_match: float = 0.05               # employer match %, of Basic
    nps_return: float = 0.105                      # annual blended

    wecare_enrolled: bool = False
    wecare_employee_pct: float = 0.10              # fixed by plan design
    wecare_db_pct_of_final_salary: float = 0.50    # guaranteed monthly pension
    commutation_factor: float = 9.81

    house_price: float = 15_000_000
    ltv: float = 0.80
    home_loan_rate: float = 0.075
    loan_tenure_years: int = 20

    equity_return: float = 0.12                    # opportunity-cost benchmark
    inflation: float = 0.055
    annuity_rate: float = 0.065                     # for converting corpus to pension if needed
    post_retirement_years: int = 25

    foir_limit: float = 0.50                       # max EMI as % of net take-home
    estimated_annual_tax: float = 283_000

    # safe-EMI budget split of net take-home
    safe_retirement_floor: float = 0.15
    safe_living_floor: float = 0.40
    safe_emergency_floor: float = 0.10


@dataclass
class Results:
    years_to_retirement: int = 0

    monthly_gross: float = 0.0
    monthly_basic: float = 0.0
    monthly_net_take_home: float = 0.0

    epf_monthly: float = 0.0
    nps_monthly: float = 0.0
    wecare_monthly: float = 0.0

    epf_corpus: float = 0.0
    nps_corpus: float = 0.0
    wecare_dc_corpus: float = 0.0
    wecare_db_lumpsum: float = 0.0
    wecare_db_monthly_pension: float = 0.0
    total_corpus_no_house: float = 0.0

    final_annual_salary: float = 0.0
    required_corpus_50: float = 0.0
    required_corpus_70: float = 0.0
    replacement_ratio_achieved: float = 0.0
    retirement_gap: float = 0.0

    loan_amount: float = 0.0
    emi: float = 0.0
    emi_pct_of_net: float = 0.0
    total_loan_repayment: float = 0.0
    total_interest_paid: float = 0.0
    opportunity_cost_fv: float = 0.0
    true_cost_of_house: float = 0.0

    max_loan_eligible_foir: float = 0.0
    max_safe_emi: float = 0.0
    max_safe_house_price: float = 0.0
    is_emi_safe: bool = False
    safety_zone: str = "Safe"

    corpus_with_house: float = 0.0
    corpus_without_house: float = 0.0
    house_opportunity_delta: float = 0.0

    timeline_ages: List[int] = field(default_factory=list)
    timeline_corpus: List[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def calculate(i: Inputs) -> Results:
    r = Results()
    years = max(i.retirement_age - i.current_age, 1)
    r.years_to_retirement = years

    # --- Salary & take-home ---
    annual_basic = i.starting_salary * i.basic_pct
    r.monthly_gross = i.starting_salary / 12
    r.monthly_basic = annual_basic / 12

    annual_epf = annual_basic * i.epf_rate
    annual_nps = annual_basic * i.nps_voluntary_pct if i.nps_voluntary_pct > 0 else 0.0
    annual_wecare = annual_basic * i.wecare_employee_pct if i.wecare_enrolled else 0.0

    annual_net = i.starting_salary - i.estimated_annual_tax - annual_epf - annual_nps - annual_wecare
    r.monthly_net_take_home = annual_net / 12

    r.epf_monthly = annual_epf / 12
    r.nps_monthly = annual_nps / 12
    r.wecare_monthly = annual_wecare / 12

    # --- Corpus build-up (growing annuity, contributions scale with salary) ---
    r.epf_corpus = fv_growing_annuity_annual(annual_epf, i.salary_growth, i.epf_return, years)

    if i.nps_voluntary_pct > 0:
        annual_nps_total = annual_basic * (i.nps_voluntary_pct + i.nps_employer_match)
        r.nps_corpus = fv_growing_annuity_annual(annual_nps_total, i.salary_growth, i.nps_return, years)
    else:
        r.nps_corpus = 0.0

    r.final_annual_salary = i.starting_salary * ((1 + i.salary_growth) ** (years - 1)) if years > 0 else i.starting_salary

    if i.wecare_enrolled:
        r.wecare_dc_corpus = fv_growing_annuity_annual(annual_wecare, i.salary_growth, i.nps_return, years)
        avg_final_12mo_salary = r.final_annual_salary  # approximation: final year's salary
        r.wecare_db_monthly_pension = (avg_final_12mo_salary / 12) * i.wecare_db_pct_of_final_salary
        r.wecare_db_lumpsum = r.wecare_db_monthly_pension * i.commutation_factor * 12
    else:
        r.wecare_dc_corpus = 0.0
        r.wecare_db_monthly_pension = 0.0
        r.wecare_db_lumpsum = 0.0

    r.total_corpus_no_house = (
        r.epf_corpus + r.nps_corpus + r.wecare_dc_corpus + r.wecare_db_lumpsum
    )

    # --- Replacement ratio & gap ---
    final_monthly_salary = r.final_annual_salary / 12
    annuity_m = i.annuity_rate / 12
    n_post = i.post_retirement_years * 12
    # capital required to pay out X% of final salary per month for N years at annuity_rate
    def corpus_required_for_monthly_income(monthly_income: float) -> float:
        if annuity_m == 0:
            return monthly_income * n_post
        factor = (1 + annuity_m) ** n_post
        return monthly_income * (1 - (1 + annuity_m) ** (-n_post)) / annuity_m

    r.required_corpus_50 = corpus_required_for_monthly_income(final_monthly_salary * 0.50)
    r.required_corpus_70 = corpus_required_for_monthly_income(final_monthly_salary * 0.70)

    achieved_monthly_income = r.total_corpus_no_house * annuity_m if annuity_m > 0 else 0.0
    # back-solve replacement ratio achieved from corpus via annuity factor
    if final_monthly_salary > 0:
        if annuity_m == 0:
            achieved_income = r.total_corpus_no_house / n_post if n_post else 0
        else:
            achieved_income = r.total_corpus_no_house * annuity_m / (1 - (1 + annuity_m) ** (-n_post))
        r.replacement_ratio_achieved = achieved_income / final_monthly_salary
    else:
        r.replacement_ratio_achieved = 0.0

    r.retirement_gap = max(r.required_corpus_70 - r.total_corpus_no_house, 0.0)

    # --- Housing / EMI ---
    r.loan_amount = i.house_price * i.ltv
    rm = monthly_rate(i.home_loan_rate)
    n_loan = i.loan_tenure_years * 12
    r.emi = pmt(rm, n_loan, r.loan_amount)
    r.total_loan_repayment = r.emi * n_loan
    r.total_interest_paid = r.total_loan_repayment - r.loan_amount

    if r.monthly_net_take_home > 0:
        r.emi_pct_of_net = r.emi / r.monthly_net_take_home
    else:
        r.emi_pct_of_net = 0.0

    inv_rm = monthly_rate(i.equity_return)
    r.opportunity_cost_fv = fv_of_annuity(r.emi, inv_rm, n_loan)
    r.true_cost_of_house = i.house_price + r.opportunity_cost_fv

    # --- FOIR-based loan eligibility ---
    max_emi_foir = r.monthly_net_take_home * i.foir_limit
    if rm > 0:
        r.max_loan_eligible_foir = max_emi_foir * (1 - (1 + rm) ** (-n_loan)) / rm
    else:
        r.max_loan_eligible_foir = max_emi_foir * n_loan

    # --- Safe EMI threshold (budget-rule based, independent of bank FOIR) ---
    safe_pct = 1 - i.safe_retirement_floor - i.safe_living_floor - i.safe_emergency_floor
    r.max_safe_emi = r.monthly_net_take_home * max(safe_pct, 0.0)
    if rm > 0:
        max_safe_loan = r.max_safe_emi * (1 - (1 + rm) ** (-n_loan)) / rm
    else:
        max_safe_loan = r.max_safe_emi * n_loan
    r.max_safe_house_price = max_safe_loan / i.ltv if i.ltv > 0 else max_safe_loan

    r.is_emi_safe = r.emi <= r.max_safe_emi
    if r.emi_pct_of_net < 0.25:
        r.safety_zone = "Safe"
    elif r.emi_pct_of_net < 0.35:
        r.safety_zone = "Caution"
    elif r.emi_pct_of_net < 0.45:
        r.safety_zone = "Danger"
    else:
        r.safety_zone = "Severe"

    # --- Combined "sacrifice" view: corpus with vs without taking the house ---
    r.corpus_without_house = r.total_corpus_no_house + r.opportunity_cost_fv
    r.corpus_with_house = r.total_corpus_no_house
    r.house_opportunity_delta = r.corpus_without_house - r.corpus_with_house

    # --- Timeline series for chart (every year) ---
    ages = list(range(i.current_age, i.retirement_age + 1))
    corpus_series = []
    for yr_idx, age in enumerate(ages):
        yrs_elapsed = yr_idx
        if yrs_elapsed == 0:
            corpus_series.append(0.0)
            continue
        partial_epf = fv_growing_annuity_annual(annual_epf, i.salary_growth, i.epf_return, yrs_elapsed)
        partial_nps = (
            fv_growing_annuity_annual(
                annual_basic * (i.nps_voluntary_pct + i.nps_employer_match),
                i.salary_growth, i.nps_return, yrs_elapsed
            ) if i.nps_voluntary_pct > 0 else 0.0
        )
        partial_wecare = (
            fv_growing_annuity_annual(annual_wecare, i.salary_growth, i.nps_return, yrs_elapsed)
            if i.wecare_enrolled else 0.0
        )
        corpus_series.append(partial_epf + partial_nps + partial_wecare)

    r.timeline_ages = ages
    r.timeline_corpus = corpus_series

    return r


# ---------------------------------------------------------------------------
# Formatting helpers (used by the UI layer)
# ---------------------------------------------------------------------------

def fmt_inr(amount: float) -> str:
    """Format a rupee amount in Indian crore/lakh shorthand."""
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= 1_00_00_000:
        return f"{sign}\u20B9{amount/1_00_00_000:,.2f} Cr"
    if amount >= 1_00_000:
        return f"{sign}\u20B9{amount/1_00_000:,.2f} L"
    return f"{sign}\u20B9{amount:,.0f}"


def fmt_inr_full(amount: float) -> str:
    """Full Indian-style comma-grouped rupee amount, e.g. 1,23,45,678."""
    amount = round(amount)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    s = str(amount)
    if len(s) <= 3:
        return f"{sign}\u20B9{s}"
    last3 = s[-3:]
    rest = s[:-3]
    parts = []
    while len(rest) > 2:
        parts.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        parts.insert(0, rest)
    return f"{sign}\u20B9{','.join(parts)},{last3}"
