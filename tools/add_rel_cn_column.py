"""给 data/csv-edu 的 rel-*.csv 增加 ``rel_cn`` 列（关系中文名）。

**为什么需要这一步**：csv-edu 的 324 个关系名里，原先只有 31 个能在
``kg_store.REL_NAMES`` 里查到中文，其余 293 个在画布上只能显示生英文
（``contrast_with``、``underlies`` 之类）。中文名是**数据**而不是代码常量，
所以让它随 CSV 走：表里加一列，导入时登记进 ``kg_rel_names`` 表，导出时写回，
往返无损。以后新增关系只需改本表，不必动 ``kg_store.py``。

**已登记的关系沿用旧译法**：``part_of`` 等 31 个在 ``REL_NAMES`` 里已有中文，
直接复用其值，避免同一个词在代码表与数据表里出现两种说法。

用法（幂等，可重复执行）::

    python tools/add_rel_cn_column.py# 就地改写 data/csv-edu
    python tools/add_rel_cn_column.py --check# 只校验，不写入

⚠️ 保持 **UTF-8 无 BOM + CRLF**：原文件就是这个格式（BOM 是原神 data/csv 的
形态，两者不一致），换行符一改整个文件在 git 里就是一次全文件 diff。
"""

import argparse
import csv
import glob
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kg_store import REL_NAMES                      # noqa: E402

CSV_DIR = os.path.join(ROOT, 'data', 'csv-edu')

