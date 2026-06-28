"""
app.py — PyScript controller
=============================
This file runs INSIDE THE BROWSER via Pyodide (loaded by PyScript).
It reads form inputs from the DOM, calls the pure-Python engine in
engine.py, and writes results back into the DOM. There is no server:
every line below executes on the visitor's own device.
"""

from pyodide.ffi import create_proxy
from js import document, window
from engine import Inputs, calculate, fmt_inr, fmt_inr_full


# ---------------------------------------------------------------------------
# DOM helpers
# ---------------------------------------------------------------------------

def by_id(id_):
    return document.getElementById(id_)


def get_num(id_, default=0.0):
    el = by_id(id_)
    try:
        return float(el.value)
    except (ValueError, AttributeError):
        return default


def get_pct(id_, default=0.0):
    """Range inputs are stored as whole-number percentages (e.g. 8 -> 0.08)."""
    return get_num(id_, default * 100) / 100.0


def get_bool(id_):
    el = by_id(id_)
    return bool(getattr(el, "checked", False))


def set_text(id_, text):
    el = by_id(id_)
    if el is not None:
        el.innerText = text


def set_class(el_id, class_name):
    el = by_id(el_id)
    if el is not None:
        el.className = class_name


# ---------------------------------------------------------------------------
# Read inputs from the form
# ---------------------------------------------------------------------------

def read_inputs() -> Inputs:
    return Inputs(
        current_age=int(get_num("current_age", 28)),
        retirement_age=int(get_num("retirement_age", 60)),
        starting_salary=get_num("starting_salary", 2_000_000),
        salary_growth=get_pct("salary_growth", 0.08),

        nps_voluntary_pct=get_pct("nps_voluntary_pct", 0.05),
        wecare_enrolled=get_bool("wecare_enrolled"),

        house_price=get_num("house_price", 15_000_000),
        ltv=get_pct("ltv", 0.80),
        home_loan_rate=get_pct("home_loan_rate", 0.075),
        loan_tenure_years=int(get_num("loan_tenure_years", 20)),
    )


# ---------------------------------------------------------------------------
# Live slider value labels
# ---------------------------------------------------------------------------

SLIDER_LABELS = {
    "salary_growth": ("salary_growth_val", "{:.1f}%"),
    "nps_voluntary_pct": ("nps_voluntary_pct_val", "{:.0f}%"),
    "ltv": ("ltv_val", "{:.0f}%"),
    "loan_tenure_years": ("loan_tenure_years_val", "{:.0f}"),
    "home_loan_rate": ("home_loan_rate_val", "{:.1f}%"),
}


def refresh_slider_labels():
    for input_id, (label_id, fmt) in SLIDER_LABELS.items():
        el = by_id(input_id)
        if el is None:
            continue
        try:
            val = float(el.value)
        except ValueError:
            continue
        set_text(label_id, fmt.format(val))


# ---------------------------------------------------------------------------
# Chart rendering (hand-drawn SVG, no charting library needed)
# ---------------------------------------------------------------------------

