# Harness Architecture

sub-checker 使用 **Plan-Execute-Verify** 架構：7 個 checker agents 產出結構化 findings 之後，先經過 deterministic 驗證（事實比對），再由有工具的 reviewer agent 查證原文、過濾 false positives 並標註 confidence scores。

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Orchestrator                             │
│                                                                   │
│  ┌─── Pre-Execution Harness ──────────────────────────────────┐  │
│  │                                                             │  │
│  │  Deterministic Pre-Pass (citation_exist)                    │  │
│  │  ├─ extract_citation_numbers(): regex 掃描全文引用編號      │  │
│  │  │   （排除年份與不合理的數字範圍）                          │  │
│  │  ├─ count_references(): 計算參考文獻行數                    │  │
│  │  └─ 結果注入 agent initial message                         │  │
│  │                                                             │  │
│  │  Multi-Source Verification (citation_claim)                 │  │
│  │  ├─ PubMed API (biomedical, esummary 批次取標題)           │  │
│  │  ├─ Semantic Scholar API (broad coverage)                   │  │
│  │  ├─ Crossref API (DOI-based)                               │  │
│  │  ├─ Cross-validate: title similarity + source overlap       │  │
│  │  └─ 驗證報告注入 agent initial message                     │  │
│  │                                                             │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌─── Phase 1: Agent Execution ───────────────────────────────┐  │
│  │                                                             │  │
│  │  全部 checkers 並發執行，受全域 semaphore 限制              │  │
│  │  (max_concurrent_agents, 預設 3)。checkers 之間沒有資料     │  │
│  │  相依，因此沒有 phase barrier — 慢的 checker 不會擋住       │  │
│  │  其他 checker。排程順序：輕量 checkers 優先，               │  │
│  │  citation_claim 最後（它有昂貴的 pre-pass）。               │  │
│  │                                                             │  │
│  │  Per-checker models（Config.models）：                      │  │
│  │    機械性檢查（typo_grammar, figure_table, citation_exist,  │  │
│  │    citation_format）預設 Sonnet；判斷性檢查（logic,         │  │
│  │    journal_guidelines, citation_claim）用全域 model（Opus） │  │
│  │                                                             │  │
│  │  每個 agent loop 使用 prompt caching（system + tools +      │  │
│  │  message breakpoints），上限 30 iterations。                │  │
│  │                                                             │  │
│  └───────────── produces findings (with structured fields) ───┘  │
│                                    │                              │
│                                    ▼                              │
│  ┌─── Phase 2: Deterministic Checks (0 cost, <1ms) ──────────┐  │
│  │                                                             │  │
│  │  優先比對 findings 的結構化欄位（claim_type / claimed_date  │  │
│  │  / ref_number），沒有結構化欄位才 fallback 到訊息 regex。   │  │
│  │                                                             │  │
│  │  ├─ validate_date_claims()      — 日期數學                  │  │
│  │  ├─ validate_citation_numbers() — 引用交叉比對              │  │
│  │  └─ validate_self_consistency() — 自相矛盾偵測              │  │
│  │                                                             │  │
│  │  Fail-safe 原則：                                           │  │
│  │  - 基於精確資料的檢查（全文 regex 掃描）→ 可 "filter"       │  │
│  │  - 基於啟發式的檢查（行數估計 ref_count）→ 只能            │  │
│  │    "downgrade"，最終判斷留給 reviewer                       │  │
│  │  - downgrade 記錄 original_severity，reviewer 確認後還原    │  │
│  │                                                             │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                    │                              │
│                                    ▼                              │
│  ┌─── Phase 3: Reviewer Agent (agentic, 有工具) ──────────────┐  │
│  │                                                             │  │
│  │  ├─ 工具: read_section / search_text / get_reference_list   │  │
│  │  ├─ 規則: filter 之前必須用工具查證原文，不能只看 preview   │  │
│  │  ├─ 批次處理 (25 findings/batch)，單批失敗不影響其他批次    │  │
│  │  ├─ verdicts 經由 submit_verdicts tool call（schema 強制）  │  │
│  │  ├─ 逐一審查: confirm / downgrade / filter + confidence     │  │
│  │  └─ deterministic 降級過的 findings 會被特別複查            │  │
│  │       → confirmed: 保留（必要時還原 severity）              │  │
│  │       → downgraded: severity→INFO                           │  │
│  │       → filtered: 從報告中移除                              │  │
│  │                                                             │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                    │                              │
│                                    ▼                              │
│                            Final Report                           │
│  ├─ 只顯示 non-filtered findings                                │
│  ├─ Confidence badges (confirmed %, downgraded %)               │
│  ├─ 成本以「實際產出該結果的 model」計價（含 cache tokens）     │
│  ├─ COT viewer (每個 agent 的推理過程)                          │
│  └─ 多語系 (en / zh-TW)                                        │
└─────────────────────────────────────────────────────────────────┘
```

## Structured Findings

`add_finding` 除了 message/severity 之外，帶有機器可驗證的欄位：

```python
@dataclass
class Finding:
    checker: str
    severity: Severity        # ERROR / WARNING / INFO
    message: str
    location: str | None
    suggestion: str | None
    context: str | None
    # Structured claim fields — 讓 harness 比對事實而非措辭
    claim_type: str | None    # "future_date" | "uncited_reference" |
                              # "missing_reference" | "inconsistency" | "other"
    claimed_date: str | None  # "YYYY" 或 "YYYY-MM"
    ref_number: int | None    # 該 claim 涉及的引用編號
    # Post-validation metadata
    confidence: float = 1.0
    validation_status: str = ""       # "confirmed", "filtered", "downgraded", ""
    validation_note: str = ""
    original_severity: Severity | None = None  # downgrade 前的 severity（可還原）
