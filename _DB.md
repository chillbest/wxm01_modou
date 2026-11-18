# 数据库结构说明

## alias全表唯一（0017，2026-11-19）

按Karl要求执行：game_alias.alias改为全表唯一，ORM与0017迁移使用uq_alias(alias)，替代uq_alias_gpc(gpc_id,alias)。实施前只读检查未发现重复alias，未删除或改写既有业务行。modou_test迁移0017命令已完成，正式库未操作。catalog_memory、bangumi_cli及网页入库结构门禁兼容0017。补充跨GPC及同GPC重复alias拒绝测试；按要求未运行测试或修改后验证。当前运行服务尚未重载，新版结构门禁需重载服务后生效。

## 当前补充：main明确存NULL（2026-11-19）

bangumi_main继续使用可空TEXT，无DDL或迁移。动态审核main输入非空的纯半角/全角空格时，草稿以main_explicit_null=true记录人工意图，final.bangumi_main为null，实际入库写SQL NULL。该标志只属于审核草稿，不写入GPC表；后续复用可信GPC保存的NULL即可重建该状态。未填写的null与空串默认仍不满足审核条件。普通单ID及|分隔多ID规则保留。

## 当前补充：黑名单与多main（2026-11-19）

保留game_alias.gpc_id外键，保留gpc_id=-1的专用GPC（name_zh=【黑名单占位】，platform=blacklist）作为黑名单目标；不属于真实产品，不参与目录候选或报价。别名sources_id记录添加时的批次来源，按现有名称规范化规则优先命中；唯一键仍为(gpc_id,alias)，服务端在写锁内避免规范化重名重复。系统占位来源为“系统：黑名单占位”。

bangumi_main仍为TEXT，允许单ID及用|分隔的多ID；合集表示平等的组成游戏，保存时规范化并去重，非合集多ID不推断母子关系。无DDL迁移，modou_test结构仍0016。初始化后9条来源、70条GPC（69条真实产品+1条占位）、71条别名、203条报价；既有业务行未改写。

## 当前外链契约（0016，2026-11-19）

GPC字段gamefaqs_link已通过0016重命名为outlink，含义为产品外链，保存完整HTTP/HTTPS URL，不限定网站。现有链接值原样保留；联合唯一约束改名uq_gpc_bangumi_platform_outlink，仍约束(bangumi_id,platform,outlink)，沿用默认NULL语义。正式库未迁移。

前台保留Bangumi游戏条目识别及可信VGCollect英文名读取；其他HTTP/HTTPS外链直接保存并确认display name，不访问任意网页、不调用AI。GameFAQs自动检索仍限GameFAQs。旧草稿读取时递归兼容旧字段（包括解析基线、候选、回执及人工字段路径），不批量改写历史草稿。

数据库资料手动变化时，旧草稿的身份及共享资料校验继续生效；“重新加载此GPC”按绑定gpc_id读取最新资料，确认差异后替换草稿GPC字段及平台，更新共享资料基线，保留价格/地区/日期/优惠等报价资料。不存在的GPC不能恢复，须重新选择现存产品。

## 当前来源契约（0015）

data_source新增review_batch_id TEXT可空，非空值由uq_source_review_batch唯一约束保护。在线新批次保存8位小写十六进制标识，历史32位标识继续有效；这里只存标识，不保存localhost地址。recorded_at为该审核链接/批次created_at，后续单条或批量提交不更新时间；历史NULL标识来源不回填、不合并、不修改recorded_at。无审核批次的新来源记录实际创建时间，单次提交内部可共享，跨提交不按两小时归并。

0015仅升级modou_test；保留所有既有业务行、主键、外键和序列，无自动降级。原有3条来源在迁移后review_batch_id均为NULL。重复报价跳过不创建来源；GPC与别名始终保留各自首次创建来源。

更新：2026-11-19（modou_test：0017；正式库未同步）

本文描述魔豆项目的 PostgreSQL 业务表结构。数据库包含四张业务表，所有主键均为 `BIGINT` 自增主键；外键均不配置自动级联删除。除明确标注“可空”的字段外，其余字段均不可空。

## 1. game_product_config：游戏产品配置表（GPC）

GPC（Game Product Configuration，游戏产品配置）用于定义游戏的内容版本。游戏颗粒度遵循 Bangumi Subject：不同体量/内容版本如果在 Bangumi 中属于不同 Subject，则分别建立 GPC 记录；同名不同版本通过主/子游戏关系关联。

GPC区分内容版本和游戏平台，地区版本仍位于报价：
- 标准版、终极版等内容版本由不同 GPC 区分。
- PS4、PS5、Switch等游戏平台由GPC中的 `platform` 区分。
- 港版、日版等地区版本由报价记录中的 `region` 区分。

