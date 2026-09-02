"""
Module: Offline intent analysis -> Intent Catalog (Phase 0, NGOAI he thong)
Architecture: docs/architecture.md §3 Trach nhiem tung module ("Offline intent analysis",
              "Intent Catalog"), §4.3 Flow C (unclassified_pool), §4.5 Data layer
Method: docs/method-offline-intent-analysis.md §6 Kiem dinh taxonomy, §9.1 Bo holdout
Labeling guide: data/golden/intent_explain.md  (NGUON CHUAN dinh nghia 5 nhan + tie-breaker)
Plan: docs/2026-09-02/feedback-gold-5label/plan.md (Revision v2)

v2: Gan tay TOAN BO 192 dong, doc truc tiep tu data/sample/feedback/feedback_extracted.csv
(content copy nguyen van, thu tu dong giu nguyen => fb_<idx:04d> khong doi).
Khac v1 (va khac relabel_feedback_gold.py 6-label):
  - KHONG con rule "truncated -> unclassified": dong bi cat `...` gan theo phan nhin thay
    khi y da tron (khong suy dien phan thieu); chi unclassified khi phan quyet dinh bi cat.
  - Cau ngan tin hieu ro gan theo tin hieu ("loi" -> bug).
  - Khong co how_to: hoi nang luc -> new_feature; hoi kem buc xuc -> complain;
    hoi chinh sach / khong suy duoc intent -> unclassified.
Deterministic, khong goi LLM: nhan nam trong bang tay LABELS de PM review/sua truc tiep.
"""
from __future__ import annotations

import csv
import io
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "sample" / "feedback" / "feedback_extracted.csv"
OUT = ROOT / "data" / "golden" / "feedback_gold.csv"

LABEL_SET = {"bug", "new_feature", "praise", "complain", "unclassified"}