```

範例：agent 回報「Reference [23] 未被引用」時同時設定
`claim_type="uncited_reference", ref_number=23`。Phase 2 直接拿 23 去比對
全文 regex 掃描出的引用集合——不管 message 是中文還是英文、怎麼措辭都能驗證。

## Pre-Execution Harness

### Deterministic Pre-Pass

`manuscript_tools.extract_citation_numbers()` 用 regex 從全文提取所有數字引用：

```python
# 支援的格式
(1)  [1]  (1-3)  [1-3]  (1,2,5)  (1, 2, 5–7)
# 排除: 年份 (2023)、大數字範圍 (1023-1045) — 上限 999
```

結果注入 `citation_exist` agent 的 initial message，agent 被指示 **信任
pre-scan 結果**，只處理 author-year 格式和 edge cases。

### Multi-Source Citation Verification

`services/citation_verifier.py` 為每個 reference 執行三源查詢
（PubMed / Semantic Scholar / Crossref），cross-validate 後注入
`citation_claim` agent context。

**Verification status levels:**

| Status | Sources | Confidence | 意義 |
|--------|---------|------------|------|
| `verified` | 2-3 sources | 0.85-0.95 | 多源確認，高可信度 |
| `likely_valid` | 1 source | 0.60-0.80 | 單源找到，可能有效 |
| `uncertain` | 0 sources, partial match | 0.12-0.40 | 無法確認 |
| `not_found` | 0 sources | 0.00-0.12 | 找不到（可能太新或未索引） |

**Rate limiting**（共用 `RateLimitedClient` base class）：
- Batch size: 3 references at a time
- Per-client intervals: PubMed 0.35s, S2 1.0s, Crossref 0.25s
- Retry: 3 attempts with 1s/3s/8s backoff on 429/5xx

## Post-Validation Harness

### Phase 2: Deterministic Checks

三種 validator，各自回傳 `(finding_index, action, reason)`。
結構化欄位優先，prose regex 為 fallback：

| Validator | 資料來源 | 允許的 action |
|-----------|---------|--------------|
| `validate_date_claims` | `claimed_date` vs 今天日期 | filter（日期數學是精確的） |
| `validate_citation_numbers` (uncited) | `ref_number` vs 全文 regex 掃描 | filter（全文掃描是精確的） |
| `validate_citation_numbers` (missing) | `ref_number` vs 行數估計 | **downgrade only**（行數是啟發式） |
| `validate_self_consistency` | message 內的範例比對 | downgrade |

### Phase 3: Reviewer Agent

獨立的 agentic reviewer（`reviewer_model`，預設同全域 `model`）：

- **有工具**：read_section / search_text / get_reference_list，可以讀完整
  原文查證，而不是只看 4000 字元 preview
- **Fail-safe 指示**：「錯殺真 finding 比留下 false positive 更糟——使用者
  可以忽略雜訊，但永遠看不到被過濾掉的東西」
- **批次**：25 findings/batch，單批 JSON 損壞或 API 失敗不影響其他批次
- **Schema 強制輸出**：verdicts 經由 `submit_verdicts` tool call 提交，
  避免 free-text JSON 解析失敗；保留 text-JSON fallback
- deterministic 降級過的 findings 帶著 `validation_note` 進入 reviewer，
  確認為真時還原 `original_severity`

## Cost Breakdown

以 ~4000 字 manuscript、29 references 為例（預設 per-checker models +
prompt caching）：

| Phase | Component | Model | Cost |
|-------|-----------|-------|------|
| Pre-pass | Regex extraction | — | $0 |
| Pre-pass | Multi-source verification | — | $0 (API free tiers) |
| Phase 1 | 4 mechanical checkers | Sonnet | ~$1-2 |
| Phase 1 | 3 judgment checkers | Opus | ~$3-5 |
| Phase 2 | Deterministic checks | — | $0 |
| Phase 3 | Reviewer agent (agentic) | Opus | ~$0.5-1 |
| **Total** | | | **~$5-8**（原架構 ~$9-13） |

Prompt caching 對 agentic loop 的 input tokens 提供約 90% 折扣
（cache read = 0.1x input price）。

## Files

| File | 功能 |
|------|------|
| `harness/deterministic.py` | Phase 2: 結構化欄位優先的 date/citation/consistency checks |
| `harness/reviewer.py` | Phase 3: agentic reviewer（工具 + submit_verdicts） |
| `services/http_client.py` | 共用 rate-limited HTTP client base |
| `services/citation_verifier.py` | Multi-source verification + cross-validation |
| `services/crossref.py` | Crossref API client（polite-pool mailto 可設定） |
| `services/pubmed.py` | PubMed client（esummary 批次取標題） |
| `services/semantic_scholar.py` | S2 API client |
| `tools/manuscript_tools.py` | `extract_citation_numbers()`, `count_references()` |
| `orchestrator.py` | Pipeline wiring、semaphore 排程、per-model 成本計算 |
| `config.py` | per-checker models、reviewer_model、max_concurrent_agents |
