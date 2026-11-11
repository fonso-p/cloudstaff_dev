"""Writes notebooks/early_signal_prediction.ipynb (one step per cell, a markdown cell above each).

Run from the project root:  python work/early_signal_prediction/make_notebook.py
then:                        jupyter nbconvert --to notebook --execute --inplace notebooks/early_signal_prediction.ipynb
"""
import os

import nbformat as nbf

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
cells = []


def md(t):
    cells.append(nbf.v4.new_markdown_cell(t.strip()))


def code(t):
    cells.append(nbf.v4.new_code_cell(t.strip()))


md("""
# Early Signals of Account Growth

**Question.** What can we observe in a client's first 90 days that predicts whether the account will reach 5 seats, keep expanding,
and become a meaningfully larger Cloudstaff customer?

**Plan.** `work/early_signal_prediction/plan.md` (approved 2026-10-10). Three targets:
- A: 5 staff at the same time within 12 months (clients not at 5 by day 90)
- B: 10 within 24 months (clients not at 10 by day 90)
- C: still growing from month 12 to month 24, among clients that reached 5 in year 1

Several models are tested out of time: train on earlier start years, then score the next year's new clients.
Every number reported comes from a cell in this notebook. Run it from the project root.
""")

md("## 1. Setup\nImports, paths and the fixed random seed. Helper modules sit in `work/early_signal_prediction/`.")
code("""
import os, sys, json, warnings
ROOT = os.path.abspath(os.getcwd() if os.path.isdir('data') else os.path.join(os.getcwd(), '..'))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'work', 'early_signal_prediction'))
sys.path.insert(0, os.path.join(ROOT, '.claude', 'skills', 'cs-data-analytics', 'scripts'))
warnings.filterwarnings('ignore')
import numpy as np, pandas as pd
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from sklearn.metrics import roc_curve, precision_recall_curve
import esp_data as E, esp_models as M
import stats_helpers as st
TOPIC = 'early_signal_prediction'
CHARTS, CSV, RES = f'outputs/charts/{TOPIC}', f'outputs/csv/{TOPIC}', f'data/{TOPIC}'
for d in (CHARTS, CSV, RES): os.makedirs(d, exist_ok=True)
PALETTE = ['#007AFF', '#00AB9C', '#FFC426', '#E34678', '#4121A9', '#AA67FD', '#F46600', '#36D6E7', '#87DD7D', '#50505C']
pd.set_option('display.width', 220); pd.set_option('display.max_columns', 30)
print('seed', M.SEED, '| extract', E.EXTRACT.date(), '| early window: day', E.EARLY_DAY)
""")

md("## 2. Load the raw engagement list and build the client table\nOne row per client. Features use only stints up to day 90 after the first start; the targets use what happened afterwards.")
code("""
raw = pd.read_excel(E.STAFF_SRC, dtype=object)
f, s, st_valid = E.build_features(raw)
print(f'source rows {len(raw):,} | in-scope rows {int(s["include"].sum()):,} | valid in-scope stints {len(st_valid):,} | clients {len(f):,}')
print('client starts', f['start_date'].min().date(), 'to', f['start_date'].max().date())
f[E.NUMERIC].describe().T[['mean', '50%', 'max']].round(2)
""")

md("""## 3. Data issues and agreed treatments
Rows and clients affected by each treatment in plan section 7.""")
code("""
issues = pd.DataFrame([
    ('Clients too young for target A (under 12 months)', int((f.age_days < 365).sum())),
    ('Clients too young for target B (under 24 months)', int((f.age_days < 730).sum())),
    ('Already at 5 staff by day 90 (left out of target A)', int(((f.age_days >= 365) & (f.days_to_5 <= E.EARLY_DAY)).sum())),
    ('Already at 10 staff by day 90 (left out of target B)', int(((f.age_days >= 730) & (f.days_to_10 <= E.EARLY_DAY)).sum())),
    ('Initial function Unknown (role title not matched)', int((f.initial_function == 'Unknown').sum())),
    ('Custom Division Unassigned (sensitivity model only)', int(f.custom_division.str.startswith('Unassigned').sum())),
    ('Industry Unknown (sensitivity model only)', int((f.industry == 'Unknown').sum())),
], columns=['issue', 'clients'])
leak = pd.crosstab(f.custom_division.str.startswith('Unassigned').rename('Unassigned division'), (f.age_days >= 0) & (pd.read_csv('data/client_profile.csv').set_index('shortcode').current_seats.reindex(f.index) == 0), normalize='index').round(3)
leak.columns = ['still has staff', 'no staff today']
print(issues.to_string(index=False)); print(); print('Why division is sensitivity-only (share with no staff today):'); print(leak)
print(); print('Initial function Unknown by start year:', f.assign(u=f.initial_function.eq('Unknown')).groupby('start_year').u.mean().round(2).to_dict())
""")

