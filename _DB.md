# 数据库结构说明

更新：2026-11-13

本文依据[_TDD.md](_TDD.md)、[SQLAlchemy模型](src/modou/models.py)及[0005迁移](migrations/versions/0005_explicit_ids.py)整理，描述PostgreSQL业务表结构，两库已在本轮完成在线结构核验。

数据库包含五张业务表。下文“数据结构”指数据库字段类型；除备注明确标为“可空”的字段外，其余字段均不可空。五表主键分别为`name_id`、`variant_id`、`alias_id`、`sources_id`、`record_id`，均为`BIGINT`自增主键；SQLite测试适配为`INTEGER`。外键均未配置自动级联删除。

## 1. game_name：游戏名称表

保存游戏标准名称，作为规格和别名的归属主体。

| 字段名 | 字段介绍 | 数据结构 | 备注 |
| --- | --- | --- | --- |
| name_id | 游戏唯一标识 | BIGINT | 自增主键 |
| name_zh | 游戏中文标准名 | TEXT | 普通索引`ix_game_name_name_zh`；无唯一约束 |
| name_en | 游戏英文标准名 | TEXT | 可空；普通索引`ix_game_name_name_en`；无唯一约束 |

## 2. game_variant：游戏规格表

保存同一游戏在不同平台、版本下的具体规格。

| 字段名 | 字段介绍 | 数据结构 | 备注 |
| --- | --- | --- | --- |
| variant_id | 规格唯一标识 | BIGINT | 自增主键；与`name_id`组成唯一约束`uq_variant_owner`，供别名复合外键引用 |
| name_id | 所属游戏标识 | BIGINT | 外键→`game_name.name_id`；参与规格联合唯一约束 |
| platform | 游戏平台 | TEXT | 检查约束`ck_platform`，仅允许`PS5`、`PS4`；参与规格联合唯一约束 |
| edition | 游戏版本 | TEXT | 与`name_id`、`platform`组成联合唯一约束`uq_variant_spec` |
| display_name | 前台完整显示名称 | TEXT | 可空；按业务规则，为空时根据游戏名和版本生成，不是数据库默认值 |
| remark | 规格说明 | TEXT | 可空；仅说明规格，不保存报价原文中的史低备注 |

## 3. game_alias：游戏别名表

保存识别入口，可关联整个游戏，也可关联具体规格。

| 字段名 | 字段介绍 | 数据结构 | 备注 |
| --- | --- | --- | --- |
| alias_id | 别名记录唯一标识 | BIGINT | 自增主键 |
| name_id | 别名所属游戏标识 | BIGINT | 外键→`game_name.name_id`；参与别名条件唯一索引及规格归属复合外键 |
| variant_id | 别名指向的具体规格标识 | BIGINT | 可空；外键→`game_variant.variant_id`；为空表示游戏级别名，非空表示规格级别名 |
| alias | 游戏别名或原始名称映射 | TEXT | 普通索引`ix_alias`；同一别名可用于不同游戏或规格，歧义需复核 |

约束及索引说明：

- `fk_alias_variant_owner`：复合外键`(variant_id, name_id)`→`game_variant(variant_id, name_id)`，保证所关联规格属于同一游戏。
- `uq_alias_game`：当`variant_id IS NULL`时，`(name_id, alias)`唯一。
- `uq_alias_variant`：当`variant_id IS NOT NULL`时，`(name_id, variant_id, alias)`唯一。
- 标准名也需要显式别名映射才能通过当前别名识别入口命中；具体识别流程见_TDD.md。

## 4. data_source：数据来源表

保存报价来源链接及时间信息，同一来源可被多条报价引用。

| 字段名 | 字段介绍 | 数据结构 | 备注 |
| --- | --- | --- | --- |
| sources_id | 来源唯一标识 | BIGINT | 自增主键 |
| source_url | 来源链接 | TEXT | 唯一约束；业务层按归一化后的URL复用来源，同一URL不重复插入；不另设`note_id` |
| published_at | 来源准确发布时间 | TIMESTAMPTZ | 可空；带时区时间戳；仅知道日期时留空 |
| recorded_at | 来源首次审核入库时间 | TIMESTAMPTZ | 带时区时间戳；数据库默认`now()`；复用来源时按业务规则不覆盖 |

## 5. m_low_record：报价记录表

保存具体游戏规格在对应区域、获取方式和日期下的人民币报价。

| 字段名 | 字段介绍 | 数据结构 | 备注 |
| --- | --- | --- | --- |
| record_id | 报价记录唯一标识 | BIGINT | 自增主键 |
| variant_id | 报价对应的游戏规格标识 | BIGINT | 外键→`game_variant.variant_id`；参与报价查询联合索引 |
| sources_id | 报价来源标识 | BIGINT | 外键→`data_source.sources_id`；普通索引`ix_price_source` |
| region | 报价所属区域 | TEXT | 参与报价查询联合索引；数据库未设置枚举或取值检查约束 |
| lowprice_cny | 人民币报价金额 | NUMERIC(10,2) | 精确小数，总精度10位、小数2位；检查约束`ck_positive_price`要求大于0；参与报价查询联合索引 |
| lowprice_method | 报价获取方式 | TEXT | 数据库未设置枚举或取值检查约束 |
| lowprice_date | 报价日期 | DATE | 仅保存日期，不含时间；参与报价查询联合索引 |

联合索引`ix_price_lookup`按`(variant_id, region, lowprice_cny, lowprice_date)`排列。本表未设置报价去重唯一约束；史低备注仅保存在本地候审信息中，不写入本表。

## 表间关联与边界

- `game_name`→`game_variant`：一个游戏可拥有多个平台、版本规格。
- `game_name`→`game_alias`：一个游戏可拥有多个别名；别名可通过`variant_id`进一步指向该游戏的具体规格。
- `game_variant`→`m_low_record`：一个规格可拥有多条报价。
- `data_source`→`m_low_record`：一条来源可对应多条报价，每条报价关联一条来源。
- `alembic_version`为Alembic维护的迁移工具表，不计入上述五张业务表。
- 未审核信息保存在本地，不额外建立候审业务表；本次经Karl明确授权将两库结构升级0005；日常操作仍仅限`modou_test`，不得自动同步数据至`modou`。


本次两库已按Karl明确授权完成0005重命名迁移，主键为name_id、variant_id、alias_id、sources_id、record_id。测试库数据与ID保留（59名称、60规格、91别名、152报价、3来源），正式库五表为空；两库结构与模型一致。日常作业仍限modou_test；本次不授权后续正式库操作或数据同步。详见_DB.md及_DEVLOG.md。

专项验证：32项相关测试通过（含modou_test事务回滚集成验证），20项空库PostgreSQL测试排除，未运行全量。快照位于.backup/，结构与数据核验记录位于.tmp/schema-0005/verification.json。
