"""
Module: inference.classify (B1) — test cases cho intent classification
Architecture: docs/architecture.md §4.3 Flow C (threshold routing 3 vùng), §6.1 R3 (max cosine
              tới exemplar), §5 Technology Stack (pytest + mock cho logic thuần; eval thật tách riêng)
Labeling guide: data/golden/intent_explain.md
Plan: docs/2026-09-02/intent-classify-embedding-eval/plan.md

Hai tầng:
  1. OFFLINE (luôn chạy, không mạng/không tiền): contract exemplar CSV + golden CSV,
     leakage guard (exemplar không được trùng feedback thật), logic routing 3 vùng
     + max-cosine với fake encoder deterministic.
  2. EVAL trên golden (cần embedding qwen3 thật — có cache đĩa): classify cả 192 dòng
     `data/golden/feedback_gold.csv`, assert sàn hồi quy. Không có auth/mạng => skip.

Chạy:  python -m pytest src/04_tests/test_intent_classification.py -v
"""
from __future__ import annotations

import csv
import io

import numpy as np
import pytest

from conftest import REPO_ROOT, load_module

classify = load_module("src/03_inference/classify.py", "b1_classify")

EXEMPLAR_CSV = REPO_ROOT / "data" / "sample" / "exemplars" / "intent_exemplars.csv"
NEG_EXEMPLAR_CSV = REPO_ROOT / "data" / "sample" / "exemplars" / "intent_exemplar_negatives.csv"
GOLDEN_CSV = REPO_ROOT / "data" / "golden" / "feedback_gold.csv"
GOLD_LABELS = {"bug", "new_feature", "praise", "complain", "unclassified"}

# Sàn hồi quy — đặt DƯỚI kết quả đo lần đầu một biên an toàn.
# Lần đầu 2026-09-02 (HF fallback, ngưỡng mặc định 0.60/0.45): accuracy 42.2% — xem
# plan §Results kèm phân tích nguyên nhân (complain hút bug, new_feature rơi unclassified).
# Sàn 0.35 chỉ chặn HỎNG HẲN (index/encoder gãy), không phải mục tiêu chất lượng.
MIN_ACCURACY = 0.35


def _read(path):
    with io.open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ══════════════════════════════════════════════════════════════════════════════
