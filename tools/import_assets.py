"""命令行导入第三方素材包：python tools/import_assets.py <素材包目录或zip> [assets.db 路径]

v3.4：人物登记改为写入配置库 config.db（不再改写 config.yaml）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asset_importer import import_assets  # noqa: E402
from config_store import ConfigStore  # noqa: E402


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 1
    src = argv[0]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = argv[1] if len(argv) > 1 else os.path.join(root, 'assets.db')
    config_store = ConfigStore(root)

    report = import_assets(src, db_path, config_store)
    print(f"导入完成 -> {db_path}")
    print(f"  帧: {report['frames']}  语音: {report['voices']}  BGM: {report['bgms']}")
    if report['new_roles']:
        print(f"  新角色: {', '.join(report['new_roles'])}（已登记到 "
              f"{os.path.basename(config_store.db_path)}）")
    if report['areas']:
        print(f"  地区: {', '.join(report['areas'])}")
    config_store.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
