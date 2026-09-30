"""Phase 2 FDS 明细链路测试：全部使用合成二进制数据，无网络、无真实记录。

- suffix 构造与 server key 拼接
- AES-CBC 解密 + 户外运动族秒级样本解析（往返）
- GPS 轨迹 v1/v2 解析（往返）
- 新表 upsert 幂等
- workout_detail 同步分支（假适配器）
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
from datetime import UTC, datetime, timedelta

import pytest

from mi_fitness_mcp.adapters.fds import (
    FDS_HEADER_META_LEN,
    TYPE_CADENCE,
    TYPE_CALORIES,
    TYPE_DISTANCE,
    TYPE_HEIGHT_VALUE,
    TYPE_HR,
    TYPE_INTEGER_KM,
    TYPE_PACE,
    FdsParseError,
    build_fds_suffix,
    decrypt_fds_blob,
    fds_server_key,
    parse_gps_record,
    parse_sport_record,
)
from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
from mi_fitness_mcp.models import GpsPoint, Workout, WorkoutSample
from mi_fitness_mcp.storage import Database


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _encrypt_blob(plaintext: bytes, key: bytes) -> str:
    """构造 FDS 下载体：AES-CBC(IV 固定) 加密后 base64url。"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    pad_len = 16 - len(plaintext) % 16
    padded = plaintext + bytes((pad_len,)) * pad_len
    encryptor = Cipher(algorithms.AES(key), modes.CBC(b"1234567887654321")).encryptor()
    return _b64url(encryptor.update(padded) + encryptor.finalize())


def _fds_key() -> bytes:
    return bytes(range(16))


def test_build_fds_suffix_layout():
    sid = "2198620807"
    timestamp = 1789998701
    # proto_type=1（户外跑），fileType=0 → data_type_byte = 128 + 4 = 132
    suffix = build_fds_suffix(
        sid=sid, timestamp=timestamp, tz_in_15min=32, proto_type=1, file_type=0
    )
    key_part, sid_part = suffix.split("_")
    expected_key = struct.pack("<I", timestamp) + bytes((32, 132))
    expected_sid = hashlib.sha1(sid.encode()).digest()
    assert key_part == _b64url(expected_key)
    assert sid_part == _b64url(expected_sid)
    assert "=" not in suffix
    assert fds_server_key(suffix, timestamp) == f"{suffix}_{timestamp}"


def test_sport_record_roundtrip():
    version = 2
    proto_type = 1
    report_time = 1789998701
    # dataValid：calories/hr/integer_km/distance 全部 exist+high → 每 nibble 0b1100
    data_valid = bytes((0xCC, 0xCC))
    header = struct.pack("<IBBB", report_time, 32, version, proto_type) + b"\x00" + data_valid
    # 段结构：pause_init(4B) + record_count(4B) + start_time(4B) + IT 摘要(v2: 1B)
    segment_start = 1789998701
    records = [
        # 每样本 4B：calories(高4位整数部分) / hr / integer_km(最高位) / distance
        bytes(((5 << 4) | 3, 150, 0x80 | 1, 200)),
        bytes(((6 << 4) | 0, 151, 0x00, 201)),
        bytes(((6 << 4) | 7, 152, 0x80, 202)),
    ]
    body = b"\x00" * 4
    body += struct.pack("<I", 3)  # record_count
    body += struct.pack("<I", segment_start)
    body += b"\x00"  # IT 摘要 1 字节（v2）
    body += b"".join(records)
    blob = header + body
    assert len(blob) > FDS_HEADER_META_LEN + 1

    decrypted = decrypt_fds_blob(_encrypt_blob(blob, _fds_key()), _b64url(_fds_key()))
    assert decrypted == blob

    segments = parse_sport_record(decrypted, proto_type)
    assert len(segments) == 1
    seg_start, samples = segments[0]
    assert seg_start == segment_start
    assert len(samples) == 3
    assert samples[0][TYPE_HR] == 150
    assert samples[0][TYPE_CALORIES] == 5
    assert samples[0][TYPE_INTEGER_KM] == 1
    assert samples[0][TYPE_DISTANCE] == 200
    assert samples[2][TYPE_HR] == 152
    assert samples[1][TYPE_INTEGER_KM] == 0


