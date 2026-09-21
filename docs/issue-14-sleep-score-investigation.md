# Issue #14：睡眠评分缺失排查（2026-09-21）

## 初次排查结论（历史记录，后续进展见文末）

- GitHub Issue #14（2026-09-20 创建）报告的是 `sleep_score` 为 `null`，并非完全没有睡眠记录。报告版本为 0.3.1；Issue 没有提供可以验证评分字段结构的合成响应或设备/账户地区信息。
- 本地检查基于 `be0af06`。现有 README.md、README.en.md 有用户未提交改动，本次未覆盖。
- 已验证：在当前支持的原始睡眠载荷中，只要 `score` 或 `sleep_score` 有正常非零评分，适配器 → 同步 → SQLite → MCP → JSON/CSV 全链路能保留评分；两字段缺失/为 null 时，睡眠记录仍可保存，评分仍为空。
- 因此没有发现“评分已经正确解析，但被存储/MCP/导出固定丢弃”的问题。当前重点是上游评分来源、适配器字段覆盖以及缓存是否曾同步到评分。
- **尚未证明 Issue 报告账户的具体根因，尚未修复或关闭 #14。** 本次仅增加合成回归测试与排查记录，不修改生产协议，不发布、不回复 GitHub。

## 已确认的代码路径

1. `src/mi_fitness_mcp/adapters/mi_fitness_cloud.py`：
   - `iter_sleep_sessions()` 只执行 `_fetch_key("sleep", ...)`。
   - `_fetch_key()` 调用 `/app/v1/data/get_fitness_data_by_time`，没有查询每日聚合睡眠数据。
   - 评分只读取 payload 顶层 `score` 或 `sleep_score`，并经 `_optional_int()` 转换；没有其他层级映射，也不本地估算小米评分。
   - `_optional_int()` 把 0 转成 None。这是额外的边界风险，但不能据此解释本次报告：Issue 并未说明上游返回了 0。非数字或越界评分还有导致整条记录被跳过的风险，不能与“已导出记录评分为 null”混为一谈。
2. `src/mi_fitness_mcp/storage/__init__.py`：`insert_sleep_session()` 写入评分，重复同步也更新评分。
3. `src/mi_fitness_mcp/services/query_service.py` 与 `server.py`：MCP 从本地缓存取评分，汇总中已有评分覆盖率，不会自动补请求上游。
4. `src/mi_fitness_mcp/export.py`：export 只读取 SQLite，不连接小米；反复 export 不会补回同步时缺失的评分。

## 外部源码线索（不是本账户的协议验证）

2026-09-21 通过 GitHub CLI 只读查询 Issue 与公开实现代码；未访问任何真实小米端点、凭证、数据库或健康日志。

- `binglua/mi-fitness-mcp-cn` 的 `src/mi_fitness_mcp/adapters/mi_fitness_cloud.py` 同样使用 `score` / `sleep_score` 两字段，未提供能直接解决本问题的不同映射。
- `Misty02600/mi-fitness-python` 的 `src/mi_fitness/client/data.py` 中 `get_sleep()` 走聚合数据路径，`src/mi_fitness/models.py` 的睡眠模型含 `sleep_score`。
- `alexgetmancom/miband-bot` 的 `src/xiaomi/client.ts` 中 `getSleep()` 使用 `getAggregatedData()`，后者访问 `/app/v1/data/get_aggregated_fitness_data_by_time`，使用 `tag=daily_report`；`parseSleep()` 读取 `sleep_score`。
- **这两个实现面向带 `relative_uid` 的亲友数据访问。** 只能说明“社区实现中存在从聚合数据读取评分的路径”，不能证明本项目自己的账户认证支持相同请求，也不能证明报告人的评分一定在该接口。

优先待验证假设：该账户的原始睡眠记录不含评分，评分来自尚未覆盖的聚合数据。其他可能包括未覆盖的字段层级、评分尚未生成/同步、设备/地区差异、旧缓存。现有 Issue 无法区分。

## 合成验证

新增 `tests/test_sleep_score_pipeline.py`，只使用虚构用户、虚构 Token、人工构造记录与 pytest 临时数据库：

- `score=88`、`sleep_score=88`、数字字符串、空首选字段后的备用字段，均通过完整同步/MCP/JSON/CSV 链路。
- 评分字段缺失或均为 null 时保留睡眠记录，JSON/MCP 为 null，CSV 为空单元格；不伪造评分。
- 同一记录先无评分、后有评分时，指定日期重新同步可以更新缓存，不需要删除数据库。

这些测试验证本地行为，不验证设备兼容性或上游当前实际响应。新增 7 项测试通过；修改前完整测试为 142 项通过，修改后完整测试为 149 项通过。`python -m ruff check src tests`、`python -m compileall -q src tests` 与 `git diff --check` 均通过（Git 仅对原有 README 改动提示换行符转换）。

## 下一步（安全且可验证）

1. 如需向报告人补充询问，仅问设备型号、账户地区、安装来源/提交版本、Mi Fitness App 是否显示睡眠分、是否已对相同日期重新同步。不要索取账号、凭证、真实分数、原始响应、数据库、导出文件或截图。
2. 如果报告人能协助提供结构证据，只接收手工构造的合成最小示例：字段名、层级、类型，所有值与时间均为虚构；不要直接上传真实数据再尝试脱敏。
3. 需要确认评分是否来自原始记录、嵌套结构或每日聚合数据。确认自己账户接口契约后，才能补充受限的请求、分页和 respx mock 回归；不能直接把亲友接口移植进来。
4. 如增加每日聚合评分，必须先明确日期、设备/来源、多段主睡眠与小睡的归属规则，避免同一天所有睡眠被填上同一个分数。
5. 仅当上游返回了当前代码支持的评分字段，显式范围重同步才可能补齐旧缓存；不能向报告人承诺“重跑 export”或“重同步”必然解决。

