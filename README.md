> English version: [README.en.md](README.en.md)

# 米桥（Mi Fitness Data Bridge）

[![Glama score](https://glama.ai/mcp/servers/shkyyy18/mi-bridge/badges/score.svg)](https://glama.ai/mcp/servers/shkyyy18/mi-bridge)

本地优先的数据桥接器，把**你自己的**小米运动健康数据导出到 SQLite、JSON、CSV、Python 以及兼容 MCP 的工具。

*小米运动健康 App 很乐意给你看你的步数、睡眠和心率——却从不让你把这些数据带走。这个桥接器把你自己的数据放进你自己硬盘上的一个 SQLite 文件里。*

<p align="center"><img src="docs/assets/bridge-hero.png" width="100%" alt="米家设备通过米桥（Mi Fitness Data Bridge）连接各大 AI 模型"></p>

> **商标声明：小米、米家、Mi Fitness 均为小米公司商标。本项目为非官方社区项目，与小米公司无任何隶属或背书关系。**

> 实验性的云端适配器可能因为小米改动私有接口而随时失效。请只在你有权访问的账号和数据上使用。

## 实测验证

2026-07-20 在 Windows（Python 3.14）上基于 `main` 分支的提交录制。所有数据均为合成数据，不涉及任何凭据或网络访问。（测试数量已于 2026-08-17 复核更新。）

测试套件：

```text
$ python -m pytest -q -p no:cacheprovider
........................................................................ [ 96%]
...                                                                      [100%]
75 passed in 10.27s
```

端到端合成演示（`examples/synthetic_demo.py` 先用合成记录填充本地 SQLite 缓存，再跑真实的 JSON/CSV 导出流水线）：

```text
$ python examples/synthetic_demo.py
Seeded synthetic database: C:\Users\<you>\AppData\Local\Temp\mi-fitness-demo-53el7cfh\mi_fitness.db
  daily_activity: 2026-07-15 .. 2026-07-15 (1 day(s))
  sleep: 2026-07-14 .. 2026-07-14 (1 day(s))
  workouts: 2026-07-15 .. 2026-07-15 (1 day(s))
  body_measurements: 2026-07-15 .. 2026-07-15 (1 day(s))

Export completed
  mi_fitness.json
  daily_activity.csv
  sleep.csv
  workouts.csv
  body_measurements.csv
  heart_rate.csv
  spo2.csv
  stress.csv
  abnormal_heart_beat.csv

JSON envelope:
  schema_version: 1.0
  source: mi_fitness_data_bridge
  records.daily_activity: 1 row(s)
  records.sleep: 1 row(s)
  records.workouts: 1 row(s)
  records.body_measurements: 1 row(s)

Sample sleep row (synthetic):
  start_at=2026-07-14T23:20:00 end_at=2026-07-15T07:05:00
  duration_minutes=465 score=86
  stages=[{"stage": "deep", "minutes": 82}, {"stage": "light", "minutes": 271}, {"stage": "rem", "minutes": 88}, {"stage": "awake", "minutes": 24}]
```

## 已合并 health-assistant 项目

`health-assistant` 项目（本地优先的个人健康看板：Strava、睡眠、身体成分、饮食分析）已合并进本仓库，其原仓库已归档。吸收过来的资产位于 `docs/health-assistant/` 目录下：

- `analytics.py` —— 零依赖的训练/恢复总结与建议引擎参考实现（7 天训练统计、急性/慢性负荷比、就绪度检查、每日训练建议）。
- `coaching_methodology.md` —— 其背后可解释的骑行教练、身体成分与运动营养方法论。
- `README.md` —— 完整的迁移说明，包括有意未移植的部分（FastAPI 看板、Strava OAuth/Webhook 管线、餐食照片分析）以及原因。

## 这个项目做什么

- 通过一个实验性的中国区云端适配器读取小米运动健康数据。
- 把规范化后的记录存进本地 SQLite 数据库。
- 导出不含凭据的便携式 JSON 或 CSV。
- 暴露本地 MCP 查询工具，供个人自动化使用。
- 为下游项目（比如个人减脂顾问）提供一份可复用的连接器实现。

它刻意**不**提供医疗建议、减肥指导、托管式账号访问或多用户云服务。

## 为什么做这个桥接器？

| 之前 | 之后 |
|---|---|
| 你的健康历史只存在于小米运动健康 App 里，唯一的"导出"方式是截图。 | `mi-fitness-bridge sync` 把每日活动、睡眠、运动、身体测量、心率、血氧（SpO2）和压力拉进一个规范化的本地 SQLite 数据库。 |
| 想回答"我上个月睡得怎么样"，得在 App 里一天天往回翻。 | `mi-fitness-bridge export --format csv --type sleep --start-date ... --end-date ...` 输出一个精确按该区间过滤、可直接用表格软件打开的 CSV。 |
| 想让 AI 助手访问你的健康数据，就得把凭据交给某个托管服务。 | `mi-fitness-bridge serve` 基于你自己的数据库暴露本地 MCP 查询工具；passToken 留在操作系统钥匙串里，导出文件中永远不会包含它。 |

## 支持的数据集

- 每日活动：步数、距离、活动热量和活动分钟数。
- 睡眠记录及睡眠阶段。
- 运动记录。
- 身体测量：体重及可用的身体成分字段。
- 心率样本，包括可用时的静息心率。
- 血氧（SpO2）、压力和异常心跳事件（取决于账号/设备是否提供）。

实际可用性因设备、账号地区、固件和小米上游服务而异。

## 安装

```bash
git clone https://github.com/shkyyy18/mi_fitness_data_bridge.git mi_fitness_data_bridge
cd mi_fitness_data_bridge
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Windows Git Bash：

```bash
source .venv/Scripts/activate
pip install -e ".[dev]"
```

macOS/Linux：

```bash
source .venv/bin/activate
pip install -e '.[dev]'
```

## 配置

更安全的交互式配置路径可以避免把 passToken 直接写进 shell 历史：

```bash
mi-fitness-bridge setup
mi-fitness-bridge doctor
```

在可用时，凭据通过本地钥匙串（keyring）存储。某些备用的 keyring 实现存储密钥的方式可能不够安全，使用前请先了解你操作系统的 keyring 行为。

### 如何获取 user_id 和 passToken

本桥接器使用的是小米账号级凭据（与米家 App 同一套登录态），以下两种方式任选其一：

**方式一：浏览器手动复制**

1. 在浏览器打开 [account.xiaomi.com](https://account.xiaomi.com) 并登录你的小米账号（与小米运动健康 App 同一个账号）。
2. 打开开发者工具（F12）→「应用 / Application」→ Cookies → `https://account.xiaomi.com`。
3. 复制 `userId` 和 `passToken` 两个 Cookie 的值，在 `mi-fitness-bridge setup` 提示时粘贴。

**方式二：扫码登录工具**

用开源的 [mijia-api](https://github.com/Do1e/mijia-api) 扫码登录一次：

```bash
pip install mijiaAPI
python -c "from mijiaAPI import mijiaAPI; mijiaAPI().login()"   # 终端出二维码，用米家 App 扫码
```

登录态默认保存在 `~/.config/mijia-api/auth.json`（Windows 为 `%USERPROFILE%\.config\mijia-api\auth.json`），其中的 `userId` 和 `passToken` 即可直接用于本桥接器——小米账号级凭据跨服务通用，桥接器会用它换取小米运动健康（`sid=miothealth`）的会话。注意 `auth.json` 以明文保存凭据：把 `userId` 和 `passToken` 录入本桥接器（系统钥匙串）后，建议删除该文件。

注意：

- passToken 会过期；`doctor` 报认证失败时按上面步骤重新获取一次即可。
- 浏览器法请在自己常用的网络环境下登录；频繁或异地操作可能触发小米账号风控（滑块/短信验证），如遇风控可改用扫码法。
- Cookie 名称与登录流程基于 2026-08 的实测，可能因账号地区、设备或风控策略而异；小米也可能随时调整私有接口（见顶部实验性声明）。
- 这两个值等同于你的账号登录态，请勿泄露，也请勿提交到 Git。

## 同步

```bash
mi-fitness-bridge sync --start-date 2026-07-01 --end-date 2026-07-15
```

或者只同步某一个数据集：

```bash
mi-fitness-bridge sync --type sleep --start-date 2026-07-01 --end-date 2026-07-15
mi-fitness-bridge sync --type body_measurements --start-date 2026-07-01 --end-date 2026-07-15
```

数据库默认落在平台用户数据目录（platformdirs 决定）。`sync`、`export`、`serve`、`doctor` 都支持用 `--db` 参数或 `MI_FITNESS_DB_PATH` 环境变量换位置，优先级：命令行 > 环境变量 > 默认位置。注意 platformdirs 在 Windows 上不响应 `LOCALAPPDATA` 环境变量，要自定义路径请用上述两种方式：

```bash
mi-fitness-bridge sync --db ./data/mi_fitness.db --start-date 2026-07-01 --end-date 2026-07-15
export MI_FITNESS_DB_PATH=./data/mi_fitness.db
```

已知限制：不带日期参数的增量同步以本地最后一条记录的时间为起点，上游对更早历史的修正或补录不会被自动拉到；需要时用更早的 `--start-date` 显式重跑该区间（会幂等覆盖，不会产生重复记录）。

## 导出

生成一个便携式 JSON 文件：

```bash
mi-fitness-bridge export --format json --output exports/mi_fitness.json
```

每个数据集各生成一个 CSV 文件：

```bash
mi-fitness-bridge export --format csv --output exports/csv
```

按数据集和日期过滤：

```bash
mi-fitness-bridge export --format json --type sleep \
  --start-date 2026-07-01 --end-date 2026-07-15 \
  --output exports/sleep.json
```

导出文件永远不会包含已保存的小米 passToken，但会包含明文 `user_id` 等标识列——导出文件属于敏感个人数据，请妥善保管。导出的健康记录默认已被 Git 忽略。

导出格式说明（JSON 信封结构、CSV 布局、闭区间日期筛选规则）见 [Export format](docs/export-format.md)。

## MCP 服务

兼容命令仍然可用：

```bash
mi-fitness-bridge serve
# legacy alias
mi-fitness-mcp serve
```

可用的工具包括连接状态、同步、覆盖范围、每日摘要、身体测量、睡眠、运动、心率、血氧（SpO2）和压力查询，以及面向 agent 的 `workout_series` 运动时序工具——按 `max_points` 硬上限自动降采样（固定时间桶均值，SQLite 内聚合），并在响应中如实标注 `downsampled`、`source_points`、`returned_points`、`method`，同时给出全精度统计（avg/min/max/分位数）与心率区间时间。`query_workouts`、`get_daily_summary` 等列表/汇总工具附带 `data_quality`（覆盖天数、缺失指标、最后同步时间）。

客户端接入示例（Claude Code / Codex 等 MCP 客户端的配置 JSON）：

```json
{
  "mcpServers": {
    "mi-bridge": {
      "command": "mi-fitness-bridge",
      "args": ["serve"]
    }
  }
}
```

注意：`serve` 是 stdio 服务，通过标准输入输出与客户端通信，不是 HTTP 服务。直接在终端运行它会看似"卡住"——那是在等待客户端的 MCP 消息，属正常现象；日常请交给 MCP 客户端按上面的配置启动。

## 作为 Python 依赖使用

规范化适配器在兼容模块名下仍然可用：

```python
from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
```

下游项目应当安装本包，而不是 vendor 或复制连接器源码。

## 许可证

许可证沿革：2026-08-03 之前发布的版本采用 MIT 许可（上游 `kubulashvili/mi-fitness-mcp` 与 `binglua/mi-fitness-mcp-cn` 的 MIT 归属保留在 `LICENSE` 顶部的 NOTICE 区块）；当前版本的新增代码采用 AGPL-3.0-only。详见 `LICENSE` 与 `THIRD_PARTY_NOTICES.md`。

## 隐私与安全

- 妥善保管 passToken、本地数据库、导出文件和日志，不要外泄。
- 导出文件不含 passToken，但含明文 `user_id` 等标识列，同样属于敏感个人数据。
- 不要把本桥接器当作公开的凭据代理来运行。
- 不要提交真实健康数据或包含个人指标的截图。
- 在 bug 报告和文档中一律使用合成数据。
- 本软件仅用于个人数据访问和工程研究，不用于诊断或治疗。

负责任披露方式见 `SECURITY.md`，出处溯源见 `THIRD_PARTY_NOTICES.md`。

## 开发

```bash
pip install -e '.[dev]'
python -m pytest -q -p no:cacheprovider
python -m ruff check src tests
```

## 发布

版本历史见 `CHANGELOG.md`，发布及发布后检查项见 `docs/release-checklist.md`。

## 相关项目

- [garmin-mcp](https://github.com/davidmosiah/garmin-mcp) —— 本地优先的 Garmin 数据 MCP 服务。与本项目共享 `agent-safe-series/v1` 数据契约（时间序列降采样字段语义逐字节对齐），同一个 AI agent 可以无缝消费两个服务的数据。

## 支持这个项目

如果这个工具帮到了你，在 [GitHub](https://github.com/shkyyy18/mi-bridge) 上帮我点个 star 吧。
