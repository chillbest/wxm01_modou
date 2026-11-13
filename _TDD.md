# 魔豆一期｜TDD 技术设计文档

> 版本：v1.14.0（表名及主键显式命名）  
> 日期：2026-11-13  
> TDD = Technical Design Document（技术设计文档），与测试驱动开发方法 Test-Driven Development 不同。  
> 基准：同版本《魔豆一期 PRD》；实现细节在开发阶段以测试和真实 API 响应校准。

## 1. 总体方案

### 1.1 架构决策

采用**模块化单体（Modular Monolith）+ 独立 NAS 采集进程**，而不是微服务集群。

- **线上查询端：**微信原生小程序 + TypeScript / Vant Weapp。
- **云端 API：**Python FastAPI，运行于 CloudBase 云托管，统一负责查询、史低计算和经审核批次导入。
- **正式数据库：**新建 CloudBase **PG 模式**环境中的 PostgreSQL，SQLAlchemy 2.x + Alembic；**五张业务表**：game_name、game_variant、game_alias、m_low_record、data_source。
- **采集/解析/审核端：**群晖 DS923+，Docker Compose 部署 Python 进程及本地管理页面。
- **外部服务：**Qovia API 读取小红书；DeepSeek API 处理名称/版本语义；Gmail SMTP 发送审核报告，IMAP + OAuth 2.0 接收确认邮件。
- **重要限制：**NAS 未确认的结果只存在本地 JSON 文件；NAS 不直接连接并写入正式 PostgreSQL。批准后经受保护的云端导入 API 写库。

CloudBase 官方已提供 PG 模式、PostgreSQL 协议访问及容器化 Python 服务支持。PG 模式仅能在**新建环境**时选择；`pg_trgm` 的可安装性仍需在具体环境中验证。

### 1.2 系统组件与数据流

```text
                         [普通用户]
                             │
                   微信小程序 TypeScript
                             │ wx.cloud.callContainer
                             ▼
                  CloudBase 云托管 / FastAPI
                       ├─ 搜索与史低计算
                       ├─ 只读查询接口
                       └─ 受保护的审批导入接口
                             │
                             ▼
                   CloudBase PostgreSQL
                   （仅有已审核正式数据）

  群晖 NAS / Docker
      ├─ APScheduler ─→ Qovia（每天 08:00 起/每 30 分钟/正则命中即停）
      ├─ Python 解析器 ─→ 别名匹配 / DeepSeek
      ├─ Pydantic 校验 ─→ 本地 JSON 候审区
      ├─ 邮件发件器 ─→ Gmail SMTP ─→ 管理员邮箱
      ├─ 邮件收件器 ←─ Gmail IMAP ←─ 人工确认回复
      └─ Jinja2 + HTMX 后台 ←─ 管理员人工修正
                │ 仅在有效审核后
                └───── HTTPS 签名请求 ─────→ 云端审批导入接口
```

## 2. 软件分层与依赖约束

### 2.1 四层代码架构

| 层级 | 职责 | 不允许做的事 |
| --- | --- | --- |
| Presentation（接口/页面层） | FastAPI 路由、请求参数、响应 DTO、Jinja2/HTMX 页面 | 在路由中直接写 SQL 或调用大模型 |
| Application（应用用例层） | 编排搜索、解析、审批、导入等用例；事务边界 | 含微信 UI 代码或耦合具体第三方 SDK |
| Domain（领域层） | 游戏版别、价格比较、来源规则、审核状态与业务校验 | 直接访问数据库、Qovia 或 Gmail |
| Infrastructure（基础设施层） | PostgreSQL、文件仓库、Qovia/DeepSeek/Gmail 适配器、日志 | 改写领域规则 |

**依赖方向：**外层依赖内层；领域层不反向依赖接口层或数据库实现。跨模块通过应用服务/公开契约交互，禁止直接引用其他模块的私有实现。

### 2.2 业务模块职责（与 PRD 编号一致）

| 模块编号 | 业务模块 | 主要技术组件 | 输入 | 输出与约束 |
| --- | --- | --- | --- | --- |
| M01 | 游戏目录与史低规则 | `Catalog`、`Pricing`（云端领域与应用服务） | 游戏/别名、已批准报价及来源 | 五表保存全部已审核报价与来源；只在查询时计算史低 |
| M02 | 规则与 AI 解析 | `Parsing`（NAS） | 新笔记正文、别名字典 | 结构化候审条目及异常；AI 建议需再次校验 |
| M03 | 历史数据导入 | 历史采集入口、`Review`/`Import` 最小能力 | 指定博主历史笔记、人工确认 | NAS 候审批次；经明确批准后由云端 API 原子导入 |
| M04 | 小程序搜索与展示 | 微信小程序、FastAPI 查询接口 | 游戏关键词 | 匹配结果、分版本史低、日期、来源 |
| M05 | 每日采集 | `Collection`、APScheduler（NAS） | 博主 ID、匹配正则、当天监控状态 | 08:00 起每 30 分钟检查，首次命中即停；一天至多解析一篇，产出本地候审数据 |
| M06 | 管理后台 | `Admin`、`Review`（NAS） | 候审批次、人工修正与确认 | 审核页面、纠错结果、授权导入和留痕 |
| M07 | 邮件审核与确认 | `Notification`、`Review`（NAS） | 候审报告、管理员回复 | 邮件通知、有效审批事件、导入结果反馈 |

