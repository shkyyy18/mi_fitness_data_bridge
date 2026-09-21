# Compatibility and safe first run / 兼容性与安全上手

> **Unofficial and experimental / 非官方、实验性。** No affiliation with, endorsement by, or support from Xiaomi. Private upstream interfaces may change without notice.

## Try without an account / 不连接账户也能先试

- [Open the synthetic browser demo / 浏览器合成数据演示](https://shkyyy18.github.io/mi_fitness_data_bridge/).
- After installing the package, run `python examples/synthetic_demo.py`.
- Both use invented records to demonstrate local SQLite → JSON/CSV export. Neither proves that a device, region or account can synchronize from Xiaomi.
- The web page is a static sample, **not a hosted bridge**, health dashboard or account connection service. It accepts no credentials, personal records or file uploads.

## Evidence, not promises / 按证据说明支持范围

| Layer / 层级 | Evidence / 已有证据 | Not established / 尚不能说明 |
| --- | --- | --- |
| Local export / 本地导出 | Automated tests and the reproducible synthetic example / 自动化测试与合成示例 | Live cloud access / 真实云端连接 |
| Cloud adapter / 云端适配器 | Implementation and mocked protocol tests / 代码与模拟协议测试 | Availability for every region, firmware or account / 所有地区、固件与账户均可用 |
| Specific device + region / 具体设备与地区 | No evidence-linked device matrix recorded here yet / 本页尚无附证据来源的设备验证表 | Universal Xiaomi-device support / 小米全设备兼容 |

**We do not currently publish a verified device list.** This does not mean every device fails; it means an implementation or a synthetic test is not device-specific evidence. Do not infer support from a product name or from an empty successful response. The software's default account region is `cn`, not a compatibility guarantee. Mi Fitness and Zepp Life are not interchangeable configurations.

**目前不发布“已验证设备名单”。** 这不代表设备都不可用，而是不能把代码存在、合成测试通过，当作设备兼容性证明。默认地区 `cn` 也不是成功保证。请先确认使用的是 Mi Fitness（小米运动健康），不要把其他应用的账户与配置直接套用。

## Real account setup / 真实账户配置的边界

The current CLI expects an existing Mi Fitness `user_id` and `passToken` and does **not** offer a one-click account authorization or guided token-acquisition flow. If you do not already have credentials obtained through a method you understand and trust, use the synthetic demo instead. Do not give an unknown website, hosted agent or maintainer your password or token. No new credential-acquisition method has been validated for this launch.

当前 CLI 需要已有的 `user_id` 和 `passToken`，**不提供一键账号授权，也没有经本轮验证的凭证获取向导**。如果尚未通过自己理解并信任的方法取得凭证，先停留在合成演示；不要为了试用，向陌生网站、托管代理或维护者提供账号密码和 Token。

If you already have authorized credentials, use interactive `mi-fitness-bridge setup`; never pass tokens as command-line arguments. `doctor` may contact Xiaomi when credentials are configured. All tests and public bug reports must use synthetic or mocked data.

## Report compatibility without exposing data / 安全反馈兼容性

[Use the compatibility report form / 使用兼容性反馈表](https://github.com/shkyyy18/mi_fitness_data_bridge/issues/new?template=compatibility_report.yml).

Only share:
- Device **model**, not serial number or device/account ID.
- Account **region**, OS and Python/package version.
- Dataset names and status: works / empty / fails / not tested.
- Test date and a plain-language description with no personal measurements.

Do **not** attach database files, raw responses, credentials, private logs or health screenshots. We will label community reports as **community-reported**, not maintainer-verified. A report is evidence for that combination and date only.

## Privacy / 隐私

Local storage and local stdio do not guarantee that an AI client/model runs offline. Query results may be forwarded by the client. Review that flow separately; do not connect this bridge to a remote or hosted proxy. Export files can include a plaintext `user_id` and must be kept private. See [SECURITY.md](../SECURITY.md).

## Sleep-score fallback / 睡眠评分补取（2026-09-21）

The unreleased #14 patch adds a best-effort own-account daily-report lookup using the existing region and authentication, with no relatives API or cross-region discovery. It is covered by encrypted respx mocks, including cn/de/us routing; this is **not** live-account, device or region verification. `KNOWN_REGIONS` remains a list of routing candidates only. Missing/ambiguous scores remain unavailable, and an optional report failure must not discard sleep sessions. See the README sleep-score section before re-syncing.

尚未发布的 #14 补丁使用既有地区及认证尝试读取本人每日聚合睡眠报告，不接亲友接口，不跨地区探测。cn/de/us 的测试只证明模拟请求路由正确，**不代表真实设备、账户或地区已经验证可用**。如接口不支持或无法明确匹配，保留原睡眠记录，不伪造评分。升级后须重新同步；只导出不会补取。