md("## 4. Targets by start-year cohort\nWho is eligible for each target, how many reached it, and the rate with a Wilson 95% range.")
code("""
rows = []
for t, lab in [('A', 'Reaches 5 within 12 months'), ('B', 'Reaches 10 within 24 months'), ('C', 'Keeps expanding (month 12 to 24)')]:
    e = f[f[f'elig_{t}']]
    for y, g in list(e.groupby('start_year')) + [('All', e)]:
        k, n = int(g[f'y_{t}'].sum()), len(g)
        lo, hi = st.wilson_ci(k, n)
        rows.append(dict(target=t, label=lab, start_year=y, eligible=n, positives=k, rate=k / n if n else np.nan, lo=lo, hi=hi))
targets = pd.DataFrame(rows)
targets.round(3)
""")

md("""## 5. Single early signals and target A
Share reaching 5 within 12 months by each early signal on its own, with Wilson 95% ranges and a chi-square test per signal.
This is the plain view before any model.""")
code("""
eA = f[f.elig_A]
def band_rows(name, keyfun, order=None):
    g = eA.assign(k=keyfun(eA)).groupby('k')['y_A'].agg(['size', 'sum'])
    if order: g = g.reindex([o for o in order if o in g.index])
    p = st.chi_square([[int(r['sum']), int(r['size'] - r['sum'])] for _, r in g.iterrows()])['p_value'] if len(g) > 1 else np.nan
    out = []
    for k, r in g.iterrows():
        lo, hi = st.wilson_ci(int(r['sum']), int(r['size']))
        out.append(dict(signal=name, level=str(k), clients=int(r['size']), reached_5=int(r['sum']), rate=r['sum'] / r['size'], lo=lo, hi=hi, p_value=p))
    return out
sig = []
sig += band_rows('Staff at day 90', lambda d: d.seats_d90.clip(upper=4).map(lambda v: '4' if v >= 4 else str(v)), ['0', '1', '2', '3', '4'])
sig += band_rows('Staff added in days 31-90', lambda d: np.where(d.adds_d31_90 > 0, 'Yes', 'No'), ['No', 'Yes'])
sig += band_rows('Second start within 90 days', lambda d: np.where(d.second_start_by_d90 == 1, 'Yes', 'No'), ['No', 'Yes'])
sig += band_rows('Any leaver by day 90', lambda d: np.where(d.leavers_d90 > 0, 'Yes', 'No'), ['No', 'Yes'])
sig += band_rows('2+ functions by day 90', lambda d: np.where(d.functions_d90 >= 2, 'Yes', 'No'), ['No', 'Yes'])
sig += band_rows('Region', lambda d: d.region, E.REGIONS)
fn_keep = eA.initial_function.value_counts(); fn_keep = set(fn_keep[fn_keep >= 30].index)
sig += band_rows('Initial function (30+ clients)', lambda d: d.initial_function.where(d.initial_function.isin(fn_keep), 'Other (under 30 clients)'))
sig += band_rows('Start quarter', lambda d: d.start_quarter, ['Q1', 'Q2', 'Q3', 'Q4'])
signals = pd.DataFrame(sig)
signals.round(3)
""")