| 字段名 | 字段介绍 | 数据结构 | 备注 |
| --- | --- | --- | --- |
| `gpc_id` | 游戏产品配置唯一标识 | BIGINT | 自增主键 |
| `name_zh` | 游戏产品配置中文标准名 | TEXT | 普通索引 `ix_gpc_name_zh`；无唯一约束 |
| `name_en` | 游戏产品配置英文标准名 | TEXT | 可空；普通索引 `ix_gpc_name_en`；无唯一约束 |
| `bangumi_id` | Bangumi Subject ID | TEXT | 可空；参与三字段联合唯一约束 |
| `bangumi_main` | 主版本或合集组成游戏的Bangumi Subject ID | TEXT | 可空；单ID或多个正整数ID以 `|` 分隔，合集表示平等组成游戏；无外键限制 |
| `note` | 对该游戏产品配置的备注 | TEXT | 可空 |
| `display_name` | 前台显示名称 | TEXT | 可空；为空时直接显示 `name_zh` |
| `outlink` | 游戏产品外链，不限定网站 | TEXT | 可空；完整HTTP/HTTPS URL；modou_test已同步0016，正式库未同步 |
| `platform` | 游戏产品对应的游戏平台 | TEXT | 必填，无默认值；不设置枚举检查；例如PS5、PS4、Switch 2 |
| `type` | 产品类型 | TEXT | 可空，无默认值；仅允许Base、rebase、Expansion、母子集、合集；modou_test已同步0008，正式库未同步 |
| `sources_id` | 首次创建该记录的来源 | BIGINT | 必填；外键→`data_source.sources_id`；复用或更新不覆盖 |

约束及说明：

- `bangumi_id`保存当前GPC对应的Bangumi Subject ID；可空，不再单列唯一。
- 联合唯一约束 `uq_gpc_bangumi_platform_outlink`：`(bangumi_id, platform, outlink)`；三个字段均非空且完全相同时禁止重复。采用PostgreSQL默认NULL语义，含NULL的组合允许重复。
- `bangumi_main` 保存主版本对应的 Bangumi Subject ID；主版本自身保存自身bangumi_id，子版本填写主版本的 `bangumi_id`。
- `bangumi_main` 仅保存主版本Subject ID，不要求对应主版本已存在于GPC表。
- `bangumi_id` 与 `bangumi_main` 均使用 `TEXT`，将 Bangumi Subject ID 作为外部标识符保存。
- `display_name` 仅控制前台显示名称，不改变 GPC 标准名称及 Bangumi Subject 对应关系。
- `outlink` 保存完整URL，例如 `https://gamefaqs.gamespot.com/ps5/324823-ghost-of-tsushima-iki-island`。

## 2. game_alias：游戏别名表

保存游戏产品配置的名称识别入口。每条别名只关联一个GPC；平台通过GPC确定，地区由报价确定。

| 字段名 | 字段介绍 | 数据结构 | 备注 |
| --- | --- | --- | --- |
| `alias_id` | 别名记录唯一标识 | BIGINT | 自增主键 |
| `gpc_id` | 别名所属游戏产品配置标识 | BIGINT | 外键 → `game_product_config.gpc_id` |
| `alias` | 游戏别名或原始名称映射 | TEXT | 普通索引 `ix_alias` |
| `sources_id` | 首次创建该记录的来源 | BIGINT | 必填；外键→`data_source.sources_id`；复用或更新不覆盖 |

约束及说明：

- 唯一约束 `uq_alias`：`alias` 全表唯一（0017）。
- 删除原 `variant_id`、`name_id` 字段及其相关外键。
- 同一个别名可以对应不同的 GPC；如果产生多个候选，必须复核，不能任意选择。
- 标准名称如需通过别名识别入口命中，也应显式建立对应别名记录。

## 3. data_source：数据来源表

保存报价来源。来源可以是网络 URL，也可以是本地文件相对路径；同一来源可被多条报价记录引用。

| 字段名 | 字段介绍 | 数据结构 | 备注 |
| --- | --- | --- | --- |
| `sources_id` | 来源唯一标识 | BIGINT | 自增主键 |
| `source_path` | 来源地址或文件路径 | TEXT | 允许重复；来源归组由review_batch_id决定，不使用时间窗口 |
| `published_at` | 来源发布日期 | DATE | 可空；URL 来源填写发布日期；TXT 文件来源填写标题中表达的日期 |
| `recorded_at` | 审核批次创建时间；非审核入口为来源创建时间 | TIMESTAMPTZ | 必填；历史时间保留；同批次复用不更新 |
| `review_batch_id` | 动态审核批次标识 | TEXT | 可空；8位新标识或32位历史标识；唯一约束`uq_source_review_batch`，NULL可重复 |

约束及说明：

- `source_path`无唯一约束；非空`review_batch_id`唯一，同一审核批次跨事务复用来源，不同批次分别记录。历史NULL行及无审核批次入口不按时间自动归并。
- `source_path` 可以是完整 URL，也可以是带相对路径的文件名，例如 `data/xhs/2026-11-13/example.txt`。
- `published_at` 类型为 `DATE`，只保存日期，不保存时刻；无法确定日期时留空。
- 对 URL 来源，`published_at` 表示来源发布日期；对 TXT 文件来源，表示 TXT 标题中表达的日期。
- 一篇笔记或一个 TXT 来源可以对应多条报价；不另设 `note_id`。
- `recorded_at`记录审核批次创建时间，由持久化batch.created_at传入；非审核入口记录创建来源时间。复用不更新，保留历史来源及时间。重复报价跳过时不创建来源。

