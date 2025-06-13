Below is a **clock-level “cookbook”** that turns your minute-bar features into a champion model in three phases.
Copy each code block into the stated file; every shell line is executable as-is (paths assume the repo layout from earlier answers).

---

# 📅  D-1 Evening  -  Environment & Skeleton

| Step                                                 | Command / File                                                                                                                           | Notes                                               |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| 1. Create venv                                       | `python -m venv .venv && source .venv/bin/activate`                                                                                      | Use the same Python in CI.                          |
| 2. Install deps                                      | `pip install "polars[all]" scikit-learn lightgbm optuna psycopg[binary] yfinance matplotlib seaborn jupyter nbconvert rich typer joblib` | *polars* = blazing load; *rich*/*typer* nicer CLIs. |
| 3. Repo tree                                         | \`\`\`bash                                                                                                                               |                                                     |
| mkdir -p modeling/{scripts,notebooks,output,configs} |                                                                                                                                          |                                                     |
| touch modeling/**init**.py                           |                                                                                                                                          |                                                     |

```| |
```

trading-lab/
│
├─ modeling/
│   ├─ scripts/
│   │   ├─ 0\_fetch.py
│   │   ├─ 1\_logreg.py
│   │   ├─ 2\_optuna\_lgbm.py
│   │   ├─ 3\_walk\_forward.py
│   │   └─ utils.py
│   ├─ notebooks/
│   │   └─ model\_report.ipynb   # will be generated
│   ├─ configs/
│   │   └─ db.toml              # Timescale credentials
│   └─ output/                  # metrics, models, figs

````

`configs/db.toml`
```toml
[db]
uri = "postgresql://trader:s3cr3t@localhost:5432/market"
schema = "public"
features_view = "features_1m"
````

---

# 📅 **Phase 1 – Baseline logistic regression**

## 1️⃣  `modeling/scripts/0_fetch.py`  (5-10 min)

```python
#!/usr/bin/env python
import polars as pl, tomli, pathlib, psycopg
from datetime import datetime

cfg = tomli.loads(pathlib.Path("modeling/configs/db.toml").read_text())
con = psycopg.connect(cfg["db"]["uri"], row_factory=psycopg.rows.dict_row)

sql = f"""
SELECT bucket AS ts,
       log_return,
       volume_z,
       vwap_gap,
       parkinson_vol,
       (lead(close,10) OVER (ORDER BY bucket) - close)/close  AS fwd_ret
FROM   {cfg['db']['features_view']}
WHERE  bucket >= (NOW() - INTERVAL '120 days');
"""
df = pl.read_database(sql, con).with_columns(
        (pl.col("fwd_ret") > 0.0015).alias("label"))  # taker fee + slippage
df.write_parquet("modeling/output/features.parquet")
print(df.shape, "rows saved")
```

Run:

```bash
python modeling/scripts/0_fetch.py
```

## 2️⃣  `modeling/scripts/utils.py`

```python
import polars as pl
from sklearn.metrics import roc_auc_score, average_precision_score

def load_features():
    return pl.read_parquet("modeling/output/features.parquet").drop_nulls()

def split_train_test(df, start, train_days=60, test_days=15, gap="1h"):
    train_end = start + pl.duration(days=train_days)
    test_start = train_end + pl.duration(hours=1)
    test_end  = test_start + pl.duration(days=test_days)
    tr = df.filter((pl.col("ts")>=start) & (pl.col("ts")<train_end))
    te = df.filter((pl.col("ts")>=test_start) & (pl.col("ts")<test_end))
    return tr, te
```

## 3️⃣  `modeling/scripts/1_logreg.py`

```python
#!/usr/bin/env python
import joblib, pathlib, typer, polars as pl
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score
from utils import load_features, split_train_test

app = typer.Typer()
@app.command()
def train(start: str = "2025-01-01"):
    df = load_features()
    tr, te = split_train_test(df, pl.from_datetime(start))
    Xtr, ytr = tr.select(pl.exclude(["ts","label"])).to_numpy(), tr["label"]
    Xte, yte = te.select(pl.exclude(["ts","label"])).to_numpy(), te["label"]

    pipe = Pipeline([
        ("sc", StandardScaler()),
        ("lg", LogisticRegression(max_iter=300, class_weight="balanced"))
    ])
    pipe.fit(Xtr, ytr)
    proba = pipe.predict_proba(Xte)[:,1]

    metrics = {
        "roc_auc": roc_auc_score(yte, proba),
        "pr_auc" : average_precision_score(yte, proba)
    }
    pathlib.Path("modeling/output/baseline_metrics.json").write_text(str(metrics))
    joblib.dump(pipe, "modeling/output/logreg.pkl")
    print("metrics:", metrics)

if __name__ == "__main__":
    app()
```

Run and verify **AUC > 0.55**:

```bash
python modeling/scripts/1_logreg.py train --start 2025-01-01
cat modeling/output/baseline_metrics.json
```

---

# 📅 **Phase 2 – LightGBM hyper-sweep with Optuna**

## 1️⃣  `modeling/scripts/2_optuna_lgbm.py`

```python
#!/usr/bin/env python
import optuna, joblib, json, polars as pl, lightgbm as lgb
from utils import load_features, split_train_test
from sklearn.metrics import average_precision_score

df = load_features()
train_df, test_df = split_train_test(df, pl.from_datetime("2025-01-01"))

Xtr, ytr = train_df.select(pl.exclude(["ts","label"])).to_numpy(), train_df["label"]
Xte, yte = test_df.select(pl.exclude(["ts","label"])).to_numpy(), test_df["label"]

dtrain = lgb.Dataset(Xtr, label=ytr)

def objective(trial):
    params = {
       "objective":"binary",
       "metric":"average_precision",
       "learning_rate": trial.suggest_float("lr", 0.005, 0.2, log=True),
       "num_leaves":    trial.suggest_int("leaves", 8, 256, log=True),
       "max_depth":     trial.suggest_int("depth", 3, 9),
       "min_data_in_leaf": trial.suggest_int("min_data", 10, 200),
       "feature_fraction": trial.suggest_float("feat_frac", 0.5, 1.0),
       "bagging_fraction": trial.suggest_float("bag_frac", 0.5, 1.0),
       "bagging_freq": 1,
       "verbosity": -1
    }
    gbm = lgb.train(params, dtrain, num_boost_round=100,
                    valid_sets=[dtrain], verbose_eval=False)
    proba = gbm.predict(Xte)
    pr = average_precision_score(yte, proba)
    return pr

study = optuna.create_study(direction="maximize")
study.optimize(objective, n_trials=60, timeout=1800)  # ~30 min

best_params = study.best_params
gbm = lgb.train({**best_params, "objective":"binary"}, dtrain, num_boost_round=300)
proba = gbm.predict(Xte)
pr_auc = average_precision_score(yte, proba)

joblib.dump(gbm, "modeling/output/lgbm_optuna.pkl")
json.dump({"pr_auc": pr_auc, "best_params": best_params},
          open("modeling/output/lgbm_metrics.json","w"))
print("PR-AUC", pr_auc)
```

Run:

```bash
python modeling/scripts/2_optuna_lgbm.py
```

**Goal:** `pr_auc ≥ baseline_pr_auc + 0.02`.

---

# 📅 **Phase 3 – Walk-forward validator & Sharpe metrics**

## 1️⃣  `modeling/scripts/3_walk_forward.py`

```python
#!/usr/bin/env python
import polars as pl, joblib, json, rich.table, rich.console
from utils import load_features
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score
import numpy as np

df = load_features()
results = []
console = rich.console.Console()

for start in pl.date_range(df["ts"].min(), df["ts"].max()-pl.duration(days=75), pl.duration(days=15)):
    tr = df.filter((pl.col("ts")>=start) & (pl.col("ts")< start + pl.duration(days=60)))
    gap_end = start + pl.duration(days=60, hours=1)
    te = df.filter((pl.col("ts")>=gap_end) & (pl.col("ts")< gap_end + pl.duration(days=15)))

    Xtr, ytr = tr.drop(["ts","label"]).to_numpy(), tr["label"]
    Xte, yte = te.drop(["ts","label"]).to_numpy(), te["label"]

    pipe = Pipeline([("sc",StandardScaler()),
                     ("lg",LogisticRegression(max_iter=250, class_weight="balanced"))])
    pipe.fit(Xtr,ytr)
    proba = pipe.predict_proba(Xte)[:,1]
    preds = (proba>0.55).astype(int)
    returns = te["log_return"].to_numpy()

    # Trade simulation
    strat_ret = preds * returns - 0.0015   # subtract fees
    equity = (1+strat_ret).cumprod()
    sharpe = np.sqrt(1440*365)*np.mean(strat_ret) / np.std(strat_ret) if np.std(strat_ret)>0 else 0
    max_dd = 1 - equity/ np.maximum.accumulate(equity)

    results.append({
        "window_start": str(start),
        "auc": roc_auc_score(yte, proba),
        "hit_rate": np.mean(strat_ret>0),
        "sharpe": sharpe,
        "max_dd": np.max(max_dd)
    })

table = rich.table.Table(title="Walk-forward Summary")
for col in results[0]: table.add_column(col)
for row in results: table.add_row(*[f"{v:.4f}" if isinstance(v,float) else v for v in row.values()])
console.print(table)
pl.DataFrame(results).write_json("modeling/output/walk_forward.json")
```

Run:

```bash
python modeling/scripts/3_walk_forward.py
```

Outputs `walk_forward.json` with per-fold AUC, Sharpe, hit-rate, max drawdown.

> **Interpretation targets**
>
> * Mean Sharpe ≥ 1.0, hit-rate > 55 %, max DD < 4 % in any fold.

---

## 2️⃣  Generate the model report notebook

```bash
jupyter nbconvert --to notebook --execute modeling/notebooks/model_report.ipynb \
   --output modeling/notebooks/model_report_run.ipynb
jupyter nbconvert --to markdown modeling/notebooks/model_report_run.ipynb \
   --output docs/MODEL.md
```

Template for `model_report.ipynb` (Markdown cells only):

1. **Objective** – recap labels & features.
2. **Baseline metrics** – embed `baseline_metrics.json`.
3. **Optuna search space & best params** – show `lgbm_metrics.json`.
4. **Walk-forward table** – load `walk_forward.json`.
5. **Key plots**

   * ROC curve baseline vs LightGBM.
   * Equity curves of two best folds.
6. **Decision** – state champion model & threshold.
7. **Next steps** – ideas (ensemble, threshold sweep, position sizing).

Notebook will auto-execute, pull JSONs, draw plots (`matplotlib`).

---

# 📈 4   Hook into CI (optional but recommended)

`.github/workflows/model.yml`

```yaml
name: model
on: [push, pull_request]
jobs:
  train:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.12'}
      - run: python -m pip install -r requirements.txt
      - run: |
          python modeling/scripts/0_fetch.py
          python modeling/scripts/1_logreg.py train --start 2025-01-01
          python modeling/scripts/3_walk_forward.py
      - name: Upload metrics
        uses: actions/upload-artifact@v4
        with:
          name: model-metrics
          path: modeling/output/*.json
```

---

# 🏁  Deliverables checklist

* [ ] `features.parquet` cached ⇒ **commit ignored** (add to `.gitignore`).
* [ ] `baseline_metrics.json` **AUC > 0.55**.
* [ ] `lgbm_metrics.json` **PR-AUC ≥ baseline + 0.02**.
* [ ] `walk_forward.json` with Sharpe / DD stats.
* [ ] `docs/MODEL.md` (auto-built) summarising everything.
* [ ] `logreg.pkl` & `lgbm_optuna.pkl` stored in `modeling/output/` (ignored by Git, pushed to object storage if needed).

When all boxes are checked, phase 3 is done and the champion model is ready to be wired into the live FastAPI inference server. 🔌📈
