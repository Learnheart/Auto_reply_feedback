"""
Module: Offline intent analysis -> Intent Catalog (Phase 0, NGOAI he thong)
Architecture: docs/architecture.md §3 Trach nhiem tung module ("Offline intent analysis",
              "Intent Catalog"), §2 Input, §4.1 Flow A, §4.5 Data layer (intent_catalog)
Method: docs/method-offline-intent-analysis.md §2.1 Data audit, §2.2 Tien xu ly,
        §6 Kiem dinh taxonomy, §9.1 Bo holdout
Plan: docs/2026-08-31/feedback-gold-relabel/plan.md

Gan lai nhan vang 6-label cho data/sample/feedback/feedback_extracted.csv.
Cot `category` goc la lua chon cua user tren widget feedback (idea/bug/other/praise) --
NHIEU, khong dung lam ground truth duoc. Script nay deterministic, khong goi LLM:
nhan nam trong bang tay LABELS ben duoi de PM review/sua truc tiep.
"""
from __future__ import annotations

import csv
import io
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "sample" / "feedback" / "feedback_extracted.csv"
OUT = ROOT / "data" / "golden" / "feedback_gold_192.csv"
LEGACY_GOLDEN = ROOT / "data" / "golden" / "golden_intent.csv"

# Taxonomy 6 label -- chot voi user 2026-08-31 (plan.md D1).
# Luu y D4: catalog_a.json dung `report_bug`; o day dung `bug` theo yeu cau user.
LABEL_SET = {"request_feature", "how_to", "bug", "praise", "complaint", "unclassified"}

# --- Dong ban: prompt go nham o feedback (cau lenh gui agent, khong phai feedback SP) ---
PROMPT_MISFIRE = {37, 62, 78, 92, 95, 98, 105, 119, 122, 123, 126}
# --- Dong ban: vo nghia / qua ngan / khong doan duoc y ---
MEANINGLESS = {9, 118, 121, 167, 174, 183, 186}

