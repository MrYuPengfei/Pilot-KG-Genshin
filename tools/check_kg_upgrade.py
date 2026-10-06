"""验证「升级安装不覆盖用户的 kg.db」。

做法：先在安装目录的 kg.db 里写一条用户自己的编辑，
再重装一次同版本（模拟升级），检查那条编辑是否还在。
"""
import os
import subprocess
import sqlite3
import sys

INSTALL_DIR = sys.argv[1]
KG = os.path.join(INSTALL_DIR, '_internal', 'kg.db')
INSTALLER = r'D:\VMwareShareFolder\project\Pilot\inno_build\原神桌面伙伴安装向导.exe'
MARK = '升级保留测试实体'


def count_nodes():
    conn = sqlite3.connect(KG)
    try:
        return conn.execute('SELECT COUNT(*) FROM kg_nodes').fetchone()[0]
    finally:
        conn.close()


def has_mark():
    conn = sqlite3.connect(KG)
    try:
        return conn.execute(
            'SELECT COUNT(*) FROM kg_nodes WHERE name=?', (MARK,)).fetchone()[0] > 0
    finally:
        conn.close()


def add_mark():
    sys.path.insert(0, r'D:\VMwareShareFolder\project\Pilot')
    from kg_store import KGStore
    store = KGStore(KG, auto_seed=False)
    store.add_node('npc', MARK, {'备注': '用户自己的编辑'})
    store.close()


print('安装目录:', INSTALL_DIR)
print('kg.db 路径存在:', os.path.isfile(KG))
print('重装前节点数:', count_nodes())

add_mark()
print('写入测试实体后:', count_nodes(), '| 测试实体存在:', has_mark())
assert has_mark(), '写入失败，无法验证升级保护'

print('\n--- 重新安装同一版本（模拟升级）---')
subprocess.run([INSTALLER, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                f'/DIR={INSTALL_DIR}'], check=True)
print('重装完成')

print('\n--- 结果 ---')
print('重装后节点数:', count_nodes())
print('测试实体仍在:', has_mark())
assert has_mark(), '❌ 升级把用户的 kg.db 覆盖了'
print('✅ 升级保留了用户的图谱编辑')