**依赖与实施约束：**M01 先定义数据与计算规则，M02 在独立样本上验证解析；M03 只实现人工审核所需的最小确认/导入接口，M06 将其扩展为管理页面，M07 再增加邮件审批入口。M05 在 M07 完成前仅产出本地候审批次。三个审批入口最终共用同一 `Review → Import` 授权门禁和云端事务性导入逻辑，不重复实现绕过审核的写库路径。


### 2.3 推荐仓库结构

```text
modou/
├── README.md
├── AGENTS.md                 # Codex 开发边界和工程规则
├── docs/
│   ├── PRD.md
│   └── TDD.md
├── apps/
│   ├── miniprogram/          # M04：微信原生 TypeScript + Vant Weapp
│   │   ├── pages/
│   │   ├── components/
│   │   └── services/         # API 访问封装
│   ├── api/                  # 云端 FastAPI（模块化单体）
│   │   ├── app/
│   │   │   ├── modules/
│   │   │   │   ├── catalog/   # M01：低价记录主表、别名表、来源表
│   │   │   │   │   ├── domain/
│   │   │   │   │   ├── application/
│   │   │   │   │   ├── infrastructure/
│   │   │   │   │   └── presentation/
│   │   │   │   ├── pricing/   # M01：史低规则；内部同样四层
│   │   │   │   └── imports/   # M03/M06/M07 共用受保护导入
│   │   │   └── bootstrap/     # 配置、依赖注入、应用启动
│   │   ├── alembic/
│   │   └── tests/
│   └── worker/               # 群晖 NAS 进程
│       ├── app/
│       │   ├── collection/    # M03 历史采集 / M05 每日采集
│       │   ├── parsing/       # M02
│       │   ├── review/        # M03 最小审核 / M06 后台 / M07 邮件审批
│       │   ├── notification/  # M07
│       │   ├── admin/         # M06
│       │   └── infrastructure/
│       └── tests/
├── packages/
│   └── contracts/            # OpenAPI / JSON Schema；两端共用契约
├── deploy/
│   ├── cloudbase/
│   └── nas/
└── tests/                    # 跨服务集成与端到端验收
```

说明：代码目录使用稳定的业务语义名称，注释中的 `M01`～`M07` 才是 PRD 中的**开发顺序编号**；不要求为了编号重命名所有代码包，也不要求提前创建空模块。共同规则优先放在稳定的契约/领域层，避免重复拷贝。

## 3. 业务数据模型（正式 PostgreSQL）

### 五张业务表与完整字段

五表主键分别为name_id、variant_id、alias_id、sources_id、record_id，均为BIGINT自增主键；外键不自动级联删除。除明确可空的字段外均为必填。

| 表 | 字段与类型 |
| --- | --- |
| game_name | name_id BIGINT；name_zh TEXT；name_en TEXT可空 |
| game_variant | variant_id BIGINT；name_id BIGINT→game_name.name_id；platform TEXT（PS5/PS4）；edition TEXT；display_name TEXT可空；remark TEXT可空 |
| game_alias | alias_id BIGINT；name_id BIGINT→game_name.name_id；variant_id BIGINT→game_variant.variant_id可空；alias TEXT |
| m_low_record | record_id BIGINT；variant_id BIGINT→game_variant.variant_id；sources_id BIGINT→data_source.sources_id；region TEXT；lowprice_cny NUMERIC(10,2)且大于0；lowprice_method TEXT；lowprice_date DATE |
| data_source | sources_id BIGINT；source_url TEXT唯一；published_at TIMESTAMPTZ可空；recorded_at TIMESTAMPTZ默认当前时间 |