md("""## 6. Backtest, target A: every model, out of time
For each test year, models are trained and tuned only on clients that started in earlier years; the test year is then scored once.
Pooled = all test years together, with bootstrap 95% ranges (2,000 resamples). Precision, recall and F1 use the threshold chosen on the training years.""")
code("""
YEARS_A = [2022, 2023, 2024, 2025]
predA, chosenA = M.backtest(f, 'A', YEARS_A, E.NUMERIC, E.CATEGORICAL)
pooledA, yearA, diffA = M.summarise(predA)
show = ['model', 'n', 'positives', 'base_rate', 'roc_auc', 'roc_auc_lo', 'roc_auc_hi', 'pr_auc', 'pr_auc_lo', 'pr_auc_hi', 'accuracy', 'balanced_accuracy',
        'precision', 'recall', 'f1', 'specificity', 'brier', 'lift_top10', 'capture_top10', 'precision_top20_per_year', 'capture_top20_per_year']
pooledA[show].round(3)
""")

md("Per test year (ROC AUC and PR AUC), and each model's ROC AUC difference from logistic regression and from staff at day 90 alone, with paired bootstrap 95% ranges (better or worse only if the range excludes zero). The last line counts the test years in which each model beats staff at day 90 alone.")
code("""
print(yearA.pivot(index='model', columns='year', values='roc_auc').round(3)); print()
print(yearA.pivot(index='model', columns='year', values='pr_auc').round(3)); print()
pvA = yearA.pivot(index='model', columns='year', values='roc_auc')
beatsA = (pvA.gt(pvA.loc['Single signal: staff at day 90'], axis=1)).sum(axis=1).rename('test years above staff at day 90 alone')
print(beatsA); print()
diffA.round(3)
""")

md("## 7. Backtest, target B (10 within 24 months)\nSame design; test years 2022 to 2024 (clients need 24 months of history). Few positives per year, so read the pooled results first.")
code("""
YEARS_B = [2022, 2023, 2024]
predB, chosenB = M.backtest(f, 'B', YEARS_B, E.NUMERIC, E.CATEGORICAL)
pooledB, yearB, diffB = M.summarise(predB)
print(yearB.pivot(index='model', columns='year', values='roc_auc').round(3)); print()
print(diffB.round(3).to_string(index=False)); print()
pooledB[show].round(3)
""")

md("""## 8. Sensitivity models (target A)
- Add today's Custom Division and industry tags (plan issue 1; rare tags pooled as Other).
- Drop the function features (plan issue 2).
- Drop every staff, start, second-start and function count, to see what the other early signals (initial function, share of roles matched, region, start season) predict on their own (change log 2026-10-10).""")
code("""
f_tags = f.copy()
for c in E.SENSITIVITY_TAGS:
    vc = f_tags[c].value_counts(); f_tags[c] = f_tags[c].where(f_tags[c].map(vc) >= 30, 'Other')
FAM2 = ['Logistic regression', 'LightGBM']
sens_rows = []
for lab, num, cat, df_ in [('Main model (signals known by day 90)', E.NUMERIC, E.CATEGORICAL, f),
                           ('Plus Custom Division and industry', E.NUMERIC, E.CATEGORICAL + E.SENSITIVITY_TAGS, f_tags),
                           ('Without function features', [c for c in E.NUMERIC if c not in E.FUNCTION_FEATURES], [c for c in E.CATEGORICAL if c not in E.FUNCTION_FEATURES], f),
                           ('Without staff and start counts', [c for c in E.NUMERIC if c not in E.SIZE_FEATURES + ['functions_d90']], E.CATEGORICAL, f)]:
    pr, _ = M.backtest(df_, 'A', YEARS_A, num, cat, families=FAM2, include_auto=False)
    po, _, _ = M.summarise(pr, n_boot=1000)
    for _, r in po[po.model.isin(FAM2)].iterrows():
        sens_rows.append(dict(variant=lab, model=r.model, roc_auc=r.roc_auc, roc_auc_lo=r.roc_auc_lo, roc_auc_hi=r.roc_auc_hi, pr_auc=r.pr_auc,
                              pr_auc_lo=r.pr_auc_lo, pr_auc_hi=r.pr_auc_hi, capture_top20=r.capture_top20_per_year))
sens = pd.DataFrame(sens_rows)
sens.round(3)
""")