# --- Nhan tay cho 130 dong noi dung sach (plan.md D2) ---
# bug             = tinh nang DA CO nhung hong khi dung (error/crash/mat data/output sai hop dong)
# request_feature = co neu huong cai thien cu the, hoac xin nang luc chua co
# how_to          = hoi ve tinh nang da co ma user chua biet
# praise          = khen chung
# complaint       = che chat luong chung chung, khong neu cai thien, khong phai malfunction
LABELS: dict[int, tuple[str, str]] = {
    0:   ("bug",             "Gen sai dinh dang (tra html thay vi slide) roi treo, khong nhan lenh tiep"),
    1:   ("request_feature", "Rang buoc toi thieu 2 slide -- xin bo gioi han, huong cai thien ro"),
    2:   ("bug",             "Input file nhung khong gen ra slide -- chuc nang gay"),
    5:   ("bug",             "Khong tra loi noi dung nao khi hoi -- agent khong phan hoi"),
    6:   ("bug",             "Khong phan hoi -- malfunction"),
    7:   ("how_to",          "Hoi ve co che han muc/credit -- tinh nang da co, user chua ro"),
    8:   ("request_feature", "Translator chua co lich su hoi thoai -- xin nang luc chua co"),
    10:  ("bug",             "Bao loi, khong dung duoc"),
    11:  ("bug",             "Khong su dung duoc"),
    13:  ("how_to",          "Hoi 'toi can lam gi' de STT slide nhay theo -- hoi cach dung"),
    14:  ("request_feature", "Chua chuyen excel thanh chart trong ppt -- xin nang luc chua co"),
    15:  ("bug",             "Khong phan hoi"),
    16:  ("request_feature", "De xuat cu the: doi marquee tu dong thanh manual scroll"),
    17:  ("how_to",          "Hoi co che search chat cu la keyword/semantic/hybrid"),
    18:  ("how_to",          "Hoi Tai co the tao format tu file excel khong -- hoi kha nang"),
    19:  ("praise",          "Khen chung"),
    20:  ("request_feature", "De xuat song ngu ten agent -- huong cai thien cu the"),
    21:  ("bug",             "Treo o trang thai still running, khong tra ket qua"),
    22:  ("request_feature", "Xin tang do dai lich su luu anh"),
    23:  ("bug",             "Hoi bang EN nhung tra loi bang VI -- sai ngon ngu output"),
    26:  ("request_feature", "Che mau nut + goi y doi mau -- huong cai thien UI cu the"),
    27:  ("praise",          "Khen chung (this is amazing)"),
    29:  ("request_feature", "De xuat cu the: them buoc comment tren slide draft de chinh AI"),
    30:  ("complaint",       "Che chat luong chung chung, khong neu cai thien"),
    31:  ("bug",             "Dich sot doan tieng Viet -- output khong dung hop dong chuc nang"),
    32:  ("how_to",          "Hoi co giao dien tieng Viet khong -- hoi kha nang da co"),
    33:  ("bug",             "Cau tra loi hien roi bien mat, tra ve I can't help with that"),
    34:  ("bug",             "Nhieu doan khong duoc dich -- dich sot"),
    35:  ("bug",             "Nut copy khong hoat dong"),
    38:  ("bug",             "Dich sot tieng Anh + output loi font"),
    40:  ("request_feature", "Xin quay lai version truoc cua slide -- version history chua co"),
    41:  ("request_feature", "Chua nhan input excel/hinh anh -- xin nang luc chua co"),
    42:  ("bug",             "Khong ra duoc ket qua"),
    43:  ("bug",             "Loi table of contents / table of figures"),
    44:  ("request_feature", "De xuat cu the: cho user tu input tu chuyen nganh truoc khi dich"),
    45:  ("request_feature", "Xin tinh nang share chat"),
    47:  ("request_feature", "Xin nut sao chep ket qua"),
    48:  ("complaint",       "Che noi dung so sai / khong dung yeu cau, khong neu cai thien"),
    49:  ("bug",             "Lam slide khong dung duoc"),
    51:  ("bug",             "Chi dich ~10% van ban, phan con lai de nguyen"),
    52:  ("praise",          "Khen xu ly nhanh, phan tich ro rang"),
    53:  ("praise",          "Khen ho tro len y tuong nhanh"),
    54:  ("request_feature", "Neu huong cai thien cu the: tang co chu, tang do tuong phan"),
    55:  ("request_feature", "De xuat them o input mo ta thong tin can tom tat"),
    57:  ("request_feature", "Xin upload nhieu file cung luc + nhan excel/anh"),
    58:  ("bug",             "Mot so trang slide khong dich, de nguyen tieng Anh"),
    59:  ("how_to",          "Khong thay ppt da tao truoc do -- hoi cho luu tru san pham"),
    60:  ("bug",             "Upload duoc nhung khong dich, lien tuc bao interrupt"),
    61:  ("request_feature", "Xin luu tien do slide dang lam"),
    65:  ("complaint",       "Che slide chua dep, khong neu cai thien"),
    68:  ("complaint",       "Che dich te, khong neu cai thien cu the"),
    71:  ("request_feature", "Xin them ngon ngu dau ra tieng Trung + dich hinh anh"),
    72:  ("bug",             "Slide vua gen xong nhung khong edit file duoc"),
    73:  ("bug",             "Loi font tieng Viet -- malfunction that (phan de xuat font la phu)"),
    74:  ("how_to",          "Hoi co add duoc nhieu file tham khao khong"),
    76:  ("request_feature", "Xin xuat ket qua ra file excel"),
    77:  ("complaint",       "Che chat luong hinh anh chung chung"),
    79:  ("request_feature", "De xuat cu the: noi gioi han 4000 ky tu"),
    81:  ("request_feature", "De xuat them hinh anh tuong trung cho slide"),
    82:  ("bug",             "Dich PDF sai noi dung, chen ca code vao ban dich"),
    83:  ("request_feature", "Chua co cong cu xuat file Word (.docx)"),
    84:  ("request_feature", "Xin them anh tham chieu giong Figma Wave"),
    85:  ("how_to",          "Hoi upload chung tu co vi pham an ninh thong tin khong -- hoi chinh sach su dung"),
    86:  ("request_feature", "Xin bo sung dinh dang audio/video"),
    87:  ("praise",          "Khen chung (tuyet voi)"),
    88:  ("bug",             "Ban dich loi font tu trang 3"),
    89:  ("bug",             "Bao loi lien tuc"),
    90:  ("request_feature", "Yeu cau tang font size -- huong cai thien cu the"),
    93:  ("request_feature", "Xin them nut xoa slide o panel trai"),
    94:  ("bug",             "Session expired giua chung, khong vao lai duoc -- mat phien lam viec"),
    96:  ("bug",             "Nut generate outline khong hoat dong"),
    97:  ("request_feature", "Xin them chuc nang attach docx/pptx/pdf/anh cho brainstorm"),
    99:  ("complaint",       "Che thiet ke slide + AI loai bo bang bieu, khong de xuat giai phap"),
    100: ("request_feature", "Xin download tung trang slide + quay ve version truoc"),
    102: ("praise",          "Khen lan dau dung, cam on"),
    103: ("bug",             "Export pptx vo font, khac preview"),
    104: ("praise",          "Khen chung"),
    106: ("complaint",       "Phan nan agent hoi qua nhieu cau"),
    107: ("request_feature", "Xin phien ban tieng Viet"),
    108: ("complaint",       "Phan nan phu thuoc Xmind, khong co thi khong dung duoc"),
    109: ("bug",             "Dich file co bang bieu bi loi, bao network error"),
    110: ("bug",             "Font chu cua slide bi loi"),
    111: ("bug",             "LLM structured output failed -- loi ky thuat lo ra UI"),
    112: ("bug",             "Xuat chart thanh anh khong chinh sua duoc -- sai hop dong xuat pptx"),
    113: ("bug",             "Session tu complete khi chua muon ket thuc, khong mo lai duoc"),
    114: ("request_feature", "De xuat them o input do dai ban tom tat"),
    115: ("praise",          "Khen chuc nang kha hay"),
    116: ("bug",             "Khong dich duoc file, chay mot luc bao network error"),
    117: ("complaint",       "Che khong tra ra dung dinh dang onepage nhu yeu cau"),
    120: ("praise",          "Khen toc do (Very quickly)"),
    127: ("bug",             "Chi dich moi tieu de thay vi ca van ban"),
    128: ("praise",          "Khen chung (loved)"),
    129: ("bug",             "Dich sang tieng Viet nhung output van la tieng Anh"),
    130: ("praise",          "Cam on (tks)"),
    131: ("how_to",          "Hoi lam sao biet ban dich dung -- hoi cach kiem chung"),
    132: ("praise",          "Khen chung (GOOD)"),
    133: ("request_feature", "De xuat cu the: phong to Featured card o home page"),
    134: ("request_feature", "Xin nang luc input chart/visual vao slide"),
    135: ("praise",          "Cam on, khen huu ich"),
    136: ("praise",          "Khen chung"),
    137: ("request_feature", "Xin paste anh truc tiep de thiet ke slide"),
    138: ("complaint",       "Che giao dien hon, khong neu cai thien"),
    139: ("request_feature", "Chua xuat duoc ket qua dang bang -- xin nang luc chua co"),
    142: ("bug",             "Van con trang chua duoc dich"),
    143: ("request_feature", "De xuat them hinh anh Techcombank tren slide"),
    146: ("how_to",          "Hoi co ket hop powerpoint-er voi translator duoc khong"),
    147: ("bug",             "Loi font tieng Viet"),
    149: ("bug",             "Hien tai khong dich duoc"),
    152: ("request_feature", "Chu va icon qua nho -- huong cai thien UI cu the (dong dang fb_0090)"),
    153: ("request_feature", "Agent chua luu lich su tro chuyen -- xin nang luc chua co"),
    154: ("bug",             "Upload docx co anh capture -> khong doc duoc noi dung file"),
    155: ("complaint",       "Che font xau, khong neu cai thien"),
    156: ("bug",             "Tra ket qua xong tu crash"),
    157: ("bug",             "Chieu Viet->Anh chua work trong khi Anh->Viet ok"),
    162: ("praise",          "Khen huu ich"),
    164: ("praise",          "Khen slide dep hon Kiro"),
    166: ("bug",             "Bia sai thuc the (MIK thay vi Masterise) -- hallucination sai du lieu"),
    172: ("praise",          "Khen chung (xinnnn)"),
    175: ("bug",             "Failed to parse the file error khi upload PPTX"),
    176: ("bug",             "O @ khong contain/resize dung -- loi UI"),
    177: ("complaint",       "Phan nan khong co du lieu chuan, khong neu cai thien"),
    178: ("complaint",       "Che dich PDF can cai thien, khong neu cach"),
    179: ("complaint",       "Phan nan du lieu outdate"),
    180: ("praise",          "Khen chung (Cool)"),
    181: ("bug",             "Khong mo duoc Graphics designer"),
    184: ("bug",             "Upload word 203kb -> Translation request failed (502)"),
    185: ("bug",             "Khong truy cap duoc"),
    187: ("praise",          "Khen ket qua tot"),
    189: ("request_feature", "Xin o nhap them huong dan (do dai ban tom tat)"),
    191: ("bug",             "Loi truy cap, khong vao duoc"),
}

