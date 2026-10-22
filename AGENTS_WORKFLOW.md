# AI Agent UMA Workflow — 必讀流程

> **每次執行 UMA pipeline 前，必須依序完成以下步驟。不可跳過。**

---

## Step 1: 確認資料路徑

**必須先問使用者：**
- 要跑哪些 `.data` 檔案？
- 檔案放在哪個路徑下？（預設: `~/UMA_example/categorized_data4UMA/`）
- 是否已分類到子資料夾（如 `NP/`, `FCC/`, `BCC/`）？

```bash
# 列出目前可用的 data 檔
find ~/UMA_example/categorized_data4UMA/ -name "*.data" -type f
```

**確認事項：**
- [ ] 使用者確認要跑的檔案清單
- [ ] 檔案路徑正確

---

## Step 2: 檢查 data 檔案格式

**每個 .data 檔案必須包含：**

### 2a. Masses 區塊必須有 `# Element` 註解

```
Masses

1 58.933194 # Co    ← 必須有 "# Element"
2 51.9961   # Cr
3 63.546    # Cu
```

❌ 缺少 `# Element` 會導致 `gptfakeQE.py` 失敗

### 2b. Atoms 區塊格式

```
Atoms  # atomic

1 1  x  y  z
2 2  x  y  z
```

### 2c. 檢查腳本

```bash
# 檢查所有 data 檔的 Masses 區塊
for f in $(find ~/UMA_example/categorized_data4UMA/ -name "*.data"); do
    echo "=== $f ==="
    grep -A 20 "^Masses" "$f" | head -15
    echo ""
done
```

**確認事項：**
- [ ] 所有檔案的 Masses 區塊都有 `# Element`
- [ ] Atoms 區塊格式正確
- [ ] 如有問題，先請使用者修正再繼續

---

## Step 3: 確認/修改 gptfakeQE.py 參數

**展示目前的 default 參數，詢問使用者是否要修改：**

| 參數 | Default | 說明 | 問使用者 |
|------|---------|------|----------|
| `$model` | `uma-s-1p2p1` | UMA 模型 | 要用 small 還是 medium？ |
| `$task` | `oc25` | FairChem task | **提案資料集固定 `oc25`**(見下方「單一理論層級」原則) |
| `@tempw` | `(300)` | **只影響資料夾名稱** `-T300`,不改任何 MD 溫度 | 只是標籤,通常不用改 |
| `@press` | `(0)` | **只影響資料夾名稱** `-P0`,不改任何 MD 壓力 | 只是標籤,通常不用改 |
| `$opt1_steps` | `250` | OPT-1 步數 | 需要調整嗎？ |
| `$opt1_fmax` | `0.1` | OPT-1 收斂 threshold (eV/A) | |
| `$opt2_steps` | `250` | OPT-2 步數 | |
| `$opt2_fmax` | `0.05` | OPT-2 收斂 threshold (eV/A) | |
| `$npt_steps` | `250` | **legacy:gptfakeQE.py 解析但不使用** | 不用改(保持 ≤999) |
| `$eq_steps` | `500` | Eq MD 步數 | 提案用 10000(與 prod 等長) |
| `$eq_temp` | `10` | Eq 溫度 (K) | 全類型 10（2026-10-22 起的新系統；既有 54 個 job 為 300） |
| `$eq_press` | `0` | Eq 壓力 (GPa) | 全類型 0 |
| `$eq_timestep` | 見類別表 | Eq timestep (fs) | 與 prod_timestep 相同 |
| `$prod_steps` | `10000` | Prod MD 步數 | 配 freq=20 → 500 幀 |
| `$prod_low` | `10` | Prod MD 起始溫度 (K) | 全類型 10（2026-10-22 起的新系統；既有 job 為 300） |
| `$prod_high` | `360` | Prod MD 終止溫度 (K) | 依類別表(360–900 K) |
| `$prod_press` | `0` | Prod 壓力 (GPa) | 全類型 0 |
| `$prod_timestep` | 見類別表 | Prod timestep (fs) | 金屬 2.0 / 共價 1.5 / 含水 1.0 |
| `$prod_freq` | `20` | 輸出頻率 | 10000/20 = **500**（末結構無能量/力，轉檔時丟棄） |
| `$do_supercell` | `0` | 自動 supercell | 納米粒子建議 1 |
| `($bulk_cx,$bulk_cy,$bulk_cz)` | `(1,1,1)` | Cell DOF：路徑**不含** `surface` 的檔案 | bulk 1,1,1；cluster 0,0,0 |
| `($surface_cx,$surface_cy,$surface_cz)` | `(0,0,0)` | Cell DOF：路徑**含** `surface` 的檔案 | surface 系列 1,1,0 |

> **DOF 三連只由路徑決定**：`.pl` 只判斷 `if ($file =~ /surface/)`。因此
> `surface/`、`surface_wet/`、`surface_pcet/` 走 `$surface_c*`;`bulk/`、`cluster/`、
> `solvent/` **全部**走 `$bulk_c*`。cluster(0,0,0)與 solvent(1,1,1)不能在同一輪裡跑,
> 要分開執行(或把資料夾改名讓它落到另一組)。

### 單一理論層級原則(必須)

