# -*- coding: utf-8 -*-
"""米哈游「原神」资料站（ys_obc）爬虫 —— 图鉴素材 + 知识图谱。

数据源
------
站点早就不是老脚本里那个 ``content/info`` 单打独斗的路子 了，实测可用的是
**频道树列表**接口，一次请求就能拿到整个频道的条目元数据：

    GET https://api-static.mihoyo.com/common/blackboard/ys_obc/v1/home/content/list
        ?app_sn=ys_obc&channel_id=<频道>

``data.list[0].children`` 是频道树（30 个频道，含角色/武器/圣遗物/敌人/食物/
秘境/组织/书籍…），每个叶子频道的 ``list`` 给出该频道**全部**条目，每条含：

===============  ==========================================================
``content_id``   条目 id（用于抓详情页）
``title``        中文名
``icon``         图标 URL（**同时是图片素材本身**）
``ext``          JSON 字符串，内含 ``c_<频道>.filter.text``：
                 形如 ``["地区/蒙德","星级/五星","元素/岩","武器/单手剑"]``
                 的**结构化筛选条件**——这是知识图谱关系的主要来源
``summary``      一句话简介
===============  ==========================================================

条目详情页（``content/info``）只对 ``content_id < 500000`` 的老条目有效；
5.x 之后的新条目（约占角色的一半）由另一套 wiki 后端承载，``content/info``
一律返回 ``retcode=-2010 内容不存在``。因此本模块**以列表接口为主**，
详情页只作为可选的补充（``--detail``），不作为数据链路的必需环节。

版本区间（1.1 ~ 7.1）
--------------------
接口**不提供**结构化的版本字段。可用的版本线索只有三处，且都不可靠：

1. ``summary``/``title`` 里偶发的「X.Y版本」字样——只覆盖约 3% 条目；
2. 详情页 ``ctime``（条目创建时间）——与上线版本**大体**吻合
   （钟离 ctime 2020-12-01 / v1.1，甘雨 2021-01-12 / v1.2），但 wiki
   条目会因改版被重建，**不精确**；
3. ``icon`` URL 里的日期段——2021 年那波全站图标重传把 38/72 个老角色的
   日期刷成了 2021，**完全不可用于判版本**。

所以本模块的做法是：把版本区间当成**时间窗**而不是精确版本号——
用 :data:`VERSION_DATES` 的升序表把 ``ctime`` 映射到「该日期当时所处的
版本」，得到一个 ``version_estimate`` 字段，并**同时保留 ctime 原值**
供人工核对。筛版本时只按这个估计值筛，不假装它是精确的上线版本。

产出
----
默认写到 ``data/spider-data``：

======================  ==================================================
``images/<类型>/``      条目图标（``title`` + content_id 命名，去重安全）
``csv/label-<类型>.csv``  实体表，表头与 ``kg_store`` 的导入约定一致
                        （``name`` / ``name_cn`` / ``label`` / ``label_cn``）
``csv/rel-*.csv``        关系表，表头 ``node1,rel,node2,rel_cn``
``manifest.json``        抓取清单：条目数、版本分布、失败 id、耗时
======================  ==================================================

``csv/`` 目录可以直接被 :meth:`kg_store.KGStore.import_csv` 整目录导入。

用法
----
::

    python tools/mihoyo_spider.py                      # 默认 1.1~7.1 全频道
    python tools/mihoyo_spider.py --from-version 5.0    # 只要 5.0 之后
    python tools/mihoyo_spider.py --no-images          # 只出图谱，不下图
    python tools/mihoyo_spider.py --channels 25 5 218  # 只抓指定频道
    python tools/mihoyo_spider.py --limit 20 --dry-run # 试跑，不写盘
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict

try:
    import requests
except ImportError:                                    # pragma: no cover
    sys.exit('缺少依赖 requests，请先 pip install requests')

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

API_HOST = 'https://api-static.mihoyo.com/common/blackboard/ys_obc/v1'
LIST_URL = API_HOST + '/home/content/list'
INFO_URL = API_HOST + '/content/info'

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
              ' (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36')

#: 默认输出根目录（相对仓库根）。素材与图谱都落在这里。
DEFAULT_OUT_DIR = os.path.join('data', 'spider-data')

#: ``content_id`` 高于此值即进入新版 wiki 后端，``content/info`` 抓不到详情。
#: 仍然会尝试（少数会成功），但默认只在 ``--detail`` 时才发这些请求。
NEW_WIKI_ID_THRESHOLD = 500000

#: 版本 → 上线日期。**升序**，用于把 ctime 映射到「当时所处版本」。
#:
#: 1.0 之前（无相性系统）与测试版本不列入；本表止于 7.1（2026-09-23 上线，
#: 即当前线上版本）。6.x 另有「月之版本」并行的月版本编号（6.0 = 月之一），
#: 这里统一用 6.x 主线编号。
VERSION_DATES = [
    ('1.0', '2020-09-28'), ('1.1', '2020-11-11'), ('1.2', '2020-12-23'),
    ('1.3', '2021-02-03'), ('1.4', '2021-03-17'), ('1.5', '2021-04-28'),
    ('1.6', '2021-06-09'), ('2.0', '2021-07-21'), ('2.1', '2021-09-01'),
    ('2.2', '2021-10-13'), ('2.3', '2021-11-24'), ('2.4', '2022-01-05'),
    ('2.5', '2022-02-16'), ('2.6', '2022-03-30'), ('2.7', '2022-05-31'),
    ('2.8', '2022-07-13'), ('3.0', '2022-08-24'), ('3.1', '2022-09-28'),
    ('3.2', '2022-11-02'), ('3.3', '2022-12-07'), ('3.4', '2023-01-18'),
    ('3.5', '2023-03-01'), ('3.6', '2023-04-12'), ('3.7', '2023-05-24'),
    ('3.8', '2023-07-05'), ('4.0', '2023-08-16'), ('4.1', '2023-09-27'),
    ('4.2', '2023-11-08'), ('4.3', '2023-12-20'), ('4.4', '2024-01-31'),
    ('4.5', '2024-03-13'), ('4.6', '2024-04-24'), ('4.7', '2024-06-05'),
    ('4.8', '2024-07-17'), ('5.0', '2024-08-28'), ('5.1', '2024-10-09'),
    ('5.2', '2024-11-20'), ('5.3', '2025-01-01'), ('5.4', '2025-02-12'),
    ('5.5', '2025-03-26'), ('5.6', '2025-05-07'), ('5.7', '2025-06-18'),
    ('5.8', '2025-07-30'), ('6.0', '2025-09-10'), ('6.1', '2025-10-22'),
    ('6.2', '2025-12-03'), ('6.3', '2026-01-14'), ('6.4', '2026-02-25'),
    ('6.5', '2026-04-08'), ('6.6', '2026-05-20'), ('6.7', '2026-07-01'),
    ('7.0', '2026-08-12'), ('7.1', '2026-09-23'),
]

#: 频道 id → (实体类型键, 类型中文名, 该频道要抽的关系名)。
#:
#: 关系名的选择对齐 ``kg_store.REL_NAMES`` / ``data/csv`` 的既有约定，
#: 这样 ``data/spider-data/csv`` 与 ``data/csv`` 里的老图谱能对上号。
CHANNELS = {
    25:  ('character', '人物', ['元素', '武器', '地区', '神之眼所属', '星级']),
    5:   ('weapon', '武器', ['武器类型', '武器星级', '获取途径']),
    218: ('artifacts', '圣遗物', ['获取方式', '星级']),
    6:   ('master', '怪物', ['元素', '类型']),
    21:  ('food', '料理', ['食物类型', '食物获取方式', '食物星级']),
    54:  ('instance', '副本', ['秘境类型', '推荐元素']),
    255: ('organization', '组织', ['地区']),
    68:  ('book', '书籍', ['书籍类型', '获取方式']),
}

#: 抽取「值」型筛选条件时，这些键产出的是**节点**（要参与关系），
#: 其余键（如「特殊机制」）只作为实体属性写进 CSV，不建节点。
#:
#: ⚠️ 关系名与 ``kg_store.REL_NAMES`` 对齐（同名同义），这样
#: ``data/spider-data/csv`` 与 ``data/csv`` 的老图谱能对上号。
#:
#: ⚠️ 「地区」在角色频道是**城市**（蒙德城/璃月港），在组织频道却是
#: **国家**（蒙德/璃月）——同名不同义，故角色侧另立 ``area`` 类型，
#: 不与国家混用，否则「蒙德城」会被当成国家。
VALUE_KEYS = {
    '元素': ('element', 'element_is', '元素'),
    '武器': ('weapon_type', 'weapon_is', '使用武器'),
    '武器类型': ('weapon_type', 'weapon_type_is', '武器类型'),
    '地区': ('area', 'located_in', '所在地区'),
    '秘境类型': ('instance_type', 'instance_type_is', '秘境类型'),
    '推荐元素': ('element', 'recommend_element', '推荐元素'),
    '类型': ('enemy_type', 'enemy_type_is', '敌人类型'),
    # 「神之眼所属」取值是蒙德/璃月…，但也有「愚人众」这种**势力**，
    # 混进国家会让「愚人众」变成一个国家，故单列 faction 类型。
    '神之眼所属': ('faction', 'affiliated_with', '所属势力'),
}

#: 「值」里需要丢弃的占位项——它们不是有意义的实体。
PLACEHOLDERS = {'未知', '无', '其他', '跨国家', '是', '否'}

#: 这些频道的「地区」筛选值是**国家/地区**级（蒙德/璃月/…/挪德卡莱/跨国家），
#: 与角色频道的城市级「地区」语义不同，故按国家口径建节点。
#: 键是 :data:`CHANNELS` 里的**类型键**。
COUNTRY_KEYS = {'organization': '地区'}

#: 组织频道的地区值 → 规范国家名。挪德卡莱/至冬都是地区而非七国之一，
#: 但图鉴里就是按国家粒度记的，保留原名即可。
COUNTRY_CANON = {
    '蒙德': '蒙德', '璃月': '璃月', '稻妻': '稻妻', '须弥': '须弥',
    '枫丹': '枫丹', '纳塔': '纳塔', '至冬': '至冬', '挪德卡莱': '挪德卡莱',
}

#: 关系名 → 中文名，写进 rel-*.csv 的 ``rel_cn`` 列。
#: 与 ``kg_store.REL_NAMES`` 同名同义，避免导入后出现两套中文名。
REL_CN = {
    'element_is': '元素',
    'recommend_element': '推荐元素',
    'weapon_is': '使用武器',
    'weapon_type_is': '武器类型',
    'located_in': '位于',
    'part_of': '属于',
    'affiliated_with': '所属势力',
    'instance_type_is': '秘境类型',
    'enemy_type_is': '敌人类型',
    'special_food': '特殊料理',
    'ingredient_is': '原料',
    'drop_from': '掉落',
    'obtainable_from': '获取途径',
    'versioned_in': '上线版本',
}

#: 文件名安全化：Windows 禁止 ``\ / : * ? " < > |``，另加控制字符。
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------

def safe_filename(name, fallback='unnamed', max_len=80):
    """把实体名转成安全的文件名（保留中文，截断到 max_len）。"""
    text = unicodedata.normalize('NFC', str(name or '')).strip()
    text = _UNSAFE.sub('_', text).rstrip('. ')
    if len(text) > max_len:
        text = text[:max_len]
    return text or fallback


def version_tuple(text):
    """``'7.1'`` → ``(7, 1)``；解析不出来返回 ``(0, 0)``（排在最前）。"""
    m = re.match(r'\s*(\d+)\.(\d+)', str(text or ''))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def version_from_date(date_str):
    """把日期映射到「该日期当时所处的版本」。

    做法是在 :data:`VERSION_DATES` 里找**最后一个不晚于该日期**的版本。
    早于 1.0 的返回 ``'1.0-'``（表示「早于有版本号的历史」，排最前）；
    晚于 7.1 的返回 ``'7.1+'``。

    ⚠️ 这是**估计值**，不是精确上线版本——wiki 条目 ctime 会被改版重建。
    调用方应把它当时间窗用，别当权威来源。
    """
    if not date_str:
        return ''
    day = str(date_str)[:10].replace('/', '-')
    if not re.match(r'\d{4}-\d{2}-\d{2}', day):
        return ''
    picked = ''
    for ver, date in VERSION_DATES:
        if date <= day:
            picked = ver
        else:
            break
    return picked or '1.0-'


def extract_ctime(content):
    """从详情页 payload 里取 ``ctime`` 的日期部分。"""
    raw = (content or {}).get('ctime') or ''
    return str(raw)[:10].replace('/', '-')


def parse_filter(ext_text):
    """把 ``ext`` 里 ``c_<频道>.filter.text`` 解析成 ``[(键, 值), ...]``。

    ``filter.text`` 本身是 JSON 数组字符串（**不是** Python 字面量），
    形如 ``["地区/蒙德","星级/五星"]``。旧脚本用 ``eval`` 解析它，
    换成 ``json`` 后不必再担心 ``null``/``true`` 之类 Python 专有字面量。

    只取第一个 ``/``：值本身可以含 ``/``（如 ``原粹树脂*20``、
    ``蒙徳/蒙德城``），用 ``split('/', 1)`` 而不是无脑 split。
    """
    if not ext_text:
        return []
    try:
        ext = json.loads(ext_text)
    except (TypeError, ValueError):
        return []
    if not isinstance(ext, dict):
        return []
    for block in ext.values():
        if not isinstance(block, dict):
            continue
        text = (block.get('filter') or {}).get('text')
        if not text:
            continue
        try:
            items = json.loads(text)
        except (TypeError, ValueError):
            continue
        pairs = []
        for item in items or []:
            text_key = str(item or '')
            if '/' not in text_key:
                continue
            key, value = text_key.split('/', 1)
            key, value = key.strip(), value.strip()
            if key and value:
                pairs.append((key, value))
        if pairs:
            return pairs
    return []


def parse_detail_version(summary, title):
    """从 summary/title 里抠出显式版本号（仅约 3% 条目有）。"""
    blob = f'{summary or ""} {title or ""}'
    m = re.search(r'(\d+\.\d+)\s*版本', blob)
    return m.group(1) if m else ''


_TAG_RE = re.compile(r'<[^>]+>')


def strip_html(text):
    """HTML 片段 → 纯文本单行（用于详情页补充字段）。"""
    return re.sub(r'\s+', ' ', _TAG_RE.sub(' ', str(text or ''))).strip()


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class MihoyoClient:
    """带重试、限速与统计的 ``requests`` 薄封装。

    老脚本对每个条目 ``time.sleep(2)`` 且完全裸奔（无超时、无重试、
    无 UA），网络一抖就整轮报废。这里改成指数退避重试 + 可调间隔，
    并且每次请求都记进 :attr:`stats`，失败 id 会汇总进 manifest。
    """

    #: 图鉴根频道。一次请求即可拿到全部 30 个子频道的条目列表
    #: （实测 13789 条），比逐频道请求省 29 次往返。
    ROOT_CHANNEL_ID = 189

    def __init__(self, interval=0.25, retries=3, timeout=40, verbose=True):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': USER_AGENT,
            'Referer': 'https://ys.mihoyo.com/main/obc',
            'Accept': 'application/json, text/plain, */*',
        })
        self.interval = max(0.0, interval)
        self.retries = max(1, retries)
        self.timeout = timeout
        self.verbose = verbose
        self._last_call = 0.0
        self.stats = Counter()
        self._tree = None

    def _throttle(self):
        """保证两次请求之间至少间隔 ``interval`` 秒。"""
        gap = time.monotonic() - self._last_call
        if gap < self.interval:
            time.sleep(self.interval - gap)
        self._last_call = time.monotonic()

    def log(self, message):
        if self.verbose:
            print(message, flush=True)

    def get_json(self, url, params=None, allow_null=False):
        """GET 并返回 ``dict``；彻底失败返回 ``None``（不抛异常）。

        ``allow_null=True`` 时，HTTP 200 但 ``data`` 为空的响应**不算失败**
        ——新版 wiki 条目走 ``content/info`` 正是这种「200 + 内容不存在」，
        属于预期内，不该污染失败统计。
        """
        last_error = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                self.stats['network_error'] += 1
            else:
                self.stats['http_ok'] += 1
                if resp.status_code == 200:
                    try:
                        payload = resp.json()
                    except ValueError as exc:
                        last_error = exc
                    else:
                        data = payload.get('data')
                        if data or allow_null:
                            return payload
                        self.stats['empty_data'] += 1
                        return None
                elif resp.status_code == 404:
                    self.stats['not_found'] += 1
                    return None
                else:
                    last_error = RuntimeError(f'HTTP {resp.status_code}')
                    self.stats['http_error'] += 1
            if attempt < self.retries:
                time.sleep(min(8.0, 1.5 * (2 ** (attempt - 1))))
        self.stats['failed'] += 1
        self.log(f'    ! 请求失败（{last_error}）: {url}')
        return None

    def catalog(self):
        """取整棵频道树（``{频道id: [条目, ...]}``），**只请求一次并缓存**。

        根频道（189「图鉴」）的响应里就带上了全部 30 个子频道的完整
        ``list``，所以没必要一个频道一次请求。
        """
        if self._tree is not None:
            return self._tree
        payload = self.get_json(
            LIST_URL,
            params={'app_sn': 'ys_obc', 'channel_id': self.ROOT_CHANNEL_ID})
        tree = {}
        if payload:
            for block in payload.get('data', {}).get('list') or []:
                self._index_channels(block, tree)
        self._tree = tree
        return tree

    def _index_channels(self, node, tree):
        """递归把频道树摊平成 ``{频道id: 条目列表}``。

        ⚠️ 节点的 ``id`` 既可能是叶子频道（自带 ``list``），也可能是
        中间分组（只有 ``children``）。两种都要收，且**同一个 id 可能在
        树里出现多次**（分组节点与叶子同名），故用 ``setdefault`` 保留
        先到的非空列表，别让后一个空壳把已有数据盖掉。
        """
        cid = node.get('id')
        entries = node.get('list') or []
        if cid is not None and entries:
            tree.setdefault(cid, []).extend(entries)
        for child in node.get('children') or []:
            self._index_channels(child, tree)

    def fetch_channel(self, channel_id):
        """取指定频道的全部条目（走缓存的整棵树）。"""
        return self.catalog().get(channel_id, [])

    def fetch_detail(self, content_id):
        """抓详情页 payload（``None`` 表示抓不到，新版条目属正常）。"""
        payload = self.get_json(
            INFO_URL,
            params={'app_sn': 'ys_obc', 'content_id': content_id},
            allow_null=True)
        if not payload:
            return None
        return (payload.get('data') or {}).get('content')

    def download(self, url, dest):
        """下载图片到 ``dest``；已存在则跳过。返回是否成功。"""
        if not url or os.path.exists(dest):
            return bool(url)
        self._throttle()
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code != 200 or not resp.content:
                self.stats['image_error'] += 1
                return False
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, 'wb') as fh:
                fh.write(resp.content)
        except (requests.RequestException, OSError):
            self.stats['image_error'] += 1
            return False
        self.stats['image_ok'] += 1
        return True


# --------------------------------------------------------------------------
# 数据模型
# --------------------------------------------------------------------------

class Node:
    """一个待写出的实体。"""

    __slots__ = ('type', 'type_cn', 'name', 'attrs', 'version', 'ctime', 'icon')

    def __init__(self, type_key, type_cn, name):
        self.type = type_key
        self.type_cn = type_cn
        self.name = name
        self.attrs = {}
        self.version = ''
        self.ctime = ''
        self.icon = ''


class Relation:
    """一条 ``src -[rel]-> dst`` 关系。

    ⚠️ 端点存的是 **(类型, 名字)** 二元组而不是光名字：值型节点里
    「至冬」既是 country 又是 area（角色频道的城市级「地区」），
    只按名字反查类型会命中先注册的那个，导致关系被写进
    ``rel-organization-area.csv``——文件名的方向就错了。
    """

    __slots__ = ('src', 'rel', 'dst', 'rel_cn', 'weight')

    def __init__(self, src, rel, dst, rel_cn='', weight=''):
        self.src = src
        self.rel = rel
        self.dst = dst
        self.rel_cn = rel_cn
        self.weight = weight

    @property
    def src_name(self):
        return self.src[1]

    @property
    def dst_name(self):
        return self.dst[1]


# --------------------------------------------------------------------------
# 采集
# --------------------------------------------------------------------------

class Spider:
    """按频道采集，产出 :class:`Node` / :class:`Relation`。"""

    def __init__(self, client, from_version='1.1', to_version='7.1',
                 channels=None, limit=0, with_images=True, detail=False):
        self.client = client
        self.lo = version_tuple(from_version)
        self.hi = version_tuple(to_version)
        self.channels = list(channels or CHANNELS)
        self.limit = limit
        self.with_images = with_images
        self.detail = detail
        self.nodes = {}
        self.relations = []
        self.version_hist = Counter()
        self.skipped_version = 0
        self.failed_ids = []
        #: 值型节点（元素/国家/武器类型…）的中文名 → 类型，用于跨频道复用，
        #: 避免「风元素」和「风」裂成两个实体。
        self._value_nodes = {}

    # ---------- 版本窗 ----------

    def _in_window(self, version):
        """版本是否落在 ``[from, to]`` 窗内。

        空版本（拿不到任何时间线索）**一律保留**——猜错版本就把实体丢掉
        代价太大，宁可多留一条并让它带空 ``version``。
        """
        if not version:
            return True
        if version.endswith('-'):
            return False
        return self.lo <= version_tuple(version) <= self.hi

    def _register_value_node(self, ntype, value, label_cn):
        """登记（或复用）一个值型节点，返回节点名。

        ⚠️ 缓存键必须是 ``(类型, 值)`` 而不是光值：同一个字符串在不同
        类型下语义不同（「蒙德」既是国家也是地区名、「风」既是元素也是
        秘境类型…）。只用值做键会让先注册的类型把后来的**吞掉**，
        关系就会指到错误类型的节点上。
        """
        value = str(value).strip()
        if not value or value in PLACEHOLDERS:
            return ''
        cache_key = (ntype, value)
        if cache_key in self._value_nodes:
            return value
        node = Node(ntype, label_cn, value)
        self.nodes[(ntype, value)] = node
        self._value_nodes[cache_key] = value
        return value

    # ---------- 主流程 ----------

    def run(self):
        """采集所有选定频道。返回自身（便于链式调用）。"""
        # 先把整棵频道树拉下来（一次请求），避免逐频道往返。
        self.client.catalog()
        for channel_id in self.channels:
            spec = CHANNELS.get(channel_id)
            if not spec:
                self.client.log(f'  ? 跳过未知频道 {channel_id}')
                continue
            type_key, type_cn, wanted = spec
            entries = self.client.fetch_channel(channel_id)
            self.client.log(
                f'  频道 {channel_id:>3} {type_cn}: 列表返回 {len(entries)} 条')
            if self.limit:
                entries = entries[:self.limit]
            for entry in entries:
                try:
                    self._handle(entry, type_key, type_cn, wanted)
                except Exception as exc:                  # noqa: BLE001
                    # 单条失败不能拖垮整轮：记录 id 继续。
                    self.failed_ids.append(
                        (entry.get('content_id'), repr(exc)))
        return self

    def _handle(self, entry, type_key, type_cn, wanted):
        """处理单条：建实体、抽关系、（可选）抓详情补字段。"""
        title = (entry.get('title') or '').strip()
        if not title:
            return
        content_id = entry.get('content_id')

        ctime = ''
        detail = None
        if self.detail:
            detail = self.client.fetch_detail(content_id)
            ctime = extract_ctime(detail)
            # 新版 wiki 条目（id ≥ 500000）拿不到详情，属预期内，不计失败。

        version = parse_detail_version(entry.get('summary'), title)
        if not version:
            version = version_from_date(ctime)

        if not self._in_window(version):
            self.skipped_version += 1
            return

        node = Node(type_key, type_cn, title)
        node.ctime = ctime
        node.version = version
        node.icon = entry.get('icon') or ''
        if entry.get('summary'):
            node.attrs['summary'] = str(entry['summary']).strip()

        pairs = parse_filter(entry.get('ext'))
        node.attrs['mhy_id'] = str(content_id or '')
        #: 本频道里需要按国家口径处理的筛选键（如组织频道的「地区」）
        country_key = COUNTRY_KEYS.get(type_key)
        for key, value in pairs:
            node.attrs[key] = value
            if key == country_key:
                # 组织频道的「地区」是国家口径，单独走 country 分支。
                canon = COUNTRY_CANON.get(value, value)
                country = self._register_value_node(
                    'country', canon, self._cn_for('country'))
                if country:
                    self.relations.append(Relation(
                        (type_key, title), 'part_of', ('country', country),
                        REL_CN['part_of']))
                continue
            spec = VALUE_KEYS.get(key)
            if not spec:
                continue                       # 非节点型条件，只当属性
            vntype, rel, rel_cn = spec
            value_node = self._register_value_node(vntype, value, self._cn_for(vntype))
            if value_node:
                self.relations.append(Relation(
                    (type_key, title), rel, (vntype, value_node), rel_cn))

        self.nodes[(type_key, title)] = node
        self.version_hist[version or '未知'] += 1

        # 版本作为关系单独挂一条，便于图谱里按版本筛选实体。
        if version:
            ver_node = self._register_value_node('version', version, '版本')
            if ver_node:
                self.relations.append(Relation(
                    (type_key, title), 'versioned_in', ('version', ver_node),
                    REL_CN['versioned_in']))

        if self.detail:
            self._enrich_from_detail(node, detail)
        if self.with_images and node.icon:
            node.attrs['icon'] = node.icon

    def _cn_for(self, ntype):
        """值型节点的中文类型名。"""
        return {'element': '元素', 'country': '国家', 'area': '地区',
                'faction': '势力', 'weapon_type': '武器类型',
                'instance_type': '秘境类型', 'enemy_type': '敌人类型',
                'version': '版本'}.get(ntype, ntype)

    def _enrich_from_detail(self, node, content):
        """从已抓到的详情页补几个高价值字段（简介、正文摘要）。

        只做「有就写、没有就跳过」的补充——详情页对新条目抓不到，
        因此这条路径**不能**承担主链路。
        """
        if not content:
            return
        ctime = extract_ctime(content)
        if ctime and not node.ctime:
            node.ctime = ctime
        summary = strip_html(content.get('summary'))
        if summary and not node.attrs.get('summary'):
            node.attrs['summary'] = summary[:200]
        contents = content.get('contents') or []
        if contents:
            plain = strip_html(contents[0].get('text'))
            if plain:
                node.attrs['detail_text'] = plain[:600]

    # ---------- 输出 ----------

    def write(self, out_dir):
        """把采集结果写到 ``out_dir``，返回 manifest 路径。"""
        csv_dir = os.path.join(out_dir, 'csv')
        os.makedirs(csv_dir, exist_ok=True)

        by_type = defaultdict(list)
        for node in self.nodes.values():
            by_type[node.type].append(node)

        files = []
        for type_key, nodes in sorted(by_type.items()):
            path = os.path.join(csv_dir, f'label-{type_key}.csv')
            self._write_nodes(path, nodes)
            files.append(os.path.basename(path))

        rel_files = self._write_relations(csv_dir)
        files.extend(rel_files)

        manifest = {
            'generated_by': 'tools/mihoyo_spider.py',
            'version_window': [self._fmt_version(self.lo), self._fmt_version(self.hi)],
            'version_estimation': (
                'summary/title 中的「X.Y版本」字样优先；否则用详情页 ctime '
                '映射到当时所处版本。两者都拿不到时 version 留空。'
                '⚠️ wiki 条目 ctime 会因改版重建，版本为估计值，非权威上线版本。'),
            'channels': list(self.channels),
            'node_count': len(self.nodes),
            'relation_count': len(self.relations),
            'nodes_by_type': {t: len(v) for t, v in sorted(by_type.items())},
            'version_histogram': dict(sorted(self.version_hist.items())),
            'skipped_out_of_window': self.skipped_version,
            'failed_entries': [{'content_id': cid, 'error': err}
                               for cid, err in self.failed_ids[:50]],
            'http_stats': dict(self.client.stats),
            'csv_files': sorted(files),
        }
        manifest_path = os.path.join(out_dir, 'manifest.json')
        with open(manifest_path, 'w', encoding='utf-8') as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
        return manifest_path

    @staticmethod
    def _fmt_version(pair):
        return f'{pair[0]}.{pair[1]}'

    def _write_nodes(self, path, nodes):
        """写实体表。表头固定为 kg_store 约定的四列 + 属性列。

        ⚠️ 主键用 ``name``（英文名），空时回退 ``name_cn``——这是
        ``kg_store._parse_node_file`` 的约定。原神实体暂无官方英文名，
        故 ``name`` 留空、``name_cn`` 填中文名，导入时自动回退。
        """
        attr_keys = []
        seen = set(('mhy_id', 'version', 'ctime'))   # 已是固定列，别再写一遍
        for node in nodes:
            for key in node.attrs:
                if key not in seen:
                    seen.add(key)
                    attr_keys.append(key)
        attr_keys.sort()
        with open(path, 'w', encoding='utf-8-sig', newline='') as fh:
            writer = csv.writer(fh)
            writer.writerow(['name', 'name_cn', 'label', 'label_cn',
                             'mhy_id', 'version', 'ctime'] + attr_keys)
            for node in sorted(nodes, key=lambda n: n.name):
                row = ['', node.name, node.type, node.type_cn,
                       node.attrs.get('mhy_id', ''), node.version, node.ctime]
                row += [str(node.attrs.get(key, '')).replace('\n', ' ')
                        for key in attr_keys]
                writer.writerow(row)

    def _write_relations(self, csv_dir):
        """写关系表，按「源类型-目标类型」分文件，文件名即方向。

        分文件的约定对齐 ``data/csv/rel-<src>-<dst>.csv``；
        ``kg_store`` 导入时把文件名里的段当**类型提示**，所以
        ``rel-character-element.csv`` 的方向确实是 人物 → 元素。

        ⚠️ 端点必须是**已登记的节点**：关系里出现但节点表里没有的名字
        （例如占位值被过滤掉）会被丢弃，否则导入时会变成指向空端的桩关系。
        """
        buckets = defaultdict(list)
        for rel in self.relations:
            if rel.src not in self.nodes or rel.dst not in self.nodes:
                continue
            buckets[(rel.src[0], rel.dst[0])].append(rel)

        written = []
        for (src_type, dst_type), rows in sorted(buckets.items()):
            path = os.path.join(csv_dir, f'rel-{src_type}-{dst_type}.csv')
            with open(path, 'w', encoding='utf-8-sig', newline='') as fh:
                writer = csv.writer(fh)
                writer.writerow(['node1', 'rel', 'node2', 'rel_cn', 'weight'])
                seen = set()
                for rel in sorted(rows, key=lambda r: (r.src[1], r.rel, r.dst[1])):
                    dedup = (rel.src[1], rel.rel, rel.dst[1])
                    if dedup in seen:
                        continue
                    seen.add(dedup)
                    writer.writerow([rel.src[1], rel.rel, rel.dst[1],
                                     rel.rel_cn or rel.rel, rel.weight])
            written.append(os.path.basename(path))
        return written


# --------------------------------------------------------------------------
# 图片
# --------------------------------------------------------------------------

def download_images(spider, out_dir, client):
    """按类型分目录下载图标，返回 ``{类型: 成功数}``。"""
    if not spider.with_images:
        return {}
    result = {}
    by_type = defaultdict(list)
    for node in spider.nodes.values():
        if node.icon:
            by_type[node.type].append(node)
    for type_key, nodes in sorted(by_type.items()):
        folder = os.path.join(out_dir, 'images', type_key)
        os.makedirs(folder, exist_ok=True)
        ok = 0
        for index, node in enumerate(nodes, 1):
            name = safe_filename(node.name, fallback=str(index))
            dest = os.path.join(folder, f'{name}.png')
            if client.download(node.icon, dest):
                ok += 1
            if index % 50 == 0:
                client.log(f'      图片 {index}/{len(nodes)}')
        result[type_key] = ok
        client.log(f'    图片 {type_key}: {ok}/{len(nodes)}')
    return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description='抓取原神图鉴素材与知识图谱数据',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('用法')[-1] if __doc__ else None)
    parser.add_argument('--out', default=DEFAULT_OUT_DIR,
                        help=f'输出目录（默认 {DEFAULT_OUT_DIR}）')
    parser.add_argument('--from-version', default='1.1', help='起始版本（默认 1.1）')
    parser.add_argument('--to-version', default='7.1', help='结束版本（默认 7.1）')
    parser.add_argument('--channels', nargs='*', type=int, default=None,
                        metavar='ID',
                        help='只抓这些频道（默认全部：' +
                             ' '.join(str(c) for c in CHANNELS) + '）')
    parser.add_argument('--limit', type=int, default=0,
                        help='每频道最多取几条（0 = 不限，用于试跑）')
    parser.add_argument('--interval', type=float, default=0.25,
                        help='两次请求最小间隔秒数（默认 0.25）')
    parser.add_argument('--no-images', action='store_true', help='不下载图片')
    parser.add_argument('--detail', action='store_true',
                        help='额外抓详情页补简介/正文（慢很多，新条目抓不到）')
    parser.add_argument('--dry-run', action='store_true',
                        help='只统计不写盘')
    parser.add_argument('--quiet', action='store_true', help='不打印进度')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    client = MihoyoClient(interval=args.interval, verbose=not args.quiet)

    client.log(f'频道: {args.channels or list(CHANNELS)}')
    client.log(f'版本窗: {args.from_version} ~ {args.to_version}')

    started = time.time()
    spider = Spider(
        client,
        from_version=args.from_version,
        to_version=args.to_version,
        channels=args.channels,
        limit=args.limit,
        with_images=not args.no_images,
        detail=args.detail,
    ).run()

    client.log('')
    client.log(f'实体 {len(spider.nodes)} 个，关系 {len(spider.relations)} 条')
    client.log('版本分布: ' + ', '.join(
        f'{k}×{v}' for k, v in sorted(spider.version_hist.items())))
    if spider.skipped_version:
        client.log(f'版本窗外跳过: {spider.skipped_version} 条')
    if spider.failed_ids:
        client.log(f'失败条目: {len(spider.failed_ids)} 条（详见 manifest）')

    if args.dry_run:
        client.log('--dry-run：不写盘')
        return 0

    images = download_images(spider, args.out, client)
    manifest_path = spider.write(args.out)
    client.log('')
    client.log(f'图片合计 {sum(images.values())} 张 -> {os.path.join(args.out, "images")}')
    client.log(f'图谱 CSV -> {os.path.join(args.out, "csv")}')
    client.log(f'清单 -> {manifest_path}')
    client.log(f'耗时 {time.time() - started:.1f}s')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