md("""## 9. Drivers: which early signals matter
Odds ratios from a logistic regression on readable signals (one more staff member, or yes / no), with 95% ranges and p-values, for each target.
An odds ratio above 1 = more likely to reach the target, holding the other signals fixed. These are associations, not causes.""")
code("""
orA, fitA = M.odds_ratios(f, 'A'); orB, fitB = M.odds_ratios(f, 'B'); orC, fitC = M.odds_ratios(f, 'C')
drivers = pd.concat([orA.assign(target='A'), orB.assign(target='B'), orC.assign(target='C')])
drivers.round(3)
""")

md("Which features the main models lean on most: mean absolute contribution per client (SHAP for LightGBM, coefficient times value for the auto-selected model), fitted on all eligible clients for target A.")
code("""
dA = f[f.elig_A]; XA = dA[E.NUMERIC + E.CATEGORICAL]
finalA = M.fit_final(f, 'A', E.NUMERIC, E.CATEGORICAL)
lgbA = M.make_model('LightGBM', chosenA[chosenA.model == 'LightGBM'].iloc[-1:]['params'].map(eval).iloc[0], E.NUMERIC, E.CATEGORICAL,
                    (len(dA) - dA.y_A.sum()) / dA.y_A.sum()).fit(XA, dA.y_A)
imp = pd.DataFrame({'LightGBM (SHAP)': M.shap_importance(lgbA, XA), f"Auto-selected: {finalA['family']}": M.shap_importance(finalA['raw'], XA)}).fillna(0)
imp = imp.sort_values('LightGBM (SHAP)', ascending=False)
print('final model for target A:', finalA['family'], finalA['params'])
imp.round(3)
""")

md("## 10. Target C: does the account keep expanding after reaching 5?\nToo few clients for a model contest (plan). Repeated 5-fold cross-validated AUC of the readable logistic regression.")
code("""
c_auc = M.cv_auc(f, 'C')
print(f"Target C: {int(f.elig_C.sum())} clients, {int(f[f.elig_C].y_C.sum())} kept growing; cross-validated AUC {c_auc[0]:.3f} (spread across 20 CV repeats {c_auc[1]:.3f} to {c_auc[2]:.3f})")
""")

md("## 11. Calibration and lift (target A, pooled out of time)\nCalibration: clients in five equal bands of predicted chance, average predicted versus actual rate. Lift: how much richer in future 5-seat accounts the top-scored clients are.")
code("""
def pooled_p(pred, model):
    g = pred[pred.model == model]; return g.y.to_numpy(), g.p.to_numpy()
calA = pd.concat([M.calibration_table(*pooled_p(predA, m)).assign(model=m) for m in ['Auto-selected + calibrated', 'Logistic regression']])
g = predA[predA.model == 'Auto-selected + calibrated']
calYear = g.groupby('year').agg(clients=('y', 'size'), predicted=('p', 'mean'), actual=('y', 'mean')).reset_index()   # calibration by test year
print(calYear.round(3).to_string(index=False)); print()
# simple rule baseline for account management: 2+ staff at day 90 or a second start by day 90 (test years 2022-2025)
tA = f[f.elig_A & f.start_year.isin(YEARS_A)]
rule = (tA.seats_d90 >= 2) | (tA.second_start_by_d90 == 1)
ruleA = pd.DataFrame([dict(rule='2+ staff at day 90 or a second start by day 90', clients=len(tA), flagged=int(rule.sum()), flagged_share=rule.mean(),
                           positives=int(tA.y_A.sum()), caught=int((rule & (tA.y_A == 1)).sum()), capture=(rule & (tA.y_A == 1)).sum() / tA.y_A.sum(),
                           precision=(rule & (tA.y_A == 1)).sum() / rule.sum())])
print(ruleA.round(3).to_string(index=False)); print()
lift = pooledA[['model', 'lift_top10', 'capture_top10', 'precision_top10', 'lift_top20', 'capture_top20', 'precision_top20',
                'precision_top20_per_year', 'capture_top20_per_year']]
print(calA.round(3).to_string(index=False)); print()
lift.round(3)
""")