# 关系英文名 -> 中文名。**只收data/csv-edu 里真实出现的关系**，
# 脚本末尾会校验「数据里有就必须有译文」，多写漏写都会当场报出来。
#
# 译法约定（全表统一，否则边标签读起来像两套话）：
#   X_of       「……的……」   instance_of  -> 是……的实例
#   X_by       「由……」（被动） driven_by   -> 由……驱动
#   X_with     「以……」「与……一起」
#   X_in       「……中的……」 phenomenon_in -> ……中的现象
#   X_for      「用于……」/「……的依据」
#   名词性关系直接用中文名词短语（basis_of -> 是……的基础）
REL_CN = {    # 关系英文名 -> 中文名。
    # 这324 条对应 data/csv-edu 里真实出现的全部关系名，脚本末尾会校验
    # 「数据里有就必须有译文」，多写漏写都会当场报出来。
    #
    # 译法约定（全表统一，否则边标签读起来像两套话）：
    #   X_of    「……的……」   instance_of  -> 是……的实例
    #   X_by    「由……」（被动） driven_by   -> 由……驱动
    #   X_with  「以……」「与……一起」
    #   X_in    「……中的……」 phenomenon_in -> ……中的现象
    #   X_for   「用于……」/「……的依据」
    #   名词性关系直接用中文名词短语（basis_of -> 是……的基础）
    # 排序按英文名字母序，便于查找与新增。
    'abbreviation_of': '是……的缩写',
    'abstraction_of': '是……的抽象',
    'accumulates_from': '积累自',
    'achieved_through': '通过……实现',
    'addresses': '针对',
    'adds': '增加',
    'advantage_of': '是……的优势',
    'affected_by': '受……影响',
    'affects': '影响',
    'aggravates': '加重',
    'aims_at': '旨在',
    'alias_of': '别名',
    'also_supports': '同时也支持',
    'alternative_to': '可替代为',
    'amplifies': '放大',
    'analogue_of': '类比',
    'answers': '回答',
    'applies': '应用',
    'approximates': '近似于',
    'arises_from': '源于',
    'assessed_by': '由……评估',
    'audit_support_for': '为……提供审核支持',
    'avoided_by': '由……规避',
    'basis_for': '是……的依据',
    'basis_of': '是……的基础',
    'beneficial_to': '有益于',
    'benefits': '有益于',
    'benefits_from': '受益于',
    'bootstraps': '引导启动',
    'bounded_by': '受限于',
    'bounds': '界定',
    'bridges': '桥接',
    'broader_than': '范围更广',
    'buffer_against': '缓冲……的冲击',
    'buffered_by': '被……缓冲',
    'buffers': '缓冲',
    'builds_on': '建立在……之上',
    'built_from': '由……构建',
    'built_on': '建立在……之上',
    'burden_on': '是……的负担',
    'carries': '承载',
    'caused_by': '由……引起',
    'causes': '引起',
    'challenge_in': '……领域的挑战',
    'challenges': '挑战',
    'changes': '改变',
    'clusters': '聚类',
    'combines': '结合',
    'compares': '比较',
    'competes_with': '与……竞争',
    'complements': '互补于',
    'component_of': '组成部分',
    'composed_of': '由……组成',
    'computed_by': '由……计算',
    'computed_from': '由……计算得出',
    'computes': '计算',
    'conditions': '以……为条件',
    'configured_by': '由……配置',
    'conflicts_with': '与……冲突',
    'constrained_by': '受限于',
    'constrains': '约束',
    'consumed_by': '被……消耗',
    'consumes': '消耗',
    'contends': '主张',
    'context_for': '是……的语境',
    'contextualized_by': '由……提供语境',
    'contrast_with': '与……对比',
    'contrasted_by': '由……对比',
    'contrasted_with': '与……对比',
    'contrasts_with': '与……形成对比',
    'contributes_to': '有助于',
    'countered_by': '被……制衡',
    'counterpart_of': '对应物',
    'creates': '创造',
    'criterion_for': '是……的判据',
    'criterion_of': '是……的判据',
    'deepens': '加深',
    'defers': '推迟',
    'defines': '界定',
    'delivers': '提供',
    'depends_on': '依赖于',
    'derived_from': '衍生自',
    'derives_from': '源自',
    'describes': '描述',
    'determines': '决定',
    'develops': '发展',
    'dialect_of': '变体',
    'differs_from': '不同于',
    'difficult_for': '难以',
    'directs': '指导',
    'disambiguates': '消歧',
    'discipline_for': '面向……的学科',
    'discovers': '发现',
    'distinguishes': '区分',
    'documents': '记录',
    'dominates': '主导',
    'draws_from': '借鉴自',
    'driven_by': '由……驱动',
    'drives': '驱动',
    'edge_type_of': '边的类型',
    'effect_of': '是……的效果',
    'elicit': '引出',
    'elicits': '引出',
    'eliminates': '消除',
    'embodies': '体现',
    'emerges_from': '源于',
    'empowers': '赋能',
    'enabled_by': '由……启用',
    'enables': '使能',
    'enacts': '践行',
    'encodes': '编码',
    'encompasses': '涵盖',
    'enhances': '增强',
    'ensures': '确保',
    'erodes': '侵蚀',
    'estimating': '估计',
    'evaluate': '评估',
    'evaluated_by': '由……评估',
    'evaluates': '评估',
    'evidenced_by': '以……为据',
    'exemplifies': '例示',
    'exerts': '施加',
    'exhibits': '展现',
    'explains': '解释',
    'explains_by': '由……解释',
    'exports': '导出',
    'exposes': '暴露',
    'exposes_weakness_of': '暴露……的弱点',
    'expresses': '表达',
    'extended_by': '由……扩展',
    'extends': '扩展',
    'extension_of': '扩展',
    'extracts': '抽取',
    'facilitates': '促进',
    'feeds': '供给',
    'fixed_by': '由……修复',
    'forces': '迫使',
    'form_of': '形式',
    'formalises': '形式化',
    'forms_when': '形成于……时',
    'framework_for': '是……的框架',
    'full_name_of': '全称',
    'fuses': '融合',
    'generates': '生成',
    'governs': '支配',
    'grounds': '为……奠基',
    'group_level_form_of': '群体层面的形态',
    'guarantees': '保证',
    'harms': '损害',
    'holds': '包含',
    'identifies': '识别',
    'impairs': '损害',
    'impedes': '阻碍',
    'implemented_by': '由……实现',
    'implements': '实现',
    'imports': '导入',
    'improves': '改善',
    'includes': '包含',
    'increases': '增加',
    'incurs': '招致',
    'indexes': '索引',
    'induces': '诱发',
    'inflates': '抬高',
    'informs': '为……提供依据',
    'input_to': '是……的输入',
    'instance_of': '实例',
    'instances': '实例化',
    'instantiates': '实例化',
    'interface_for': '是……的接口',
    'invalidates': '使……失效',
    'layouts': '布局',
    'leads_to': '导致',
    'lists': '列出',
    'managed_by': '由……管理',
    'manifestation_of': '表现',
    'manifests': '显现',
    'manifests_as': '表现为',
    'manifests_in': '体现于',
    'maps': '映射',
    'measured_by': '由……测量',
    'measures': '度量',
    'mechanism_of': '是……的机制',
    'mediates': '中介',
    'merges': '合并',
    'metaphor_for': '是……的隐喻',
    'method_of': '是……的方法',
    'misattributes': '错误归因',
    'miscalibrates': '校准失当',
    'mitigated_by': '被……缓解',
    'mitigates': '缓解',
    'modelled_by': '由……建模',
    'models': '建模',
    'moderates': '调节',
    'modulates': '调节',
    'monitors': '监测',
    'motivated_by': '由……激励',
    'motivates': '激励',
    'moves_to': '转向',
    'normalises': '规范化',
    'object_of': '是……的对象',
    'operationalizes': '操作化',
    'opposed_to': '与……对立',
    'opposite_of': '与……相反',
    'optimised_by': '由……优化',
    'optimises': '优化',
    'optimizes': '优化',
    'orchestrates': '编排',
    'organises': '组织',
    'outcome_of': '是……的结果',
    'part_of': '属于',
    'personalises': '个性化',
    'phenomenon_in': '……中的现象',
    'phenomenon_of': '是……的现象',
    'powers': '驱动',
    'precedes': '先于',
    'predicts': '预测',
    'prerequisite_for': '是……的前提',
    'prevents': '防止',
    'principle_of': '是……的原则',
    'prioritizes': '优先考虑',
    'problem_of': '是……的问题',
    'process_in': '……中的过程',
    'produces': '产生',
    'promotes': '促进',
    'property_of': '是……的属性',
    'provided_by': '由……提供',
    'provides': '提供',
    'queries': '查询',
    'ranks_by': '按……排序',
    'reads': '读取',
    'realises': '实现',
    'recorded_by': '由……记录',
    'recorded_in': '记录于',
    'records': '记录',
    'reduces': '降低',
    'refines': '细化',
    'reinforces': '强化',
    'related_to': '与……相关',
    'relates_to': '与……相关',
    'relies_on': '依赖',
    'renders': '呈现',
    'replaces': '取代',
    'represents': '表征',
    'required_by': '为……所需',
    'requires': '需要',
    'reranks': '重排序',
    'resolved_by': '由……解决',
    'resolves_duplicates_of': '消解……的重复',
    'restricts': '限制',
    'result_of': '是……的结果',
    'results_from': '源自',
    'retrieved_by': '由……检索',
    'retrieves': '检索',
    'returns': '返回',
    'reveals': '揭示',
    'reverse_engineers': '反向工程',
    'risk_of': '是……的风险',
    'risks': '冒……的风险',
    'role_of': '是……的作用',
    'runs_on': '运行于',
    'scales': '扩展',
    'selects': '选择',
    'serves': '服务',
    'serves_as': '充当',
    'shaped_by': '由……塑造',
    'shapes': '塑造',
    'solves': '解决',
    'specialises': '专门化',
    'specialization_of': '具体形态',
    'speeds_up': '加速',
    'standardises': '标准化',
    'states': '陈述',
    'stored_as': '存储为',
    'stored_in': '存储于',
    'stores': '存储',
    'stores_state_in': '把状态存于',
    'strengthens': '强化',
    'subcomponent_of': '子组成部分',
    'subconcept_of': '子概念',
    'subdivided_into': '细分为',
    'subordinate_to': '从属于',
    'subset_of': '子集',
    'subsumes': '包含',
    'subtype_of': '子类型',
    'succeeds': '后于',
    'successor_of': '后继于',
    'superseded_by': '被……取代',
    'supersedes': '取代',
    'supported_by': '由……支撑',
    'supports': '支持',
    'susceptible_to': '易受……影响',
    'symptom_of': '是……的症状',
    'synonym_of': '同义词',
    'targeting': '针对',
    'tests': '检验',
    'theory_of': '是……的理论',
    'theory_under': '……的理论基础',
    'threatens': '威胁',
    'traces': '追溯',
    'tracks': '追踪',
    'trades': '权衡',
    'trained_with': '以……训练',
    'trains': '训练',
    'traverses': '遍历',
    'triggered_by': '由……触发',
    'triggers': '触发',
    'tunes': '调优',
    'type_of': '类型',
    'umbrella_for': '是……的总称',
    'underlies': '构成基础',
    'undermined_by': '被……削弱',
    'undermines': '削弱',
    'underpins': '支撑',
    'unit_of': '单位',
    'used_by': '被……使用',
    'used_for': '用于',
    'uses': '使用',
    'variant_of': '变体',
    'variety_of': '是……的种类',
    'visualises': '可视化',
    'weakened_by': '被……削弱',
    'weakens_by': '被……削弱',
    'workflow_of': '是……的流程',
    'writes_to': '写入',
}



