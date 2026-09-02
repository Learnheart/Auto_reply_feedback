# Experiment runs — B1 intent classification

| run | approach | accuracy | macro-F1 | ok/low/unc | note |
|---|---|---:|---:|---|---|
| [2026-09-03_00-37-03](2026-09-03_00-37-03_exemplar_cosine_hf/report.txt) | exemplar_cosine_hf | 42.2% | 0.45 | 34/101/57 | baseline exemplar v1 |
| [2026-09-03_00-46-00](2026-09-03_00-46-00_exemplar_cosine_hf/report.txt) | exemplar_cosine_hf | 42.2% | 0.45 | 34/101/57 | re-run baseline (xac nhan tai lap) |
| [2026-09-03_00-49-52](2026-09-03_00-49-52_exemplar_cosine_hf_t50_35/report.txt) | exemplar_cosine_hf_t50_35 | 43.8% | 0.42 | 96/86/10 | ha nguong 0.50/0.35 theo yeu cau PM |
| [2026-09-03_01-02-58](2026-09-03_01-02-58_exemplar_v2_hf/report.txt) | exemplar_v2_hf | 49.0% | 0.48 | 42/124/26 | (b) complain rewrite + 10/nhan + register khau ngu |
| [2026-09-03_01-03-19](2026-09-03_01-03-19_exemplar_v2_instruct_hf/report.txt) | exemplar_v2_instruct_hf | 47.4% | 0.46 | 47/131/14 | (b)+(c) v2 + instruct prefix query |
| [2026-09-03_01-10-32](2026-09-03_01-10-32_exemplar_v2_hf_t50/report.txt) | exemplar_v2_hf_t50 | 43.2% | 0.45 | 134/0/58 | PM chot nguong co dinh 0.50 cho moi phuong an tu day |
| [2026-09-03_01-27-42](2026-09-03_01-27-42_contrastive_neg_hf_l03/report.txt) | contrastive_neg_hf_l03 | 51.6% | 0.51 | 42/121/29 | v2 + 17 negative, lam=0.3 |
| [2026-09-03_01-28-03](2026-09-03_01-28-03_contrastive_neg_hf_l05/report.txt) | contrastive_neg_hf_l05 | 50.5% | 0.51 | 40/122/30 | v2 + 17 negative, lam=0.5 |
| [2026-09-03_01-54-16](2026-09-03_01-54-16_exemplar_v2_hf/report.txt) | exemplar_v2_hf | 49.0% | 0.48 | 42/124/26 | kiem chung tai lap sau khi doi default sang contrastive |
| [2026-09-03_01-55-30](2026-09-03_01-55-30_exemplar_v2_hf/report.txt) | exemplar_v2_hf | 49.0% | 0.48 | 42/124/26 | kiem chung tai lap sau khi doi default sang contrastive |