TRUNCATED_RE = re.compile(r"(…|\.\.\.)\s*$")


def main() -> int:
    rows = list(csv.DictReader(io.open(SRC, encoding="utf-8-sig")))
    out_rows = []
    for i, r in enumerate(rows):
        content = r["content"].strip()
        if TRUNCATED_RE.search(content):
            # Cat cut luc extract tu anh (data/sample/feedback/image*.png) -> mat duoi quyet dinh nhan
            label, flag = "unclassified", "truncated"
            why = "Noi dung bi cat cut khi extract tu anh -- khong du de gan nhan chac chan"
        elif i in PROMPT_MISFIRE:
            label, flag = "unclassified", "prompt_misfire"
            why = "Cau lenh gui agent bi go nham vao o feedback, khong phai feedback ve san pham"
        elif i in MEANINGLESS:
            label, flag = "unclassified", "meaningless"
            why = "Noi dung vo nghia / qua ngan / khong doan duoc y"
        elif i in LABELS:
            label, why = LABELS[i]
            flag = ""
        else:
            print(f"THIEU NHAN: fb_{i:04d} | {content[:90]}", file=sys.stderr)
            return 1
        assert label in LABEL_SET, f"nhan la: {label}"
        # File xuat CHI co 5 cot: agent/user/date/content/label.
        # id, source_category, review_flag, rationale giu trong bo nho de in bao cao audit,
        # KHONG ghi ra CSV (yeu cau user 2026-08-31 -- xem plan.md D5).
        out_rows.append({
            "agent": r["agent"],
            "user": r["user"],
            "date": r["date"],
            "content": r["content"],
            "label": label,
            "_id": f"fb_{i:04d}",
            "_source_category": r["category"],
            "_review_flag": flag,
            "_rationale": why,
        })

    assert len(out_rows) == len(rows) == 192, f"expect 192 rows, got {len(out_rows)}"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fields = ["agent", "user", "date", "content", "label"]
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)

    # ---------------- Bao cao audit (chi in ra man hinh, khong ghi file) ----------------
    dist = Counter(r["label"] for r in out_rows)
    n = len(out_rows)
    print(f"\n== Phan bo nhan vang ({n} dong) -> {OUT.relative_to(ROOT)}")
    for lab, c in dist.most_common():
        print(f"  {lab:<16} {c:>4}  {c/n:6.1%}")
    print("\n== Chat luong dong (khong ghi ra CSV -- chay lai script de xem)")
    for flag, c in Counter(r["_review_flag"] or "(clean)" for r in out_rows).most_common():
        print(f"  {flag:<16} {c:>4}")
    dirty = [r["_id"] for r in out_rows if r["_review_flag"]]
    print(f"  -> id can loai khi train/eval ({len(dirty)}): {', '.join(dirty)}")

    print("\n== Ma tran category goc (widget) x label (gold) -- do nhieu cua nhan cu")
    m = defaultdict(Counter)
    for r in out_rows:
        m[r["_source_category"]][r["label"]] += 1
    labs = sorted(LABEL_SET)
    print(f"  {'widget':<8}" + "".join(f"{l[:9]:>11}" for l in labs) + f"{'agree%':>9}")
    AGREE = {"bug": "bug", "praise": "praise"}  # chi 2 nhan widget co doi ung truc tiep
    for cat in ("idea", "bug", "other", "praise"):
        row = m[cat]
        tot = sum(row.values())
        line = f"  {cat:<8}" + "".join(f"{row.get(l, 0):>11}" for l in labs)
        if cat in AGREE:
            line += f"{row.get(AGREE[cat], 0) / tot:>9.0%}"
        print(line)

    if LEGACY_GOLDEN.exists():
        legacy = {r["id"]: r["intent"] for r in csv.DictReader(io.open(LEGACY_GOLDEN, encoding="utf-8-sig"))}
        new = {r["_id"]: r["label"] for r in out_rows}
        # golden_intent.csv la taxonomy 5 label (bug gop vao complaint) -> chieu gold moi ve 5 label de so
        to5 = lambda l: "complaint" if l == "bug" else l
        overlap = [i for i in legacy if i in new]
        conflict = [(i, legacy[i], new[i]) for i in overlap if legacy[i] != to5(new[i])]
        print("\n== Doi chieu data/golden/golden_intent.csv (5 label, bug->complaint)")
        print(f"  overlap {len(overlap)} dong | khop {len(overlap) - len(conflict)} | XUNG DOT {len(conflict)}")
        for i, old, cur in conflict:
            print(f"    {i}: legacy={old:<16} -> gold6={cur}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
