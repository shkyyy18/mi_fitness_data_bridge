# AGENTS.md — 米桥（mi-bridge，原 mi_fitness_data_bridge）

> 本文件在原有 9 行工作规则基础上扩展。原有规则仍然有效，保留在「既有工作规则」一节。

## 项目定位

本地优先（local-first）的小米运动健康（Mi Fitness）数据桥接工具：通过非官方/实验性的小米云端适配器读取**用户本人**的健康数据，落本地 SQLite，导出 JSON/CSV 或暴露为 MCP 查询工具。明确不做医疗建议、托管账号访问、多用户云服务。

## 技术栈

- Python ≥ 3.11，hatchling 构建，src 布局 `src/mi_fitness_mcp/`
- 依赖：`mcp>=1.0`、`pydantic>=2`、`httpx>=0.27`、`platformdirs`、`keyring>=25`（CLI 用 argparse 实现，无 click/rich）
- 测试：pytest + pytest-asyncio + respx（HTTP mock）；lint：ruff（line-length 100，select E/F/I/N/W/UP/B/C4/SIM，忽略 E501）

## 常用命令

```bash
pip install -e '.[dev]'
python -m pytest -q -p no:cacheprovider
python -m ruff check src tests
```

## 既有工作规则（原文保留）

- Read `PROJECT_GUIDE.md` and `README.md` before work.
- Use `D:\AIWork\repos\mi-fitness-bridge-audit` as the stable path.
- Keep credentials, databases, exports, logs, caches, and personal health data out of Git.
- Do not duplicate this connector inside downstream projects.
- Preserve the experimental/unofficial status and upstream MIT attribution.
- Run `python -m pytest -q -p no:cacheprovider` after changes.

## Text encoding

- Pure Python project: pass `encoding="utf-8"` on every text file read/write and explicit `encoding` on `subprocess` text capture; user health data may contain Chinese.
- Export convention: JSON is UTF-8, CSV is `utf-8-sig` (BOM, so Excel opens Chinese correctly); SQLite stores text natively.

## 本仓库 agent 的搜索范围与要求

- 只允许改动本仓库；**严禁读取、复制、传输任何真实凭证与健康数据**：passToken、SQLite 库、导出文件、日志均不得入库、不得进报告、不得上传到任何第三方（.gitignore 已覆盖 `.env*`、`*.db`、`exports/`、`logs/` 等，不得绕过）。
- 适配器（`adapters/mi_fitness_cloud.py`）只访问用户本人有权访问的账号；任何测试/调试一律用合成数据（`examples/synthetic_demo.py`）或 respx mock，不得对真实小米端点发起探测性请求。
- 保持非官方/实验性定位声明与上游 MIT 归属（THIRD_PARTY_NOTICES.md），不得在 README/文档中弱化这些声明。
- `setup` 只走交互式（getpass 不回显）；`--user-id` / `--pass-token` 命令行旗标已于 2026-08-17 移除（会进 shell 历史），不得在文档/脚本中重新引入。

## 升级建议有效性 / 采纳规则（本仓定制）

1. 凡涉及凭证处理、隐私数据流、MCP 工具暴露面的建议：默认从严，凡扩大凭证/数据暴露面的（如托管代理、共享 token、公网部署）一律**记录不做**（SECURITY.md 已明确超出安全模型）。
2. 适配器协议变更（登录、加密、分页）：必须用 respx mock 补测试，禁止以真实账号请求作为验证手段。
3. 任何引入遥测/上报/联网分析的建议：一律**记录不做**（local-first 定位）。
4. 上游 API 变动导致的修复：属"立即做"（工具会实际失效），修复后同步 README 的实验性声明和 KNOWN_REGIONS。
5. 导出格式/查询能力增强：有效即可排期做，但导出内容不得包含 passToken 等凭证字段。

## 升级建议 backlog

（暂无。近期问题已修复；后续发现按全局规则 `github-project-evaluation/docs/agent-collab-rules.md` 收录。）
