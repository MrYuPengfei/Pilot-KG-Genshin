# -*- coding:utf-8 -*-
# by: Slash
# date: 2022-12-04
# summary: 生成原神知识图谱 需要连接neo4j数据库
#
# v3.4：由 GenshinKG/utils/ 迁入 tools/，数据路径 ../data → <项目根>/data/csv。
# 注意：这是原项目的历史数据加工脚本，依赖第三方包 connDB（提供 Neo4j 客户端）
# 与一个外部 neo4j 实例，默认配置不可用；data/csv 下的 CSV 才是本项目实际消费的数据
# （见 kg_store.py）。此处保留仅为可追溯。
import os

import pandas
import pandas as pd
from connDB.neo4j import Neo4j

# 知识图谱 CSV 目录（v3.4 起为 <项目根>/data/csv）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KG_CSV = os.path.join(ROOT_DIR, 'data', 'csv')

pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
neo4j_config = {
    'api': 'http://127.0.0.1:7474/',
    'auth': ("neo4j", "slash123456")
}
neo4j_config2 = {
    'api': 'http://47.97.6.229/:7474/',
    'auth': ("neo4j", "slash123456")
}

neo4j = Neo4j(config=neo4j_config2)


class YuanShen():
    def __init__(self):
        """
        读取文件 删除一些无需导入的属性
        """
        self.character = pd.read_csv(str(KG_CSV) + '/label-character.csv')
        self.character.drop(
            ['element', 'country', 'break_material', 'skill_material', 'weapon_choice', 'constellation'], axis=1,
            inplace=True)

        self.material = pd.read_csv(str(KG_CSV) + '/label-material.csv')
        self.material.drop(['getting', 'using'], axis=1, inplace=True)

        self.area = pd.read_csv(str(KG_CSV) + '/label-area.csv')
        self.area.drop(
            ['common_master', 'elite_master', 'boss_master', 'dropping_material', 'ingredient', 'picking_material',
             'specialty'], axis=1, inplace=True)

        self.element = pd.read_csv(str(KG_CSV) + '/label-element.csv')

        self.weapon = pd.read_csv(str(KG_CSV) + '/label-weapon.csv')
        self.weapon.drop(['material'], axis=1, inplace=True)

        self.master = pd.read_csv(str(KG_CSV) + '/label-master.csv')
        self.master.drop(['dropping'], axis=1, inplace=True)

        self.food = pd.read_csv(str(KG_CSV) + '/label-food.csv')
        self.food.drop(['ingredient', 'getting'], axis=1, inplace=True)

        self.npc = pd.read_csv(str(KG_CSV) + '/label-npc.csv')

        self.country = pd.read_csv(str(KG_CSV) + '/label-country.csv')

        self.place = pd.read_csv(str(KG_CSV) + '/label-place.csv')

        self.instance = pd.read_csv(str(KG_CSV) + '/label-instance.csv')
        self.instance.drop(['prob_product','fix_product','master'],axis=1,inplace=True)

        self.artifacts = pd.read_csv(str(KG_CSV) + '/label-artifacts.csv')

        self.artifacts.drop(['getting','role'],axis=1,inplace=True)

    def create_relationship(self, rel_df: pd.DataFrame, node1, node2, label1: str, label2: str):
        for _, row in rel_df.iterrows():
            attr1 = [i for i in node1 if i['name'] == row['node1']]
            attr2 = [i for i in node2 if i['name'] == row['node2']]
            if attr1 and attr2:
                neo4j.create_relationship(label1=label1, attrs1=attr1[0], relationship=row['rel'],
                                          label2=label2, attrs2=attr2[0], unique_key1='name',
                                          unique_key2='name')

    def built(self, node=False, relationship=False):
        """
        创建节点和关系用于构建知识图谱
        :param nodes: 存放节点元组的列表
        :param relations: 存放关系元组的列表
        :return:
        """
        if node:
            for data in ['self.character', 'self.material', 'self.area', 'self.element', 'self.weapon',
                         'self.artifacts',
                         'self.master', 'self.food', 'self.npc', 'self.country', 'self.place', 'self.instance']:
                df = eval(data)
                df.fillna('暂无', inplace=True)
                df['mhy_id'] = df['mhy_id'].apply(lambda x: str(x))
                df = df.to_dict(orient='records')
                label = data.replace('self.', '')
                unique_key = 'name' if label in ['instance', 'food','artifacts'] else 'mhy_id'  # instance food artifacts 这三类是没有米游社ID号的
                [neo4j.create_node(label=label, attrs=i, unique_key=unique_key) for i in df]
        if relationship:
            character = self.character.to_dict(orient='records')
            element = self.element.to_dict(orient='records')
            weapon = self.weapon.to_dict(orient='records')
            material = self.material.to_dict(orient='records')
            food = self.food.to_dict(orient='records')
            master = self.master.to_dict(orient='records')
            country = self.country.to_dict(orient='records')
            area = self.area.to_dict(orient='records')
            place = self.place.to_dict(orient='records')
            instance = self.instance.to_dict(orient='records')
            artifacts = self.artifacts.to_dict(orient='records')
            """
            country-area
            area-place
            """
            country_area = pd.read_csv(str(KG_CSV) + '/rel-country-area.csv')
            area_place = pd.read_csv(str(KG_CSV) + '/rel-area-place.csv')
            self.create_relationship(rel_df=country_area, node1=area, node2=country,
                                     label1='area', label2='country')
            self.create_relationship(rel_df=area_place, node1=place, node2=area,
                                     label1='place', label2='area')

            """
            character-country
            character-element
            character-weapon
            character-break-material
            character-food
            character-instance-material
            character-artifacts
            """
            char_cultivating_material = pd.read_csv(str(KG_CSV) + '/rel-character-cultivating_material.csv')
            char_country = pd.read_csv(str(KG_CSV) + '/rel-character-country.csv')
            char_element = pd.read_csv(str(KG_CSV) + '/rel-character-element.csv')
            char_weapon = pd.read_csv(str(KG_CSV) + '/rel-character-weapon.csv')
            char_material = pd.read_csv(str(KG_CSV) + '/rel-character-break_material.csv')
            char_food = pd.read_csv(str(KG_CSV) + '/rel-character-food.csv')
            char_artifacts = pd.read_csv(str(KG_CSV) + '/rel-character-artifacts.csv')

            self.create_relationship(rel_df=char_country,node1=character,node2=country,
                                     label1='character',label2='country')
            self.create_relationship(rel_df=char_element, node1=character, node2=element,
                                     label1='character', label2='element')
            self.create_relationship(rel_df=char_weapon, node1=character, node2=weapon,
                                     label1='character', label2='weapon')
            self.create_relationship(rel_df=char_material, node1=character, node2=material,
                                     label1='character', label2='material')
            self.create_relationship(rel_df=char_food, node1=character, node2=food,
                                     label1='character', label2='food')
            self.create_relationship(rel_df=char_cultivating_material, node1=character, node2=material,
                                     label1='character', label2='material')
            self.create_relationship(rel_df=char_artifacts, node1=character, node2=artifacts,
                                     label1='character', label2='artifacts')
            """
            weapon-material
            """
            weapon_material = pd.read_csv(str(KG_CSV) + '/rel-weapon-material.csv')
            self.create_relationship(rel_df=weapon_material, node1=weapon, node2=material,
                                     label1='weapon', label2='material')
            """
            master-material
            """
            master_material = pd.read_csv(str(KG_CSV) + '/rel-master-material.csv')
            self.create_relationship(rel_df=master_material, node1=master, node2=material,
                                     label1='master', label2='material')
            """
            food-material
            """
            food_material = pd.read_csv(str(KG_CSV) + '/rel-food-material.csv')
            self.create_relationship(rel_df=food_material, node1=food, node2=material,
                                     label1='food', label2='material')
            """
            instance-material
            instance-artifacts
            """
            instance_material = pd.read_csv(str(KG_CSV) + '/rel-instance-material.csv')
            instance_artifacts = pd.read_csv(str(KG_CSV) + '/rel-instance-artifacts.csv')
            self.create_relationship(rel_df=instance_material, node1=material, node2=instance,
                                     label1='material', label2='instance')
            self.create_relationship(rel_df=instance_artifacts, node1=artifacts, node2=instance,
                                     label1='artifacts', label2='instance')

if __name__ == '__main__':
    # neo4j.del_node(mode='all')
    kg = YuanShen()
    kg.built(relationship=True,node=True)