- game_variant以(name_id, platform, edition)唯一；display_name为前台完整显示名，为空时按游戏名和版本生成。remark仅说明规格，不存报价原文中的史低备注。
- game_alias.variant_id为空时，alias指向name_id对应的游戏；非空时指向具体规格。复合外键(variant_id,name_id)保证该规格属于同一name_id，另有独立外键验证name_id和variant_id。
- 游戏级别名以(name_id,alias)条件唯一；规格级别名以(name_id,variant_id,alias)条件唯一。同一alias可用于不同游戏/规格，出现歧义必须复核。
- source_url在归一化后作为唯一依据，不设note_id。一篇笔记共用一条来源，多条报价通过sources_id引用；相同URL不重复插入。
- published_at只保存已知的准确发布时间，只有日期时留空；报价日期仍可使用已确认发布日期。recorded_at为来源首次审核入库时间，复用来源时不覆盖。
- 未审核信息只存本地；正式写入按目录、规格、来源、报价、别名的依赖顺序，在同一审批事务完成。史低备注仅供候审核对，绝不写业务表或单独构造报价。
- alembic_version是迁移工具表，不计入五张业务表。

### 查询与持久化

search_games从game_name与game_variant查询，即使尚无报价也返回目录结果；匹配游戏级别名时返回该游戏各平台，匹配规格别名时只命中该规格，再按游戏名和平台归并。

lowest_prices将m_low_record→game_variant→game_name关联，按中文名、平台、edition筛选，地区分组取最低价，同价按日期降序、ID降序。查询仍返回(PriceRecord, region_group, source_url, recorded_at)四元组；名称/平台/版本不再是PriceRecord属性。公开API在M04组装目录字段与显示名。

save_observation接收已确认variant_id、归一化source_url、region、lowprice_cny、lowprice_method、lowprice_date及可选published_at。复用同URL来源；同来源同规格同报价字段复用报价，不同来源保留。PostgreSQL按固定顺序锁data_source和m_low_record，调用方必须整批事务提交。未知字段不能直接传入，备注不接受为入库参数。

```sql
SELECT r.record_id, n.name_zh, v.platform, v.edition, v.display_name,
       r.region, r.lowprice_cny, r.lowprice_method, r.lowprice_date,
       s.source_url, s.recorded_at
FROM m_low_record r
JOIN game_variant v ON v.variant_id = r.variant_id
JOIN game_name n ON n.name_id = v.name_id
JOIN data_source s ON s.sources_id = r.sources_id
WHERE n.name_zh = :name_zh AND v.platform = :platform AND v.edition = :edition
ORDER BY r.lowprice_cny, r.lowprice_date DESC, r.record_id DESC;
```

## 4. NAS 数据处理与审核设计

### 4.1 采集机制

**历史导入（M03）：**Qovia `user_notes` 分页获取指定博主的历史笔记 ID，再对每篇未解析笔记逐一调用 `note` 详情接口取得完整正文；成功解析后在 NAS 本地记下笔记 ID，不重复解析。

**每日监控（M05）：**

1. 使用 `Asia/Shanghai` 时区，每天 **08:00** 启动；若未发现目标新帖，于 08:30、09:00 …… **23:30** 每隔 **30 分钟**检查一次。到当日结束停止；次日 08:00 重启当天任务。
2. 用 Qovia `user_notes` 查询指定博主新发布且尚未处理的笔记，用可配置的 `note_match_regex` 匹配笔记的指定字段（优先利用列表标题等元数据），并排除 NAS 本地已解析 ID。正则内容及匹配字段由开发/部署时配置；若列表不足以判断，可读取候选笔记详情核验，但只解析最终锁定的一篇。
3. 一旦发现符合正则的新笔记，**立即锁定该笔记 ID 并停止当天其他笔记的发现**；随后调用 `note` 详情接口取得完整正文，交给解析器生成候审 JSON。一整天**最多选择并解析一篇笔记**，但同篇笔记的所有游戏报价都要解析。
4. 如该笔记的详情获取或解析失败，仅对**当天锁定的同一笔记**进行有限次数重试/人工修复，不在当天改选第二篇；避免失败重试造成多帖解析。成功解析并持久化候审 JSON 后才记为 `processed_note_id`。
5. 已解析笔记永久跳过：即使作者编辑正文，也不查询修改、不重新调用详情接口、不重新解析。
6. NAS `state/` 保存已解析 ID、当天命中笔记 ID 与监控停止状态，保证容器重启后同日不误解析第二篇。调度任务不允许重叠执行。

`user_notes` 用于发现新帖、读取 ID 及所需元数据；**每篇锁定的笔记必须调用 `note` 详情接口获取完整正文**，不使用列表正文代替。若列表缺少筛选所需字段，可通过详情接口核验候选，但价格解析仍只针对当日锁定的唯一笔记。跨夜发布且尚未处理的新帖，次日首次检查仍纳入候选，避免漏掉前一日最后一次轮询之后的笔记。

### 4.2 解析流水线

```text
新笔记正文
  → 分区定位（如“实时新增”“福袋8折减80”“积/v3区”）
  → 每行提取游戏名、地区标识、当前价、附注
  → game_alias.alias入口精确匹配
  → 未命中、歧义或规格冲突项请求DeepSeek（仅建议游戏和版别）
  → Pydantic 结构校验与业务校验
  → 生成候审记录、异常明细、报告
```