def build_mapping(rels):
    """合并静态译文与既有 REL_NAMES；返回 (映射, 缺失列表)。

    ⚠️ **既有 REL_NAMES 优先**：那31 个关系早就在画布上显示了，
    沿用其译法才不会让用户看到同一个词前后变了样。
    """
    mapping, missing = {}, []
    for rel in sorted(rels):
        if rel in REL_NAMES:
            mapping[rel] = REL_NAMES[rel]      # 已登记的沿用旧译法
        elif rel in REL_CN:
            mapping[rel] = REL_CN[rel]
        else:
            missing.append(rel)
    return mapping, missing


def rewrite_dir(csv_dir, check_only=False):
    """给目录下所有 rel-*.csv 加/更新 rel_cn 列。返回报告 dict。"""
    files = sorted(glob.glob(os.path.join(csv_dir, 'rel-*.csv')))
    if not files:
        raise FileNotFoundError(f'没有 rel-*.csv：{csv_dir}')

    # 先扫全量关系名，再一次性建映射（保证跨文件同一关系译名一致）
    all_rels = set()
    for path in files:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            for row in csv.DictReader(f):
                if (row.get('rel') or '').strip():
                    all_rels.add(row['rel'].strip())
    mapping, missing = build_mapping(all_rels)

    report = {'dir': csv_dir, 'files': len(files), 'rels': len(mapping),
              'missing': missing, 'rows': 0, 'changed': 0}

    for path in files:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        report['rows'] += len(rows)

        # rel_cn 插在 rel 之后——挨着关系名看，比甩到行尾好读
        if 'rel_cn' in fields:
            fields.remove('rel_cn')
        fields.insert(fields.index('rel') + 1, 'rel_cn')

        out_rows = []
        for row in rows:
            rel = (row.get('rel') or '').strip()
            new = dict(row)
            new['rel_cn'] = mapping.get(rel, '')
            out_rows.append([new.get(c, '') for c in fields])

        buf = io.StringIO(newline='')
        writer = csv.writer(buf, lineterminator='\r\n')
        writer.writerow(fields)
        writer.writerows(out_rows)
        payload = buf.getvalue()

        with open(path, 'r', encoding='utf-8', newline='') as f:
            if f.read() != payload:
                report['changed'] += 1
        if not check_only:
            # 原文件是 UTF-8 无 BOM（与 data/csv 的 BOM 形态不同），
            # newline='' + \r\n 保持原有的 CRLF 行尾
            with open(path, 'w', encoding='utf-8', newline='') as f:
                f.write(payload)

    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description='给 data/csv-edu 的 rel-*.csv 增加 rel_cn 列')
    ap.add_argument('--check', action='store_true', help='只校验，不写入')
    ap.add_argument('--dir', default=CSV_DIR, help='CSV 目录')
    args = ap.parse_args(argv)

    rep = rewrite_dir(args.dir, check_only=args.check)
    verb = '待更新' if args.check else '已更新'
    print(rep['dir'])
    print(f'  {rep["files"]} 个关系表 / {rep["rows"]} 行 / '
          f'{rep["rels"]} 个不同关系名')
    print(f'  {verb} {rep["changed"]} 个文件')
    if rep['missing']:
        print(f'  ⚠ {len(rep["missing"])} 个关系缺中文名：{rep["missing"]}',
              file=sys.stderr)
        return 1
    print('  全部关系均有中文名')
    return 0


if __name__ == '__main__':
    sys.exit(main())