def test_unsupported_proto_type_returns_empty():
    blob = struct.pack("<IBBB", 1789998701, 32, 2, 8) + b"\x00" + bytes((0xCC, 0xCC))
    assert parse_sport_record(blob, 8) == []


def test_gps_record_v1_roundtrip():
    version = 1
    report_time = 1789998701
    # v1 只有 time/lon/lat；valid 位序同 GPS_DATA_TYPES → 0b11100000
    data_valid = bytes((0b11100000,))
    header = struct.pack("<IBBB", report_time, 32, version, 1) + b"\x00" + data_valid
    points = [
        (1789998702, 121.4737, 31.2304),
        (1789998703, 121.4739, 31.2305),
    ]
    body = b"".join(struct.pack("<Iff", ts, lon, lat) for ts, lon, lat in points)
    decrypted = header + body

    samples = parse_gps_record(decrypted)
    assert len(samples) == 2
    assert samples[0].timestamp == points[0][0]
    assert samples[0].longitude == pytest.approx(121.4737, abs=1e-4)
    assert samples[0].latitude == pytest.approx(31.2304, abs=1e-4)
    assert samples[0].speed_mps is None
    assert samples[0].altitude_m is None


def test_gps_record_v2_with_speed_and_source():
    version = 2
    # time/lon/lat/accuracy/speed/source → 6 bits → 0b11111100
    data_valid = bytes((0b11111100,))
    header = struct.pack("<IBBB", 1789998701, 32, version, 1) + b"\x00" + data_valid
    # speed 2B：高 12 位 = 0.1m/s 步进（0x12C=300 → 30.0 m/s），低 4 位 = 来源 5
    body = struct.pack("<Iff", 1789998702, 121.0, 31.0)
    body += struct.pack("<f", 4.5)  # accuracy
    body += struct.pack("<H", (0x12C << 4) | 0x5)
    samples = parse_gps_record(header + body)
    assert len(samples) == 1
    assert samples[0].speed_mps == pytest.approx(30.0)
    assert samples[0].gps_source == 5
    assert samples[0].accuracy == pytest.approx(4.5, abs=1e-4)


def _sample(workout_id: str, offset: int, user_id: str = "u-1") -> WorkoutSample:
    return WorkoutSample(
        id=f"mi_fitness_sample_{workout_id}_{offset}",
        provider="mi_fitness",
        source_type="cloud_session",
        user_id=user_id,
        workout_id=workout_id,
        offset_seconds=offset,
        timestamp=datetime(2026, 9, 25, 14, 0, 0, tzinfo=UTC) + timedelta(seconds=offset),
        heart_rate_bpm=150 + offset,
        distance_m=float(offset * 3),
    )


def _gps_point(workout_id: str, offset: int, user_id: str = "u-1") -> GpsPoint:
    return GpsPoint(
        id=f"mi_fitness_gps_{workout_id}_{offset}",
        provider="mi_fitness",
        source_type="cloud_session",
        user_id=user_id,
        workout_id=workout_id,
        offset_seconds=offset,
        timestamp=datetime(2026, 9, 25, 14, 0, 0, tzinfo=UTC) + timedelta(seconds=offset),
        latitude=31.0 + offset / 1e5,
        longitude=121.0 + offset / 1e5,
        speed_mps=3.0,
    )


def test_workout_detail_tables_upsert_idempotent(tmp_path):
    db = Database(tmp_path / "mi_fitness.db")
    samples = [_sample("wo-1", offset) for offset in (0, 1, 2)]
    points = [_gps_point("wo-1", offset) for offset in (0, 30, 60, 90)]

    added, updated = db.insert_workout_detail_samples(samples)
    assert (added, updated) == (3, 0)
    gps_added, gps_updated = db.insert_workout_gps_points(points)
    assert (gps_added, gps_updated) == (4, 0)

    # 完全重跑：0 新增，全部计为更新（幂等）。
    re_added, re_updated = db.insert_workout_detail_samples(samples)
    assert (re_added, re_updated) == (0, 3)
    re_gps_added, re_gps_updated = db.insert_workout_gps_points(points)
    assert (re_gps_added, re_gps_updated) == (0, 4)

    # 值更新生效。
    changed = [_sample("wo-1", 0), _sample("wo-1", 1)]
    changed[0].heart_rate_bpm = 999
    db.insert_workout_detail_samples(changed)
    import sqlite3

    with sqlite3.connect(db.db_path) as conn:
        hr = conn.execute(
            "SELECT heart_rate_bpm FROM workout_detail_samples"
            " WHERE workout_id='wo-1' AND offset_seconds=0"
        ).fetchone()[0]
    assert hr == 999