**规则边界：**Python 负责可以确定的字符格式与数值；AI 只做语义辅助，不应擅自补造日期、价格、商品规格或优惠条件。所有 AI 结果必须再次校验，置信度不足应标记待核对。

**优惠方式名称：**无论原文分区标题是简称还是带“区”字的写法，只要符合该优惠类型的识别规则，`lowprice_method` 统一填写 **“福袋8折减80”**，不将原始分区缩写作为用户展示名称。

**解析样例：**

原文：`🔸羊蹄山之魂完全版｜🇭🇰265｜史低257`，对应优惠方式归一名称：`福袋8折减80`。

提取：游戏名“羊蹄山之魂”、版本“完全版”、地区“港版”、本次价 265 元、优惠方式“福袋8折减80”、博主提及史低 257 元。若 ¥257 缺少可核对日期/优惠方式，**不能**据此伪造一条完整价格记录；本次可确认的 ¥265 **无论是否史低都要保存**。

区域标记`UN`/`🇺🇳`归一为“海外版”，表示非国行、非港版但具体地区未确定；不得归一为“欧版”。`EU`/`🇪🇺`才表示“欧版”。未知地区标记进入人工复核。

### 4.3 本地候审文件与状态

推荐 NAS 持久化目录：

```text
/volume1/docker/modou/
├── data/
│   ├── source/          # 首次采集的笔记原文
│   ├── review/          # 候审批次 JSON、报告及人工修改稿
│   ├── archive/         # 已审批批次、导入回执
│   └── state/           # 已解析笔记 ID、每日监控与已锁定目标状态
├── logs/                # 导入与人工纠错操作日志
└── compose.yaml
```

待审 JSON 包含 `batch_id`、`note_ids`、每篇笔记的 `source_url`、`items`、`validation_errors`、`payload_sha256`、`created_at`。状态和操作记录只在 NAS 上，不额外创建正式数据库表。文件写入宜采用临时文件 + 原子改名，并进行备份。

**本地状态：**`draft → approved → importing → imported`；邮件通知后可标记 `notified`；失败标记 `failed`。仅审核通过的批次能提交云端导入。

### 4.4 邮件审批协议

1. 发送邮件标题包含唯一批次号，正文包含数据明细、来源、警告、审批指令及后台修改入口。
2. 一期推荐指令格式：`CONFIRM <batch_id> <一次性验证码>`（独立一行），其中验证码仅在受保护的本地审批准入记录中校验；最终格式由实施时固定。
3. NAS 通过 Gmail IMAP（OAuth 2.0）轮询回复，核对**授权邮箱、对应邮件会话、批次号、一次性验证码、未使用状态、候审文件哈希**。
4. 审核过程中如果候审文件被修改，旧邮件指令立即失效；必须重新生成报告/指令或通过管理后台人工提交。
5. 审批通过后，先重新校验所有条目，再以签名 HTTPS 请求把**已审批**批次提交给云端 API；收到成功回执才标记 `imported`。
6. 同一消息、批次或导入请求再次到来，只返回已完成结果，不再次入库。
7. 无效命令、不明发件人、超期/已使用验证码、包含未解决异常的批次：**拒绝执行**并记录原因。

**安全提示：**仅检查发件人地址不够；邮件确认属于授权操作，必须采用一次性凭据与批次内容绑定。验证码或凭证不得输出到普通调试日志。

### 4.5 有误数据的人工纠错

- 管理后台 Jinja2 + HTMX 在 NAS 私有管理入口提供：原文对照、候审列表、字段编辑、重新校验、预览变更和“确认手动导入”。
- 管理员修改的仍是**NAS 本地 JSON**，不是正式数据库中的候审记录。
- 修改后生成新 `payload_sha256`，原邮件指令作废；管理员在后台重新确认并手动提交云端导入 API。
- 若发现已入库的报价记录错误，可经管理员确认后**按 `m_low_record.record_id`** 更正该条，在 NAS 本地留下旧值、新值、时间及原因日志；其他报价行完全保留。

## 5. 云端接口设计（示意契约）

| 方法与路径 | 使用方 | 用途 |
| --- | --- | --- |
| `GET /api/v1/games/search?q=...` | 小程序 | 中文名、英文名及别名搜索，按游戏和平台归并结果 |
| `GET /api/v1/prices/lowest?name_zh=...&platform=...&edition=...` | 小程序 | 从全部报价中计算国行/港版/海外版史低及对应日期、方式、来源 |
| `GET /internal/v1/catalog/aliases` | NAS（授权） | 读取已审核别名参考表 |
| `POST /internal/v1/import-batches` | NAS（已获批） | 受保护地批量**插入所有有效报价**及别名 |

