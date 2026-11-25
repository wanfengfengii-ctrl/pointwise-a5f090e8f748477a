# 共同校准范围签报

夜班先点收各班的固定件，关站后以实际实收号发起范围签报。标称读数和原稳定性口径见 `README.md`。整轮共用温补参数 `a` 和交班校正参数 `b`，两者均在闭区间 `[-1,1]` 内。不同班段可声明各自的附加闭约束。

## 冻结及点收

在 `evidence.freeze` 提供 `freeze_calibrated_revision(directory, station, issues, revision_id, calibration_id, coefficients, halfplanes)`。按给定的观测修订另发一份固定件，返回的对象仍可交给 `evidence.encode.encode_parcel(parcel)` 得到 JSON 正文，并通过 `evidence.retrieve.load_issued_parcel(issues, issue_id)` 复领。同一观测修订可以按不同校准声明分别发行。

- `calibration_id` 是非空白 UTF-8 字符串。V2 的坐标次序始终是 `(a,b)`。
- `coefficients` 是该修订所有实测拍到 `(α,β)` 的映射，键是原整数拍号，缺测拍和范围外拍不得有条目。原实测值 `x` 在这组参数下解释为 `x+αa+βb`，两个系数为零时仍登记该拍。参数系数与约束数值沿用 V1 有理输入，即 `Fraction`、非布尔整数或 `Fraction` 可解析的有理字符串。
- `halfplanes` 是 `(A,B,C)` 三元组列表，表示 `A·a+B·b≤C`，可为空，允许相反的两条不等式表达等式。收件核对声明格式与证据自洽性，共同域是否为空由签报裁定。

V2 正文保留 V1 的发行号、观测修订号、班段号、轮次、覆盖、缺测及贡献字段，`version` 为整数 `2`。正文增加 `calibration_id` 及 `halfplanes`，其中每条半平面写作 `[A,B,C]`。每条贡献在原 `width`、`index` 和标称 `sum` 外增加 `alpha_sum` 和 `beta_sum`。它们分别是该箱片段内实测读值的两个响应系数和。所有有理数均采用 V1 `sum` 的 `[分子字符串,正分母字符串]` 格式。逐拍原读与逐拍系数留站。

沿 `receipts.accept.accept_parcel(directory, receipts, body)` 点收 V2，返回与 V1 同样的实收号、接收回执及正文信息，`receipts.retrieve.load_accepted` 按号读回。仍核对登记轮次、覆盖、缺测、每个相交片段的唯一贡献及 JSON 字段。标称和及两个系数和都须满足原双宽加和关系，全缺片段的三项均须为零。重收比较归约后的精确有理值，忽略 JSON 空白、对象键顺序及证据条目顺序。半平面按声明的有理三元组比较，顺序无关，保留重复条目的次数。同一发行号改动系数、约束声明或其他绑定正文时拒收，保留已收原件和首执。

## 签报及复领

在 `reports.publish` 提供 `publish_calibrated_report(directory, receipts, reports, round_id, width, receipt_ids)`。复用原有箱宽和有序实收选择规则，所选件须同轮且恰好分割整轮，并且全部为同一个 `calibration_id` 的 V2。V1 点值签报继续使用 V1 实收。

共同域取参数盒与所选件全部半平面的交集，可以是空集、单点、线段或有面积的闭域。沿用同起拍、满宽且每拍实测的资格，只对原箱序号相差 1 的完整箱计一对。跨班箱合并贡献后按所选箱宽求均值。每一组候选 `(a,b)` 同时解释所有合格相邻对，稳定性仍为这些箱均值差平方的平均值除以二。

返回的范围报告对象提供 `report_id`、`round_id`、`width`、`calibration_id`、`result`、有序 `parents` 和 `ack_id`，父件字段沿用 V1。`result` 提供 `status`、`pair_count`、`lower`、`upper`、`lower_at`、`upper_at`。`pair_count` 始终是按覆盖和缺测得到的有效对数。

- 共同域为空签 `infeasible`，即使有效对数也是零。
- 共同域非空而有效对数为零签 `insufficient`。这两种结果的 `lower`、`upper`、`lower_at`、`upper_at` 均为 `None`。
- 其余签 `measured`，两端均为精确 `Fraction`，可相等。各端附一组 `(a,b)` 的 `Fraction` 二元组，满足参数盒与全部所选件约束，且代回原稳定性口径恰得该端值。同端有多个见证时可任选。

报告、按请求顺序固定的父件和签发回执同事务写入。校准依据可凭定稿保存的实收号从中心已收件查出。非法申请或正文抛 `ValueError`，未知号沿用 `LookupError`，未登记轮次的送件仍按坏件处理。存储失败沿用原异常，报告与回执无新增，实收可再用于签报。

重开中心后，使用 `reports.retrieve.load_report(reports, report_id)` 和 `export_report(reports, report_id)` 读取定稿。V2 导出沿用 V1 外层报告标识、父件和回执字段，增列 `calibration_id`，结果对象使用上述范围字段和原 `unit`。每个有理端值用 V1 有理数格式，每个见证用按 `(a,b)` 排列的两个有理数，空值为 JSON `null`。后续修订另发另签，历史报告仍按原号读回原值。V1 的输入、编码、导出及完整回归照常。

## 样例及运行

`samples/calibration_ranges.json` 是可手算的业务输入和预期。`first` 是轮次起拍，`cut` 是日班拍数，剩余拍归夜班。`values` 与 `coefficients` 按拍顺序对应，样例中的 `null` 系数表示该拍缺测，应从传给冻结入口的映射中省掉。`day`、`night` 分别是两班半平面，选件共用一个校准号。样例的 `pairs` 对应 `pair_count`，`range` 给出有理数文本表示的两端或 `null`。两端见证以代入核验，每个端点均可任选合法坐标。

沿用 `.pointwise-runtime.json`。版本为 `1`，类型为 `cli`，`setup` 仍为准备命令的 argv 列表，可空。`verify` 和 `demo` 各是一条命令的 argv。交付时让 `verify` 执行完整原回归和范围签报核验，失败时退出非零。`demo` 展示实际收件、关站签发及重开领取的范围和实收出处。原 V1 演示仍可按 `README.md` 单独运行。