class _DetailAdapter:
    """假适配器：返回固定的合成样本/GPS，验证同步分支编排。"""

    def __init__(self, user_id: str, detail: dict[str, tuple[list, list]]):
        self._user_id = user_id
        self._detail = detail
        self.requested: list[str] = []

    def is_connected(self) -> bool:
        return True

    def get_user_id(self) -> str:
        return self._user_id

    async def fetch_workout_detail(self, workout: dict):
        self.requested.append(workout["workout_id"])
        return self._detail.get(workout["workout_id"], ([], []))


def _seed_workout(db: Database, user_id: str, workout_id: str) -> None:
    db.insert_workout(
        Workout(
            id=f"mi_fitness_workout_{workout_id}",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id=user_id,
            workout_id=workout_id,
            activity_type="running",
            start_at=datetime(2026, 9, 25, 22, 1, 31),
            end_at=datetime(2026, 9, 25, 22, 39, 29),
            duration_minutes=37,
            fds_sid="2198620807",
            proto_type=1,
            report_version=2,
            report_time=1789998701,
            tz_in_15min=32,
        )
    )


@pytest.mark.asyncio
async def test_sync_workout_detail_branch(tmp_path):
    from mi_fitness_mcp.services.sync_service import SyncService

    db = Database(tmp_path / "mi_fitness.db")
    _seed_workout(db, "u-1", "wo-1")
    adapter = _DetailAdapter("u-1", {"wo-1": ([_sample("wo-1", i) for i in range(3)], [])})
    service = SyncService(adapter, db)

    result = await service.sync_data_type("workout_detail", "2026-09-25", "2026-09-25")
    assert result["status"] == "ok"
    assert result["added"] == 3
    assert adapter.requested == ["wo-1"]

    # 重跑同一 range：已有明细的运动默认跳过（不发起请求）。
    rerun = await service.sync_data_type("workout_detail", "2026-09-25", "2026-09-25")
    assert rerun["status"] == "ok"
    assert rerun["skipped"] == 1
    assert rerun["added"] == 0
    assert adapter.requested == ["wo-1"]  # 未新增请求

    # force_full 重拉：幂等 upsert，全部计为更新。
    refetch = await service.sync_data_type(
        "workout_detail", "2026-09-25", "2026-09-25", force_full=True
    )
    assert refetch["status"] == "ok"
    assert refetch["updated"] == 3
    assert refetch["added"] == 0
    assert adapter.requested == ["wo-1", "wo-1"]


@pytest.mark.asyncio
async def test_sync_workout_detail_skips_rows_without_fds_metadata(tmp_path):
    from mi_fitness_mcp.services.sync_service import SyncService

    db = Database(tmp_path / "mi_fitness.db")
    # 不带 FDS 元数据的旧记录：Phase 1 之前同步的行。
    db.insert_workout(
        Workout(
            id="w-old",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id="u-1",
            workout_id="wo-old",
            activity_type="running",
            start_at=datetime(2026, 9, 17, 22, 20, 28),
            end_at=datetime(2026, 9, 17, 22, 39, 28),
            duration_minutes=19,
        )
    )
    adapter = _DetailAdapter("u-1", {})
    service = SyncService(adapter, db)

    result = await service.sync_data_type("workout_detail", "2026-09-17", "2026-09-17")
    assert result["status"] == "ok"
    assert result["skipped"] == 1
    assert result["added"] == 0
    assert adapter.requested == []


# --- 端到端：真实签名/加密传输，respx 拦截全部 HTTP ---

USER = "123456"
BASE = "https://hlth.io.mi.com"
FDS_PATH = "/healthapp/service/gen_download_url"
FDS_SIGN_PATH = "/service/gen_download_url"
CDN_PATH = "/synthetic-fds/object.bin"


