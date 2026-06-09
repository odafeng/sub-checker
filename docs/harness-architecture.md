# Harness Architecture

sub-checker 使用 **Plan-Execute-Verify** 架構，在 7 個 checker agents 產出 findings 之後，透過 deterministic 驗證和 LLM-based reviewer 過濾 false positives、標註 confidence scores。

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Orchestrator                             │
│                                                                   │
│  ┌─── Pre-Execution Harness ──────────────────────────────────┐  │
│  │                                                             │  │
│  │  Deterministic Pre-Pass (citation_exist)                    │  │
│  │  ├─ extract_citation_numbers(): regex 掃描全文引用編號      │  │
│  │  ├─ count_references(): 計算參考文獻行數                    │  │
│  │  └─ 結果注入 agent initial message                         │  │
│  │                                                             │  │
│  │  Multi-Source Verification (citation_claim)                 │  │
│  │  ├─ PubMed API (biomedical)                                │  │
│  │  ├─ Semantic Scholar API (broad coverage)                   │  │
│  │  ├─ Crossref API (DOI-based)                               │  │
│  │  ├─ Cross-validate: title similarity + source overlap       │  │
│  │  └─ 驗證報告注入 agent initial message                     │  │
│  │                                                             │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌─── Agent Execution (Phase 1-3) ────────────────────────────┐  │
│  │                                                             │  │
│  │  Phase 1 (parallel):                                        │  │
│  │    typo_grammar | figure_table | citation_exist             │  │
│  │                                                             │  │
│  │  Phase 2 (parallel):                                        │  │
│  │    citation_format | journal_guidelines | logic             │  │
│  │                                                             │  │
│  │  Phase 3:                                                   │  │
│  │    citation_claim (with multi-source verification data)     │  │
│  │                                                             │  │
│  └───────────────────────── produces findings ────────────────┘  │
│                                    │                              │
│                                    ▼                              │
│  ┌─── Post-Validation Harness ────────────────────────────────┐  │
│  │                                                             │  │
│  │  Phase 4: Deterministic Checks (0 cost, <1ms)              │  │
│  │  ├─ validate_date_claims()                                  │  │
│  │  ├─ validate_citation_numbers()                             │  │
│  │  └─ validate_self_consistency()                             │  │
│  │       → filtered findings: validation_status="filtered"     │  │
│  │       → downgraded findings: severity→INFO, confidence↓     │  │
│  │                                                             │  │
│  │  Phase 5: Reviewer Agent (Opus 4.8, ~$0.50)                │  │
│  │  ├─ 接收全部 non-filtered findings + manuscript context     │  │
│  │  ├─ 逐一審查: confirm / downgrade / filter                 │  │
│  │  ├─ 標註 confidence score (0.0-1.0)                        │  │
│  │  └─ 已知 false positive 模式清單                            │  │
│  │       → confirmed: 保留，顯示 confidence badge             │  │
│  │       → downgraded: severity→INFO                           │  │
│  │       → filtered: 從報告中移除                              │  │
│  │                                                             │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                    │                              │
│                                    ▼                              │
│                            Final Report                           │
│  ├─ 只顯示 non-filtered findings                                │
│  ├─ Confidence badges (confirmed %, downgraded %)               │
│  ├─ COT viewer (每個 agent 的推理過程)                          │
│  ├─ Model 名稱顯示在 header + footer                           │
│  └─ 多語系 (en / zh-TW)                                        │
└─────────────────────────────────────────────────────────────────┘
```

## Pre-Execution Harness

### Deterministic Pre-Pass

`manuscript_tools.extract_citation_numbers()` 用 regex 從全文提取所有數字引用：

```python
# 支援的格式
(1)  [1]  (1-3)  [1-3]  (1,2,5)  (1, 2, 5–7)
```

結果注入 `citation_exist` agent 的 initial message：

```
--- DETERMINISTIC PRE-SCAN (regex, highly reliable) ---
Citation numbers found in text: [1, 2, 3, ..., 29]
Total distinct citation numbers: 29
Reference list entries (by line count): 29
All numbered citations match reference list entries. No mismatches.
--- END PRE-SCAN ---
```

Agent 被指示 **信任 pre-scan 結果**，只處理 author-year 格式和 edge cases。

### Multi-Source Citation Verification

`services/citation_verifier.py` 為每個 reference 執行三源查詢：

```
Reference text → parse (author, year, DOI, title keywords)
                    │
                    ├─→ PubMed search
                    ├─→ Semantic Scholar search
                    └─→ Crossref search (DOI direct lookup if available)
                    │
                    └─→ Cross-validate
                         ├─ Title similarity (SequenceMatcher)
                         ├─ Source overlap count
                         └─ Confidence score + status
