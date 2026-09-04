"""Command-line interface for Mi Fitness Data Bridge."""

import argparse
import asyncio
import getpass
import sys

from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
from mi_fitness_mcp.auth import (
    keyring_backend_warning,
    load_mi_fitness_token,
    mask_account_id,
    save_mi_fitness_token,
)
from mi_fitness_mcp.config import (
    Config,
    get_config_path,
    load_config,
    resolve_database_path,
    save_config,
)
from mi_fitness_mcp.export import DATASETS, export_database
from mi_fitness_mcp.server import main as server_main
from mi_fitness_mcp.services.sync_service import SyncService
from mi_fitness_mcp.storage import Database

PROGRAM_NAME = "mi-fitness-bridge"


def _apply_database_override(config: Config, args) -> Config:
    """CLI --db beats MI_FITNESS_DB_PATH, which beats the configured/default path."""
    override = resolve_database_path(getattr(args, "db", None))
    if override is not None:
        config.database_path = override
    return config


def _warn_on_weak_keyring() -> None:
    warning = keyring_backend_warning()
    if warning:
        print(f"⚠️  警告： {warning}")
        print()



def _create_cloud_adapter(
    user_id: str, pass_token: str, config: Config
) -> MiFitnessCloudAdapter:
    adapter = MiFitnessCloudAdapter(
        user_id=user_id,
        pass_token=pass_token,
        region=config.region,
    )
    adapter.http_timeout = config.http_timeout_seconds
    adapter.request_retries = config.request_retries
    adapter.max_pages = config.max_pages
    return adapter


async def _check_adapter_health(
    adapter, timeout_seconds: float | None = None
) -> tuple[bool, list[str], str | None]:
    async def check() -> tuple[bool, list[str], str | None]:
        connected = await adapter.connect()
        region = getattr(adapter, "region", None)
        data_types = adapter.get_available_data_types() if connected else []
        return connected, data_types, region

    try:
        if timeout_seconds is None:
            return await check()
        return await asyncio.wait_for(check(), timeout=timeout_seconds)
    finally:
        if hasattr(adapter, "close"):
            await adapter.close()


def cmd_setup(args):
    # Credentials are only accepted interactively: CLI flags would leave the
    # passToken in shell history.
    _warn_on_weak_keyring()
    print(f"{PROGRAM_NAME} - 配置向导")
    print("=" * 50)
    print()
    user_id = input("Mi Fitness user_id： ").strip()
    pass_token = getpass.getpass("Mi Fitness passToken： ").strip()
    region = input("区域 [cn]： ").strip() or "cn"
    if not user_id or not pass_token:
        print("❌ 必须提供 user_id 和 passToken")
        sys.exit(1)
    save_mi_fitness_token(user_id, pass_token)
    config = Config(mode="mi_fitness_cloud", region=region)
    save_config(config)
    print("✅ Mi Fitness 配置已保存！")


def cmd_doctor(args):
    print(f"{PROGRAM_NAME} - 诊断")
    print("=" * 50)
    print()
    config_path = get_config_path()
    print(f"配置文件： {config_path}")

    if not config_path.exists():
        print("❌ 未找到配置文件")
        print(f"   请运行： {PROGRAM_NAME} setup")
        print("   user_id / passToken 的获取方法见 README「配置」一节的")
        print("   「如何获取 user_id 和 passToken」（README.en.md → Configure →")
        print("   “How to get user_id and passToken”）")
        sys.exit(1)

    healthy = True
    try:
        config = _apply_database_override(load_config(), args)
        print("✅ 配置已加载")
        _warn_on_weak_keyring()
        print(f"   模式： {config.mode}")
        if config.mode == "not_configured":
            print("❌ 服务尚未配置")
            print(f"   请运行： {PROGRAM_NAME} setup")
            healthy = False

        user_id, pass_token = load_mi_fitness_token()
        if user_id and pass_token:
            print("✅ 已找到 Mi Fitness 凭据")
            print(f"   User ID: {mask_account_id(user_id)}")
            print(f"   Region: {config.region}")
            adapter = _create_cloud_adapter(user_id, pass_token, config)
            connected, data_types, region = asyncio.run(
                _check_adapter_health(adapter, config.health_check_timeout_seconds)
            )
            print(f"   连接状态： {'✅' if connected else '❌'}")
            if connected:
                print(f"   识别到的区域： {region}")
                print(f"   数据类型： {', '.join(data_types)}")
            else:
                healthy = False
        else:
            print("❌ 未找到 Mi Fitness 凭据")
            print(f"   请运行： {PROGRAM_NAME} setup")
            healthy = False

        print()
        print(f"数据库： {config.database_path}")
        if resolve_database_path(getattr(args, "db", None)) is not None:
            # 非默认路径（--db 或 MI_FITNESS_DB_PATH）：Windows 上本工具不会为
            # 自定义位置设置 ACL，只提醒用户自行确认，不写 icacls。
            print("⚠️  警告： 正在使用非默认数据库路径（--db 或 MI_FITNESS_DB_PATH）")
            print("   Windows 下自定义路径不会自动收紧 ACL，请自行确认该数据库文件")
            print("   仅当前用户可读写（可用 icacls 检查）。")
        if config.database_path.exists():
            Database(config.database_path)
            print("✅ 数据库可用")
        else:
            print("ℹ️  数据库将在首次运行时创建")
    except Exception as e:
        print(f"❌ 加载配置失败： {e}")
        sys.exit(1)

    if not healthy:
        sys.exit(1)