## 4. m_low_record：报价记录表

保存某个GPC对应游戏在指定地区版本、获取方式和日期下的人民币报价；游戏平台通过关联GPC读取。

| 字段名 | 字段介绍 | 数据结构 | 备注 |
| --- | --- | --- | --- |
| `record_id` | 报价记录唯一标识 | BIGINT | 自增主键 |
| `gpc_id` | 报价对应的游戏产品配置标识 | BIGINT | 外键 → `game_product_config.gpc_id`；参与报价查询联合索引 |
| `sources_id` | 报价来源标识 | BIGINT | 外键 → `data_source.sources_id`；普通索引 `ix_price_source` |
| `region` | 地区版本 | TEXT | 例如港版、日版、欧版、国行、韩版、美版；参与报价查询联合索引 |
| `lowprice_cny` | 人民币报价金额 | NUMERIC(10,2) | 精确小数；检查约束 `ck_positive_price`，要求大于 0；参与报价查询联合索引 |
| `lowprice_method` | 报价获取方式 | TEXT | 直接购买存字符串“直接购买”；ck_price_method_nonempty禁止空白，不设置枚举 |
| `lowprice_date` | 报价日期 | DATE | 仅保存日期；参与报价查询联合索引 |

约束及索引说明：

- `gpc_id` 外键指向 `game_product_config.gpc_id`。
- 本表已删除 `platform`；平台由关联GPC提供。
- `region` 表示地区版本，例如港版、日版，不表示游戏平台。
- `ix_price_lookup` 联合索引按 `(gpc_id, region, lowprice_cny, lowprice_date)` 排列。
- `ix_price_source` 为 `sources_id` 建立普通索引。
- 本表不设置报价去重唯一约束；去重由业务事务入口处理。
- 所有审核通过的有效报价均保留，不因出现更低价格而覆盖或删除历史记录。
- 史低备注仅供本地候审核对，不写入本表。

## 5. 表间关系

- `game_product_config` → `game_alias`：一个 GPC 可以拥有多个别名；每条别名属于一个 GPC。
- `game_product_config` → `m_low_record`：一个 GPC 可以拥有多条报价记录；每条报价记录属于一个 GPC。
- `data_source` → `m_low_record`：一个来源可以被多条报价记录引用；每条报价关联一个来源。
- `game_product_config.bangumi_main` 为逻辑主子关联，无数据库外键；主版本自身保存自身bangumi_id。
- 所有外键均不配置自动级联删除。

## GPC产品类型（0008）

| 值 | 解释 |
| --- | --- |
| `Base` | 标准主版本 |
| `rebase` | 变基版。同一游戏的增强或修订内容版本；确认不包含可识别的剧情扩展包。豪华版、导演剪辑版名称本身不决定类型 |
| `Expansion` | 内容扩展（剧情DLC） |
| `母子集` | 特指“Base版/rebase版+Expansion版”的产品合集（年度版、完整版） |
| `合集` | 不同游戏产品的合集 |

CHECK约束ck_gpc_type严格区分大小写；NULL表示未分类，不自动填Base。type与bangumi_main分别描述产品类型和主版本归属，不推导彼此，也合集可通过bangumi_main的多个ID表示收录游戏。类型先按实际资料执行明确规则，否则由DeepSeek基于证据判断；证据不足留空并提供有依据的备选，最终人工审核。

## 来源与时间（0012）

GPC、别名和报价均通过sources_id关联data_source，用来源recorded_at表示审核批次创建时间（历史来源保留原时间），published_at表示来源发布日期。三表均无created_at。GPC及别名保存首次创建该记录的来源，后续复用和资料更新不覆盖；新别名可以关联不同于GPC的来源。外键均为必填BIGINT，无默认值，不级联删除。

手动新增且没有笔记来源时，source_path="手动插入"。现行0015规则按审核批次标识复用来源；非网页入口只在单次提交内共享来源；GPC及别名仍保留首次创建来源。直接SQL插入须显式填写sources_id。

0012仅允许modou_test；锁表后要求目标三表为空再删除created_at、为GPC/别名增加sources_id，避免丢失已有时间或伪造历史来源。不支持自动降级；正式库未同步。

## 来源提交与报价判重（0013）

0013仅用于modou_test，保留历史数据、外键及序列，取消data_source.source_path唯一约束；不自动降级。应用对报价按gpc_id、region、lowprice_cny、lowprice_method、lowprice_date跨来源判重，重复复用已有记录且不新增来源；数据库允许保留既有重复报价。GPC身份约束不变，准备新增同bangumi_id及platform的不同身份GPC时，网页要求确认相似记录。


## 审核展示与数据语义修正（f3a82c19，2026-11-17）

0014仅用于modou_test，将m_low_record.lowprice_method原空字符串改为“直接购买”，增加ck_price_method_nonempty约束length(trim(lowprice_method))>0；无默认值、无枚举，NULL仍由NOT NULL拒绝。迁移不改主键、来源关系或序列，不自动降级；正式库未迁移。
