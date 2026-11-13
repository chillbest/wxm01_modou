# 魔豆一期

当前已交付五张业务表、迁移、只读搜索和分地区史低查询；NAS的modou与modou_test均为0005。受保护审批及批量导入属于M03。

## 本地环境

固定Python **3.13.18**，使用uv；不修改系统Python或永久环境变量。

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.tmp/uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PWD '.tmp/python'
uv python install 3.13.18
uv sync --locked
uv run --locked pytest
```

若uv无法获取指定解释器，停止正式环境验收；不要自动改成其他Python版本。可更新项目内uv或提供可信的同版本解释器。

## PostgreSQL

NAS测试库：192.168.1.23:15432/modou_test，账号modou。项目根目录.env提供POSTGRES_PASSWORD，支持LF/CRLF、UTF-8 BOM及成对引号，密码不提交仓库。

```powershell
uv run --locked python test/run_postgresql.py
```

也可显式设置MODOU_TEST_DATABASE_URL后运行pytest。只允许名称为modou_test的PostgreSQL库，拒绝未知表和已有业务数据；自动应用Alembic迁移并比较实际结构与模型。全部业务测试同时运行SQLite和PostgreSQL，测试数据事务回滚，保留结构以便重复运行。常规测试不删除既有表，不操作modou开发库。Alembic另有alembic_version工具表，不计入五张业务表。

当前仅允许modou_test数据库作业，不连接或操作modou；不得将测试库数据、结构、迁移或配置同步正式库，除非Karl特别明确授权。本轮目录读取与验证不执行迁移。

## 云端与NAS环境约定

后续使用Docker构建：固定Python3.13.18基础镜像和uv版本，在Linux镜像内执行`uv sync --locked --no-dev`；Windows的`.venv`不进入镜像。构建时安装依赖，运行时直接启动已安装应用。镜像可用性、CloudBase构建网络与NAS架构仍需部署阶段验证。本阶段没有HTTP服务和部署文件，不可直接部署为云端API。

## 当前来源关联

五张业务表：

| 表 | 全部字段 |
| --- | --- |
| game_name | name_id、name_zh、name_en |
| game_variant | variant_id、name_id、platform、edition、display_name、remark |
| game_alias | alias_id、name_id、variant_id、alias |
| m_low_record | record_id、variant_id、sources_id、region、lowprice_cny、lowprice_method、lowprice_date |
| data_source | sources_id、source_url、published_at、recorded_at |

一篇笔记只存一条来源，source_url唯一，多条报价通过sources_id共用来源。variant_id为空的别名关联游戏；有值时关联具体规格，数据库保证其name_id一致。显示名和规格备注可空，史低价格备注不写库。完整类型及约束见_TDD.md。

历史0004迁移时两库为空；当前测试库已有审核业务数据，正式库仍为空。0004只允许空旧业务表迁移，锁表检查后事务性替换，不支持自动降级。持久化入口save_observation使用variant_id，不再接受旧的名称/平台/版本参数；调用方须在M03审批门禁后使用，并整批事务提交。搜索从目录关联规格，不依赖已有报价。

## 交付状态

M01原范围已验收，本轮完成五表结构调整及相关查询、存储适配。68项SQLite/PostgreSQL回归通过，两库实际结构与模型无差异。M02本地解析已实现，DeepSeek Key已由Karl配置；单次真实API已联调成功，数据库别名参考接入与三篇真实批量验证已完成；152条中147条获AI建议，2个输入失败涉及5行，均保留待核对。人工验收待完成。未进行Git写入。

## M02本地解析

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe -m modou.parse_cli 'Doc/11.3｜Ps好价光盘.txt' --date 2026-11-03 --output .tmp/m02/manual-review.json
```

输出路径须尚不存在；自动识别UTF-8与带BOM的UTF-16。--source-url补来源链接；--catalog指定JSON数组，例如[{"name_zh":"只狼","name_en":"Sekiro","aliases":["狼"]}]。目录为空时保留游戏原名并标注未匹配，不凭空建立官方名称。

