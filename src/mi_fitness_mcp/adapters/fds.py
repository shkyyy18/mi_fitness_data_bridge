"""FDS (File Data Service) 明细数据协议实现。

小米运动健康把每次运动的秒级样本（心率等）与 GPS 轨迹存为独立的 AES
加密二进制 blob，通过 `healthapp/service/gen_download_url` 获取预签名
下载地址。本模块实现：

- FDS 数据 ID / suffix 构造（ FitnessDataId 的 6 字节 FDS key 变体）
- blob 下载体（base64url 密文）的 AES-CBC 解密
- fileType=0（秒级样本，四维格式）与 fileType=2（GPS 轨迹）的二进制解析

协议来源：APK v3.52.0i 反编译资料（kevinkwee/Mi-Fitness-Sync，MIT，
见 THIRD_PARTY_NOTICES.md）与 docs/workout-detail-feasibility.md。
私有接口可能随 App 版本变化；已知的坑（必须用 proto_type 与报告级 time、
version<=0 无数据）在调用方 mi_fitness_cloud.fetch_workout_detail 处理。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import struct
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 明细文件类型（FitnessDataId.fileType）
FDS_FILE_TYPE_SPORT_RECORD = 0
FDS_FILE_TYPE_GPS_TRACK = 2

AES_IV = b"1234567887654321"
# 解密后 blob 的头部长度：timestamp(4) + tzIn15Min(1) + version(1) + sportType(1)
FDS_HEADER_META_LEN = 7


class FdsParseError(ValueError):
    """Raised when a decrypted FDS blob does not match the expected layout."""


def b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded)


def build_fds_suffix(
    *, sid: str, timestamp: int, tz_in_15min: int, proto_type: int, file_type: int
) -> str:
    """构造 FDS 请求的 suffix：`<b64url(6B)>_<b64url(sha1(sid))>`。

    6 字节 = [timestamp(4 LE)] [tzIn15Min(1)] [genDataTypeByte(1)]，
    genDataTypeByte = (1<<7) | (proto_type<<2) | file_type。
    """
    data_type_byte = ((1 << 7) + (proto_type << 2) + file_type) & 0xFF
    key = struct.pack("<I", int(timestamp)) + bytes((tz_in_15min & 0xFF, data_type_byte))
    sid_hash = hashlib.sha1(sid.encode("utf-8")).digest()
    return f"{b64url_no_pad(key)}_{b64url_no_pad(sid_hash)}"


def fds_server_key(suffix: str, timestamp: int) -> str:
    """gen_download_url 响应 map 的键：`<suffix>_<timestamp>`。"""
    return f"{suffix}_{int(timestamp)}"


def decrypt_fds_blob(ciphertext: str | bytes, obj_key: str) -> bytes:
    """AES-CBC(PKCS7) 解密 FDS blob：key 来自响应 obj_key（base64url，16B）。"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = b64url_decode(obj_key)
    if len(key) != 16:
        raise FdsParseError(f"FDS obj_key must decode to 16 bytes, got {len(key)}")
    raw = ciphertext.encode() if isinstance(ciphertext, str) else ciphertext
    # 下载体可能是 JSON 字符串包一层引号（reference 行为：json() 失败退回原文）。
    if raw[:1] == b'"' and raw[-1:] == b'"':
        raw = raw[1:-1]
    data = b64url_decode(raw.decode("utf-8", errors="strict").strip())
    if not data or len(data) % 16 != 0:
        raise FdsParseError(f"FDS ciphertext length invalid: {len(data)}")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(AES_IV)).decryptor()
    padded = decryptor.update(data) + decryptor.finalize()
    pad_len = padded[-1]
    if not 1 <= pad_len <= 16 or padded[-pad_len:] != bytes((pad_len,)) * pad_len:
        raise FdsParseError("FDS blob PKCS7 padding invalid")
    return padded[:-pad_len]


@dataclass(frozen=True, slots=True)
class FdsHeader:
    timestamp: int
    tz_in_15min: int
    version: int
    sport_type: int
    data_valid: bytes
    body: bytes


