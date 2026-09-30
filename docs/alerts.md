# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert mẫu để tham khảo

Ví dụ dưới đây minh họa mức độ cụ thể cần có. Học viên không cần copy nguyên, nhưng ba alert trong bài nộp nên rõ ràng tương tự: điều kiện là gì, kéo dài bao lâu, ảnh hưởng tới user ra sao và người trực cần kiểm tra gì trước.

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms`
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 3000ms` trong 5 phút
- Ảnh hưởng tới người dùng: người dùng phải chờ lâu hơn trước khi nhận câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard latency để xác nhận P95/P99 và khoảng thời gian tăng.
  2. Lọc `data/logs.jsonl` trong khoảng đó, lấy một `correlation_id` có `latency_ms` cao.
  3. Mở trace cùng `correlation_id` trên Langfuse, so sánh các span chính để xác định bước nào bất thường.
- Mitigation tạm thời: dựa trên evidence thực tế để rollback prompt, khôi phục cấu hình liên quan, tắt practice scenario hoặc giảm tải khi demo.
- Owner: `student-<MSSV>`

## Alert 1

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms`, ngưỡng SLO 3000ms trong `config/slo.yaml`
- Điều kiện và thời gian duy trì: `p95(response_sent.latency_ms) > 1000` liên tục 5 phút. Đây là cảnh báo sớm. SLO vẫn là 3000ms; baseline đo được có P95 khoảng 161ms, còn practice `rag_slow` đẩy P95 lên khoảng 2666ms nên ngưỡng 1000ms bắt được hồi quy trước khi đốt error budget.
- Ảnh hưởng tới người dùng: người dùng phải chờ lâu hơn nhiều so với baseline ~160ms. Với một worker xử lý `agent.run()` đồng bộ, request xếp hàng còn thấy chậm hơn latency ghi trong log.
- Ba bước kiểm tra đầu tiên:
  1. Mở panel Latency, xác nhận P95/P99 và TTFT P95 cùng khoảng thời gian alert cháy.
  2. Lọc `data/logs.jsonl` với `event == "response_sent"` và `latency_ms > 1000`, lấy một `correlation_id`. Đối chiếu `retrieval_ms` và `generation_ms` trên cùng dòng log.
  3. Mở trace Langfuse cùng `correlation_id`. Nếu span `retrieval` chiếm phần lớn thời gian thì khoanh vùng RAG; nếu span `generation` dài hoặc token tăng thì khoanh vùng LLM/prompt.
- Mitigation tạm thời: rollback label `production` về prompt version trước nếu trace gắn version mới; tắt practice scenario `rag_slow` nếu đang bật; giảm concurrency của workload demo. Không tắt alert để “cho qua” demo.
- Owner: `student-2A202602504`

## Alert 2

- Tên: `ElevatedErrorRate`
- Severity: `critical`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: error rate = `count(request_failed) / count(request_received)`, guardrail `error_rate_pct_max: 2`
- Điều kiện và thời gian duy trì: `error_rate_pct > 2` liên tục 5 phút
- Ảnh hưởng tới người dùng: một phần request trả HTTP 500, người dùng không nhận được câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Mở panel Errors, xem error rate và breakdown `error_type` trong cùng time range.
  2. Lọc log `event == "request_failed"`, lấy `correlation_id`, `error_type` và `tool_success`.
  3. Mở trace cùng `correlation_id`. `RuntimeError` kèm span `retrieval` level ERROR nghĩa là vector store/tool fail; lỗi ở span `generation` nghĩa là bước LLM.
- Mitigation tạm thời: tắt scenario `tool_fail` nếu đang practice; khoanh vùng dependency retrieval và trả fallback đã scrub thay vì 500 khi demo. Giữ request thất bại trong log để còn correlation ID.
- Owner: `student-2A202602504`

## Alert 3

- Tên: `RetrievalSuccessDrop`
- Severity: `warning`
- Duration: `10m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: retrieval success = `count(tool_success == true) / count(tool_success != null)`, guardrail tối thiểu 90%
- Điều kiện và thời gian duy trì: `retrieval_success_rate_pct < 90` liên tục 10 phút
- Ảnh hưởng tới người dùng: câu trả lời mất ngữ cảnh tài liệu, quality proxy giảm dù request có thể vẫn HTTP 200 hoặc đã 500 nếu tool ném lỗi
- Ba bước kiểm tra đầu tiên:
  1. Mở panel Errors và panel Quality trong cùng cửa sổ 60 phút. Success rate và quality mean đi xuống cùng lúc là dấu hiệu RAG, không phải chỉ latency.
  2. Lọc log có `tool_name == "retrieval"` và `tool_success == false`, lấy `correlation_id`.
  3. Mở trace cùng ID, đọc span `retrieval`: timeout thì đối chiếu alert latency; lỗi tool thì đối chiếu alert error rate.
- Mitigation tạm thời: tắt scenario làm retrieval fail, giữ corpus fallback, và không promote prompt `candidate` nếu quality mean tụt dưới 0.75. Sau khi phục hồi, xác nhận success rate vượt lại 90% trước khi đóng alert.
- Owner: `student-2A202602504`