async def cmd_sync_async(args):
    print(f"{PROGRAM_NAME} - 同步")
    print("=" * 50)
    print()

    try:
        config = _apply_database_override(load_config(), args)
    except Exception as e:
        print(f"❌ 加载配置失败： {e}")
        sys.exit(1)

    if config.mode == "not_configured":
        print("❌ 服务尚未配置")
        print(f"   请运行： {PROGRAM_NAME} setup")
        sys.exit(1)

    user_id, pass_token = load_mi_fitness_token()
    if not user_id or not pass_token:
        print("❌ 未找到 Mi Fitness 凭据")
        print(f"   请运行： {PROGRAM_NAME} setup")
        sys.exit(1)

    db = Database(config.database_path)
    adapter = _create_cloud_adapter(user_id, pass_token, config)
    try:
        if not await adapter.connect():
            print("❌ 无法连接到 Mi Fitness API")
            sys.exit(1)

        sync_service = SyncService(
            adapter,
            db,
            default_lookback_days=config.default_lookback_days,
            chunk_days=config.sync_chunk_days,
        )
        data_types = [args.type] if args.type else adapter.get_available_data_types()
        print(f"正在同步 {len(data_types)} 种数据类型...")
        print()
        had_failures = False
        for data_type in data_types:
            try:
                result = await asyncio.wait_for(
                    sync_service.sync_data_type(
                        data_type=data_type,
                        start_date=args.start_date,
                        end_date=args.end_date,
                    ),
                    timeout=config.sync_type_timeout_seconds,
                )
                status = result.get("status", "ok")
                if status == "ok":
                    print(
                        f"✅ {data_type}: 新增 {result['added']} 条，"
                        f"更新 {result['updated']} 条"
                    )
                else:
                    had_failures = True
                    marker = "\u26a0\ufe0f" if status == "partial" else "\u274c"
                    error = result.get("error", "no error detail")
                    print(
                        f"{marker} {data_type}: status={status}, "
                        f"added={result.get('added', 0)}, "
                        f"updated={result.get('updated', 0)}, error={error}"
                    )
            except Exception as e:
                had_failures = True
                print(f"❌ {data_type}: {e}")

        print()
        if had_failures:
            print("同步结束，但存在失败或部分成功的数据类型。")
            sys.exit(1)
        print("同步完成！")

    finally:
        await adapter.close()


def cmd_sync(args):
    asyncio.run(cmd_sync_async(args))


def cmd_export(args):
    try:
        config = _apply_database_override(load_config(), args)
        written = export_database(
            config.database_path,
            args.output,
            output_format=args.format,
            dataset=args.type,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    except Exception as exc:
        print(f"Export failed: {exc}")
        sys.exit(1)

    print("Export completed")
    for path in written:
        print(f"   {path}")
    empty_datasets = [name for name, count in written.row_counts.items() if count == 0]
    if empty_datasets:
        print(f"Warning: no rows found for selected dataset(s): {', '.join(empty_datasets)}")


def main():
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME, description="Local-first Mi Fitness health data bridge"
    )
    db_help = (
        "SQLite 数据库路径（优先级高于 MI_FITNESS_DB_PATH 环境变量和默认位置）"
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    serve_parser = subparsers.add_parser("serve", help="运行 MCP Server")
    serve_parser.add_argument("--db", help=db_help)

    setup_parser = subparsers.add_parser("setup", help="配置服务")
    setup_parser.add_argument("--mode", choices=["mi_fitness_cloud"], help="配置模式")
    setup_parser.add_argument("--region", help="云端区域")

    doctor_parser = subparsers.add_parser("doctor", help="检查配置并诊断问题")
    doctor_parser.add_argument("--db", help=db_help)

    sync_parser = subparsers.add_parser("sync", help="从数据源同步数据")
    sync_parser.add_argument(
        "--type",
        choices=[
            "daily_activity",
            "body_measurements",
            "heart_rate",
            "sleep",
            "workouts",
            "spo2",
            "stress",
            "abnormal_heart_beat",
        ],
        help="要同步的数据类型",
    )
    sync_parser.add_argument("--start-date", help="开始日期（YYYY-MM-DD）")
    sync_parser.add_argument("--end-date", help="结束日期（YYYY-MM-DD）")
    sync_parser.add_argument("--db", help=db_help)

    export_parser = subparsers.add_parser("export", help="Export normalized local data")
    export_parser.add_argument("--format", choices=["json", "csv"], default="json")
    export_parser.add_argument("--type", choices=list(DATASETS), help="Export one dataset only")
    export_parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    export_parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    export_parser.add_argument(
        "--output",
        default="exports",
        help="JSON file path or CSV output directory",
    )
    export_parser.add_argument("--db", help=db_help)

    args = parser.parse_args()
    if args.command == "serve" or args.command is None:
        asyncio.run(server_main(db_path=resolve_database_path(getattr(args, "db", None))))
    elif args.command == "setup":
        cmd_setup(args)
    elif args.command == "doctor":
        cmd_doctor(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "export":
        cmd_export(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