def _sport_blob(version=2, proto_type=1, report_time=1789998701, segment_start=None):
    segment_start = report_time if segment_start is None else segment_start
    data_valid = bytes((0xCC, 0xCC))  # calories/hr/integer_km/distance 全部 exist+high
    blob = struct.pack("<IBBB", report_time, 32, version, proto_type) + b"\x00" + data_valid
    body = b"\x00" * 4 + struct.pack("<I", 2) + struct.pack("<I", segment_start) + b"\x00"
    body += bytes(((5 << 4) | 3, 150, 0x80 | 1, 200))
    body += bytes(((6 << 4) | 0, 151, 0x00, 201))
    return blob + body


def _gps_blob(version=1, report_time=1789998701):
    data_valid = bytes((0b11100000,))
    blob = struct.pack("<IBBB", report_time, 32, version, 1) + b"\x00" + data_valid
    blob += struct.pack("<Iff", 1789998703, 121.4737, 31.2304)
    return blob


def _workout_row(**overrides):
    values = {
        "workout_id": "2198620807_outdoor_running_1789998701",
        "fds_sid": "2198620807",
        "proto_type": 1,
        "report_version": 2,
        "report_time": 1789998701,
        "tz_in_15min": 32,
        "start_at": "2026-09-21T21:51:41+08:00",
        "timezone": "GMT+08:00",
    }
    values.update(overrides)
    return values


async def _run_fetch_detail(workout):
    from urllib.parse import parse_qs

    import httpx
    import respx

    from mi_fitness_mcp.adapters import mi_fitness_cloud as cloud

    adapter = cloud.MiFitnessCloudAdapter(USER, "synthetic-unused-token", region="cn")
    adapter._ssecurity = b"synthetic-session-key"
    adapter._cookies = "serviceToken=synthetic-cookie"
    adapter._connected = True
    adapter.request_retries = 1
    observed: dict = {}

    def fds_reply(request):
        form = parse_qs(request.content.decode("utf-8"))
        signed = cloud._gen_signed_nonce(adapter._ssecurity, base64.b64decode(form["_nonce"][0]))
        plaintext_data = cloud._rc4_crypt(signed, base64.b64decode(form["data"][0]))
        # rc4_hash__ 传输时被 RC4 加密，解密后应等于对明文 data 按
        # 剥离 healthapp/ 前缀路径计算的签名。
        expected_hash = cloud._gen_signature(
            "POST", FDS_SIGN_PATH, {"data": plaintext_data.decode()}, signed
        )
        transmitted_hash = cloud._rc4_crypt(
            signed, base64.b64decode(form["rc4_hash__"][0])
        ).decode()
        assert transmitted_hash == expected_hash
        payload = json.loads(plaintext_data)
        observed["payload"] = payload
        key = _fds_key()
        result = {}
        for item in payload["items"]:
            suffix = item["suffix"]
            file_byte = base64.urlsafe_b64decode(suffix.split("_")[0] + "==")[5]
            file_type = file_byte & 0x03
            blob = _sport_blob() if file_type == 0 else _gps_blob()
            result[f"{suffix}_{item['timestamp']}"] = {
                "url": BASE + CDN_PATH,
                "obj_key": _b64url(key),
                "method": "GET",
            }
            # 每个文件类型的密文分别缓存，供 CDN mock 按需区分。
            observed.setdefault("blobs", []).append(_encrypt_blob(blob, key))
        ciphertext = cloud._rc4_crypt(
            signed, json.dumps({"code": 0, "result": result}).encode("utf-8")
        )
        return httpx.Response(200, text=base64.b64encode(ciphertext).decode("ascii"))

    with respx.mock(assert_all_called=False) as router:
        router.post(BASE + FDS_PATH).mock(side_effect=fds_reply)
        router.get(BASE + CDN_PATH).mock(
            side_effect=lambda request: httpx.Response(200, text=observed["blobs"].pop(0))
        )
        async with httpx.AsyncClient(trust_env=False) as client:
            adapter._client = client
            samples, gps_points = await adapter.fetch_workout_detail(workout)
    return samples, gps_points, observed