def parse_fds_header(decrypted: bytes, data_valid_len: int) -> FdsHeader:
    header_len = FDS_HEADER_META_LEN + 1 + data_valid_len
    if len(decrypted) < header_len:
        raise FdsParseError(
            f"Decrypted blob too short ({len(decrypted)} bytes) for header ({header_len} bytes)"
        )
    timestamp = struct.unpack_from("<I", decrypted, 0)[0]
    tz_in_15min = decrypted[4]
    version = decrypted[5]
    sport_type = decrypted[6]
    data_valid = decrypted[8 : 8 + data_valid_len]
    return FdsHeader(
        timestamp=timestamp,
        tz_in_15min=tz_in_15min,
        version=version,
        sport_type=sport_type,
        data_valid=data_valid,
        body=decrypted[header_len:],
    )


def read_uint(buf: memoryview, offset: int, size: int) -> tuple[int, int]:
    if size == 1:
        return buf[offset], offset + 1
    if size == 2:
        return struct.unpack_from("<H", buf, offset)[0], offset + 2
    if size == 4:
        return struct.unpack_from("<I", buf, offset)[0], offset + 4
    raise FdsParseError(f"Unsupported read size: {size}")


def header_version(decrypted: bytes) -> int:
    """blob 头中的格式版本字节（offset 5）。"""
    if len(decrypted) < FDS_HEADER_META_LEN + 1:
        raise FdsParseError("Decrypted blob too short to read version byte")
    return decrypted[5]


@dataclass(frozen=True, slots=True)
class FourDimenType:
    type_id: int
    byte_size: int
    support_version: int
    high_start_bit: int | None = None
    high_bit_count: int | None = None


@dataclass(frozen=True, slots=True)
class FourDimenValid:
    exist: bool
    high: bool
    middle: bool
    low: bool


@dataclass(frozen=True, slots=True)
class OneDimenType:
    """一维格式通道定义（GPS 轨迹与四维配置的 IT 摘要/暂停段共用）。"""

    type_id: int
    byte_count: int
    support_version: int


@dataclass(frozen=True, slots=True)
class _RecordConfig:
    """一个 proto_type 家族的秒级记录解析配置。"""

    proto_types: frozenset[int]
    data_valid_len: dict[int, int]
    four_dimen_types: list[FourDimenType]
    it_summary_types: tuple[OneDimenType, ...] = ()
    pause_init_types: tuple[OneDimenType, ...] = ()


def parse_four_dimen_valid(
    data_types: list[FourDimenType], version: int, data_valid: bytes
) -> dict[int, FourDimenValid]:
    """data_valid 每 4 bit 对应一个通道：exist/high/middle/low。"""
    valid_map: dict[int, FourDimenValid] = {}
    nibble_index = 0
    for data_type in data_types:
        if data_type.support_version > version:
            valid_map[data_type.type_id] = FourDimenValid(False, False, False, False)
            continue
        byte_idx = nibble_index // 2
        if byte_idx >= len(data_valid):
            raise FdsParseError(f"dataValid too short: need byte {byte_idx}")
        nibble = (
            (data_valid[byte_idx] & 0xF0) >> 4
            if nibble_index % 2 == 0
            else data_valid[byte_idx] & 0x0F
        )
        valid_map[data_type.type_id] = FourDimenValid(
            exist=bool(nibble & 0x8),
            high=bool(nibble & 0x4),
            middle=bool(nibble & 0x2),
            low=bool(nibble & 0x1),
        )
        nibble_index += 1
    return valid_map


def extract_high_value(raw: int, data_type: FourDimenType) -> int:
    if data_type.high_start_bit is not None and data_type.high_bit_count is not None:
        return (raw >> data_type.high_start_bit) & ((1 << data_type.high_bit_count) - 1)
    return raw


# --- fileType=0 秒级样本（四维格式，配置驱动） ---

# 上游 TYPE_* 常量（HuaMi 通道 ID）
TYPE_CALORIES = 2
TYPE_PACE = 12
TYPE_HR = 5
TYPE_INTEGER_KM = 6
TYPE_DISTANCE = 9
TYPE_HEIGHT_VALUE = 87
TYPE_CADENCE = 49
TYPE_SPEED = 51
TYPE_RUNNING_POWER = 57