可选--deepseek从进程环境读取DEEPSEEK_API_KEY、DEEPSEEK_MODEL，支持从--env-file（默认.env）只读加载，不把密钥写入命令或日志。默认模型deepseek-flash。AI结果只进入建议字段，保留人工确认标记。此前单次真实请求已成功；本次批量结果见_CURRENT.md。

Doc三篇样本共152条光盘报价，数字折扣排除；平台、未明确版本、名称匹配和来源链接等待补充。解析JSON不是批准入库文件。M02自动测试已覆盖真实样本和模拟AI；待Karl核对新增识别建议后再验收M02；人工确认与写入闭环由M03实现。

## M02数据库记忆入口

先匹配game_alias.alias，可靠命中复用name_id及可确定的variant_id；未命中、歧义或规格冲突才问AI。两条路径始终待人工确认，不直接入库。标准名也需显式alias映射，--catalog离线JSON的aliases同样是唯一匹配入口。

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe -m modou.parse_cli 'Doc/11.3｜Ps好价光盘.txt' --date 2026-11-03 --test-db --deepseek --output .tmp/m02-memory/single-review.json
.venv/Scripts/python.exe -m modou.memory_cli .tmp/m02-memory/manifest.json --deepseek --output-dir .tmp/m02-memory/another-run
```

运行前确认输出尚不存在；批量运行共享本轮AI缓存。清单格式如下（路径相对清单目录，发布日期由Karl提供，不推断年份）：

```json
[{"path":"../../Doc/11.3｜Ps好价光盘.txt","date":"2026-11-03"}]
```

默认使用.env内POSTGRES_PASSWORD连接既有NAS modou_test；也可配置MODOU_TEST_DATABASE_URL，但代码拒绝其他库名和URL覆盖参数，通用DATABASE_URL不使用。DeepSeek使用DEEPSEEK_API_KEY及可选DEEPSEEK_MODEL。程序不输出凭证、不写业务表、不自动保存AI建议为数据库记忆。

专项验证（不运行全量）：

```powershell
$env:MODOU_MEMORY_PG_TEST = '1'
.venv/Scripts/python.exe -m pytest test/test_parsing.py test/test_catalog_memory.py -q --tb=short -p no:tmpdir
```

真实PostgreSQL专项测试只在modou_test事务内构造少量目录、规格、别名并回滚；不运行迁移，不改变表结构。所有测试临时文件放.tmp/，不自动清理既有目录。

## 当前打印审核稿

使用outputs/m02-review/M02拟入库内容_cd6ba1.md，3篇笔记各一张表，共152条，增加区域列并修正最后生还者1。人工审核文件使用MD并在文件名追加6位内容哈希；旧Excel和旧MD仅作历史参考。

地区支持字母代码及国旗：HK港版、UN海外版、EU欧版、JP日版、CN国行版、US美版、KR韩版。UN不等同EU。原始AI批次JSON未覆盖，不能直接用其旧region值导入。本轮无数据库操作，仍等待Karl核对后授权入库；国行版的查询分组适配尚待完成。

## 最新入库状态（2026-11-13）

Karl授权d92f4b67的首批审核内容已写入modou_test：59标准名、60规格、91别名、152报价、3来源。最新文档为docs/imports/M02入库定稿_8ed6a8.md和M02入库回执_8ed6a8.md；原打印稿和旧AI JSON仅为历史参考。

CN存国行；无实现方式存空字符串，不写直接购买；游戏原名保留，normalized_name先大写再识别，别名按相同规则归一。本批羊蹄山之魂完全版备注带DLC，神秘海域盗贼传奇合辑备注4+dlc。TXT文件名来源只适用本次授权批次。

modou_test已有审核业务数据，前文test/run_postgresql.py为空业务表专用入口，不得直接对当前库运行，也不得清空样本满足测试。新一轮解析仍需人工审核。现有解析器对2种+DLC命名和羊蹄山之魂规格存在8条回放例外，详见最新回执；通用M03审批工具尚未交付。


本次两库已按Karl明确授权完成0005重命名迁移，主键为name_id、variant_id、alias_id、sources_id、record_id。测试库数据与ID保留（59名称、60规格、91别名、152报价、3来源），正式库五表为空；两库结构与模型一致。日常作业仍限modou_test；本次不授权后续正式库操作或数据同步。详见_DB.md及_DEVLOG.md。