@pytest.mark.asyncio
async def test_fetch_workout_detail_end_to_end():

    workout = _workout_row()
    samples, gps_points, observed = await _run_fetch_detail(workout)

    # 请求体：did + 两个文件类型的 items。
    payload = observed["payload"]
    assert payload["did"] == "2198620807"
    assert len(payload["items"]) == 2
    assert all(item["timestamp"] == 1789998701 for item in payload["items"])

    # 秒级样本：2 条，时间从报告级 time 的段起点开始。
    assert len(samples) == 2
    assert samples[0].heart_rate_bpm == 150
    assert samples[0].offset_seconds == 0
    assert samples[1].heart_rate_bpm == 151
    assert samples[1].offset_seconds == 1
    assert samples[0].workout_id == workout["workout_id"]
    assert samples[0].timestamp.utcoffset() is not None

    # GPS：1 个点。
    assert len(gps_points) == 1
    assert gps_points[0].longitude == pytest.approx(121.4737, abs=1e-4)
    assert gps_points[0].latitude == pytest.approx(31.2304, abs=1e-4)
    assert gps_points[0].offset_seconds == 2


@pytest.mark.asyncio
async def test_fetch_workout_detail_skips_without_metadata():
    adapter = MiFitnessCloudAdapter(user_id="u", pass_token="t")
    samples, gps_points = await adapter.fetch_workout_detail({"workout_id": "wo-1"})
    assert samples == [] and gps_points == []
    samples, gps_points = await adapter.fetch_workout_detail(_workout_row(report_version=0))
    assert samples == [] and gps_points == []


def test_sport_record_proto22_step_config_roundtrip():
    """户外计步类（proto 22，本机跑步实际上报类型）：v5 含步频/配速通道。"""
    version = 5
    proto_type = 22
    report_time = 1789998701
    # v5 活跃通道（按位置）：calories/hr/integer_km/distance/stride/
    # landing_impact/touchdown_ratio/cadence/pace，共 9 nibble，全部 exist+high。
    data_valid = bytes((0xCC, 0xCC, 0xCC, 0xCC, 0xC0))
    blob = struct.pack("<IBBB", report_time, 32, version, proto_type) + b"\x00" + data_valid
    body = b"\x00" * 4  # pause_init
    body += struct.pack("<I", 2)  # record_count
    body += struct.pack("<I", report_time)  # segment start
    body += b"\x00" * 1  # IT 摘要: 41 (v1, 1B)
    body += b"\x00" * 4  # IT 摘要: 43 (v3, 4B)
    for cadence in (168, 172):
        rec = bytes(((5 << 4) | 3, 150, 0x80 | 1, 200, 105))
        rec += struct.pack("<I", (42 << 26) | 0x3FF)  # landing impact
        rec += bytes((80, cadence))
        rec += struct.pack("<H", 570)  # pace 9'30"
        body += rec

    blob += body

    segments = parse_sport_record(blob, proto_type)
    assert len(segments) == 1
    seg_start, samples = segments[0]
    assert seg_start == report_time
    assert len(samples) == 2
    assert samples[0][TYPE_HR] == 150
    assert samples[0][TYPE_CADENCE] == 168
    assert samples[0][TYPE_PACE] == 570
    assert samples[1][TYPE_CADENCE] == 172
    # 海拔通道 v9 才引入：v5 blob 中不存在。
    assert TYPE_HEIGHT_VALUE not in samples[0]


def test_sport_record_proto22_v9_data_valid_length():
    """v9 引入海拔与 2B integer_km 通道；dataValid 长度 7 字节。

    通道表 15 个位置需要 8 字节 validity，上游表只给 7 —— 与参考实现
    行为一致：当前会抛 FdsParseError 并由调用方记录后跳过。此测试固定
    该行为，真实设备 v9 blob 如可用再调整表值。
    """
    version = 9
    blob = struct.pack("<IBBB", 1789998701, 32, version, 22) + b"\x00" + bytes(7)
    with pytest.raises(FdsParseError):
        parse_sport_record(blob, 22)