# 户外共用族（proto 1/2/4/5/15）：暂停初始化 4B 保留通道 + IT 摘要（v2 起 1B）。
OUTDOOR_CONFIG = _RecordConfig(
    proto_types=frozenset({1, 2, 4, 5, 15}),
    it_summary_types=(OneDimenType(41, 1, 2),),
    pause_init_types=(OneDimenType(0, 4, 1),),
    data_valid_len={1: 2, 2: 2},
    four_dimen_types=[
        # 卡路里：高 4 位为整数部分扩展
        FourDimenType(TYPE_CALORIES, 1, 1, high_start_bit=4, high_bit_count=4),
        FourDimenType(TYPE_HR, 1, 1),
        # 整数公里标记：最高位
        FourDimenType(TYPE_INTEGER_KM, 1, 1, high_start_bit=7, high_bit_count=1),
        FourDimenType(TYPE_DISTANCE, 1, 1),
    ],
)

# 户外计步类（proto 22，含 23 共用结构）：本机户外跑步上报为 22。
# 通道表与 dataValid 长度来自上游 OutdoorStepRecordParser / OutdoorNoStepRecordParser。
STEP_CONFIG = _RecordConfig(
    proto_types=frozenset({22, 23}),
    it_summary_types=(
        OneDimenType(41, 1, 1),
        OneDimenType(43, 4, 3),
        OneDimenType(78, 4, 7),
        OneDimenType(54, 4, 6),
        OneDimenType(55, 2, 6),
    ),
    pause_init_types=(OneDimenType(0, 4, 1),),
    data_valid_len={1: 2, 2: 3, 3: 3, 4: 3, 5: 5, 6: 6, 7: 6, 8: 7, 9: 7},
    four_dimen_types=[
        FourDimenType(TYPE_CALORIES, 1, 1, high_start_bit=4, high_bit_count=4),
        FourDimenType(TYPE_HR, 1, 1),
        FourDimenType(TYPE_HEIGHT_VALUE, 4, 9),
        FourDimenType(TYPE_INTEGER_KM, 2, 9, high_start_bit=15, high_bit_count=1),
        FourDimenType(TYPE_INTEGER_KM, 1, 1, high_start_bit=7, high_bit_count=1),
        FourDimenType(TYPE_DISTANCE, 1, 1),
        FourDimenType(40, 1, 2),  # 步幅
        FourDimenType(44, 4, 4, high_start_bit=26, high_bit_count=6),  # 着地冲击
        FourDimenType(48, 1, 5),  # 触地腾空比
        FourDimenType(TYPE_CADENCE, 1, 5),  # 步频
        FourDimenType(TYPE_PACE, 2, 5),
        FourDimenType(56, 2, 6),
        FourDimenType(TYPE_RUNNING_POWER, 2, 6),
        FourDimenType(79, 2, 8),
        FourDimenType(80, 2, 8),
    ],
)

# 通道表按位置解析；valid_map 以 type_id 为键，重复通道（INTEGER_KM 新旧
# 两种宽度并存）沿用上游语义：后出现的覆盖前者的有效性位。
SUPPORTED_RECORD_PROTO_TYPES = frozenset().union(
    OUTDOOR_CONFIG.proto_types, STEP_CONFIG.proto_types
)


def parse_sport_record(decrypted: bytes, proto_type: int) -> list[tuple[int, list[dict[int, int]]]]:
    """fileType=0 入口：按 proto_type 选择配置，解析秒级样本。

    返回 [(段绝对起始秒, [{TYPE_*: value}, ...]), ...]；段内 index i 的
    样本时间为 segment_start + i。blob 可能含多段（对应运动中的暂停）。
    version<1 或配置未收录的 proto_type 返回空列表。
    """
    config = next(
        (c for c in (OUTDOOR_CONFIG, STEP_CONFIG) if proto_type in c.proto_types), None
    )
    if config is None:
        logger.info("Skipping FDS sport record: proto_type=%s not supported", proto_type)
        return []
    if header_version(decrypted) < 1:
        return []
    version = header_version(decrypted)
    data_valid_len = config.data_valid_len.get(version)
    if data_valid_len is None:
        logger.info(
            "Skipping FDS sport record: proto_type=%s version=%s has no dataValid length",
            proto_type,
            version,
        )
        return []
    header = parse_fds_header(decrypted, data_valid_len)
    return _parse_record_body(header, config)