```

**Verification status levels:**

| Status | Sources | Confidence | 意義 |
|--------|---------|------------|------|
| `verified` | 2-3 sources | 0.85-0.95 | 多源確認，高可信度 |
| `likely_valid` | 1 source | 0.60-0.80 | 單源找到，可能有效 |
| `uncertain` | 0 sources, partial match | 0.12-0.40 | 無法確認 |
| `not_found` | 0 sources | 0.00-0.12 | 找不到（可能太新或未索引） |

**Rate limiting:**
- Batch size: 3 references at a time
- Per-client intervals: PubMed 0.35s, S2 1.0s, Crossref 0.25s
- Retry: 3 attempts with 1s/3s/8s backoff on 429/5xx

## Post-Validation Harness

### Phase 4: Deterministic Checks

三種 deterministic validator，各自回傳 `(finding_index, action, reason)`：

#### `validate_date_claims()`
偵測 findings 中宣稱某日期為「未來日期」的錯誤：

```python
# Finding 說 "November 2025 是未來日期"
# 但 today = 2026-06-10，所以 November 2025 是過去
# → action: "filter", reason: "November 2025 is in the past"
```

#### `validate_citation_numbers()`
用 regex pre-scan 交叉比對 agent 的引用判斷：

```python
# Finding 說 "Reference [23] not cited in text"
# 但 regex scan 確認 23 在文中出現
# → action: "filter", reason: "Reference [23] IS cited in text"
```

#### `validate_self_consistency()`
偵測 finding 自身矛盾的情況：

```python
# Finding 說 "組件名稱格式不一致：X 用下劃線，Y 也用下劃線"
# 所有範例都用下劃線 → 不是不一致
# → action: "downgrade"
```

### Phase 5: Reviewer Agent

獨立的 Opus 4.8 agent，接收：
- Manuscript context（title, sections, text preview, references）
- 所有 non-filtered findings（JSON 格式）

產出 JSON verdicts：

```json
[
  {"index": 0, "action": "confirm", "confidence": 0.95, "reason": "Pearson vs Spearman mismatch is real"},
  {"index": 1, "action": "filter", "confidence": 0.1, "reason": "Pre-scan year numbers misidentified as citations"},
  {"index": 2, "action": "downgrade", "confidence": 0.4, "reason": "Style preference, not a compliance issue"}
]
```

**Reviewer 的已知 false positive 模式清單：**
- 宣稱日期為未來但實為過去
- Section 內容在 sub-sections 卻被報為空
- 引用格式不一致但所有範例使用相同格式
- 未指定期刊卻假設特定格式
- Word auto-numbering 被報為缺少編號
- 獨立 heading 文字被報為位置錯誤

## Finding Model

每個 Finding 有三個 validation 欄位：

```python
@dataclass
class Finding:
    checker: str
    severity: Severity        # ERROR / WARNING / INFO
    message: str
    location: str | None
    suggestion: str | None
    context: str | None
    # Post-validation metadata
    confidence: float = 1.0           # 0.0-1.0
    validation_status: str = ""       # "confirmed", "filtered", "downgraded", ""
    validation_note: str = ""         # Reviewer's reasoning
```

**HTML 報告行為：**
- `filtered`: 不顯示
- `confirmed`: 顯示 + 綠色 confidence badge
- `downgraded`: severity 降為 INFO + 黃色 confidence badge
- 無 status（未經 reviewer）: 正常顯示，無 badge

## Cost Breakdown

以 ~4000 字 manuscript、29 references 為例：

| Phase | Component | Cost | Time |
|-------|-----------|------|------|
| Pre-pass | Regex extraction | $0 | <1ms |
| Pre-pass | Multi-source verification (29 refs × 3 APIs) | $0 | ~30-60s |
| Phase 1-3 | 7 agents (Opus 4.8) | ~$8-12 | ~8-12 min |
| Phase 4 | Deterministic checks | $0 | <1ms |
| Phase 5 | Reviewer agent (Opus 4.8) | ~$0.50 | ~30s |
| **Total** | | **~$9-13** | **~10-15 min** |

## Files

| File | 功能 |
|------|------|
| `harness/__init__.py` | Package |
| `harness/deterministic.py` | Phase 4: date, citation, consistency checks |
| `harness/reviewer.py` | Phase 5: LLM-based reviewer agent |
| `services/citation_verifier.py` | Multi-source verification + cross-validation |
| `services/crossref.py` | Crossref API client |
| `services/pubmed.py` | PubMed API client (rate limited) |
| `services/semantic_scholar.py` | S2 API client (rate limited) |
| `tools/manuscript_tools.py` | `extract_citation_numbers()`, `count_references()` |
| `orchestrator.py` | 5-phase pipeline wiring |
| `reporters/html_reporter.py` | Confidence badges, filtered finding removal |