def test_detail_samples_table_migration_adds_proto22_columns(tmp_path):
    """早期 Phase 2 建的样本表（无步频/配速/速度/海拔列）自动补列。"""
    import sqlite3

    from mi_fitness_mcp.storage import Database

    db_path = tmp_path / "old_detail.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE workout_detail_samples (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_record_id TEXT,
                user_id TEXT NOT NULL,
                device_id TEXT,
                timezone TEXT DEFAULT 'UTC',
                collected_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                workout_id TEXT NOT NULL,
                offset_seconds INTEGER NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                heart_rate_bpm INTEGER,
                calories_kcal REAL,
                distance_m REAL,
                steps INTEGER,
                UNIQUE(user_id, workout_id, offset_seconds)
            )
        """)
        conn.commit()

    db = Database(db_path)
    assert db.insert_workout_detail_samples([_sample("wo-1", 0)]) == (1, 0)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT cadence, pace_sec_per_km, speed_mps, altitude_m"
            " FROM workout_detail_samples WHERE workout_id = 'wo-1'"
        ).fetchone()
    assert row == (None, None, None, None)

    # 带新通道的样本正常写入。
    sample = _sample("wo-1", 1)
    sample.cadence = 168
    sample.pace_sec_per_km = 570.0
    db.insert_workout_detail_samples([sample])
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT cadence, pace_sec_per_km FROM workout_detail_samples"
            " WHERE workout_id = 'wo-1' AND offset_seconds = 1"
        ).fetchone()
    assert row == (168, 570.0)


@pytest.mark.asyncio
async def test_default_sync_includes_detail_and_skips_covered(tmp_path):
    """adapter 支持列表含 workout_detail：默认同步纳入，且只拉缺明细的运动。"""
    from mi_fitness_mcp.services.sync_service import SyncService

    db = Database(tmp_path / "mi_fitness.db")
    _seed_workout(db, "u-1", "wo-1")
    adapter = _DetailAdapter("u-1", {"wo-1": ([_sample("wo-1", i) for i in range(2)], [])})
    service = SyncService(adapter, db)

    # 模拟默认全量同步：data_types 来自 adapter.get_available_data_types。
    # （_DetailAdapter 没有该方法，补一个与云端适配器一致的序列。）
    adapter.get_available_data_types = lambda: [
        "workouts",
        "workout_detail",
    ]
    for data_type in adapter.get_available_data_types():
        await service.sync_data_type(data_type, "2026-09-25", "2026-09-25")
    assert adapter.requested == ["wo-1"]  # workouts 同步后 detail 拿到元数据

    # 二次默认同步：明细已覆盖，不再请求。
    adapter.requested.clear()
    await service.sync_data_type("workout_detail", "2026-09-25", "2026-09-25")
    assert adapter.requested == []


@pytest.mark.asyncio
async def test_default_detail_sync_scans_full_cache_without_watermark(tmp_path):
    """默认明细同步不走日期水位：早于任何水位的运动也会被回填。"""
    from mi_fitness_mcp.services.sync_service import SyncService

    db = Database(tmp_path / "mi_fitness.db")
    _seed_workout(db, "u-1", "wo-old")  # start 2026-09-25
    # 模拟旧的 workout_detail 水位把范围卡在更晚日期。
    db.update_sync_state("workout_detail", datetime(2026, 9, 25))
    adapter = _DetailAdapter("u-1", {"wo-old": ([_sample("wo-old", 0)], [])})
    service = SyncService(adapter, db)

    result = await service.sync_data_type("workout_detail")  # 无日期参数
    assert result["status"] == "ok"
    assert result["added"] == 1
    assert adapter.requested == ["wo-old"]


def test_negative_offset_sample_is_accepted(tmp_path):
    """blob 时间戳早于云端 start_at（GPS 提前锁定）→ 负 offset 必须可入库。

    旧行为：pydantic ge=0 抛 ValidationError → 整场运动明细被丢弃且每次
    同步都重试（review 发现 #1）。
    """
    sample = WorkoutSample(
        id="mi_fitness_sample_wo-1_-2",
        provider="mi_fitness",
        source_type="cloud_session",
        user_id="u-1",
        workout_id="wo-1",
        offset_seconds=-2,
        timestamp=datetime(2026, 9, 25, 14, 1, 29, tzinfo=UTC),
        heart_rate_bpm=120,
    )
    assert sample.offset_seconds == -2
    db = Database(tmp_path / "mi_fitness.db")
    added, _ = db.insert_workout_detail_samples([sample])
    assert added == 1
    import sqlite3

    with sqlite3.connect(db.db_path) as conn:
        row = conn.execute(
            "SELECT offset_seconds FROM workout_detail_samples WHERE workout_id='wo-1'"
        ).fetchone()
    assert row == (-2,)


@pytest.mark.asyncio
async def test_sync_workout_detail_reports_partial_when_all_fail(tmp_path):
    """全部尝试失败时报 partial（而非 ok），与分块路径语义对齐（review #4）。"""
    from mi_fitness_mcp.services.sync_service import SyncService

    class FailingAdapter(_DetailAdapter):
        async def fetch_workout_detail(self, workout):
            raise RuntimeError("synthetic total failure")

    db = Database(tmp_path / "mi_fitness.db")
    _seed_workout(db, "u-1", "wo-1")
    service = SyncService(FailingAdapter("u-1", {}), db)
    result = await service.sync_data_type("workout_detail", "2026-09-25", "2026-09-25")
    assert result["status"] == "partial"
    assert result["added"] == 0 and result["updated"] == 0
    assert result["bad_records"][0]["record_id"] == "wo-1"