# 1) Contract dữ liệu
# ══════════════════════════════════════════════════════════════════════════════
class TestExemplarContract:
    def test_dung_4_nhan_du_mau(self):
        # v2 (plan exemplar-v2-instruct-metrics D1): 10 mẫu/nhãn — source bank được phép
        # nhiều hơn trần 3–5 của R3 (trần đó áp cho catalog frozen khi PM chọn chốt)
        by_label = classify.load_exemplars(EXEMPLAR_CSV)
        assert set(by_label) == set(classify.INTENT_LABELS)
        for label, texts in by_label.items():
            assert 5 <= len(texts) <= 15, f"nhãn {label} có {len(texts)} mẫu (kỳ vọng 5–15)"
            assert all(t.strip() for t in texts)

    def test_khong_co_exemplar_cho_sink_unclassified(self):
        # §4.3: unclassified là sink threshold-routing, không phải nhãn để so cosine
        rows = _read(EXEMPLAR_CSV)
        assert all(r["label"] != classify.SINK_LABEL for r in rows)

    def test_id_scheme_tach_namespace_fb(self):
        rows = _read(EXEMPLAR_CSV)
        for r in rows:
            assert r["id"].startswith(f"ex_{r['label']}_"), r["id"]
            assert not r["id"].startswith("fb_")

    def test_load_exemplars_fail_loud_khi_co_sink(self, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("id,agent,content,label\nex_x_01,tai,abc,unclassified\n", encoding="utf-8-sig")
        with pytest.raises(ValueError, match="sink"):
            classify.load_exemplars(bad)

    def test_load_exemplars_fail_loud_khi_nhan_la(self, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("id,agent,content,label\nex_x_01,tai,abc,how_to\n", encoding="utf-8-sig")
        with pytest.raises(ValueError, match="nhan la"):
            classify.load_exemplars(bad)


class TestGoldenContract:
    def test_192_dong_nhan_hop_le(self):
        rows = classify.load_golden(GOLDEN_CSV)
        assert len(rows) == 192
        assert all(r["label"] in GOLD_LABELS for r in rows)
        assert rows[0]["id"] == "fb_0000" and rows[-1]["id"] == "fb_0191"

    def test_du_5_nhan_deu_xuat_hien(self):
        rows = classify.load_golden(GOLDEN_CSV)
        assert {r["label"] for r in rows} == GOLD_LABELS

    def test_content_khop_nguyen_van_file_nguon(self):
        # D1v2 (plan feedback-gold-5label): content bê nguyên văn từ feedback_extracted.csv
        src = _read(REPO_ROOT / "data" / "sample" / "feedback" / "feedback_extracted.csv")
        gold = _read(GOLDEN_CSV)
        assert len(src) == len(gold)
        assert all(s["content"] == g["content"] for s, g in zip(src, gold))


class TestLeakageGuard:
    """Giữ tính golden: exemplar (cả POSITIVE lẫn NEGATIVE) không được lấy từ feedback
    thật. Fail khi ai đó thêm exemplar chép (nguyên văn hoặc chứa nhau) từ bộ gold."""

    @pytest.mark.parametrize("csv_path", [EXEMPLAR_CSV, NEG_EXEMPLAR_CSV],
                             ids=["positive", "negative"])
    def test_exemplar_doc_lap_voi_golden(self, csv_path):
        ex = [r["content"].strip().lower() for r in _read(csv_path)]
        gold = [r["content"].strip().lower() for r in _read(GOLDEN_CSV)]
        for e in ex:
            for g in gold:
                assert e != g, f"exemplar trùng nguyên văn feedback thật: «{e[:60]}»"
                # chứa nhau chỉ tính khi chuỗi đủ dài — tránh false positive kiểu 'GOOD'/'1'
                if len(g) >= 15:
                    assert g not in e, f"exemplar chứa feedback thật: «{g[:60]}»"
                if len(e) >= 15:
                    assert e not in g, f"feedback thật chứa exemplar: «{e[:60]}»"


# ══════════════════════════════════════════════════════════════════════════════
# 2) Logic routing + max-cosine (fake encoder, offline)
# ══════════════════════════════════════════════════════════════════════════════
def _fake_encoder(mapping: dict[str, list[float]]):
    """texts -> vectors theo bảng tra; L2-norm sẵn để dot = cosine."""
    def enc(texts):
        vecs = np.asarray([mapping[t] for t in texts], dtype=np.float32)
        return vecs / np.clip(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12, None)
    return enc


def _axis_vec(cos_to_axis0: float, axis: int = 0) -> list[float]:
    """Vector đơn vị 3D có cosine tới trục `axis` đúng bằng giá trị cho trước,
    phần dư dồn vào trục thứ 3 (không thuộc intent nào)."""
    v = [0.0, 0.0, float(np.sqrt(1 - cos_to_axis0**2))]
    v[axis] = cos_to_axis0
    return v


def _toy_index():
    # 2 intent, mỗi intent 1 exemplar, trục trực giao trong không gian 3D
    # (chiều thứ 3 làm "phần không giống intent nào" => tạo được cosine thấp)
    return classify.ExemplarIndex(
        labels=["bug", "praise"],
        texts=["mẫu bug", "mẫu praise"],
        vectors=np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32),
    )


class TestRouting:
    def test_vung_ok(self):
        enc = _fake_encoder({"a": _axis_vec(0.95, axis=0)})
        (r,) = classify.classify_texts(["a"], _toy_index(), enc,
                                       threshold_high=0.60, threshold_low=0.45)
        assert (r.label, r.flag) == ("bug", "ok")
        assert r.confidence >= 0.60

    def test_vung_low_confidence_van_gan_nhan(self):
        # cosine ≈ 0.5: giữa low (0.45) và high (0.60) => vẫn gán nhãn, cờ cảnh báo
        enc = _fake_encoder({"a": _axis_vec(0.5, axis=1)})
        (r,) = classify.classify_texts(["a"], _toy_index(), enc,
                                       threshold_high=0.60, threshold_low=0.45)
        assert (r.label, r.flag) == ("praise", "low_confidence")

    def test_vung_duoi_nguong_khong_doan_nhan(self):
        # §4.3: c < low => KHÔNG đoán nhãn; best_label vẫn giữ (unclassified_pool.best_intent_id)
        enc = _fake_encoder({"a": _axis_vec(0.30, axis=0)})
        (r,) = classify.classify_texts(["a"], _toy_index(), enc,
                                       threshold_high=0.60, threshold_low=0.45)
        assert (r.label, r.flag) == ("unclassified", "unclassified")
        assert r.best_label == "bug"

    def test_thu_tu_vung_quanh_bien(self):
        # ngay trên/dưới mỗi ngưỡng (tránh so bằng float chính xác tại biên)
        enc = _fake_encoder({
            "tren_high": _axis_vec(0.61), "duoi_high": _axis_vec(0.59),
            "tren_low": _axis_vec(0.46), "duoi_low": _axis_vec(0.44),
        })
        r1, r2, r3, r4 = classify.classify_texts(
            ["tren_high", "duoi_high", "tren_low", "duoi_low"], _toy_index(), enc,
            threshold_high=0.60, threshold_low=0.45)
        assert [r.flag for r in (r1, r2, r3, r4)] == \
            ["ok", "low_confidence", "low_confidence", "unclassified"]

    def test_max_cosine_chon_exemplar_gan_nhat(self):
        # R3: max tới TỪNG exemplar, không mean — thêm exemplar lệch không kéo sai nhãn
        idx = classify.ExemplarIndex(
            labels=["bug", "bug", "praise"],
            texts=["b1", "b2", "p1"],
            vectors=np.asarray([[1, 0], [0.7, 0.714], [0, 1]], dtype=np.float32),
        )
        enc = _fake_encoder({"a": [0.1, 0.99]})
        (r,) = classify.classify_texts(["a"], idx, enc)
        assert r.label == "praise" and r.best_exemplar == "p1"

    def test_build_index_du_exemplar_va_thu_tu_nhan(self):
        # encoder giả trả vector hằng — chỉ kiểm shape/labels, không cần mạng
        enc = lambda texts: np.ones((len(texts), 4), dtype=np.float32)
        idx = classify.build_index(enc)
        n_ex = sum(len(v) for v in classify.load_exemplars(EXEMPLAR_CSV).values())
        assert len(idx.labels) == len(idx.texts) == idx.vectors.shape[0] == n_ex
        # exemplar gom theo nhãn, đúng thứ tự INTENT_LABELS
        seen = [idx.labels[0]]
        for l in idx.labels[1:]:
            if l != seen[-1]:
                seen.append(l)
        assert seen == list(classify.INTENT_LABELS)

    def test_negative_loader_contract(self, tmp_path):
        by_label = classify.load_negatives(NEG_EXEMPLAR_CSV)
        assert set(by_label) <= set(classify.INTENT_LABELS)  # cho phép thiếu nhãn
        assert all(t.strip() for texts in by_label.values() for t in texts)
        bad = tmp_path / "bad.csv"
        bad.write_text("id,agent,content,label\nneg_x_01,tai,abc,unclassified\n", encoding="utf-8-sig")
        with pytest.raises(ValueError, match="sink"):
            classify.load_negatives(bad)

    def test_contrastive_negative_lat_nguoc_nhan(self):
        # feedback gần positive complain (0.7) NHƯNG cũng gần negative complain (0.66)
        # => λ=0.5 trừ điểm complain, bug (0.65) thắng; λ=0 giữ nguyên complain (≡ plain)
        pos = classify.ExemplarIndex(
            labels=["bug", "complain"], texts=["pos bug", "pos complain"],
            vectors=np.asarray([[1, 0, 0], [0, 1, 0]], dtype=np.float32))
        neg = classify.ExemplarIndex(
            labels=["complain"], texts=["neg complain (khuôn bug)"],
            vectors=np.asarray([[0, 0.6, 0.8]], dtype=np.float32))
        v = [0.65, 0.70, float(np.sqrt(1 - 0.65**2 - 0.70**2))]
        enc = _fake_encoder({"a": v})
        (r0,) = classify.classify_texts_contrastive(["a"], pos, neg, enc, lam=0.0)
        assert r0.best_label == "complain"
        (r5,) = classify.classify_texts_contrastive(["a"], pos, neg, enc, lam=0.5)
        assert r5.best_label == "bug"
        # confidence = raw cosine POSITIVE của nhãn thắng, không phải score đã trừ
        assert abs(r5.confidence - 0.65) < 1e-4
        assert (r5.label, r5.flag) == ("bug", "ok")

    def test_query_instruction_chi_ap_phia_query(self):
        # (c): prefix chỉ ghép vào text query trước khi embed, exemplar không đổi
        captured = []
        def enc(texts):
            captured.extend(texts)
            return np.ones((len(texts), 3), dtype=np.float32)
        classify.classify_texts(["câu hỏi"], _toy_index(), enc,
                                query_instruction="do intent matching")
        assert captured == ["Instruct: do intent matching\nQuery: câu hỏi"]


# ══════════════════════════════════════════════════════════════════════════════
# 3) Eval trên golden dataset (embedding thật — skip nếu không có auth/mạng)
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def golden_metrics():
    try:
        return classify.evaluate_golden(verbose=False)
    except Exception as e:  # noqa: BLE001 — thiếu databrickscfg / mạng / endpoint
        pytest.skip(f"Không gọi được embedding thật: {type(e).__name__}: {e}")


class TestEvalGolden:
    def test_phu_du_192_du_doan_hop_le(self, golden_metrics):
        m = golden_metrics
        assert m["n"] == 192
        assert sum(m["flags"].values()) == 192
        pred_total = sum(sum(row.values()) for row in m["confusion"].values())
        assert pred_total == 192

    def test_accuracy_khong_thap_hon_san(self, golden_metrics):
        assert golden_metrics["accuracy"] >= MIN_ACCURACY, (
            f"accuracy {golden_metrics['accuracy']:.1%} < sàn {MIN_ACCURACY:.0%} — "
            "hồi quy so với kết quả đã ghi ở plan §Results"
        )

    def test_moi_nhan_duong_deu_duoc_du_doan(self, golden_metrics):
        # index hỏng (vd embed lỗi trả vector hằng) sẽ dồn hết về 1 nhãn — chặn ở đây
        per = golden_metrics["per_label"]
        for lab in classify.INTENT_LABELS:
            assert per[lab]["predicted"] > 0, f"nhãn {lab} không được dự đoán lần nào"