由于 `m_low_record.record_id` 标识**某一条报价记录**，不是游戏唯一 ID，所以不使用 `GET /games/{id}/lowest` 设计。若将来增加历史报价页，可直接从 `m_low_record` 分页查询，无需新建价格历史表。

### 5.1 查询返回约定

公开查询的单条史低结果可包含：`name_zh`、`name_en`、`platform`、`region_group`、`region`、`edition`、`lowprice_cny`、`lowprice_method`、`lowprice_date`、`source_url`、`observation_id`。

其中三个 `lowprice_` 字段来自查询时胜出的最低报价行；`source_url` 由关联的 `data_source` 表返回，`observation_id` 指向 `m_low_record.record_id`。地区显示组由查询服务计算。没有匹配数据则返回空结果，不推断价格或券资格。

### 5.2 审批导入约定

- NAS 通过 HTTPS 请求受保护导入 API；云端验证授权凭证及请求真实性，普通小程序用户无写入权限。
- 请求包含 `batch_id`、`payload_sha256`、批准信息、全部已校验报价及别名记录。批次状态和回执保存在 NAS 本地文件，**不建 `import_batches` 表**。
- 云端再次使用 Pydantic 校验必填字段、日期、金额、平台、地区及来源链接，拒绝未获批准的数据。
- **同一审批事务中**维护已确认目录与规格，复用或新建唯一来源，再通过save_observation追加或复用报价，维护别名。任何一步失败整批回滚。来源URL须由M03归一化。
- 重试去重依赖NAS批次回执与save_observation原语；同来源同报价返回既有行，不同来源保留。禁止绕过该入口直接写入报价与来源。
- 已入库记录纠错须管理员授权并按 `m_low_record.record_id` 精确更新，留 NAS 本地日志；普通导入只追加不修改已有报价。

### 5.3 小程序访问与权限

小程序通过 `wx.cloud.callContainer` 调用 CloudBase 云托管 FastAPI，**不直接持有 PostgreSQL 写入凭证**。普通用户只能访问只读查询接口，管理能力不暴露给普通用户。

## 6. 索引与性能设计

- game_name.name_zh/name_en和game_alias.alias有搜索索引；规格唯一索引及别名分层条件唯一索引见第3节。
- m_low_record组合索引(variant_id,region,lowprice_cny,lowprice_date)及sources_id索引；不按规格限制报价行数。
- 跨表去重由事务入口完成；data_source.source_url唯一，m_low_record.sources_id可重复引用。
- 中文模糊搜索可评估 `pg_trgm`；若 CloudBase 环境不支持，采用精确/前缀匹配及受控 `ILIKE`，不阻塞一期上线。
- 从m_low_record关联game_variant、game_name与data_source查询全部已审核报价并分组取最低价，不增设缓存表。

## 7. 工程规范与测试策略

### 7.1 工程纪律

- 单一 Git 仓库管理前端、云端、NAS 进程与契约；开发/测试/正式环境隔离。
- 外部 API 和数据库调用必须经适配器；从环境变量/安全配置读取 Qovia、DeepSeek、Gmail、CloudBase 凭证。
- 用 Alembic 统一管理**业务表**迁移，避免与 CloudBase 自身系统 schema/迁移工具重复管理相同对象。
- OpenAPI/Pydantic 定义 API 契约，小程序 TypeScript 类型由契约生成或同步检查；变更要保持向后兼容。
- Python 测试：pytest；格式与静态检查可采用 Ruff 和类型检查；CI 运行单元及契约测试后才允许部署。
- 日志包含 `job_id`、`note_id`、`batch_id`、`request_id`，不得包含 API Key、完整邮箱令牌或一次性审批码。

### 7.2 关键测试矩阵

| 测试类型 | 必测案例 |
| --- | --- |
| 数据结构测试 | 五张业务表、完整字段、来源URL唯一、报价sources_id外键、别名规格归属、条件唯一约束 |
| 解析单测 | 多栏目、“福袋8折减80”统一命名、版本后缀、不同地区旗帜、`凑-50`、缺字段、历史史低备注不误当完整报价 |
| 名称识别单测 | 中文名/英文名/别名命中、同名不同平台、AI 不确定时人工复核 |
| 全量保存测试 | 同规格五次报价 ¥180、¥160、¥170、¥140、¥155 全部保留，不能因价格较高而丢弃 |
| 史低查询测试 | 五条均在库时返回 ¥140；同价取较晚日期；国行/港/台/海外分类正确；不同平台/版本不混算 |
| 采集集成测 | 北京时间 08:00 首查；未命中每 30 分钟轮询到 23:30；配置正则过滤；命中立即停止、每日最多解析一篇；仅对锁定笔记重试；旧帖修改跳过 |
| 审批安全测 | 未审核不得写五张业务表、伪造发件人、错误批次/验证码、候审文件修改后旧码失效 |
| 导入集成测 | 五表审批事务、同篇笔记多报价共用来源、重复批次去重、日期含义区分、出错整体回滚 |
| 管理纠错测 | 按记录 ID 纠错、其他报价不受影响、NAS 本地留下修改前后日志 |
| 小程序端到端 | 输入别名→匹配游戏→从全量报价选出史低→展示日期、优惠方式与来源链接 |

