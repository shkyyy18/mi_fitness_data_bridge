# 运动秒级明细数据拉取 — 可行性调研

> 日期：2026-09-27。结论先行：**可行**。社区已完整逆向了小米运动健康 App 的运动明细获取链路，
> 且与本项目现有适配器共用同一套认证与签名机制。建议分三阶段实施。

## 1. 现状缺口

- `workouts` 表只存汇总字段（距离/卡路里/平均最大心率/配速/步数）。
- `heart_rate_samples` 只有日常 passive（约 10 分钟间隔）/active/resting 采样；运动窗口内实测约 60 秒一跳，非秒级。
- 数据库无 GPS 轨迹、海拔、步频的任何存储。
- 适配器只调用 3 个端点（`get_fitness_data_by_time`、`get_aggregated_fitness_data_by_time`、`get_sport_records_by_time`）。

## 2. 协议结论（依据 APK 反编译资料，APK v3.52.0i）

主要参考 [kevinkwee/Mi-Fitness-Sync](https://github.com/kevinkwee/Mi-Fitness-Sync)（MIT 许可，
2026-03 创建、持续维护）的 `docs/mi-fitness-*.md` 反编译笔记与可运行实现。

### 2.1 秒级明细不在现有 JSON 里

`get_sport_records_by_time` 返回的 `value`（SportBasicReport，约 200 字段）只是汇总。
**每秒样本与 GPS 轨迹是独立于 JSON API 的二进制 blob**，存放在 FDS（File Data Service）层：

| 文件类型 | 内容 | 通道示例 |
| --- | --- | --- |
| fileType=0 | 每秒运动记录 | 心率、步频（cadence）、海拔、配速/速度、累计距离/步数/卡路里、SpO2、压力、着地冲击、跑功率等 40+ 通道 |
| fileType=1 | 运动报告（二进制版汇总） | — |
| fileType=2 | GPS 轨迹 | 经纬度、精度、速度、海拔、hdop、GPS 来源 |
| fileType=3 | 恢复率 | — |

### 2.2 获取链路

```
sport_records[].value (SportBasicReport: sid, proto_type, version, timezone, time)
  → 构造 FitnessDataId / suffix
  → POST https://hlth.io.mi.com/healthapp/service/gen_download_url   (RC4 签名，同现有机制)
  → 返回预签名下载 URL + obj_key（按 "suffix_timestamp" 键组织的 map）
  → HTTP GET 下载密文
  → AES-CBC 解密（key = base64url_decode(obj_key)，IV 固定 "1234567887654321"，PKCS5Padding）
  → 二进制解析（header: timestamp LE4 + tzIn15Min + version + sportType + data_valid）
```

### 2.3 suffix 构造

```
suffix = base64url_nopad(6字节) + "_" + base64url_nopad(SHA1(sid_utf8))
6字节   = [timestamp(4B LE)] [tzIn15Min(1B)] [genDataTypeByte(1B)]
genDataTypeByte = (1 << 7) | (proto_type << 2) | fileType   # 即 128 + proto_type*4 + fileType
```

### 2.4 已知的关键坑（反编译笔记明确标注）

1. **sportType 必须用 `proto_type` 而非 `sport_type`**——用错拿不到正确 suffix。
2. **timestamp 必须用 `value` 内部的 report 级 `time`**，而非记录信封的 `time`——两者可能不一致。
3. `version <= 0` 的运动记录没有二进制数据，App 端直接跳过（不发起下载）。
4. `obj_key` 缺失时 App 静默放弃（无重试、无备用端点）——服务端何时返回 obj_key 无法从客户端代码完全确定。
5. summary JSON 内已有大量本项目未存储的汇总字段：平均/最大步频、海拔统计、VO2max、训练效果、训练负荷、恢复时间等。

## 3. 与本仓库的兼容性评估

| 维度 | 结论 |
| --- | --- |
| 认证 | 完全复用：passToken → serviceLogin(sid=miothealth) → serviceToken + ssecurity，适配器已实现（`mi_fitness_cloud.py:223-264`） |
| 请求签名 | 完全复用：RC4/nonce 签名与响应解密已实现（`mi_fitness_cloud.py:96-316`）；FDS 端点唯一差异是签名路径需剥离 `healthapp/` 前缀（`/healthapp/service/gen_download_url` 按 `/service/gen_download_url` 签名）；App 端会注入 `region_tag` 头，但真实账号实测（2026-09-27/28，17200+ 行明细成功落库）不带该头也能正常工作 |
| 需新增持久化 | workouts 表需补存 `sid`、`proto_type`、`version`、`timezone(15min)`、report 级 `time`（均可从现有响应的 value JSON 直接提取，无需新请求） |
| 新依赖 | AES-CBC 需要 `pycryptodome` 或 `cryptography`（标准库无 AES） |
| 许可证 | 参考实现为 MIT，与本项目 AGPL-3.0-only 兼容；引入参考代码须在 `THIRD_PARTY_NOTICES.md` 记录归属 |
| 数据体量 | 35 分钟跑步 ≈ 2000+ 秒级样本 + 数百 GPS 点/次；SQLite 新表即可，但 MCP 查询工具须沿用 agent-safety 限点约定（参照 `workout_series` 的 400/500 点上限） |

## 4. 约束与风险（对照 AGENTS.md）

- 非官方私有接口：`gen_download_url` 与二进制格式同样可能随 App 版本变化，须保留实验性声明并按适配器协议变更规则处理。
- 测试一律 respx mock + 合成二进制 fixture；**禁止以真实账号请求验证**。真实试点由用户自行执行（对齐 release-checklist 的 pilot gate）。
- 不得复制该连接器进下游项目；本项目仍是唯一的 Mi Fitness 连接器实现。
- proto_type 覆盖范围 1–25（跑步=1，户外骑行=6，徒步=15 等）；扩展运动类型由服务端映射到核心 proto_type，映射表不在客户端，需实测记录。

## 5. 建议实施路径

- **Phase 1（低成本，先做）**：✅ 已完成（2026-09-27）。扩展 `iter_workouts` 解析与 `workouts` 表，步频/海拔/VO2max/训练效果等 summary 字段与 FDS 元数据（`fds_sid/proto_type/report_version/report_time/tz_in_15min`）已入库；老库经增量迁移自动补列，需重新同步 workouts 才会回填数据。零新端点、零新依赖。
- **Phase 2（核心）**：✅ 已完成并经真实账号验证（2026-09-27）。新增 `adapters/fds.py`（suffix 构造 + `gen_download_url` + AES-CBC 解密 + 秒级样本/GPS 二进制解析），`workout_detail_samples` / `workout_gps_points` 新表落库。`workout_detail` 已纳入默认全量同步（排在 workouts 之后，已有明细的运动自动跳过），也可显式 `sync --type workout_detail` 或 MCP `sync_data data_types=["workout_detail"]` 单独拉取，`force_full_sync` 重拉。导出数据集新增 `workout_detail` / `workout_gps`，`get_data_coverage` 可查询覆盖。实测发现本机（Redmi Watch 类设备）户外跑步上报 **proto_type=22（户外计步类）** 而非 1，解析器按配置驱动实现，当前覆盖 proto_type 1/2/4/5/15（户外共用配置）与 22/23（户外计步/无计步类，含秒级步频、配速、v9 起的海拔通道）；其他运动类型跳过并记日志。
- **Phase 3（可选）**：TCX/GPX 导出（对齐现有手动 TCX 工作流），MCP 暴露 `workout_track` 等查询工具（限点设计）。

每阶段独立可交付，Phase 1 完成即解决"汇总缺字段"问题；Phase 2 完成后秒级 GPS/心率/步频可自动化，替代手动 TCX 导出。

## 5.1 已知限制（接受的权衡）

- **缺明细的运动每次同步重试**：自回填语义本就是"缺就拉"，网络/解析失败的运动下次同步会再试一次（单次代价 1 个元数据 POST）。不做负缓存，换取零额外状态。
- **首次回填顺序执行**：逐运动串行下载，受 `sync_type_timeout_seconds`（默认 180s）约束；数百场运动的历史库需要分日期范围多次同步或调大超时。当前个人规模（个位数运动）无影响。

## 6. 备选路径

- 维持现状：手动从 App 导出 TCX（已验证可用，缺点是每次手动）。
- 独立使用 kevinkwee/Mi-Fitness-Sync：功能完整（GPX/TCX/FIT 导出 + Strava 同步），但采用邮箱密码登录、与本项目 passToken/keyring 体系不同，且违反"单点连接器、下游依赖而非复制"的仓库定位，仅作协议参考。

## 参考

- https://github.com/kevinkwee/Mi-Fitness-Sync （MIT）— 反编译笔记 `docs/mi-fitness-activity-findings.md`、`docs/mi-fitness-fds-findings.md`、`docs/mi-fitness-fds-download-gaps.md`；实现位于 `src/mi_fitness_sync/activity/` 与 `src/mi_fitness_sync/fds/`
- https://github.com/Misty02600/mi-fitness-python — 亲友共享/消息 API 的独立参考（不含运动明细）
- 本仓库 `docs/mcp-tool-contracts.md`、`docs/release-checklist.md`（pilot gate 流程）