# Bang tay du 192 dong: idx (0-based, = fb_<idx:04d>) -> (label, rationale).
# Rationale de PM review; "(vd intent_explain)" = truong hop duoc neu lam vi du trong guide.
LABELS: dict[int, tuple[str, str]] = {
    0:   ("bug",          "Nho tao slide nhung chi tra html roi treo, khong nhan lenh tiep"),
    1:   ("new_feature",  "Rang buoc toi thieu 2 slide -- gioi han thiet ke, xin bo (vd intent_explain)"),
    2:   ("bug",          "Input file nhung khong gen ra slide"),
    3:   ("new_feature",  "De xuat san pham: sunset AI Visionary, thay bang AI Coach -- y tron trong phan nhin thay"),
    4:   ("new_feature",  "Xin indicator bao het credits -- TL;DR da tron y du duoi bi cat"),
    5:   ("bug",          "Khong tra loi noi dung nao khi hoi"),
    6:   ("bug",          "Khong phan hoi"),
    7:   ("complain",     "Buc xuc vi han muc chan su dung -- chinh sach, app khong hong (vd intent_explain)"),
    8:   ("new_feature",  "Translator chua co lich su, refresh mat ket qua -- xin nang luc luu lich su"),
    9:   ("bug",          "'loi' -- ngan nhung tin hieu ro: user bao app loi"),
    10:  ("bug",          "Loi khong dung duoc"),
    11:  ("bug",          "Khong su dung duoc"),
    12:  ("bug",          "Dang khong su dung duoc TAI studio -- y tron du duoi bi cat"),
    13:  ("new_feature",  "STT slide xuat ra khong tu danh lai so khi them trang -- gioi han thiet ke export"),
    14:  ("new_feature",  "Chua chuyen duoc excel thanh chart trong ppt -- nang luc chua co"),
    15:  ("bug",          "Khong phan hoi"),
    16:  ("new_feature",  "De xuat doi marquee tu dong thanh manual scroll"),
    17:  ("complain",     "Che search chat cu 'very limited', khong neu huong cai thien cu the"),
    18:  ("new_feature",  "Hoi/xin nang luc tao format tu file excel -- chua co"),
    19:  ("praise",       "Khen chung (Very good)"),
    20:  ("new_feature",  "De xuat song ngu ten agent"),
    21:  ("bug",          "Treo 'still running', khong tra ket qua"),
    22:  ("new_feature",  "Lich su luu anh it, muon tim lai anh cu (vd intent_explain)"),
    23:  ("bug",          "Hoi bang ENG nhung tra loi tieng Viet -- sai ngon ngu output"),
    24:  ("new_feature",  "De nghi owner review lai huong dan su dung -- cai thien tai lieu, y tron du vi du bi cat"),
    25:  ("bug",          "Agent lap viet lai html nhieu lan, phai tu dung -- an credits"),
    26:  ("new_feature",  "Che mau nut + de xuat dung mau xanh"),
    27:  ("praise",       "Khen chung (this is amazing)"),
    28:  ("bug",          "Error ky thuat lo ra UI: structured output failed"),
    29:  ("new_feature",  "De xuat buoc comment tren slide draft de chinh AI (phan 'bia thong tin' la boi canh)"),
    30:  ("complain",     "Che chung 'cang lam cang xau', khong neu cai thien"),
    31:  ("bug",          "Dich sot 1 doan tieng Viet"),
    32:  ("new_feature",  "Xin giao dien tieng Viet -- nang luc chua co"),
    33:  ("bug",          "Cau tra loi hien roi bien mat, tra 'I'm sorry, i can't help with that'"),
    34:  ("bug",          "Nhieu doan khong duoc dich"),
    35:  ("bug",          "Nut copy khong hoat dong"),
    36:  ("bug",          "Translator khong chay voi email chua ten nguoi -- user bao khong dung duoc"),
    37:  ("unclassified", "Prompt go nham o feedback (yeu cau phan tich theo luc luong ban)"),
    38:  ("bug",          "Dich sot tieng Anh + output loi font (vd intent_explain)"),
    39:  ("new_feature",  "Xin them dinh dang html/md cho reference -- y tron du duoi bi cat"),
    40:  ("new_feature",  "Muon quay lai version truoc sau re-generate -- xin version history"),
    41:  ("new_feature",  "Chua nhan input excel/hinh anh -- nang luc chua co"),
    42:  ("bug",          "Khong ra duoc ket qua"),
    43:  ("bug",          "Loi table of contents / table of figures"),
    44:  ("new_feature",  "De xuat cho user tu input tu chuyen nganh truoc khi dich"),
    45:  ("new_feature",  "Xin tinh nang share chat nhieu nguoi"),
    46:  ("new_feature",  "Hoi cach tao slide dang bang + dang phai workaround copy tay -- nhu cau nang luc tao bang"),
    47:  ("new_feature",  "Xin nut sao chep nhanh ket qua"),
    48:  ("complain",     "Che 'noi dung so sai, chua dung yeu cau' (vd intent_explain)"),
    49:  ("bug",          "Lam slide khong dung duoc"),
    50:  ("new_feature",  "Xin upload cac loai file va anh -- y dau tron, phan sau bi cat"),
    51:  ("bug",          "Chi dich ~10% van ban, con lai de nguyen"),
    52:  ("praise",       "Khen xu ly nhanh, phan tich ro rang"),
    53:  ("praise",       "Khen ho tro len y tuong nhanh"),
    54:  ("new_feature",  "Neu cai thien cu the: tang co chu, do tuong phan"),
    55:  ("new_feature",  "De xuat them o mo ta thong tin can tom tat"),
    56:  ("unclassified", "Hoi co che tinh/reset usage limit -- cau hoi chinh sach, khong che khong xin gi"),
    57:  ("new_feature",  "Xin upload nhieu file cung luc + nhan excel/anh"),
    58:  ("bug",          "Mot so trang khong dich, de nguyen tieng Anh"),
    59:  ("new_feature",  "Khong thay ppt cu -- chua co noi luu san pham da tao (cung ho fb_0190)"),
    60:  ("bug",          "Upload nhung khong dich, lien tuc bao interrupt"),
    61:  ("new_feature",  "Xin luu tien do slide dang lam"),
    62:  ("unclassified", "Prompt go nham (chi dan sua slide dang lam)"),
    63:  ("unclassified", "Prompt go nham (chi dan lam slide tu slide so 4)"),
    64:  ("unclassified", "Prompt go nham (yeu cau gop 3 target vao 1 bang)"),
    65:  ("complain",     "Che 'slide tao chua dep' (vd intent_explain)"),
    66:  ("new_feature",  "Xin toggle sync scroll 2 ben de doi chieu -- y tron du duoi bi cat"),
    67:  ("unclassified", "Danh sach thuat ngu bi cat -- khong doan duoc y (bao loi dich? gop y glossary?)"),
    68:  ("complain",     "Che 'dich qua te', khong neu cai thien"),
    69:  ("new_feature",  "Xin tinh nang tai lieu tham khao dang link dinh kem -- y tron du duoi bi cat"),
    70:  ("new_feature",  "Xin input anh mau roi chinh sua theo concept -- y tron du duoi bi cat"),
    71:  ("new_feature",  "Xin ngon ngu dau ra tieng Trung + dich hinh anh"),
    72:  ("bug",          "Slide vua gen xong nhung khong edit duoc"),
    73:  ("bug",          "Loi font tieng Viet (de xuat chon font la phu)"),
    74:  ("new_feature",  "Hoi/xin add nhieu file tham khao -- cung ho fb_0057"),
    75:  ("new_feature",  "Bao loi khong noi ro ky tu nao bi cam -- xin thong bao loi cu the hon"),
    76:  ("new_feature",  "Chua xuat duoc ket qua ra excel -- nang luc chua co"),
    77:  ("complain",     "Che hinh anh chua dep, khong neu cai thien"),
    78:  ("unclassified", "Prompt go nham (giu nguyen 2 slide dau)"),
    79:  ("new_feature",  "De xuat noi gioi han 4000 ky tu"),
    80:  ("unclassified", "Noi dung van ban nghiep vu dan vao o feedback -- khong phai feedback"),
    81:  ("new_feature",  "De xuat them hinh anh tuong trung cho slide"),
    82:  ("bug",          "Dich PDF sai noi dung, chen code vao ban dich"),
    83:  ("new_feature",  "Chua co cong cu xuat .docx"),
    84:  ("new_feature",  "Xin anh tham chieu giong Figma Wave"),
    85:  ("unclassified", "Cau hoi chinh sach an ninh thong tin -- khong phai feedback ve san pham"),
    86:  ("new_feature",  "Xin bo sung dinh dang audio/video"),
    87:  ("praise",       "Khen chung (tuyet voi)"),
    88:  ("bug",          "Ban dich loi font tu trang 3"),
    89:  ("bug",          "Loi lien tuc"),
    90:  ("new_feature",  "TANG FONT SIZE -- cai thien cu the (vd intent_explain)"),
    91:  ("new_feature",  "Xin tinh nang so sanh diem khac biet giua cac van ban -- y tron du duoi bi cat"),
    92:  ("unclassified", "Prompt go nham (yeu cau so sanh voi cong ty khac)"),
    93:  ("new_feature",  "Xin nut xoa slide o panel trai (vd intent_explain)"),
    94:  ("bug",          "Session expired giua chung, khong vao lai duoc"),
    95:  ("unclassified", "Prompt go nham (gop thanh 2-3 slide, dung hinh con ga TCB)"),
    96:  ("bug",          "Nut generate outline khong hoat dong"),
    97:  ("new_feature",  "Xin attach docx/pptx/pdf/anh cho brainstorm"),
    98:  ("unclassified", "Prompt go nham (hay bo sung noi dung, toi da 8 slide)"),
    99:  ("complain",     "Che thiet ke + AI loai bang bieu, 'can dao tao them' -- khong rut duoc dong backlog cu the"),
    100: ("new_feature",  "Xin download tung trang + quay ve version truoc"),
    101: ("unclassified", "Prompt go nham (bo sung thong tin AWS Connect vao noi dung slide)"),
    102: ("praise",       "Khen, cam on"),
    103: ("bug",          "Export pptx vo font, khac preview"),
    104: ("praise",       "Khen chung (10 diem)"),
    105: ("unclassified", "Prompt go nham (hay tao slide theo mau TCB)"),
    106: ("complain",     "Phan nan agent hoi qua nhieu, khong neu cai thien"),
    107: ("new_feature",  "Xin phien ban tieng Viet"),
    108: ("complain",     "Phan nan phu thuoc Xmind -- rao can, khong neu de xuat"),
    109: ("bug",          "Dich file co bang bieu bi loi, bao network error"),
    110: ("bug",          "Font chu slide bi loi"),
    111: ("bug",          "Error ky thuat lo ra UI: structured output failed"),
    112: ("new_feature",  "Chart xuat dang anh (dung thiet ke hien tai) -- xin xuat chart editable trong pptx"),
    113: ("bug",          "Session tu complete khi chua muon ket thuc, khong mo lai duoc"),
    114: ("new_feature",  "De xuat them input do dai ban tom tat"),
    115: ("praise",       "Khen chuc nang hay"),
    116: ("bug",          "Khong dich duoc file, chay 1 luc bao network error"),
    117: ("complain",     "Che khong tra dung dang onepage nhu yeu cau -- khong co truc trac ky thuat"),
    118: ("unclassified", "Cau qua ngan/gay 'tai file dich ve sao' -- khong chac y"),
    119: ("unclassified", "Prompt go nham (gop slide 2 va 3)"),
    120: ("praise",       "Khen toc do (Very quickly)"),
    121: ("unclassified", "Vo nghia ('uew')"),
    122: ("unclassified", "Prompt go nham (thong ke tuyen duong vi mo)"),
    123: ("unclassified", "Prompt go nham (nho thong ke tuyen duong vi mo)"),
    124: ("bug",          "Button send feedback che mat option tren man edit -- loi UI overlap"),
    125: ("new_feature",  "Xin nang luc nhan phan hoi + re-generate slide -- y tron du duoi bi cat"),
    126: ("unclassified", "Prompt go nham (bo sung phan loai level gia)"),
    127: ("bug",          "Chi dich moi tieu de thay vi ca van ban"),
    128: ("praise",       "Khen chung (loved)"),
    129: ("bug",          "Dich ra tieng Viet nhung output van tieng Anh"),
    130: ("praise",       "Cam on (tks)"),
    131: ("unclassified", "Nghi van do tin cay ban dich -- khong xin nang luc, khong che, khong bao loi"),
    132: ("praise",       "Khen chung (GOOD)"),
    133: ("new_feature",  "De xuat phong to Featured cards o home page"),
    134: ("new_feature",  "Chua co option input chart/visual vao slide"),
    135: ("praise",       "Cam on, khen huu ich"),
    136: ("praise",       "Khen chung"),
    137: ("new_feature",  "Xin paste anh truc tiep de thiet ke slide (giong copilot)"),
    138: ("complain",     "Che 'trang rat hon', khong neu cai thien"),
    139: ("new_feature",  "Khong cung cap duoc dang bang -- nang luc chua co"),
    140: ("bug",          "Khong lan chuot duoc trong o chat nhieu dong -- loi UI, y tron du duoi bi cat"),
    141: ("new_feature",  "Xin gui hinh anh de trao doi thong tin -- y tron du duoi bi cat"),
    142: ("bug",          "Van co trang chua duoc dich"),
    143: ("new_feature",  "De xuat them anh Techcombank tren slide"),
    144: ("bug",          "Tu thong thuong khong duoc dich (dich sot) -- y tron du duoi bi cat"),
    145: ("new_feature",  "Xin vong lap human feedback + agent fix -- y dau tron, phan che design la boi canh"),
    146: ("new_feature",  "Xin ket hop powerpoint-er voi translator -- nang luc chua co"),
    147: ("bug",          "Loi font tieng Viet"),
    148: ("bug",          "Guardrail chan sai input nhac 'Anthropic, PBC' -- false positive, y tron du duoi bi cat"),
    149: ("bug",          "Hien tai khong dich duoc"),
    150: ("unclassified", "'Em co feedback nhu sau...' -- noi dung chinh bi cat het"),
    151: ("praise",       "Phan nhin thay chi liet ke uu diem (script speaker, slide dep, template TCB)"),
    152: ("new_feature",  "Chu va icon qua nho -- cai thien UI cu the (cung ho fb_0090)"),
    153: ("new_feature",  "Agent chua luu lich su tro chuyen -- nang luc chua co"),
    154: ("bug",          "Upload docx co anh -> khong doc duoc noi dung file"),
    155: ("complain",     "Che 'font chu hoi xau', khong neu cai thien"),
    156: ("bug",          "Tra ket qua xong tu crash"),
    157: ("bug",          "Chieu Viet->Anh chua chay, trong khi Anh->Viet ok"),
    158: ("new_feature",  "De xuat chuyen nut Summarize len box Drop files -- y tron du duoi bi cat"),
    159: ("new_feature",  "Xin tich hop tao slide sau khi summarize -- y tron du duoi bi cat"),
    160: ("bug",          "Dich file chua PII: nut tai hien nhung khong tai duoc"),
    161: ("unclassified", "Mo ta file gui vao, bi cat dung cho noi van de -- khong biet chuyen gi xay ra"),
    162: ("praise",       "Khen huu ich"),
    163: ("bug",          "Loi translate voi cau cu the -- y tron du duoi bi cat"),
    164: ("praise",       "Khen slide dep hon Kiro"),
    165: ("bug",          "Nut back o buoc Outline dieu huong sai mong doi"),
    166: ("bug",          "Bia sai thuc the (MIK thay vi Masterise) -- output sai du lieu"),
    167: ("bug",          "Dich xong nhung moi duoc 2 trang -- dich khong het"),
    168: ("new_feature",  "Xin upload excel du lieu tho -> tu define insight lam bao cao -- y tron du duoi bi cat"),
    169: ("unclassified", "Khen + 'chua dung duoc vi ...' -- ly do chinh bi cat, khong suy dien"),
    170: ("unclassified", "Trung noi dung fb_0169 -- ly do chinh bi cat"),
    171: ("new_feature",  "De xuat chuan hoa chuc danh/bo phan theo bo HR -- y tron du duoi bi cat"),
    172: ("praise",       "Khen chung (xinnnn)"),
    173: ("bug",          "Guardrail trigger muon, xoa response sau khi da hien -- y tron du duoi bi cat"),
    174: ("unclassified", "'Test feedback' -- khong phai feedback that"),
    175: ("bug",          "Failed to parse file khi upload PPTX"),
    176: ("bug",          "@ box khong contain/resize -- loi UI"),
    177: ("complain",     "Phan nan 'khong co du lieu chuan', khong neu cai thien"),
    178: ("complain",     "'Need to improve pdf translation' -- che chung, khong neu cach"),
    179: ("complain",     "Phan nan 'du lieu outdate', khong neu cai thien"),
    180: ("praise",       "Khen chung (Cool)"),
    181: ("bug",          "Khong mo duoc Graphics designer"),
    182: ("unclassified", "'nen bo sung tinh nang sau:' -- danh sach tinh nang bi cat het"),
    183: ("unclassified", "'No' -- khong doan duoc y"),
    184: ("bug",          "Upload word 203kb -> Translation request failed (502)"),
    185: ("bug",          "'coundn't acess' -- ngan nhung ro: khong truy cap duoc"),
    186: ("unclassified", "'1' -- khong doan duoc y"),
    187: ("praise",       "Khen ket qua tot"),
    188: ("new_feature",  "De xuat cap nhat theme moi (dang dung format cu 30 nam) -- y tron du duoi bi cat"),
    189: ("new_feature",  "Xin o input them huong dan (vd tom tat 10 trang)"),
    190: ("new_feature",  "Xin noi luu tru san pham da tao -- y tron du duoi bi cat"),
    191: ("bug",          "Loi truy cap khong vao duoc"),
}