md("""## 12. Watch list: clients 90 days to 12 months old
Scored with the final auto-selected, calibrated model for target A (fitted on all eligible clients) and the same approach for target B.
Each client shows the chance of reaching 5 within 12 months and 10 within 24 months, and the signals that raise or lower its score most.
Clients that have already reached 5 (by day 90 or since) are listed as such, without a score.""")
code("""
finalB = M.fit_final(f, 'B', E.NUMERIC, E.CATEGORICAL)
w = f[f.watch].copy()
X_w = w[E.NUMERIC + E.CATEGORICAL]
w['p_5_in_12m'] = np.where(w.reached5_already == 1, np.nan, finalA['calibrated'].predict_proba(X_w)[:, 1])
notB = ~(w.days_to_10 <= E.EARLY_DAY)
w['p_10_in_24m'] = np.where(notB, finalB['calibrated'].predict_proba(X_w)[:, 1], np.nan)
contrib = M.contributions(finalA['raw'], X_w)
LABEL = {'seats_d90': 'staff at day 90', 'peak_d90': 'peak staff by day 90', 'leavers_d90': 'leavers by day 90',
         'function_known_d90': 'roles matched', 'adds_d31_90': 'adds in days 31-90', 'initial_function': 'initial function', 'second_start_by_d90': 'second start by day 90',
         'functions_d90': 'functions by day 90', 'region': 'region', 'start_quarter': 'start quarter', 'seats_d60': 'staff at day 60', 'seats_d30': 'staff at day 30',
         'starting_seats': 'starting seats', 'starts_d90': 'starts by day 90', 'starts_first_week': 'starts in week 1', 'days_to_2nd_start_capped': 'days to second start'}
def top(row, k=2, sign=1):
    r = (row * sign).sort_values(ascending=False); r = r[r > 0].head(k)
    return ', '.join(LABEL.get(i, i) for i in r.index) or '-'
w['raises_score'] = [top(contrib.loc[i]) for i in w.index]
w['lowers_score'] = [top(contrib.loc[i], sign=-1) for i in w.index]
w['status'] = np.select([w.reached5_by_d90 == 1, w.reached5_already == 1], ['Already at 5 by day 90', 'Already reached 5 (after day 90)'], 'Scored')
watch = w.sort_values('p_5_in_12m', ascending=False)[['client_name', 'region', 'start_date', 'age_days', 'seats_d90', 'adds_d31_90', 'second_start_by_d90',
                                                       'initial_function', 'p_5_in_12m', 'p_10_in_24m', 'raises_score', 'lowers_score', 'status']]
print(f'watch list: {len(watch)} clients, {int((watch.status == "Scored").sum())} scored')
watch.head(15).round(3)
""")