暂不把研究假设写成已支持功能；不生成替代睡眠分，不关闭 Issue。


## 后续实施：2026-09-21 本地修复候选

用户要求继续处理后，已完成本地实现，**本地验收时尚未发布，也未验证报告人的真实账户，不能宣称 #14 已被实测解决**。前文“本次只增加测试、不修改协议”是初次排查时的状态，本节取代该状态。

### 新的协议依据及限制

只读检查公开客户端类型定义，定位到本人数据路径，与 relatives 接口明确分开：

- 公开索引仓库 `KurenaiRyu/XiaomiHealth`，核查提交 `04e79cf5debe3f9a43e57f6d981e472ea6b59637`。
- `decompiler/com/xiaomi/fit/fitness/persist/server/service/FitnessApiService.java`：`data/get_aggregated_fitness_data_by_time`；本人原始与聚合查询采用相同传输注解，亲友路径另列为 `relatives/get_aggregated_data`。
- `decompiler/com/xiaomi/fit/fitness/persist/dailyreport/bean/AggregateFitnessDataByTimeParam.java`：tag、key、limit、start_time、end_time、next_key；`AggregateFitnessDataByTime.java`：data_list、has_more、next_key；`AggregateFitnessData.java`：sid、time、value、zone_offset。
- `decompiler/com/xiaomi/fit/fitness/export/data/aggregation/cloud/CloudSleepReport.java` 与 `CloudSleepSegment.java`：sleep_score、segment_details、bedtime、wake_up_time；`AllDaySleepReport.java` 也含 sleep_score。`DataCloudUtilKt.java` 提供 daily_report 标签映射。
- 实现只独立采用接口/字段事实，未复制或引入上游实现代码。沿用本项目已有加密 POST 传输；公开类型定义并不是当前在线服务契约或所有地区成功的保证。

### 本地变更

1. 缺评分的主睡眠触发本人 daily_report 补取，同地区、同认证，不使用 relative_uid，不发探测请求。完整分页、循环/页数上限保护；分页失败不使用不完整报告。
2. 用已有睡眠的本地醒来日期确定报告范围，前后各扩一天覆盖时区和分块边界。来源、日期及报告主睡眠段边界需匹配；无边界时仅对单一来源的唯一最长主睡眠补分。小睡、来源不符、边界不符、并列主睡眠、多设备歧义和冲突评分不填充。
3. 原始合法评分优先；0 默认值不当作零分，非数字/布尔/越界/小数评分不再导致整条睡眠被丢弃，并可回退到备用字段或日报评分。字符串 false 的 is_nap 不再被当成 true。
4. 聚合失败只记固定诊断/缺失数量，不记录错误正文、报告内容、账号或凭证；保留基础记录，取消操作继续传播。
5. 增加 sleep_score_source 至模型、SQLite、MCP 和导出；旧库自动加列。评分来源为 sleep_record / daily_report，旧缓存未知来源保持 null。
6. 对同一 sleep_id，只有起止时间和小睡标记不变时才保留缺失更新前的最后已知评分；合法新评分覆盖旧值，边界改变不能继承旧评分。文档明确“最后已知”不是“本次新获取”。
7. README、中英文兼容性说明、导出格式与 CHANGELOG 更新；保留原有未提交 README 隐私段落。

### 交付与验收边界

- 合成加密 HTTP 测试覆盖本人接口请求、不同路由、分页、空/坏响应、401/403/404/429/500 降级、匹配歧义与跨午夜，不使用真实账户。
- 端到端测试覆盖原始/聚合评分 → 同步 → SQLite → MCP → JSON/CSV，以及旧库迁移、重复同步、来源更新及失败不清空同一记录的已知评分。
- 用户/报告人安装修复代码后须重启 MCP 并显式重新同步相关日期，再导出；不用删除数据库。只有报告人确认 App 有评分且更新后补取成功，才可把该组合标为社区验证，并考虑关闭 Issue。

### 最终本地验证

- Python 3.12.10：`python -m pytest -q -p no:cacheprovider` → **206 passed**。
- `python -m ruff check src tests scripts`、`python -m compileall -q src tests scripts`、`git diff --check` 均通过（Git 仅提示换行符转换）。
- 首轮全量测试发现公开合成样例尚未包含新增列；已仅通过 `scripts/build_synthetic_site.py` 从虚构种子重新生成 `site/sample.js`，然后完整复测通过。没有替换成个人导出。
- 本地验收阶段没有访问实际小米端点，没有读取真实凭证/健康记录，没有提交、推送、发布或回复/关闭 Issue。旧 README 未提交隐私说明仍保留。

### 推送授权（2026-09-21）

用户随后明确授权推送本次修复。仅提交睡眠评分相关实现、合成测试与文档；原有 README 隐私说明不混入本次提交。不创建版本标签或 Release，Issue #14 保持开放，等待真实账户复测；推送和 CI 结果以 GitHub 提交及工作流记录为准。
