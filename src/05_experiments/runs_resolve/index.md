# Experiment runs — B2 bước 1 guideline resolve (metric chính: F1 lớp solved=True)

| run | approach | precision | recall | F1 | tp/fp/fn | verbatim | llm calls / s | note |
|---|---|---:|---:|---:|---|---:|---|---|
| [2026-09-03_02-17-25](2026-09-03_02-17-25_whole_page_nothink/report.txt) | whole_page_nothink | 0.50 | 0.17 | **0.25** | 2/2/10 | 1.00 | 20 / 95s | vong 1 |
| [2026-09-03_02-19-02](2026-09-03_02-19-02_whole_page_think/report.txt) | whole_page_think | 0.80 | 0.33 | **0.47** | 4/1/8 | 1.00 | 20 / 254s | vong 1 |
| [2026-09-03_02-23-18](2026-09-03_02-23-18_evidence_nothink/report.txt) | evidence_nothink | 0.56 | 0.42 | **0.48** | 5/4/7 | 1.00 | 20 / 138s | vong 1 |
| [2026-09-03_02-25-38](2026-09-03_02-25-38_evidence_think/report.txt) | evidence_think | 0.50 | 0.50 | **0.50** | 6/6/6 | 1.00 | 20 / 305s | vong 1 |
| [2026-09-03_02-32-40](2026-09-03_02-32-40_evidence_think_anchor/report.txt) | evidence_think_anchor | 0.57 | 0.67 | **0.62** | 8/6/4 | 1.00 | 20 / 304s | vong 2: gate anchor |
| [2026-09-03_02-37-47](2026-09-03_02-37-47_evidence_think_anchor_verify/report.txt) | evidence_think_anchor_verify | 1.00 | 0.42 | **0.59** | 5/0/7 | 1.00 | 34 / 368s | vong 2: gate anchor |
| [2026-09-03_02-43-58](2026-09-03_02-43-58_decide_think_anchor/report.txt) | decide_think_anchor | 0.55 | 0.50 | **0.52** | 6/5/6 | 1.00 | 20 / 274s | vong 2: gate anchor |
| [2026-09-03_02-48-34](2026-09-03_02-48-34_decide_think_anchor_verify/report.txt) | decide_think_anchor_verify | 1.00 | 0.25 | **0.40** | 3/0/9 | 1.00 | 29 / 299s | vong 2: gate anchor |