md("## 13. Charts\nSaved to `outputs/charts/early_signal_prediction/` in the Cloudstaff palette.")
code("""
def save(fig, name):
    fig.tight_layout(); fig.savefig(f'{CHARTS}/{name}.png', dpi=160); plt.close(fig)
MODELS = ['Logistic regression', 'Elastic net logistic', 'Random forest', 'LightGBM', 'XGBoost', 'Auto-selected + calibrated', 'Single signal: staff at day 90']
for tgt, pred, po in [('A', predA, pooledA), ('B', predB, pooledB)]:
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.4))
    for i, m in enumerate(MODELS):
        y, p = pooled_p(pred, m); fpr, tpr, _ = roc_curve(y, p); pr, rc, _ = precision_recall_curve(y, p)
        auc = po.set_index('model').loc[m, 'roc_auc']; ap = po.set_index('model').loc[m, 'pr_auc']
        ax[0].plot(fpr, tpr, color=PALETTE[i], lw=1.6, label=f'{m} ({auc:.2f})'); ax[1].plot(rc, pr, color=PALETTE[i], lw=1.6, label=f'{m} ({ap:.2f})')
    ax[0].plot([0, 1], [0, 1], color='#C9D2E1', ls='--'); ax[1].axhline(pred.groupby(['year', 'sc']).y.first().mean(), color='#C9D2E1', ls='--')
    ax[0].set(title=f'Target {tgt}: ROC curve, out of time', xlabel='False positive rate', ylabel='True positive rate')
    ax[1].set(title=f'Target {tgt}: precision-recall, out of time', xlabel='Recall', ylabel='Precision')
    for a in ax: a.legend(fontsize=7, frameon=False)
    save(fig, f'roc_pr_target_{tgt}')
fig, ax = plt.subplots(figsize=(7, 4))
for i, m in enumerate(MODELS[:6]):
    yy = yearA[yearA.model == m]; ax.plot(yy.year, yy.roc_auc, marker='o', color=PALETTE[i], label=m)
ax.set(title='Target A: ROC AUC by test year', xlabel='Test year (start-year cohort)', ylabel='ROC AUC', ylim=(0.5, 1)); ax.set_xticks(YEARS_A); ax.legend(fontsize=7, frameon=False)
save(fig, 'auc_by_year_target_A')
fig, ax = plt.subplots(figsize=(5.5, 4.4))
for i, m in enumerate(['Auto-selected + calibrated', 'Logistic regression']):
    c = calA[calA.model == m]; ax.plot(c.predicted, c.actual, marker='o', color=PALETTE[i], label=m)
ax.plot([0, 1], [0, 1], color='#C9D2E1', ls='--'); ax.set(title='Target A: calibration (pooled)', xlabel='Average predicted chance', ylabel='Actual rate', xlim=(0, 1), ylim=(0, 1)); ax.legend(fontsize=7, frameon=False)
save(fig, 'calibration_target_A')
fig, ax = plt.subplots(figsize=(7, 4.4))
o = orA.sort_values('odds_ratio'); ax.errorbar(o.odds_ratio, o.signal, xerr=[o.odds_ratio - o.lo, o.hi - o.odds_ratio], fmt='o', color=PALETTE[0], ecolor='#9AA4B5')
ax.axvline(1, color='#C9D2E1', ls='--'); ax.set_xscale('log'); ax.set(title='Target A: odds ratios with 95% ranges', xlabel='Odds ratio (log scale)')
save(fig, 'odds_ratios_target_A')
fig, ax = plt.subplots(figsize=(7, 4))
lm = [m for m in MODELS]
ax.barh(lm, [pooledA.set_index('model').loc[m, 'capture_top20_per_year'] for m in lm], color=PALETTE[0]); ax.axvline(0.2, color='#C9D2E1', ls='--')
ax.set(title='Target A: share of future 5-seat accounts in the top 20% of scores', xlabel='Capture (each test year ranked separately)', xlim=(0, 1))
save(fig, 'lift_capture_target_A')
print(sorted(os.listdir(CHARTS)))
""")

md("## 14. Save results and exports\nResults for the workbook go to `data/early_signal_prediction/` (local, not in git); exports to `outputs/csv/early_signal_prediction/`.")
code("""
f.to_csv(f'{RES}/features.csv', index_label='shortcode')
for name, d in dict(predA=predA, predB=predB, pooledA=pooledA, pooledB=pooledB, yearA=yearA, yearB=yearB, diffA=diffA, diffB=diffB, chosenA=chosenA, chosenB=chosenB,
                    targets=targets, signals=signals, sens=sens, drivers=drivers, imp=imp.reset_index(names='feature'), calA=calA, calYear=calYear, ruleA=ruleA,
                    beatsA=beatsA.reset_index(), watch=watch.reset_index(names='shortcode')).items():
    d.to_csv(f'{RES}/{name}.csv', index=False)
json.dump(dict(c_auc=c_auc, finalA=dict(family=finalA['family'], params=finalA['params']), finalB=dict(family=finalB['family'], params=finalB['params'])),
          open(f'{RES}/meta.json', 'w'), default=str)
pooledA.to_csv(f'{CSV}/model_comparison_target_A.csv', index=False); pooledB.to_csv(f'{CSV}/model_comparison_target_B.csv', index=False)
watch.to_csv(f'{CSV}/watch_list.csv', index_label='shortcode')
print(sorted(os.listdir(RES)))
""")

