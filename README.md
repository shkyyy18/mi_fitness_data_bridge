> English: [README.en.md](README.en.md)

# 米桥（Mi Fitness Data Bridge）

[![Glama score](https://glama.ai/mcp/servers/shkyyy18/mi_fitness_data_bridge/badges/score.svg)](https://glama.ai/mcp/servers/shkyyy18/mi_fitness_data_bridge)

这是一个把**小米运动健康（Mi Fitness）及相关小米设备数据导出到本地**的工具。你可以将运动、睡眠、心率、体重等数据保存为 SQLite、JSON 或 CSV 文件，再交给 ChatGPT、Claude、Gemini 等大模型进行分析、对比和总结。项目也提供 Python 接口和本地 MCP 工具，方便大模型或其他程序读取这些数据。

> **非官方、实验性项目。** 本项目与小米没有隶属、背书或支持关系；小米、米家（Mi Home）和 Mi Fitness 是小米公司的商标。适配器依赖非公开上游接口，小米的服务、账户地区、设备、固件或认证方式变化后，登录、连接或某些数据类型可能随时失效。仅可用于你有权访问的账户和数据。

![米桥合成数据终端演示](docs/assets/bridge-synthetic-demo.png)

*截图和本文全部示例均为合成数据；不含凭证、账户标识符或真实健康导出数据。*

## 功能一览

| 功能 | 说明 |
| --- | --- |
| 本地缓存 | 将同步并规范化后的记录保存到你的本机 SQLite 数据库。 |
| 可移植导出 | 导出 JSON 或 CSV 文件，便于备份、交给自己的分析工具或导入大模型；不会导出已保存的 `passToken`。 |
| 本地 MCP 服务 | 通过标准输入/输出（stdio）提供个人自动化和本地 AI 工作流所需的查询工具。 |
| Python 集成 | 保留 `mi_fitness_mcp` 命名空间，兼容既有下游使用者。 |

默认云端地区为 `cn`，也可在配置时指定其他地区。实际可用记录取决于账户地区、设备、固件及小米上游服务；某个数据类型同步成功但返回 0 条记录，可能只是指定范围内没有该类型数据。

## 支持的数据

- **日常活动**：步数、距离、活动卡路里、活动分钟及相关字段。
- **睡眠**：睡眠会话与阶段。
- **运动记录**。
- **身体测量**：体重，以及账户或设备提供的身体成分字段。
- **心率样本**：包括可用时的静息心率。
- 可用时的 **血氧（SpO₂）**、压力和异常心跳事件。

日常活动的步数按本地“分钟切片”汇总：当手机、手环或手表对同一分钟上报重叠记录时，会保留较大的单条记录而不是相加，以避免双设备重复计步。该规则是对非公开上游数据的最佳兼容处理，最终数值仍可能与 App 的服务端修正结果不同。

## 项目边界

这是数据连接器和本地数据基础设施，明确**不提供**：

- 医疗诊断、治疗、健康教练或减重建议；
- 托管账户、共享凭证、公开 Token 代理或多用户云服务；
- Web 仪表盘、第三方健身 OAuth/Webhook 或餐食照片分析。

下游项目应安装本包或消费本地导出结果，而不是复制连接器源码。

## 安装

**要求：Python 3.11 或更高版本。**

```bash
git clone https://github.com/shkyyy18/mi_fitness_data_bridge.git
cd mi_fitness_data_bridge
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e .
```

macOS / Linux：

```bash
source .venv/bin/activate
pip install -e .
```

安装开发依赖：

```bash
pip install -e '.[dev]'
```

主命令为 `mi-fitness-bridge`；旧命令 `mi-fitness-mcp` 仍保留为兼容别名。

## 配置与诊断

请使用交互式配置。`passToken` 提示会隐藏输入，避免它进入 shell 历史：

```bash
mi-fitness-bridge setup
mi-fitness-bridge doctor
```

配置过程会询问 Mi Fitness 的 `user_id`、`passToken` 和地区（默认 `cn`）。凭证会在可用时保存到本机操作系统的密钥环；使用前请了解当前密钥环后端的安全特性。**不要**在命令行、脚本、Issue、日志或截图中粘贴 `passToken`。`setup` 不接受 `--user-id` 或 `--pass-token` 命令行参数。

`doctor` 会检查本地配置、凭证和数据库；配置了凭证时还会检查云端连通性。云端检查可能因网络或上游服务变动失败，但已有本地数据和导出操作仍可离线使用。

`sync`、`export`、`serve` 和 `doctor` 支持 `--db`，也支持 `MI_FITNESS_DB_PATH` 环境变量指定数据库路径，优先级为：命令行参数 > 环境变量 > 配置/默认路径。

## 同步数据

同步日期范围内所有支持的数据类型：

```bash
mi-fitness-bridge sync --start-date 2026-07-01 --end-date 2026-07-15
```

只同步某一种数据：

```bash
mi-fitness-bridge sync --type sleep --start-date 2026-07-01 --end-date 2026-07-15
mi-fitness-bridge sync --type body_measurements --start-date 2026-07-01 --end-date 2026-07-15
```

`--type` 可选值：`daily_activity`、`heart_rate`、`body_measurements`、`sleep`、`workouts`、`spo2`、`stress`、`abnormal_heart_beat`。CLI 会按数据类型报告新增、更新、部分完成和失败情况。指定明确日期范围的重复同步是幂等的，不会复制已有记录；若小米后来修正了较早日期，请用显式的较早 `--start-date` 重跑该范围。

## 导出本地数据

导出一个 JSON 文件：

```bash
mi-fitness-bridge export --format json --output exports/mi_fitness.json
```

导出 CSV（每个数据集一个文件）：

```bash
mi-fitness-bridge export --format csv --output exports/csv
```

按数据集和日期筛选：

```bash
mi-fitness-bridge export --format json --type sleep \
  --start-date 2026-07-01 --end-date 2026-07-15 \
  --output exports/sleep.json
```

日期必须使用 `YYYY-MM-DD`，开始日期不得晚于结束日期。JSON 使用 UTF-8，CSV 使用带 BOM 的 `utf-8-sig`，便于 Excel 正确打开中文。导出的健康记录属于敏感个人数据，且可能含明文 `user_id`；默认 `.gitignore` 会忽略数据库、导出目录和常见日志，但你仍需妥善保存、分享和备份它们。

详见 [导出格式说明（英文）](docs/export-format.md)，其中描述 JSON 信封、CSV 布局及包含边界的日期筛选规则。

## MCP 服务

启动本地 stdio MCP 服务：

```bash
mi-fitness-bridge serve
# 兼容别名
mi-fitness-mcp serve
```

可用工具包括：`get_connection_status`、`sync_data`、`get_sync_status`、`get_profile`、`get_daily_summary`、`query_metric_series`、`get_data_coverage`、`query_body_measurements`、`query_sleep`、`query_workouts`、`workout_series`、`query_heart_rate`、`query_spo2`、`query_stress` 和 `query_abnormal_heart_beat`。

服务通过标准输入/输出通信，应由本机 MCP 客户端启动和管理；直接在终端运行时看似“卡住”是因为它正在等待 MCP 消息。它不会在启动时连接小米，只有状态检查或同步操作才按需建立云端连接。不要将它暴露为公网服务或凭证代理。

客户端配置示例：

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

## 作为 Python 依赖使用

兼容包名保持为 `mi_fitness_mcp`：

```python
from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
```

不要硬编码真实凭证，也不要将它们提交到源代码管理。下游项目应安装本包，而不要供应或复制其源码。

## 合成端到端演示

仓库包含完全不访问网络或真实账户的演示：

```bash
python examples/synthetic_demo.py
```

它会创建临时 SQLite 数据库、写入合成记录，并运行真实的 JSON/CSV 导出流程。可用于验证本地导出路径，或准备不泄露隐私的 Bug 报告。

## 开发

```bash
pip install -e '.[dev]'
python -m pytest -q -p no:cacheprovider
python -m ruff check src tests
```

Issue、测试、文档和截图中只可使用合成数据。安全问题请遵循 [SECURITY.md](SECURITY.md)；发布步骤请见 [docs/release-checklist.md](docs/release-checklist.md)。

## 隐私、来源与许可

- 将 `passToken`、SQLite 数据库、导出文件和日志保密。
- 不要提交真实健康数据，或包含个人指标的截图。
- `query_*` MCP 工具返回的健康数据会流入你使用的 MCP 客户端；仅限本机 stdio 客户端使用，切勿接入远程或托管代理。
- 本软件仅用于个人数据访问和工程研究，不用于诊断或治疗。
- 上游来源和 MIT 归属见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

当前版本采用 **AGPL-3.0-only** 许可证；2026-08-03 之前发布的版本为 MIT。详见 [LICENSE](LICENSE)。