def render_chart(ages, corpus_values, required_corpus):
    svg = by_id("corpus-chart")
    if svg is None:
        return

    W, H = 600, 220
    pad_l, pad_r, pad_t, pad_b = 58, 16, 16, 28
    plot_w = W - pad_l - pad_r
    plot_h = H - pad_t - pad_b

    max_val = max(max(corpus_values, default=1), required_corpus, 1)
    max_val *= 1.08  # headroom

    def x_at(i):
        if len(ages) <= 1:
            return pad_l
        return pad_l + (i / (len(ages) - 1)) * plot_w

    def y_at(v):
        return pad_t + plot_h - (v / max_val) * plot_h

    # grid lines (4 horizontal)
    grid_parts = []
    for g in range(5):
        gy = pad_t + plot_h * g / 4
        grid_parts.append(
            f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{W-pad_r}" y2="{gy:.1f}" '
            f'stroke="#E4DECC" stroke-width="1" />'
        )
        val = max_val * (4 - g) / 4
        grid_parts.append(
            f'<text x="{pad_l-6}" y="{gy+3:.1f}" font-size="9" fill="#4A5160" '
            f'text-anchor="end" font-family="Roboto Mono, monospace">{fmt_inr(val)}</text>'
        )

    # required-corpus reference line
    req_y = y_at(required_corpus)
    grid_parts.append(
        f'<line x1="{pad_l}" y1="{req_y:.1f}" x2="{W-pad_r}" y2="{req_y:.1f}" '
        f'stroke="#DD9A2B" stroke-width="1.5" stroke-dasharray="5,4" />'
    )
    grid_parts.append(
        f'<text x="{W-pad_r}" y="{req_y-5:.1f}" font-size="9" fill="#8A5E10" '
        f'text-anchor="end" font-family="Inter, sans-serif" font-weight="600">Target corpus</text>'
    )

    # area path
    points = [(x_at(i), y_at(v)) for i, v in enumerate(corpus_values)]
    if points:
        path_d = f"M {points[0][0]:.1f} {y_at(0):.1f} "
        for px, py in points:
            path_d += f"L {px:.1f} {py:.1f} "
        path_d += f"L {points[-1][0]:.1f} {y_at(0):.1f} Z"
        area = f'<path d="{path_d}" fill="#157A8C" opacity="0.16" />'

        line_d = "M " + " L ".join(f"{px:.1f} {py:.1f}" for px, py in points)
        line = f'<path d="{line_d}" fill="none" stroke="#157A8C" stroke-width="2.5" />'

        dot = ""
        if points:
            lx, ly = points[-1]
            dot = f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4.5" fill="#0B1F3A" stroke="#fff" stroke-width="1.5" />'
    else:
        area, line, dot = "", "", ""

    # x-axis labels (first, mid, last age)
    x_labels = ""
    if ages:
        idxs = sorted(set([0, len(ages) // 2, len(ages) - 1]))
        for i in idxs:
            x_labels += (
                f'<text x="{x_at(i):.1f}" y="{H-8}" font-size="9" fill="#4A5160" '
                f'text-anchor="middle" font-family="Roboto Mono, monospace">Age {ages[i]}</text>'
            )

    svg.innerHTML = "".join(grid_parts) + area + line + dot + x_labels


# ---------------------------------------------------------------------------
# Main calculation + render cycle
# ---------------------------------------------------------------------------

def run_calculation(*args, **kwargs):
    inputs = read_inputs()
    r = calculate(inputs)

    # --- Headline "sacrifice" number ---
    set_text("sacrifice-value", fmt_inr(r.house_opportunity_delta))
    set_text(
        "sacrifice-sub",
        f"Taking this loan instead of investing the same EMI costs you "
        f"{fmt_inr(r.house_opportunity_delta)} of retirement wealth by age {inputs.retirement_age}."
    )

    # --- Balance / safety strip ---
    pct = min(max(r.emi_pct_of_net, 0), 1.0)
    fill_el = by_id("balance-fill")
    if fill_el is not None:
        fill_el.style.width = f"{pct*100:.1f}%"
    set_text("emi-pct-label", f"EMI: {r.emi_pct_of_net*100:.0f}% of take-home")
    set_text("zone-badge", f"{r.safety_zone} zone")
    set_class("zone-badge", f"zone-badge {r.safety_zone}")

    # --- Result cards ---
    set_text("r-emi", fmt_inr_full(r.emi))
    set_text("r-emi-pct", f"{r.emi_pct_of_net*100:.0f}% of net take-home")

    set_text("r-corpus", fmt_inr(r.total_corpus_no_house))
    set_text("r-rr", f"{r.replacement_ratio_achieved*100:.0f}% replacement ratio")

    set_text("r-interest", fmt_inr(r.total_interest_paid))
    set_text("r-oppcost", fmt_inr(r.opportunity_cost_fv))

    set_text("r-safe-emi", fmt_inr_full(r.max_safe_emi))
    set_text("r-safe-house", fmt_inr(r.max_safe_house_price))

    # --- Chart ---
    set_text("chart-age-from", str(inputs.current_age))
    set_text("chart-age-to", str(inputs.retirement_age))
    render_chart(r.timeline_ages, r.timeline_corpus, r.required_corpus_70)

    set_text("py-status", "Live — recalculated in your browser")
    set_class("py-status", "py-status ready")


def on_input_change(*args, **kwargs):
    refresh_slider_labels()


def on_recalc_click(event=None):
    run_calculation()


# ---------------------------------------------------------------------------
# Wire up event listeners
# ---------------------------------------------------------------------------

def attach_listeners():
    input_ids = [
        "current_age", "retirement_age", "starting_salary", "salary_growth",
        "nps_voluntary_pct", "wecare_enrolled",
        "house_price", "ltv", "loan_tenure_years", "home_loan_rate",
    ]
    change_proxy = create_proxy(on_input_change)
    for id_ in input_ids:
        el = by_id(id_)
        if el is not None:
            el.addEventListener("input", change_proxy)

    recalc_btn = by_id("recalc-btn")
    if recalc_btn is not None:
        recalc_btn.addEventListener("click", create_proxy(on_recalc_click))

    # Auto-recalculate live as sliders/number inputs move (debounced lightly
    # by just recalculating on every input — the Python engine is fast enough)
    live_proxy = create_proxy(lambda evt=None: run_calculation())
    for id_ in input_ids:
        el = by_id(id_)
        if el is not None:
            el.addEventListener("input", live_proxy)


def hide_loading_screen():
    el = by_id("loading-screen")
    if el is not None:
        el.classList.add("hidden")


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

refresh_slider_labels()
attach_listeners()
run_calculation()
hide_loading_screen()
