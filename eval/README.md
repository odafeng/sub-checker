# Harness Regression Evaluation

用真實（私有）稿件量測 harness 品質：expected findings 的 recall、被錯殺的真
findings、漏掉的已知 false positives。**稿件永遠不進 repo** —— `eval/cases/`
已列入 `.gitignore`，runner 程式碼在 repo、評測資料在本地。

## 隱私模型

| 資料 | 位置 | 是否進 git |
|------|------|-----------|
| Runner 程式 (`sub_checker/eval_runner.py`) | repo | ✅ |
| 本說明與範例產生器 | repo | ✅ |
| 稿件 (.docx) 與 golden labels | `eval/cases/`（gitignored）或 `$SUB_CHECKER_EVAL_DIR` 指向的任何目錄 | ❌ 永不 |
| 評測結果 JSON | 你指定的 `--output` 路徑 | ❌（注意結果含 finding 文字，勿提交） |

注意：跑評測時稿件內容仍會送到 Anthropic API、references 衍生的查詢會送到
PubMed/Crossref/Semantic Scholar——和正常使用 sub-check 完全相同，評測不增加
額外暴露面。

## 快速開始

```bash
# 1. 先用合成範例確認 runner 能跑（不需要真實稿件）
python eval/make_example_case.py
sub-check-eval                       # 預設讀 ./eval/cases

# 2. 加入真實稿件 case
mkdir -p eval/cases/my-paper
cp ~/Documents/my-paper.docx eval/cases/my-paper/manuscript.docx
$EDITOR eval/cases/my-paper/golden.yaml   # 見下方格式

# 3. 之後每次調整 harness / prompt / model：
sub-check-eval --output /tmp/eval-results.json
```

也可以把 cases 放在 repo 外（例如加密磁碟或私人雲端同步資料夾）：

```bash
export SUB_CHECKER_EVAL_DIR=~/private/sub-checker-cases
sub-check-eval
```

## golden.yaml 格式

```yaml
journal: "The Lancet"        # optional，這個 case 跑的目標期刊
checkers: null               # optional，限制只跑某些 checkers（同 --only）
lang: en

# 必須在最終報告中存活的真 findings
expected:
  - id: typo-promissing
    description: "abstract 裡的 promissing 拼字錯誤"
    checker: typo_grammar    # optional：限定哪個 checker 回報
    keywords: ["promissing"] # 全部都要出現（不分大小寫，比對 message+suggestion+context）
  - id: ref-31-missing
    claim_type: missing_reference   # optional：比對結構化欄位
    ref_number: 31                  # optional
    keywords: []

# 已知的 false positives——必須被 harness 過濾掉，不能出現在報告裡
forbidden:
  - id: fp-nov-2025-future
    description: "舊版會把 November 2025 報成未來日期"
    keywords: ["November 2025"]
```

標 label 的建議流程：先 `sub-check manuscript.docx -o json --output-file run.json`
跑一次，人工審查每個 finding，真的放進 `expected`、假的放進 `forbidden`，
keywords 取 finding 訊息裡穩定的片段（引用編號、拼錯的字、圖表編號）。

## 怎麼讀結果

| 欄位 | 意義 | 期望 |
|------|------|------|
| Recall | expected 中存活的比例 | 100% |
| Wrongly filtered | **被 harness 錯殺的真 findings** —— 最糟的失敗模式，使用者永遠看不到 | 0 |
| FP leaked | 已知 false positives 卻出現在報告 | 0 |
| FP caught | 已知 false positives 被正確過濾 | 越多越好 |
| Noise | 存活但沒對到任何 label 的 findings | 人工抽查後補進 expected 或 forbidden |

任何 missed / wrongly filtered / leaked 都會讓 exit code = 1，方便接腳本。

## CI 注意事項

真實稿件的 cases **不要**接到公開 CI。可行做法：

- 本地在每次 harness 改動後手動跑（建議，最簡單）
- self-hosted runner + 機器上的私有 cases 目錄（`SUB_CHECKER_EVAL_DIR`）
- 合成範例 case（`make_example_case.py`）不含隱私，可用於 CI 冒煙測試，
  但仍需要 `ANTHROPIC_API_KEY` secret 且會產生 API 費用