**CI 核心门禁：未经人工审批不得写正式业务表；完整已审核报价不得因不是史低而被过滤或覆盖。**

## 8. 部署与运维

### 8.1 CloudBase

- 创建**新的 PG 模式云开发环境**，部署 PostgreSQL 与 FastAPI 云托管容器；小程序关联目标环境。
- 只允许云端 API 使用必要的数据库写权限；公开查询角色只读；不将 `service_role` 或数据库连接串放入小程序。
- 验证 CloudBase 实例连接、SSL/网络、数据库迁移、扩展安装权限和备份策略。

### 8.2 群晖 DS923+

- Docker Compose 部署采集/解析/邮件审核进程与私有管理入口，挂载 `data/` 和 `logs/` 到 NAS 持久化目录。
- APScheduler 每天北京时间 08:00 启动监控，未命中每 30 分钟轮询至 23:30，命中后停止当天其他笔记发现；邮件检查独立轮询，不与采集冲突。
- 设置错误重试、任务互斥、健康检查、日志轮转、JSON 文件备份及故障告警。
- NAS 对 CloudBase 只开放最小必要的**出站 HTTPS**；管理后台限制在受保护的私有网络/登录方式。

### 8.3 故障原则

1. Qovia / DeepSeek 不可用：保留原文/已有工作文件，标记失败，稍后重试；不产生正式写入。
2. 发邮件失败：保存候审批次并重试发送，不丢弃可审核数据。
3. 管理员尚未回复：保持本地待审，正式数据不变。
4. 云端导入超时：按批次回执和事务性报价去重入口确认/重试，禁止生成重复行。
5. 已解析笔记被作者修改：直接忽略，不再采集或解析，不影响现有正式史低。

## 9. 实施顺序（严格按 PRD 优先级）

| 顺序 | 模块 | 主要开发内容 | 完成判定 |
| --- | --- | --- | --- |
| 1 | M01 游戏目录与史低规则 | 五表目录、规格、别名、共享来源及全量报价 | 迁移及回归通过，最低价查询正确 |
| 2 | M02 规则与 AI 解析 | 栏目与行解析、别名匹配、DeepSeek、Pydantic 校验 | 真实文本能输出候审 JSON；未知字段不被虚构 |
| 3 | M03 历史数据导入 | Qovia 历史获取、候审文件、最小人工确认工具、受保护导入 API | 未批准不入库；批准历史批次后可安全、幂等导入 |
| 4 | M04 小程序搜索与展示 | 微信 TypeScript 页面、搜索 API、史低/日期/优惠方式/来源展示 | 用已导入历史数据完成小程序查询全链路 |
| 5 | M05 每日采集 | 08:00 起每 30 分钟监控、正则匹配、首次命中即停、同日目标锁定与重启恢复 | 当日最多解析一篇新帖并产出本地候审 JSON，**不自动入库** |
| 6 | M06 管理后台 | Jinja2 + HTMX、审核列表、原文对照、字段编辑、手动确认 | 管理员可纠错并留痕导入；复用 M03 审批门禁 |
| 7 | M07 邮件审核与确认 | Gmail SMTP/IMAP、批次报告、一次性回复指令、自动提交回执 | 邮件回复经完整身份/批次校验后只导入一次 |

**阶段依赖解释：**M03 交付的是最小可用人工核对与导入能力，M06 再开发完整管理后台；M05 可独立定时采集并落本地 JSON，待 M07 完成后启用邮件提醒/回复确认。此顺序与正式业务库“审核前零写入”的要求兼容，不意味着允许 M03 或 M05 绕过审批。

## 10. 已决定与开发时验证的事项

**已决定：**微信原生 TypeScript、Vant Weapp、FastAPI、PostgreSQL、SQLAlchemy/Alembic、Python 规则解析、DeepSeek、Qovia、NAS Docker、Gmail 邮件审批、Jinja2+HTMX、pytest、CloudBase。

**开发时验证：**Qovia 列表分页和详情接口字段稳定性、详情接口能否返回目标博主的完整正文、PS5 实体版识别、日期确认规则、CloudBase `pg_trgm` 权限、Gmail IMAP OAuth 2.0 授权与运行方式，以及真实 API 性能。