同一個訓練資料集只用一組 `model` + `task`(如同一份 DFT 資料庫只有一種設定)。
本提案(電催化界面)固定:`model = uma-s-1p2p1`,`task = oc25`。
不同類型的資料**不可混用不同 task**(omat/omol/oc22…) — 混頭的資料庫
訓練出的 DeePMD 模型沒有單一理論層級可言。

### 每類資料的建議參數(含 EQ/PROD)

所有類型共通:`eq_steps=10000`、`eq_temp=10`、`eq_press=0`、
`prod_steps=10000`、`prod_press=0`、`prod_freq=20`
→ 每 job **500 幀**(`prod_steps/prod_freq`;檔尾第 10000 步的結構**沒有**能量/力,
真 QE 不會對最後構型再跑 SCF,轉檔時丟棄)。
新系統自 2026-10-22 起 eq 與 prod **都從 10 K 起跑**(既有 54 個 job 為 300 K,不重跑)。
opt1/opt2/npt 用 repo 預設 250 步。

| 類型(資料夾) | timestep (fs) | prod ramp (K) | cell DOF (bulk / surface) | do_supercell |
|---|---|---|---|---|
| bulk(fcc 金屬) | 2.0 | 10→900 | 1,1,1 / 0,0,0 | 0 |
| cluster(奈米粒子) | 2.0 | 10→600 | 0,0,0 / 0,0,0 | **1** |
| surface(清潔 slab) | 1.5 | 10→600 | 0,0,0 / 1,1,0 | 0 |
| surface_ads(吸附物覆蓋) | 1.5 | 10→500 | 0,0,0 / 1,1,0 | 0 |
| surface_wet(wet / PCET / 界面) | 1.0 | 10→400 | 0,0,0 / 1,1,0 | 0 |
| solvent(水 / 水+離子) | 1.0 | 10→360 | 1,1,1 / 0,0,0 | 0 |

每類的科學理由(ramp 上限、timestep、cell DOF)見提案 repo
`deepmd/scripts/uma_pipeline/category_params.py` 內各類別的 `reason` 註解。

**確認事項：**
- [ ] 使用者確認或修改參數
- [ ] 不同類型的 data 用對應的參數

---

## Step 4: 修改 arrange_data4UMA.pl

根據 Step 3 的確認，修改 `~/UMA_example/scripts/arrange_data4UMA.pl` 頂部的參數。

```bash
# 修改前先備份
cp ~/UMA_example/scripts/arrange_data4UMA.pl ~/UMA_example/scripts/arrange_data4UMA.pl.bak
```

> **提案自動化**:跑 `uma_auto.py arrange-pass <class>` 時,這一步(備份 + 改參數)由腳本
> 自動完成(參數來自 `category_params.py`),不需要手改。手改只用於單獨/臨時執行。
>
> ⚠️ `.pl` 執行時會先 `rm -rf $out_folder/*-UMA` 再重建,**已完成 job 的目錄會一併消失**。
> 重跑前先把要保留的 job 目錄搬走。

**確認事項：**
- [ ] 參數已正確寫入 .pl 檔案
- [ ] 路徑指向正確的資料夾

---

## Step 5: 生成 Slurm 腳本

```bash
cd ~/UMA_example/scripts
perl arrange_data4UMA.pl
```

**檢查生成結果：**
```bash
ls ~/UMA_example/UMA_inputs/
# 應該看到每個 data 檔對應的資料夾和 .sh 檔案
```

**確認事項：**
- [ ] 生成的 .sh 檔案數量正確
- [ ] .sh 檔案內的參數正確（抽查 1-2 個）

---

## Step 6: 確認後提交

**向使用者報告：**
- 共生成 N 個 job
- 參數摘要
- 預估運行時間

**獲得確認後才提交：**
```bash
cd ~/UMA_example/scripts
perl submit_allslurm_sh.pl
```

**確認事項：**
- [ ] 使用者確認提交
- [ ] squeue 確認 job 已進入排隊

---

## Step 7: 完工驗收

job 標記完成後,每個 job 目錄必須滿足(以 `prod_steps=10000`、`prod_freq=20` 慣例):

```bash
ls <job_dir>/data_files/*.data | wc -l    # → 500
grep -c "^!" <job_dir>/<name>.sout        # → 500
```

- `thermo_summary.png` 必須有曲線(空白面板 → `plot_thermo.py` 過時,見 `docs/RUNBOOK.md`)
- `<name>.err` 不得有 traceback;`.sout` 不得出現 divergence 中止

**確認事項：**
- [ ] 500 / 500 通過
- [ ] 0 traceback

---

## ⚠️ 絕對不可做的事

1. **不可跳過 Step 1-3 直接提交** — 必須先確認 data 和參數
2. **不可假設所有 data 檔格式相同** — 逐類型檢查
3. **不可用 srun/salloc** — 只能用 sbatch
4. **不可在未備份的情況下修改 .pl** — 先 cp .bak
5. **不可一次提交大量 job 而不告知使用者** — 先報告數量

---

## 速查：完整執行流程

```
Step 1: 問路徑 → find *.data
Step 2: 檢查格式 → grep Masses
Step 3: 問參數 → 展示 default，詢問修改
Step 4: 改 .pl → 備份 + 修改
Step 5: 生成 → perl arrange_data4UMA.pl
Step 6: 確認 → 報告數量 + 等使用者說 OK → sbatch
Step 7: 驗收 → data_files=500、grep -c '^!'=500、.err 無 traceback
```