@pytest.mark.parametrize("validity", [b"\xcc\xcc", b"\x00\x00"])
def test_sport_record_rejects_impossible_sample_count(validity):
    header = struct.pack("<IBBB", 1789998701, 32, 2, 1) + b"\x00" + validity
    body = b"\x00" * 4 + struct.pack("<II", 0xffffffff, 1789998701) + b"\x00"
    with pytest.raises(FdsParseError, match="sample count"):
        parse_sport_record(header + body, 1)


def test_sport_record_rejects_truncated_samples():
    with pytest.raises(FdsParseError, match="sample count"):
        parse_sport_record(_sport_blob()[:-1], 1)


@pytest.mark.asyncio
async def test_failed_gps_parse_leaves_workout_uncached_and_retries(tmp_path, monkeypatch):
    from mi_fitness_mcp.services.sync_service import SyncService

    db = Database(tmp_path / "mi_fitness.db")
    _seed_workout(db, "u-1", "wo-1")
    adapter = MiFitnessCloudAdapter("u-1", "synthetic-unused-token")
    adapter._connected = True
    requests = []

    async def request(base_url, api_path, payload, sign_path=None):
        requests.append(payload)
        return {
            f"{item['suffix']}_{item['timestamp']}": {
                "url": f"https://synthetic.invalid/{'sport' if i == 0 else 'gps'}",
                "obj_key": "synthetic-unused-key",
            }
            for i, item in enumerate(payload["items"])
        }

    async def download(url, obj_key):
        return _sport_blob() if url.endswith("/sport") else b"bad"

    monkeypatch.setattr(adapter, "is_connected", lambda: True)
    monkeypatch.setattr(adapter, "_request", request)
    monkeypatch.setattr(adapter, "_download_fds_blob", download)
    service = SyncService(adapter, db)
    for _ in range(2):
        result = await service.sync_data_type("workout_detail")
        assert result["status"] == "partial"
        assert result["added"] == 0
        assert result["bad_records"][0]["error_type"] == "FdsParseError"
        assert db.workout_detail_counts("u-1", "wo-1") == (0, 0)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_workout_detail_mixed_success_reports_partial(tmp_path):
    from mi_fitness_mcp.services.sync_service import SyncService

    class MixedAdapter(_DetailAdapter):
        async def fetch_workout_detail(self, workout):
            if workout["workout_id"] == "wo-bad":
                raise RuntimeError("synthetic detail failure")
            return [_sample(workout["workout_id"], 0)], []

    db = Database(tmp_path / "mi_fitness.db")
    for workout_id in ["wo-good", "wo-bad"]:
        _seed_workout(db, "u-1", workout_id)
    result = await SyncService(MixedAdapter("u-1", {}), db).sync_data_type("workout_detail")
    assert result["status"] == "partial"
    assert result["added"] == 1
    assert result["bad_records"][0]["record_id"] == "wo-bad"