**后续扩展点：**若升级为 ClawBot/微信审核，只替换 `Notification` 与 `Review` 的输入适配器；保持 `Review → Import` 授权门禁不变。若增加历史价格明细页，可直接查询已保存的 `m_low_record`，无须再建历史价格表。

## 11. 官方技术参考

- [CloudBase 新建 PG 模式环境](https://docs.cloudbase.net/quick-start/create-env)
- [CloudBase PostgreSQL 连接方式](https://docs.cloudbase.net/database/postgresql/connecting-to-postgresql)
- [CloudBase 云托管 Python 部署](https://docs.cloudbase.net/run/quick-start/dockerize-python)
- [CloudBase 小程序调用云托管](https://docs.cloudbase.net/run/develop/access/mini)
- [Qovia 小红书 user_notes](https://www.qovia.ai/zh/docs/api-reference/raw.xiaohongshu.user_notes/)
- [Qovia 小红书 note](https://www.qovia.ai/zh/docs/api-reference/raw.xiaohongshu.note/)

## 12. 实际工程与迁移

- Python3.13.18、uv、uv.lock；最小工程src/modou，测试test/。Windows虚拟环境不复制到Linux部署。
- 0001—0003保留迁移历史；0004锁定三张旧业务表并检查为空，再事务性替换为五表。非空立即拒绝，不支持自动降级，离线SQL不能替代在线空表检查。
- modou_test先迁移并运行68项SQLite/PostgreSQL完整回归，再升级modou。该次升级后两个NAS PostgreSQL17数据库均为0004、业务数据为空；当前状态见下文0005记录，与SQLAlchemy元数据比较无差异。
- 凭证只从忽略文件.env或进程环境读取，不输出。test/run_postgresql.py仅连接modou_test；业务测试事务回滚。CloudBase与NAS应用尚未部署。
- 本轮仅结构、查询和持久化适配；没有自动学习循环或DeepSeek真实联调。审批门禁仍由M03实现，M01持久化原语不是公开写入入口。

## M02实际解析契约（2026-11-12）

- parsing.py：Pydantic候审结构、UTF-8/UTF-16读取及规则解析。CatalogEntry新增name_id、variant_id、platform、edition；aliases为唯一名称识别入口，name_zh/name_en仅保存目标名称，不作为隐式匹配入口。
- 优先按完整原名匹配alias；没有完整命中才用剥离明确平台/版本线索后的名称匹配。全名命中有歧义或冲突时不降级绕过；对候选按原文明确平台/版本过滤，同一目标去重后仅唯一候选可复用。
- 游戏级alias只复用name_id和标准名；不因为数据库仅有一种规格就自动补平台/版本。规格级alias还可复用variant_id、平台及版本。原文明示冲突或仍有多个候选时不绑定任何数据库ID，转交AI并保留问题。
- ReviewItem新增name_id、variant_id、match_status（alias/unmatched/ambiguous/conflict），review_status只能为pending；两条识别路径都待Karl确认。ai_suggestion独立保存，不覆盖价格、日期、地区、优惠方式或确定名称。
- catalog_memory.py从game_alias出发关联game_name与game_variant；只建立modou_test连接，在连接前校验驱动、库名并拒绝URL连接覆盖参数；显式dbname和只读事务参数防止默认环境覆盖，连接后再次核对current_database。读取过程中无写入、迁移、建表。
- local_config.py只读本地.env，支持UTF-8 BOM、成对引号；进程同名配置优先。不使用通用DATABASE_URL。测试连接可用MODOU_TEST_DATABASE_URL（仅postgresql+psycopg且库名modou_test），否则用POSTGRES_PASSWORD连接既有NAS测试库。密钥、连接URL和服务端异常正文不输出。
- deepseek.py的CachedSuggestions按完整原名归一空白、忽略大小写后缓存本轮成功和失败；保留完全版等语义线索。同一输入只请求一次；失败不无限重试。统计requests/cache_hits/failures；AI仍只返回name_zh/edition。
- parse_cli.py支持--test-db、--env-file，与--catalog互斥；单篇输出独占创建。memory_cli.py接受清单数组（path相对清单目录、date为明确ISO日期、source_url可选），一次读取测试库快照并在多篇间共享AI缓存。输出目录须全新，含每篇JSON、summary.json和review.md，不覆盖既有结果。
- ParsedNote保留source_text、标题、发布日期、来源链接、items、异常和跳过行。行尾明确YYYY-MM-DD优先于发布日期；非法日期阻止字段确认。未知日期/平台/版本不补造；数字栏目跳过；史低只留notes。
- 本轮解析结果保存在.tmp/m02-memory/real-run/；M02不调用save_observation或写目录/别名，无自动审批。M03实现人工确认后的目录、规格、别名和报价事务写入，并保证史低备注不写业务表；M05承担调度恢复。
- 数据库严格仅限modou_test。测试库任何数据、结构、迁移、配置不自动同步modou；只有Karl特别说明才调整范围。该限制同样适用于M03开发验证和未来部署指令的解释。
- DeepSeek官方JSON接口约定：https://api-docs.deepseek.com/guides/json_mode/ 。此前单次真实请求HTTP200并通过结构校验；本次按三篇样本验证批量与缓存。

## 当前实现边界

M02只完成记忆读取、识别建议和候审输出，不实现人工编辑界面、审批状态存储或确认后写入。当前五表没有审批状态字段，读入目录按M03约束视为已经人工确认；M03不得将未经确认的AI建议写入目录或别名。

## 区域解析修正f28c6a91（2026-11-13）

- parsing.py的REGIONS修正UN为海外版、CN为国行版；新增REGION_CODES与价格前缀识别。HK/🇭🇰→港版；UN/🇺🇳→海外版；EU/🇪🇺→欧版；JP/🇯🇵→日版；CN/🇨🇳→国行；US/🇺🇸→美版；KR/🇰🇷→韩版。UN只表示非国行、非港版且具体地区未确定，不是欧版。
- 字母代码不区分大小写，支持紧接金额或空白后跟金额/人民币符号；只匹配价格字段开头，拒绝HKG、UNEU等未知前缀，不把前两字母盲目截取。既有台版旗帜解析保持原样，本批无该地区报价。
- 仅运行test/test_parsing.py，共59项通过；涵盖7种字母代码的3种形式、国旗、未知标记及样本区域总数。未连接数据库、未调用真实AI、未跑全量或数据库测试。
- 新打印稿outputs/m02-review/M02拟入库内容_cd6ba1.md：3表152行；港版93、日版18、海外版27、国行版3、美版1、欧版8、韩版2。名称最后生还者1涉及3条报价；其他审核名、版本、价格和优惠方式保持上一稿。历史JSON和旧打印稿保留为旧批次原始输出，不得作为本轮修正后的入库载荷。
- 已知后续事项：pricing.py仍以旧值国行识别国行组，后续写入国行版前应适配查询分组。此次授权范围为解析映射、打印稿和相关文档，未改查询或持久化代码。

## d92f4b67最终规则与一次性导入

- ReviewItem.normalized_name为原帖名归一空白并upper()后的识别输入；raw_name/raw_line保留原文。先归一再提取规格词面、匹配alias，AI收到normalized_name。normalize_name用于两端匹配和请求缓存；本次alias按同规则存储，标准名保留审核文字。
- CN最终值恢复国行；国行版仅为展示分组。此前本文件f28c6a91节“CN国行版及需适配查询”的记录为当时状态，已由此处决策取代；pricing.py无需改动。
- 解析条目初始lowprice_method为空字符串，已知优惠栏目或行尾说明可覆盖；不能使用直接购买占位。空值表示没有优惠条件文字，不表示金额缺失。空版本标准版与未知None仍区分。
- 一次性执行文件在.tmp/m02-approved-import/import_batch.py；载荷为人工审核MD加本轮明确追加规则。通过库名守卫、显式dbname、current_database及0004检查限制modou_test，同事务锁定五表，显式字段白名单写入目录/规格/别名并调用save_observation维护来源与报价。
- 所有业务写入在同一事务，金额传Decimal；任何异常不提交。成功事务内再次运行整批持久化，计数和ID一致，随后提交，另开只读事务核验152条字段及来源关联。回执不替代审批，本次审批依据为Karl的d92f4b67执行指令。
- 已写入59个game_name、60个game_variant、91个game_alias、152个m_low_record及3个data_source。只保存已确认名称、规格、区域、价格、日期、方式；notes、AI建议、史低备注不在写入白名单。
- source_url本批保存3个TXT文件名；published_at因未获具体时刻保持NULL。逐条报价日期沿用审核的发布日期；recorded_at由数据库生成，不能把它当报价日期。文件名来源例外仅适用本批，通用解析器URL校验保持原样。
- 真实数据回放144条命中预期规格，8条例外：艾尔登法环+dlc和神秘海域4+dlc的+DLC词面与人工命名规格冲突、羊蹄山之魂标准名同时关联2个规格。数据库关联均正确，本轮不静默改写规格或强行消歧。
- 本轮78项非数据库相关测试通过、4项排除，无全量/数据库测试/真实AI调用。modou_test已含业务数据，原空库专用测试入口不得直接使用或清空已导入数据。


本次两库已按Karl明确授权完成0005重命名迁移，主键为name_id、variant_id、alias_id、sources_id、record_id。测试库数据与ID保留（59名称、60规格、91别名、152报价、3来源），正式库五表为空；两库结构与模型一致。日常作业仍限modou_test；本次不授权后续正式库操作或数据同步。详见_DB.md及_DEVLOG.md。
