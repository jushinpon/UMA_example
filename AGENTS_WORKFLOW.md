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
| `$task` | `omat` | FairChem task | omat/oc20/omol/odac/omc/oc22/oc25？ |
| `@tempw` | `(300)` | 溫度 (K) | 要跑哪些溫度？ |
| `@press` | `(0)` | 壓力 (GPa) | 要跑哪些壓力？ |
| `$opt1_steps` | `250` | OPT-1 步數 | 需要調整嗎？ |
| `$opt1_fmax` | `0.1` | OPT-1 收斂 threshold (eV/A) | |
| `$opt2_steps` | `250` | OPT-2 步數 | |
| `$opt2_fmax` | `0.05` | OPT-2 收斂 threshold (eV/A) | |
| `$npt_steps` | `250` | MD 步數 (0=SCF only) | |
| `$eq_steps` | (from .pl) | Eq MD 步數 | |
| `$prod_low` | `300` | Prod MD 起始溫度 (K) | Heating ramp 起始溫度？ |
| `$prod_high` | `600` | Prod MD 終止溫度 (K) | Heating ramp 終止溫度？ |
| `$prod_freq` | (from .pl) | 輸出頻率 | |
| `$timestep` | `1.5` | MD timestep (fs) | 金屬用2.0，共價用1.5 |
| `$do_supercell` | `0` | 自動 supercell | 納米粒子建議 1 |
| `($cx,$cy,$cz)` | `(0,0,0)` | Cell DOF | bulk: 1,1,1; surface: 1,1,0 |

### 不同資料類型的建議參數

| 類型 | model | task | temp | timestep | do_supercell | cell DOF |
|------|-------|------|------|----------|--------------|----------|
| Bulk 合金 | uma-s-1p2p1 | omat | 300 | 2.0 | 0 | 1,1,1 |
| 納米粒子 (NP) | uma-s-1p2p1 | omat | 300 | 2.0 | **1** | 0,0,0 |
| 表面 (surface) | uma-s-1p2p1 | omat | 300 | 1.5 | 0 | 1,1,0 |
| 分子 | uma-s-1p2p1 | omol | 300 | 1.0 | 0 | 0,0,0 |
| 催化 (氧化物) | uma-s-1p2p1 | **oc22** | 300 | 1.5 | 0 | 1,1,0 |
| 電催化 | uma-s-1p2p1 | **oc25** | 300 | 1.5 | 0 | 1,1,0 |

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
```