md("## 15. Build the workbook\nRuns `work/early_signal_prediction/build_early_signal_prediction.py`, which reads the saved results and the raw file, and runs the QA gate.")
code("""
import subprocess
r = subprocess.run([sys.executable, 'work/early_signal_prediction/build_early_signal_prediction.py'], capture_output=True, text=True, env={**os.environ, 'CS_QA_DIR': 'qa'})
print(r.stdout[-3000:]); print(r.stderr[-2000:])
""")

md("## 16. Headline numbers\nEvery figure quoted in the summary and the chat reply.")
code("""
pa, pb = pooledA.set_index('model'), pooledB.set_index('model')
H = [
    ('Target A eligible clients (all cohorts)', int(f.elig_A.sum())), ('Target A positives', int(f[f.elig_A].y_A.sum())),
    ('Target A clients in the backtest (2022-2025)', int(pa.loc['Logistic regression', 'n'])), ('Target A base rate in the backtest', pa.loc['Logistic regression', 'base_rate']),
]
for m in ['Logistic regression', 'Auto-selected + calibrated', 'LightGBM', 'Single signal: staff at day 90']:
    H += [(f'A {m}: ROC AUC', pa.loc[m, 'roc_auc']), (f'A {m}: ROC AUC 95% low', pa.loc[m, 'roc_auc_lo']), (f'A {m}: ROC AUC 95% high', pa.loc[m, 'roc_auc_hi']),
          (f'A {m}: PR AUC', pa.loc[m, 'pr_auc']), (f'A {m}: precision', pa.loc[m, 'precision']), (f'A {m}: recall', pa.loc[m, 'recall']),
          (f'A {m}: accuracy', pa.loc[m, 'accuracy']), (f'A {m}: top-20% capture (per year)', pa.loc[m, 'capture_top20_per_year']),
          (f'A {m}: top-10% lift', pa.loc[m, 'lift_top10'])]
H += [('Target B clients in the backtest', int(pb.loc['Logistic regression', 'n'])), ('Target B base rate', pb.loc['Logistic regression', 'base_rate']),
      ('B Logistic regression: ROC AUC', pb.loc['Logistic regression', 'roc_auc']), ('B Logistic regression: PR AUC', pb.loc['Logistic regression', 'pr_auc']),
      ('B Logistic regression: top-20% capture (per year)', pb.loc['Logistic regression', 'capture_top20_per_year']),
      ('Target C clients', int(f.elig_C.sum())), ('Target C cross-validated AUC', c_auc[0]),
      ('A without staff and start counts, LightGBM ROC AUC', sens.set_index(['variant', 'model']).loc[('Without staff and start counts', 'LightGBM'), 'roc_auc']),
      ('A without staff and start counts, logistic ROC AUC', sens.set_index(['variant', 'model']).loc[('Without staff and start counts', 'Logistic regression'), 'roc_auc']),
      ('A always-no accuracy (test years)', 1 - pa.loc['Logistic regression', 'base_rate']),
      ('Rule 2+ staff or second start: share flagged', ruleA.flagged_share.iloc[0]), ('Rule 2+ staff or second start: capture', ruleA.capture.iloc[0]),
      ('A plus division and industry, logistic ROC AUC', sens.set_index(['variant', 'model']).loc[('Plus Custom Division and industry', 'Logistic regression'), 'roc_auc']),
      ('A odds ratio: second start within 90 days', orA.set_index('signal').loc['Second start within 90 days', 'odds_ratio']),
      ('A odds ratio: per extra staff at day 90', orA.set_index('signal').loc['Staff at day 90 (per extra staff)', 'odds_ratio']),
      ('Watch list clients', len(watch)), ('Watch list scored', int((watch.status == 'Scored').sum()))]
headline = pd.DataFrame(H, columns=['figure', 'value'])
headline.to_csv(f'{RES}/headline.csv', index=False)
headline.assign(value=headline.value.map(lambda v: round(float(v), 3)))
""")

nb = nbf.v4.new_notebook()
nb["cells"] = cells
nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
os.makedirs(os.path.join(ROOT, "notebooks"), exist_ok=True)
nbf.write(nb, os.path.join(ROOT, "notebooks", "early_signal_prediction.ipynb"))
print("Wrote notebooks/early_signal_prediction.ipynb with", len(cells), "cells")
