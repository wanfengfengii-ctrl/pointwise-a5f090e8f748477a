# 材研计量室参考仪核检台账

日班按参考仪规程开轮，班员登记实测和缺测，交班员冻结选定版本。夜班分析员收件后可脱离站库签报。质控员凭有效对数和稳定性值核对复校依据，发现错录时可沿勘误后的新报告和原报告分别核账。

使用 Python 3.11 标准库。由控制台物化工程后，在项目根目录运行以下命令。

```sh
python3 -B check_project.py
python3 -B -m samples.demo
```

演示在隔离目录内登记六拍轮，在第 3 拍后交班，发行并点收，再更正第 3 拍。关源后签出两份报告，重开中心后读取原定稿。`samples/independent_missing.json` 是可独立点收的 V1 运输样例，其中第 3 拍缺测。

## 初始化和公开 API

用 `ledger_db.connect(path)` 分别连接轮次目录、站库和中心库。`path` 接受 `str` 或 `Path`。连接由调用者关闭。各 Store 接收连接，调用 `initialize()` 可重复补齐表结构，保留用户记录。目录装配 `RoundStore`，站库装配 `ObservationStore` 和 `IssueStore`，同一中心库装配 `ReceiptStore` 和 `ReportStore`。以下 API 自行管理写事务。

| 工作 | 接口 | 返回 |
| --- | --- | --- |
| 开轮及查轮 | `rounds.registry.open_round(directory, round_id, first, last, protocol=REFERENCE_PROTOCOL)`、`load_round(directory, round_id)` | `RoundSpec` |
| 班段录入 | `observations.ingest.record_segment(directory, station, round_id, segment_id, first, last, entries)` | `Revision` |
| 勘误与查历史 | `observations.corrections.amend_revision(station, base_revision_id, beat, value)`、`observations.read.load_revision(directory, station, revision_id)` | 新 `Revision` 或指定版本的 `RevisionSnapshot` |
| 指定修订发行 | `evidence.freeze.freeze_revision(directory, station, issues, revision_id)`、`evidence.retrieve.load_issued_parcel(issues, issue_id)` | `FrozenParcel`，用 `evidence.encode.encode_parcel(parcel)` 输出运输正文 |
| 点收与查实收 | `receipts.accept.accept_parcel(directory, receipts, body)`、`receipts.retrieve.load_accepted(receipts, receipt_id)` | `AcceptedParcel`，含实收号、接收回执和固定件 |
| 签报 | `reports.publish.publish_report(directory, receipts, reports, round_id, width, receipt_ids)` | `ReportRecord`，含报告号、结果、有序父件和签发回执 |
| 复领和导出 | `reports.retrieve.load_report(reports, report_id)`、`export_report(reports, report_id)` | 原 `ReportRecord` 或原定稿的 JSON |

`entries` 是 `(拍号, 读值)` 的可迭代序列。拍号为整数，范围两端均包含。读值接受 `Fraction`、整数或 `Fraction` 可解析的有理数字符串。`None` 表示显式缺测，浮点和布尔值拒绝。每个范围内拍号必须恰好出现一次。班段号在轮次内唯一，修订号全局独立。更正只接受仍为现行版本的修订号和范围内一拍。各次发行按明确给出的修订号生成独立发行身份。

非法输入、身份冲突或过时勘误抛出 `ValueError`，未知号抛出 `LookupError`，存储故障保留 `sqlite3.Error`。相同规程和边界的重复开轮返回原轮次，同号异轮次描述拒绝。合法重收返回原实收号和接收回执。非法签报保留既有实收。报告、父件、签发回执同事务提交，失败后可用原实收重试。

## 固定件与稳定性口径

V1 正文是 JSON 对象。`issue_id`、`revision_id`、`segment_id` 标识来源，`round` 固定轮次号、闭区间、规程标识 `reference-stability-v1`、单位 `μm` 和箱宽 `[2,4]`。`coverage` 是班段闭区间，`missing` 列出其显式缺测拍。每个相交箱贡献含 `width`、从轮次起拍算起的零基 `index` 和 `sum`。`sum` 用十进制分子和正分母字符串组成的二元组表达。全部缺测的片段保留为零和，缺测状态由 `missing` 区分。实收以规范化正文比较身份冲突，允许 JSON 空白、键顺序和证据条目顺序变化。点收校验可证明正文结构和证据的自洽性，所记实测来自发行人负责的站端实录。

起拍为 s、箱宽为 w 时，第 k 箱从 s+k×w 开始，计划长度 w。中心检查选件覆盖恰好分割整轮，按箱号合并精确部分和与实测拍数。只有足宽且全部实测的箱才有资格，缺测箱打断相邻比较。相邻箱均值差的平方取平均后除以二。`measured` 表示有有效对，值可为精确零。`insufficient` 表示零对，值为 JSON `null`。轮末短箱须有证据覆盖，但无统计资格。报告.父件采用请求顺序。导出把 `result.value` 表达为分子和分母字符串组成的二元组，单位为 `μm²`。