def _parse_record_body(
    header: FdsHeader, config: _RecordConfig
) -> list[tuple[int, list[dict[int, int]]]]:
    version = header.version
    valid_map = parse_four_dimen_valid(config.four_dimen_types, version, header.data_valid)
    it_bytes = sum(
        t.byte_count for t in config.it_summary_types if t.support_version <= version
    )
    init_bytes = sum(
        t.byte_count for t in config.pause_init_types if t.support_version <= version
    )
    min_segment = init_bytes + 8 + it_bytes
    buf = memoryview(header.body)
    segments: list[tuple[int, list[dict[int, int]]]] = []
    offset = 0
    while offset + min_segment <= len(buf):
        offset += init_bytes
        record_count, offset = read_uint(buf, offset, 4)
        start_time, offset = read_uint(buf, offset, 4)
        offset += it_bytes  # IT 摘要段对样本值无用，跳过
        record_bytes = sum(
            data_type.byte_size
            for data_type in config.four_dimen_types
            if data_type.support_version <= version
            and valid_map[data_type.type_id].exist
        )
        # Reject impossible counts before looping: a truncated/no-channel blob
        # must not allocate millions of empty samples or become cached as valid.
        if record_count and (
            not record_bytes or record_count > (len(buf) - offset) // record_bytes
        ):
            raise FdsParseError("FDS sample count exceeds available record bytes")
        records: list[dict[int, int]] = []
        for _ in range(record_count):
            record: dict[int, int] = {}
            for data_type in config.four_dimen_types:
                if data_type.support_version > version:
                    continue
                valid = valid_map.get(data_type.type_id)
                if valid is None or not valid.exist:
                    continue
                if offset + data_type.byte_size > len(buf):
                    break
                value, offset = read_uint(buf, offset, data_type.byte_size)
                if valid.high:
                    record[data_type.type_id] = extract_high_value(value, data_type)
            records.append(record)
        segments.append((start_time, records))
    return segments


# --- fileType=2 GPS 轨迹 ---

GPS_TYPE_TIME = 0
GPS_TYPE_LONGITUDE = 1
GPS_TYPE_LATITUDE = 2
GPS_TYPE_ACCURACY = 3
GPS_TYPE_SPEED = 4
GPS_TYPE_GPS_SOURCE = 5
GPS_TYPE_ALTITUDE = 6
GPS_TYPE_HDOP = 7

_GPS_FLOAT_TYPES = frozenset(
    {GPS_TYPE_LONGITUDE, GPS_TYPE_LATITUDE, GPS_TYPE_ACCURACY, GPS_TYPE_ALTITUDE, GPS_TYPE_HDOP}
)


GPS_DATA_TYPES = [
    OneDimenType(GPS_TYPE_TIME, 4, 1),
    OneDimenType(GPS_TYPE_LONGITUDE, 4, 1),
    OneDimenType(GPS_TYPE_LATITUDE, 4, 1),
    OneDimenType(GPS_TYPE_ACCURACY, 4, 2),
    OneDimenType(GPS_TYPE_SPEED, 2, 2),
    OneDimenType(GPS_TYPE_GPS_SOURCE, 0, 2),
    OneDimenType(GPS_TYPE_ALTITUDE, 4, 3),
    OneDimenType(GPS_TYPE_HDOP, 4, 3),
]

# GPS dataValid 长度（上游 SportGpsParser）：v1–v4 各 1 字节。
GPS_DATA_VALID_LEN = {1: 1, 2: 1, 3: 1, 4: 1}


def parse_one_dimen_valid(
    data_types: list[OneDimenType], version: int, data_valid: bytes
) -> dict[int, bool]:
    valid_map: dict[int, bool] = {}
    bit_index = 0
    for data_type in data_types:
        if data_type.type_id < 0:
            continue
        if data_type.support_version > version:
            valid_map[data_type.type_id] = False
            continue
        if not data_valid:
            valid_map[data_type.type_id] = True
            continue
        byte_idx = bit_index // 8
        bit_idx = bit_index % 8
        if byte_idx >= len(data_valid):
            raise FdsParseError(f"dataValid too short: need byte {byte_idx}")
        valid_map[data_type.type_id] = bool(data_valid[byte_idx] & (1 << (7 - bit_idx)))
        bit_index += 1
    return valid_map


