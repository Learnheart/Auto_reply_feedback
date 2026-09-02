# Feedback Classification Table

> Đây là **hướng dẫn gán nhãn vàng** (người + agent relabel `data/golden/*.csv`).
> B1 runtime (`src/03_inference/classify.py`) KHÔNG đọc file này — nó chạy max-cosine trên
> `exemplars` của Intent Catalog. **Không bê cột "Không phải nhãn này khi" vào `exemplars`**:
> index coi mọi exemplar là mẫu DƯƠNG, thêm negative vào sẽ kéo nhãn sai lại gần.

| Nhãn | Định nghĩa tôi áp dụng | Không phải nhãn này khi | Ghi chú |
|------|------------------------|-------------------------|---------|
| bug | Feedback chứa ý kiến của user về **lỗi của app xảy ra trong quá trình họ sử dụng app** | App chạy đúng như thiết kế nhưng user muốn khác đi ⇒ `new_feature`. Chê chất lượng output mà không có trục trặc ("nội dung sơ sài") ⇒ `complain` | Người dùng gặp trục trặc thật khi dùng |
| new_feature | Những **gợi ý của user về tính năng mới** nảy ra trong quá trình sử dụng app. Gồm cả **góp ý cải thiện tính năng đã có** khi nêu được thay đổi cụ thể ("tăng font size", "thêm nút xóa slide") | Chỉ chê, không chỉ ra được thứ muốn thêm/đổi ⇒ `complain`. Tính năng có nhưng đang gãy ⇒ `bug` | Có "cái muốn thêm/đổi" chỉ ra được ⇒ đưa được vào backlog |
| praise | Khen ngợi nói chung | Khen kèm một đề nghị cụ thể ⇒ `new_feature` (phần action thắng) | — |
| complain | Chê chất lượng chung chung: không nêu cải thiện, không phải malfunction ("slide chưa đẹp", "dịch quá tệ") | Nêu được thay đổi cụ thể ⇒ `new_feature`. Có error/crash/mất dữ liệu ⇒ `bug` | Không action được ngoài xin lỗi + hỏi thêm |
| unclassified | Không đoán được ý | Đoán được ý nhưng câu bị cắt cụt ⇒ vẫn `unclassified` (không suy diễn phần thiếu) | Sink — không auto-reply, chuyển PM |

## Ranh giới dễ nhầm — tie-breaker theo cặp

Nhập nhằng nằm ở **cặp nhãn**, không ở từng nhãn. Khi lưỡng lự, hỏi đúng một câu:

| Cặp | Câu hỏi quyết định | Ví dụ thật trong gold |
|-----|--------------------|------------------------|
| `bug` vs `new_feature` | App có **hành xử sai so với thiết kế** không? Sai ⇒ `bug`. Chạy đúng thiết kế nhưng user muốn khác ⇒ `new_feature` | *"chưa tạo dc 1 slide, mà phải tối thiểu 2 slide"* ⇒ `new_feature` (giới hạn thiết kế, không phải hỏng) |
| `bug` vs `complain` | Có **trục trặc kỹ thuật** (error/crash/không phản hồi/mất dữ liệu) hay chỉ **chất lượng kém**? | *"Tại sao cứ báo tôi bị hết hạn mức"* ⇒ `complain` (chính sách hạn mức, app không hỏng); *"không dịch hết tiếng Anh, output bị lỗi font"* ⇒ `bug` |
| `new_feature` vs `complain` | Có **rút ra được một dòng backlog** không? Có ⇒ `new_feature`. Không ⇒ `complain` | *"lịch sử lưu ảnh hơi ít, muốn tìm lại ảnh cũ hơn thì k thấy"* ⇒ `new_feature`; *"nội dung sơ sài, chưa theo đúng yêu cầu"* ⇒ `complain` |
| `praise` vs `new_feature` | Có kèm đề nghị cụ thể không? Có ⇒ `new_feature` | Khen thuần ⇒ `praise` |
| bất kỳ vs `unclassified` | Sau khi đọc, **có dám soạn reply** không? Không ⇒ `unclassified` | Câu bị cắt `…` lúc extract, prompt gõ nhầm ô feedback |