def main() -> int:
    rows = list(csv.DictReader(io.open(SRC, encoding="utf-8-sig")))
    assert len(rows) == 192, f"expect 192 rows in {SRC.name}, got {len(rows)}"
    missing = [i for i in range(len(rows)) if i not in LABELS]
    if missing:
        print(f"THIEU NHAN cho idx: {missing}", file=sys.stderr)
        return 1

    out_rows = []
    for i, r in enumerate(rows):
        label, _why = LABELS[i]
        assert label in LABEL_SET, f"fb_{i:04d}: nhan la {label}"
        # Content copy NGUYEN VAN tu file goc (yeu cau D1v2) -- chi bo cot `category` (nhieu widget)
        out_rows.append({
            "agent": r["agent"],
            "user": r["user"],
            "date": r["date"],
            "content": r["content"],
            "label": label,
        })

    fields = ["agent", "user", "date", "content", "label"]
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)

    n = len(out_rows)
    dist = Counter(r["label"] for r in out_rows)
    print(f"== Phan bo nhan vang 5-label v2 ({n} dong) -> {OUT.relative_to(ROOT)}")
    for lab, c in dist.most_common():
        print(f"  {lab:<14} {c:>4}  {c/n:6.1%}")

    print("\n== Danh sach unclassified (sink cho PM -- xem rationale)")
    for i, r in enumerate(rows):
        label, why = LABELS[i]
        if label == "unclassified":
            print(f"  fb_{i:04d}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