@dataclass(frozen=True, slots=True)
class GpsSample:
    timestamp: int
    latitude: float
    longitude: float
    accuracy: float | None = None
    speed_mps: float | None = None
    gps_source: int | None = None
    altitude_m: float | None = None
    hdop: float | None = None


def _gps_min_record_bytes(version: int) -> int:
    return sum(
        data_type.byte_count
        for data_type in GPS_DATA_TYPES
        if data_type.support_version <= version and data_type.byte_count > 0
    )


def _read_gps_field(
    buf: memoryview, offset: int, data_type: OneDimenType
) -> tuple[int | float, int]:
    if data_type.type_id in _GPS_FLOAT_TYPES and data_type.byte_count == 4:
        return struct.unpack_from("<f", buf, offset)[0], offset + 4
    return read_uint(buf, offset, data_type.byte_count)


def parse_gps_record(decrypted: bytes) -> list[GpsSample]:
    """fileType=2 入口：解析 GPS 轨迹点。"""
    version = header_version(decrypted)
    data_valid_len = GPS_DATA_VALID_LEN.get(version)
    if data_valid_len is None:
        logger.info("Skipping FDS GPS record: unsupported version=%s", version)
        return []
    header = parse_fds_header(decrypted, data_valid_len)
    valid_map = parse_one_dimen_valid(GPS_DATA_TYPES, version, header.data_valid)
    if not (
        valid_map.get(GPS_TYPE_TIME)
        and valid_map.get(GPS_TYPE_LONGITUDE)
        and valid_map.get(GPS_TYPE_LATITUDE)
    ):
        raise FdsParseError("GPS validity missing required time/lon/lat fields")

    buf = memoryview(header.body)
    min_bytes = _gps_min_record_bytes(version)
    offset = 0
    record_count = len(buf) // min_bytes if min_bytes else 0
    if version >= 4 and len(buf) >= 4:
        record_count, offset = read_uint(buf, 0, 4)

    samples: list[GpsSample] = []
    for _ in range(record_count):
        if offset + min_bytes > len(buf):
            break
        raw: dict[int, int | float] = {}
        for data_type in GPS_DATA_TYPES:
            if data_type.support_version > version or data_type.byte_count == 0:
                continue
            if offset + data_type.byte_count > len(buf):
                return samples
            value, offset = _read_gps_field(buf, offset, data_type)
            if valid_map.get(data_type.type_id, False):
                raw[data_type.type_id] = value
        timestamp_val = raw.get(GPS_TYPE_TIME)
        lon_val = raw.get(GPS_TYPE_LONGITUDE)
        lat_val = raw.get(GPS_TYPE_LATITUDE)
        if timestamp_val is None or lon_val is None or lat_val is None:
            continue
        sample = GpsSample(
            timestamp=int(timestamp_val),
            longitude=float(lon_val),
            latitude=float(lat_val),
        )
        if GPS_TYPE_ACCURACY in raw:
            sample = _replace(sample, accuracy=float(raw[GPS_TYPE_ACCURACY]))
        if GPS_TYPE_SPEED in raw:
            int_speed = int(raw[GPS_TYPE_SPEED])
            # 高 12 位为 0.1 m/s 步进速度，低 4 位为 GPS 来源。
            sample = _replace(sample, speed_mps=((int_speed & 0xFFF0) >> 4) / 10.0)
            if valid_map.get(GPS_TYPE_GPS_SOURCE, False):
                sample = _replace(sample, gps_source=int_speed & 0x0F)
        if GPS_TYPE_ALTITUDE in raw:
            sample = _replace(sample, altitude_m=float(raw[GPS_TYPE_ALTITUDE]))
        if GPS_TYPE_HDOP in raw:
            sample = _replace(sample, hdop=float(raw[GPS_TYPE_HDOP]))
        samples.append(sample)
    return samples


def _replace(sample: GpsSample, **changes: object) -> GpsSample:
    values = {
        "timestamp": sample.timestamp,
        "latitude": sample.latitude,
        "longitude": sample.longitude,
        "accuracy": sample.accuracy,
        "speed_mps": sample.speed_mps,
        "gps_source": sample.gps_source,
        "altitude_m": sample.altitude_m,
        "hdop": sample.hdop,
    }
    values.update(changes)
    return GpsSample(**values)
