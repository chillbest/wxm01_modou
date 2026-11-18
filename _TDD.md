# 魔豆一期｜TDD 技术设计文档

## alias全表唯一（0017，2026-11-19）

按Karl要求执行：game_alias.alias改为全表唯一，ORM与0017迁移使用uq_alias(alias)，替代uq_alias_gpc(gpc_id,alias)。实施前只读检查未发现重复alias，未删除或改写既有业务行。modou_test迁移0017命令已完成，正式库未操作。catalog_memory、bangumi_cli及网页入库结构门禁兼容0017。补充跨GPC及同GPC重复alias拒绝测试；按要求未运行测试或修改后验证。当前运行服务尚未重载，新版结构门禁需重载服务后生效。

## 当前契约补充（2026-11-19）

草稿增加顶层main_explicit_null布尔状态，final.bangumi_main继续为数字ID列表字符串或null。状态仅由服务端根据main原始空白字符串、可信已保存GPC或Restore基线产生，不接受前端任意标志作为豁免。显式NULL参与草稿持久化、manual_fields、预览摘要及Restore基线；必须同时main为None才豁免main门禁。清空/填写ID重置标志。普通GPC/报价写入仍在原事务中，catalog_import将None写入已有TEXT可空列。

GameFAQs两段自动AI实现注释保留，后两轮批量记录status=disabled、空item_ids/交互；历史stage槽位仍可读取。suggest_main不发起请求；prepare_row和/api/resolve不调用GameFAQs主版本AI。普通Bangumi关系查询不受影响。

## 黑名单、多main与默认未入库筛选（9c31a7e2，2026-11-19）

已实现动态表edit时B行第1列文字后的🚫按钮：页面dialog按原名确认“确定要把【文本】要加入黑名单吗？”，是/否及Esc取消；是将该文本写入game_alias，gpc_id=-1，保留批次来源。重复规范化名称幂等，拒绝过期revision、篡改文本、已勾选/已入库条目及预览批次。黑名单优先于普通别名，PS光盘过滤也不排除它；停止本地预读、API、AI、main/type补查，取消在途候选补查。当前批次同名未入库项即时标记，其他批次下次刷新检查；不批量改写历史草稿。黑名单视为已处理（already_imported、未勾选）并计入完成统计，所有报价/普通产品导入入口拒绝其入库。页面仅显示A行第一个label原文，灰色删除线，禁止白底黑字高亮；默认开启“仅看未入库”，关闭筛选可查看黑名单及已入库项。

bangumi_main沿用TEXT，支持以|分隔多个正整数ID，去空白、前导零及重复，拒绝非法字符/空项；编辑、提交、入库、复用及HTML/JS展示同步支持。每个ID单独链接；type为合集时表示平等组成游戏，不当作母子关系，不自动推断多个main。既有单ID和自动识别流程保留。

保留外键，以gpc_id=-1、name_zh=【黑名单占位】、platform=blacklist的系统GPC承载黑名单引用，排除普通目录及产品读取，禁止报价。无DDL变更，结构版本仍0016。modou_test初始化仅新增1条系统来源及1条占位GPC；原8条来源、69条真实GPC、71条别名、203条报价逐行保持不变。备份与回执：.backup/blacklist-before-init-20261119-015018/。未实际将业务文本加入黑名单，未改生产库或Git。

新增14项专项（含参数化）及相关回归分批通过；各批结果114通过/4跳过、105通过/1跳过、70通过/15跳过、最终报价入口补查14通过/1跳过，批次含重复用例，非去重总数。跳过为历史样本缺失或未启用数据库专项；新增专项全部执行通过，含启用外键的SQLite实际持久化、API鉴权/过期/篡改/重复拦截、零报价及多main复用。JS语法通过。确认无活动解析后已重载4001；首页HTTP200、线上JS/CSS与磁盘一致、blacklist接口已注册，历史批次2e56475d的45项API正常。未运行全量测试及浏览器交互验收。

## GPC外链与恢复接口（c7a42e19，2026-11-19）

0016将game_product_config.gamefaqs_link重命名outlink，改名uq_gpc_bangumi_platform_outlink并更新列注释；仍采用(bangumi_id,platform,outlink)联合唯一及默认NULL语义。数据库迁移仅允许modou_test。ORM、SQL、AI返回键、候选/审核/拟增/判重/导入统一outlink；自动GameFAQs检索仍保留专用URL校验。Store.read及CLI validate_rows递归兼容旧字段和final.gamefaqs_link人工标记，保留原URL与证据文本，不批量重写草稿。

GET /api/batches/{key}/rows/{index}/gpc返回revision、row_revision和product（GPC可编辑字段及platform）。POST同路径/reload-gpc经Store批次revision和row_revision检查，按当前绑定gpc_id重读并逐字段比较已确认product，变化返回409；载入后取消candidate_lookup等派生状态，更新gpc_baseline并保留parse_baseline及其他报价字段。勾选/已入库/预览或不存在记录拒绝。后续提交仍校验身份和共享资料并发变化。前台弹窗textContent显示差异，确认后保存；直接编辑/导入也校验HTTP/HTTPS外链。网页提交要求0016，来源规则仍为0015。通用外链候选按规范化URL匹配，Bangumi Subject候选须精确匹配受支持域名，避免其他网站的subject路径误匹配。

## 批量入库预览校验修复（e2a7c951，2026-11-19）

alias_bulk.preview仍返回完整公开行用于展示，但生成token的row来自persisted(public)[rows][index]，与Store草稿持久化规则一致，剔除proposed_inserts。approved_indices保留当前合格条目完整index/token列表比较；Store.update保留批次revision校验。前端错误已含“预览”时直接显示后端说明，其他错误仅追加一次关闭重开建议。test_alias_bulk真实调用refresh_duplicates（隔离SQLite）覆盖GET附加拟增、Store省略拟增、POST提交成功及回滚，不再把此刷新替换为空操作。无API或数据库结构变化。

## 动态审核链接与预览接口（6e94a2c7）

/api/batches/{key}/rows/{index}/candidate的VGCollect URL分支在草稿写锁外请求可信产品页，限制HTTPS主机/数字产品路径、重定向与2MB大小；按“游戏名 - 平台 - VGCollect”标题提取英文名，失败不持久化。进入锁后沿用row_revision冲突校验，手填链接清空bangumi_id/gpc_id，VGCollect覆盖name_en，保留main/type/报价。/api/preview/{sid}新增platform字符串，取Bangumi infobox“平台”值，API数组按顺序连接、本地文本保留资料内容，无资料返回空串。前端候选预览增加平台行；拟增ID应用web-manual斜纹；显示名由Promise封装dialog，取消返回null，不监听blur或visibilitychange关闭。


## 别名命中一键入库（7c2e9a64，2026-11-18）

web.alias_bulk.preview在public_batch副本上按alias_bound及eligibility_errors筛选未入库条目；返回revision与index/token/row列表，SHA-256摘要绑定批次ID、索引和完整公开行数据。GET /api/batches/{key}/alias-preview复用load去重刷新；POST /api/batches/{key}/alias-commit经Store.update批次revision锁检查，再比较当前完整合格列表的index/token，拒绝过期、篡改或空列表。commit_batch新增可选indices参数，只对传入索引走既有单事务入库，保持未入选条目的勾选；原index及selected提交语义保留。不变更数据库结构。review.js在标题后插入绿底黑字按钮，dialog打开期间沿用现有轮询暂停规则，快照只读展示；提交使用预览revision而非最新本地revision，成功adopt并render，失败要求重开。显示名/备注tooltip挂dialog内，防止top layer遮挡，note为只读预览。

## 已勾选A行取消高亮（2026-11-18）

A行白底黑字高亮排除已勾选（selected）、已入库及早已入库条目，仅选择视口内最上方可见的未勾选且未入库行；居中副本不可见时仍回退同一行左侧原文。全部可见条目均不符合时不显示白底高亮。勾选后转移至下一符合项，取消勾选后重新按可见顺序选择。本节取代此前“已勾选未入库仍参与高亮”的说明。topmostVisibleOriginal在现有imported/already_imported过滤外加入selected过滤，居中副本及左侧回退共用此选择结果；保存/布局更新流程保持不变。

## note按钮状态与悬浮预览（2026-11-18）

review.js的wireNotePreview基于textarea当前值trim判断web-note-filled类，summary::after绘制空心/金色实心7px圆点；单例web-note-tooltip挂载body，fixed定位按视口边界计算，textContent显示备注，CSS pre-wrap与overflow-wrap保留换行及长文本换行。mouseenter/focus显示，mouseleave/blur/click/Escape隐藏，input更新状态；render及滚动/resize隐藏浮窗。不改保存API、数据库或人工修改标记。

## 空Bangumi ID相似提示修正（2026-11-18）

相似产品提示仅在当前条目具有非空Bangumi ID时按相同ID及平台查询；NULL、空串或纯空白ID不作为相似依据，避免无ID的不同游戏仅因同平台被误关联。完整身份（Bangumi ID、平台、产品链接）的精确复用及报价判重保持不变。已补充无ID不同VGCollect链接独立入库、同链接重复报价复用及新价格复用GPC的回归测试；按Karl“快马加鞭，不用验证”要求未运行测试或其他验证。

## VGCollect手填产品支持（2026-11-18）

手填产品链接现支持GameFAQs及https://vgcollect.com/item/数字ID（可带末尾斜杠），保存时确认display name并同步name_zh；不抓取外站、不调用AI，保留英文名、main、type和平台。结束edit显示可点击链接，刷新后持久保留。

兼容沿用历史字段gamefaqs_link存储这两类外部产品链接，字段名保持不变，语义扩展为受支持外部产品URL；manual_gamefaqs沿用手填模式标记。共享valid_product_link同时供提交校验与审核链接输出使用，自动GameFAQs搜索及网页读取仍限定GameFAQs。现有身份唯一键、判重、拟增及入库沿用该链接字段，不新增表或迁移。

本节取代此前“VGCollect不支持保存、仅保留页面输入”的说明。

## 编辑输入防丢失（2026-11-18）

review.js以inputDrafts Map按条目索引及url/main区分保存页面内输入；bindDraftInput在重绘时优先恢复输入并监听input事件，异步保存成功仅清理与本次提交相同的草稿，避免覆盖后续输入。mainSubjectURL将纯数字转换Bangumi Subject URL，沿用/api/resolve校验；manual_gamefaqs保留原数字直存规则。main框回显保存值，删除main成功后清理草稿。不更改API、数据库字段或既有草稿，vgcollect等不支持域名明确报未保存。

## 完成字效与前台记录精简（c83f6a21，2026-11-18）

review.css的button.web-complete:disabled采用#ffcb7c字色、24px/800字重、italic、skew(-5deg)、1px 2px 0 #b95329文字阴影，取消背景渐变、描边、drop-shadow及complete-glow动画；review.js的完成判定与禁用逻辑不变。web.app.review不再把manual_resolutions渲染为独立details区块，其他识别证据输出保留。service.edit_row继续追加manual_resolutions，public_batch及草稿持久化不变，不变更API或数据结构，不批量改写历史草稿。接口专项覆盖旧/新记录保留、刷新后不展示以及字段值/人工标记持久化。

## A行居中与高亮回退（9b4e7c12，2026-11-18）

originalFreeSpace从original实际边界及可见子控件矩形计算剩余区间：web-single/web-receipt为右侧边界，其他控件最大right为左侧边界。fitCenteredOriginal按区间中点设置副本left，沿用8px碰撞间距。updateOriginalFocus先清理左右文本高亮类，再用A行矩形及batch.rows入库状态选目标；对目标重新计算副本避让，不递归调度动画帧。副本可见时添加web-original-focus，否则给web-original-text添加同一类；CSS对两者共用白底黑字非斜体及锁定态取消压暗，高亮左侧不增加内边距。后端接口、数据及入库行为不变。

## A行高亮状态过滤（2026-11-18）

topmostVisibleOriginal接收与rects同索引的batch.rows，先排除imported/already_imported，再按既有视口及遮挡规则选择；CSS无需变更，已入库副本被移除web-original-focus后恢复普通样式及锁定压暗。入库状态更新沿用syncChecks触发重新选择。

## 视口首个A行高亮（6d2f8a41，2026-11-18）

review.js根据居中副本实际矩形、计算可见性及sticky-header底边选择视口内最上方可见项，仅该项带web-original-focus类；无匹配清空。滚动/resize及原有避让检查触发requestAnimationFrame合并更新，ResizeObserver补充观察entry以响应详情收拢、异步内容和追加布局。CSS普通副本继承原字色/斜体，focus使用白底黑字非斜体，并取消该副本的锁定压暗；内边距保持一致以避免切换背景导致几何抖动。仅影响前端展示，不改数据或后端接口。

## 别名及最终命中年份补充（2026-11-18）

在线B行第2列最终命中现在也显示年份，取代e4b7c2a9中该列不带年份的约定。已有/api/preview/{sid}响应增加year（由发行资料提取，未知为空）；前端优先使用现有候选资料，缺失时按Subject ID缓存补查Promise，供别名候选及最终命中共用。补查失败仅不显示年份，不影响身份、平台和入库字段。按Karl要求不运行验证。

## 当前增量设计：e4b7c2a9（2026-11-18）

Store.create生成uuid4.hex[:8]并在同一Store锁内检查草稿文件冲突，冲突则重试；Store.path只接受8或32位小写十六进制标识，旧文件名不迁移。服务重启不重置已保存批次；中断解析仍按既有规则标失败并保留已发布审核内容。

0015仅允许modou_test：data_source增加可空TEXT review_batch_id和uq_source_review_batch唯一约束；NULL历史行可并存。get_or_create_source仅按明确批次标识复用，创建时必须传带时区的batch.created_at；批次内路径/发布日期冲突拒绝。commit_batch从持久化批次传入id/created_at，不接受客户端提供来源元数据。commit_rows在判重后创建/复用来源，把source_id显式传给目录及报价写入，确保同次新增三表引用同一来源。非网页入口使用提交内缓存，不再跨提交按时间复用；旧GPC/别名首次来源不覆盖。网页版本门禁为0015，目录读取/CLI识别0015。

build_review新增on_total回调，在候选查询前发布解析整体条数；parse_job存total_rows，首页API提供imported_count和total_rows。旧ready批次以完整rows长度兜底，未完成且缺总数时前端显示“解析中”。

PS光盘本地唯一结果仍调用API，按Subject ID合并候选；多版本时撤销local最终命中，由原AI/人工流程处理。stage_trace保留date；review_table.release_year解析已有date/发行日期，命中情况补充年份但subject_label默认及B行最终候选保持原样。前端已有草稿按Subject ID从完整候选补充年份。

candidate_pick.choose在保存候选时同步计算quote.platform，applied_quote标记自动平台，与protected_fields共同保护人工值；切回原目标复用可信基线平台。alias_bound基于alias命中GPC及当前身份判定，普通edit_row仅允许B行第2列note/display_name；候选接口为受控身份切换入口。前端关闭main、type、平台、地区、价格、优惠及拟增name_en编辑，切换后重算绑定。

微光金只替换web-single-ready样式。滚动标题按titlebar.bottom<=0显隐，并按两个按钮间实际矩形计算中心；宽度不足120px时独立居中行，滚动/resize及ResizeObserver更新，不覆盖操作按钮。

> 版本：v1.29.0（审核短标识与来源关联）
> 日期：2026-11-18
> TDD = Technical Design Document（技术设计文档），与测试驱动开发方法 Test-Driven Development 不同。  
> 基准：同版本《魔豆一期 PRD》；实现细节在开发阶段以测试和真实 API 响应校准。









## 英文名入库门禁与按钮状态（2026-11-18）

eligibility_errors为缺失name_en追加“英文名待确认”，前后端勾选/提交均复用该校验。singleImportState综合英文名、eligibility_errors及编辑/忙碌/预览/已勾选/已入库状态；disabled=false时添加web-single-ready微光金高亮，否则灰化。数据库字段可空性未修改，仅在线审批契约收紧。

## 恢复B行英文名输入框（7a3d9c62，2026-11-18）

已撤销上次入口精简：恢复手填GameFAQs模式下B行第2列“手动填写英文名”输入框；拟增GPC表的name_en编辑入口继续保留。仅做入口及JS语法检查，刷新页面生效。

## 当前契约：手填GameFAQs独立保存（2026-11-18）

candidate接口url分支对GameFAQs仅valid_gamefaqs_link校验，调用save_manual_gamefaqs，不进入网络解析或candidate_pool。保存gamefaqs_link/display_name/name_zh，清除旧gpc_id/gpc_baseline绑定及在途candidate_lookup，其他字段原值保留。manual_gamefaqs标识禁止normalize_draft自动填英文名；Restore或选择其他候选时清除。

前端URL输入回显final.gamefaqs_link；手填模式增加name_en文本框，main使用数字ID直接保存；平台/type等控件仅提交对应字段补丁，不使用旧final快照差量回写。取消display name明确提示未保存。无需SQL迁移。

## 当前增量：产品URL保存与英文名（b6e42a79）

候选专用POST接口增加url分支：服务端用subject/gamefaqs解析可信产品URL并填name_en；choose增加仅服务端传递的resolved_candidate，不接受前台任意candidate对象。取得产品资料后继续条目版本/锁定校验及Store原子保存，提交原有candidate_pool补查；不等待hydrate/MainSubjects/DeepSeek。URL输入先等待已有保存队列，避免之前note/display保存导致row_revision过期。

GameFAQs产品名取h1优先、title后备，去除GameFAQs及平台后缀并校验英文名，保留page_title和规范产品URL；重定向仅允许HTTPS gamefaqs.gamespot.com规范产品页，不接受跨站或搜索页。访问验证页或名称无效抛ValueError，网络异常转换为明确未保存提示，不修改草稿。无数据库迁移。

## 当前增量：原文副本响应式避让（8f24c6a1）

review.js初始化A行时创建aria-hidden的web-original-center，去除序号；CSS绝对定位left:50%并水平平移半宽。centeredOriginalFits比较副本、整行及其他子元素实际矩形，保留8px间隙；隐藏使用visibility以保留测量尺寸。ResizeObserver观察A行/操作区，结合字体就绪、render和syncChecks重算，覆盖动态追加及单条刷新。不改变后端契约。

## 当前修正设计：基线红底与回填取消（c72a9e15）

refresh_review_state从空集合合并parse_baseline和当前eligibility_errors，忽略原red_columns历史累计值，兼容已污染草稿的读取显示。candidate_pick.choose及前端candidateSelection在目标身份等于原始基线时复用main/type；applied_fields同时记录自动置空，防止过渡空值被manual_fields误认为人工覆盖。Restore删除candidate_lookup/candidate_main_resolution/candidate_type_resolution后恢复基线并重算红底；token不再匹配，在途补查不可回填。原始解析问题提示保留，不清除真正的当前错误。

## 当前增量设计：候选选择与异步补查（a93c7e42）

POST /api/batches/{key}/rows/{index}/candidate以subject_id/gamefaqs_link定位草稿已有候选，拒绝任意注入候选、已选择/已入库行和过期条目版本。接口直接使用Store原子保存，不等待网络或重复数据库预览检查；row_revision限制同条目并发修改，允许前一次后台补查完成导致的单次版本递增（需token/原pending状态匹配）。正常审批/入库仍沿用既有重复检查。

前端candidatePending覆盖显示与请求队列分离，点击即render；每行sequence保证旧响应不回退最新显示，保存失败恢复持久化值。2线程candidate_pool在Store锁外执行GPC匹配与main查询，不取网页、不调用AI。后台完成需同时匹配token、条目revision及未锁定状态；人工输入中的控件不被轮询重建，失焦后可更新补查结果。

草稿candidate_lookup保存token/status/protected_fields/applied_fields；状态pending/done/failed/superseded。后台记录candidate_main_resolution和candidate_type_resolution，保留原解析证据；applied_fields标记自动值，避免下一次候选切换将自动main误认成人工覆盖。main_subject.cached_edges以路径/文件mtime_ns/大小为key，缓存只读关系边，文件变化自动失效；文件流形式保持原行为。无数据库迁移。

## 当前增量设计：十条AI批量解析（6e4b9a20）

build_review先取10条报价的别名/本地/API初步结果，再由ai_batch.resolve_group顺序执行name、gamefaqs、main_subject。Bangumi resolve支持defer_ai，初步结果供AI阶段复用，不重复请求API，不重复记录条目最终结果；名称成功即从后两轮移除。GameFAQs获得产品后才进入main，main返回值通过原有Bangumi游戏详情校验。prepare_row以ai_main_attempted阻止失败后额外逐条补问。

ai_prompts生成Markdown的规则、条目及输出说明；批量回复为results数组。每项以稳定item_id对应原报价序号；漏项或重复仅拒绝受影响ID，未知ID/格式错误拒绝整轮，不自动重试。输出字段：name为item_id/candidate/reason；gamefaqs为item_id/name_zh/name_en/gamefaqs_link/platforms/reason；main_subject为item_id/main_subject_id/reason。

草稿新增ai_mode（batch/single）、ai_item_id、ai_group_id、ai_main_attempted；组尾行ai_group保存id/start/end/stages。每阶段包含task/stage/item_ids/status/interactions/errors，交互保留完整system/user/content/raw_response及失败信息；未执行阶段为skipped。组信息随组内最后一条同次发布，存储/API继续兼容旧行。

ai_review生成组尾标签、模板和3页签；沿用review_html原AI浮窗及格式化/换行控制。review.js将分隔线移出entry，避免行锁定/筛选破坏组入口，动态追加保持原分组次序。单条重解析不走批量入口，保留原ai_group及previous_parse，并恢复本条AI模板。无SQL结构变化。

## 当前结构基线与实现差异（2026-11-13）

本节优先于下文旧五表实现描述。modou_test采用0012四表结构，正式库最近确认仍为0005。下文涉及game_name、game_variant、variant_id、edition、source_url的实现描述保留为现有业务代码/正式库旧结构说明，不代表新测试库契约。

### 测试库0006：GPC四表

完整字段、空值、约束及索引以_DB.md为准，不重复维护字段表。

- game_product_config以gpc_id标识内容版本；中文/英文名普通索引且不唯一。bangumi_id为可空TEXT，与必填platform及可空gamefaqs_link联合唯一（0010，默认NULL互异）；bangumi_main为可空TEXT，保存主版本Subject ID，无外键限制。note与display_name可空；显示名为空时显示name_zh。
- game_variant已删除。游戏平台由game_product_config.platform区分（必填TEXT，无默认值及枚举检查），m_low_record删除platform，地区由region区分。报价通过gpc_id直接关联GPC，查询索引为(gpc_id,region,lowprice_cny,lowprice_date)。
- game_alias仅关联gpc_id，(gpc_id,alias)唯一；同一别名可以关联多个GPC，歧义须复核。无隐式标准名识别入口。
- data_source以source_path保存可重复的URL或相对文件路径（0013），published_at为可空DATE，recorded_at为默认now()的TIMESTAMPTZ。
- 主键均为BIGINT自增；外键不自动级联删除；报价金额大于0，无报价去重唯一约束。

0006在线校验库名、锁表及空表条件，事务性替换旧五表，不转换任何历史业务数据，不支持自动降级。迁移脚本拒绝正式库；正式库不得直接upgrade head，后续升级需另行设计及授权。

ORM、搜索/史低查询、save_observation、目录读取及解析契约尚未适配，旧代码和旧数据库测试无法正常使用0006。暂不定义这些接口的新签名；后续授权后统一适配。Alembic target_metadata仍指向旧ORM，当前不得据此自动生成迁移或声称与新库无差异。

GPC结构专项验证入口为test/test_gpc_schema.py，以MODOU_GPC_SCHEMA_TEST=1显式启用。验证数据使用回滚事务，自增序列使用事务性RESTART后回滚，避免验证改变业务数据和序列状态。具体执行结果及备份、回执位置记录在_CURRENT.md，不在技术设计中维护。

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

## Bangumi独立GPC入口（2026-11-13）

bangumi.py按NFKC、大小写及空白归一化匹配，读取data/bangumi_locale文件名日期最新ZIP，单批流式扫描subject.jsonlines并筛type=4；解析name/name_cn及infobox别名。索引不写业务库，当前每批扫描而非持久化索引。

匿名POST /v0/search/subjects以filter.type=[4]、sort=match、limit=10搜索，再GET /v0/subjects/{id}补全详情；超时20秒，同运行缓存成功请求。不发送Authorization或Cookie，不自动重试。API失败保留本地候选与错误供审核。搜索只取前10项，不能视为完整候选集。

独立命令bangumi_cli读取0006测试库game_alias/GPC，不调用旧ORM；候选保留原笔记、来源、Subject与错误，可选DeepSeek只能选择候选ID，不能直接写库。审核文件使用Markdown内唯一JSON块；每项必须confirmed或rejected，confirmed必须指定已有gpc_id或最终名称与Subject字段。候选建议与final隔离，人工填写final，不自动确认。

导入二次校验审核结构、库名及0006版本，锁定GPC/别名表后同事务写入；复用Subject，冲突拒绝，不覆盖已有目录；主子关系由人工填写，不要求主版本已在本表存在。仅目录与别名，不导入报价；正式库无入口。

## GPC报价适配（2026-11-13，c8e42a71）

models已切换0006四表；CatalogEntry/ReviewItem以gpc_id代替name_id/variant_id，别名不再携带平台事实。observations以source_path、gpc_id、platform持久化，published_at为DATE；同来源同报价复用。note_review串接规则提取与Bangumi，候选/AI建议/extracted只作证据，final及quote为人工确认载荷；全批验证后同事务导入GPC、别名、来源、报价。pricing保留旧实现，本轮不适配，当前不可用。

## 未注明版本的默认规则（2026-11-14）

原文未注明内容版本时，默认按标准版（主版本）处理，不因未写版本而单独标记“内容版本待确认”。原文明确注明豪华版、年度版、完全版或+DLC等内容版本时，按明确版本识别。默认规则不代替游戏名称识别；游戏名称或主版本对应关系仍有歧义时，保留相应歧义供人工审核。 GPC选择以标准版（主版本）为默认目标；不据此凭空创建Bangumi主子关系。此规则取代此前将原文无版本一律视为版本未知的处理约定。

## ABC审核表（2026-11-14）

review_table.render_review使用HTML table嵌入MD，以colspan=8合并A/C行，转义输入并支持br换行。命中顺序alias/local/api/ds，仅唯一命中进入stage_hits；DS选择记录于ds。旧证据仅恢复可证明的本地唯一命中及DS选择，不推测API命中。缺省版本按标准版（主版本），不再因未注明版本追加问题；其他缺字段、失败及版本冲突仍保留。JSON审核载荷与可读表分离，导入门禁不变。

## 人工审核排版调整（2026-11-14）

按Karl快马加鞭指令：A行改为项目符号原文，每个条目的B/C行使用独立无表头HTML小表格；文首仅一个字段说明表。C行仍按问题超过10字时出现并合并8列。生成逻辑已同步，4项相关专项测试通过；49条现有证据离线重排，未调用API/DS，未入库。

2026-11-14：按Karl快马加鞭指令，审核表使用统一width:100%、table-layout:fixed及colgroup列宽4/16/36/7/6/6/11/14%，所有独立表格分割线共享相同位置，长内容换行。4项相关专项测试通过；查看器须支持内联样式及colgroup。

2026-11-14排版微调：A行改为数字序号开头，B行删除序号列，文首仅单行7列表头（无解释行）。各表统一7列宽20/36/7/6/6/11/14%，C行colspan=7；替代此前8列约定。4项相关专项测试通过，49条离线重排；未调用API/DS，未入库。

2026-11-14：A行数字后的句点转义，显示为字面递增序号1—49，避免独立Markdown列表反复从1开始。5项排版专项测试通过；未重新解析或入库。

2026-11-14：按Karl本条快马加鞭授权，A行使用全角括号手动递增编号（1）至（49），替代数字句点格式。5项相关排版测试通过，49条编号完整核验；未重新调用API/DS，未入库。最新审核表：outputs/note-review/11.3_人工核对表_7ad64f.md。

## 平台规则修正（2026-11-14，f39a7c28）

报价默认PS5；原名明确PS4优先。命中候选平台清单支持PS4且未列PS5时显示PS4；资料缺失或不完整不作为无PS5证据，仍默认PS5。候选唯一命中或DS已选择后才使用其平台信息，不使用未选候选。默认规则不改变Bangumi Subject/GPC，也不自动确认入库。现有49条离线更新，最新审核表：outputs/note-review/11.3_人工核对表_b8ad97.md。原始候选证据保留不变，未调用API/DS，未入库。67项相关测试通过、4项历史样本缺失跳过。

## 本地CLI日志基础设施（2026-11-14，a6f029c3）

logging_setup使用标准库logging、RotatingFileHandler及ContextVar；四个CLI显式初始化，库导入不创建日志文件。日志路径固定项目logs/modou.log，UTF-8文本，单文件10MiB、5份备份，同时输出stderr，不接管第三方logger或业务stdout。run_id每次运行生成，job_id为入口；note_id/line定位条目，batch_id关联事务，request_id关联服务调用。缺失上下文用“-”。日志初始化失败阻止入口继续。

识别阶段由实际分支记录：候选名称/编号、命中/歧义/未命中、服务失败原因和跳过原因；最终状态与每篇汇总只反映候选识别，不代表人工批准。note_review关闭初步parse_note的重复识别日志。外部调用记录耗时和安全异常类别；不保存原始异常、笔记正文、提示词及响应正文。格式化统一屏蔽URL/凭证模式/环境密钥并转义控制换行。事务提交事件仅发生于engine.begin上下文成功退出之后。

当前轮转面向单进程CLI，不支持多个进程安全共享轮转文件，也不构成不可篡改的审计系统。详情见docs/logging.md。

## 唯一命中即停止（2026-11-14）

按Karl快马加鞭授权：别名库→本地Bangumi→匿名API→DeepSeek依次处理，任一前序阶段唯一命中即停止名称识别，不调用后续阶段；多个候选不算唯一命中。人工审核门禁保留。日志记录后续阶段未执行及唯一命中跳过原因。25项相关专项测试通过。11.3真实笔记已重新启动解析，运行ID dfc409d9ff43，日志logs/modou.log；不入库。

## 夜间HTML人工核对表（2026-11-14，7e6b2a90）

默认新增独立静态HTML审核文件，MD/JSON仍保留为审核导入载荷。HTML文件名人工核对表_出价日YYYY-MM-DD_文件名前缀或URL标题_MMDDHHMMSS.html；Windows非法字符替换为下划线，页面出价日显示YYYY/MM/DD。日期解析文件名前缀优先、标题次之，无年份使用上海时区当前年份。夜间模式、自适应宽度，统一7列竖线；A数字序号原文，BCD为子行，C沿用长问题规则，D【命中情况】逐阶段说明后留空。平台背景按alias #22C55E、local #64748B、api #0284C7、ds #9333EA、均未命中 #FF0000，文字黑色。resolve新增stage_trace保存命中/歧义/失败/跳过；本次旧数据从运行dfc409d9ff43日志还原，无记录明确标注。13项专项测试通过。最新49条HTML：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114205753.html。未重新调用API/DS、未入库。

2026-11-14夜间HTML样式微调：ABCD字号18/16/16/16px，窄屏不缩字号；D行网格对齐B第二列，标签与首条同一行、后续阶段缩进；表头采用相同children缩进。左右宽屏100px/窄屏10px。均未命中平台文字加删除线。3项HTML专项测试通过。最新表：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114211309.html。未重新识别、未入库。

2026-11-14执行a84e2c69：HTML命中情况隐藏因前序命中而未执行的后续阶段；日志和原始阶段证据完整保留，其他未执行原因不隐藏。4项专项测试通过；现有49条离线重排，无API/DS请求、无入库。最新HTML：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114211453.html。

2026-11-14执行c57e9a24：命中字段以灰色 / 与占位-分隔；表头/B行居中，C/D保留左对齐。阶段证据保存候选名称、GPC/Subject ID，HTML展示候选详情；本次从原日志还原49条。日志改为modou_YYYY-MM-DD.log，上海时区任务启动日固定，不随跨午夜切换，仍可按大小轮转；旧日志保留。25项专项测试通过，含跨日固定文件验证。最新HTML：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114212330.html。未重新识别或入库。

2026-11-14审核HTML交互升级：D阶段标签与内容分为两列，候选续行对齐——后的首字；B行所有格子居中。表头及按钮栏sticky悬浮。A行前增加复选框，按钮为清除全部勾选、仅看未勾选、显示全部；勾选仅为本页临时筛选状态，不代表审核确认，不入库，刷新不保留。6项HTML专项测试通过，含Node执行筛选及清除行为验证。最新49条表：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114213244.html。未重新识别。

2026-11-14：新增隐藏/显示问题详情、隐藏/显示命中详情、显示全部详情；右上导出未勾选项弹窗提供大文本框与复制全部按钮。导出严格遵循Karl给定格式：原序号原文一行，B1—B2——B2——B3——B4——B5——B6一行，条目间空2行（保留重复B2）。复制优先Clipboard API，失败使用选区复制回退，仍失败提示手动复制；文本框可编辑。勾选/显示控制均为本页临时状态，不代表审批。6项专项测试通过，含JS运行验证隐藏切换、未选筛选、导出顺序及空行。最新HTML：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114214524.html。未重新识别或入库。

2026-11-14导出微调：B1至B6按——分隔，不再重复B2；仅导出文本中B2各阶段去除分隔/左右空白、占位-改_，网页原展示保持。弹窗底部复制左、条数中、关闭最后靠右，复制反馈另列。按钮改清除全部/仅看未选，详情按钮组行内居中。6项专项测试通过，含导出字符串与动态条数。最新HTML：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114224928.html。未重新识别或入库。

2026-11-14控件微调：🧹清除全部、🔎仅看未选、🌈显示全部加入彩色emoji；仅看未选、问题详情、命中详情改为带左右滑块的role=switch按钮，右绿开启/左灰关闭，aria-checked与实际状态同步，显示全部/显示全部详情同步复位相应开关。导出按钮改为导出ALL未选。6项专项测试通过，含连续切换验证。最新HTML：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114230118.html。未重新识别或入库。

2026-11-14：D行每个候选以code行内高亮显示，保留Subject链接；未命中/无匹配候选、命中/唯一候选、歧义/多个候选省略重复原因，只显示状态。其他原因（含失败）及日志原始信息保留。7项HTML专项测试通过。最新文件：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114231635.html。未重新识别或入库。

2026-11-14：Karl选择B金色强调，B行命中项采用金色底/描边/加粗code徽章及✓，保留链接；D行候选维持原样。表头阶段标签使用对应背景黑字，DS辅助改DeepSeek辅助；开关为C行=问题详情、D行=命中详情。导出自动去除装饰✓。8项HTML专项测试通过。最新文件：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114232802.html。未重新识别或入库。

2026-11-14：表头命中说明末尾新增未命中标记，红底#FF0000、黑字、删除线；同步生成逻辑与现有HTML。9项专项测试通过。最新文件：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114233036.html。未重新识别或入库。

2026-11-14：勾选状态字号14px，表头及内部所有文字12px（含阶段色块、窄屏），其余字号不变。10项HTML专项测试通过。最新文件：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114233307.html。未重新识别或入库。

2026-11-14：HTML页面链接统一target=_blank，新标签页打开；Subject链接同时加rel=noopener noreferrer，base指定后续链接默认目标。11项专项测试通过。最新文件：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114233455.html。未重新识别或入库。

2026-11-14：截图所示整个sticky-header区域（全部按钮、开关文字、勾选状态、表头及阶段标签）字号统一13px，正文条目不变。11项HTML专项测试通过。最新文件：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114233634.html。未重新识别或入库。

2026-11-14：D行阶段名称列固定7em并右对齐、不换行，使各阶段——及右侧首字、候选续行统一对齐。12项HTML专项测试通过。最新文件：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114233852.html。未重新识别或入库。

2026-11-14：D行——左侧名称改为固定宽度内两端分散对齐，分隔线独立列，右侧内容位置不变。12项HTML专项测试通过。最新文件：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114234022.html。未重新识别或入库。

2026-11-14执行d8a31f62：撤回最后的D阶段名称两端对齐，恢复固定7em右对齐，——及右侧内容仍纵向对齐；其他功能不变。12项HTML专项测试通过。当前采用既有右对齐文件outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114233852.html，不删除其他版本。未重新识别或入库。

2026-11-14：C/D详情同时关闭时自动收紧条目间距及B行上下内边距，打开任一详情恢复原布局；D行——左侧阶段名称18px加粗，其余文字保持16px。13项HTML专项测试通过。最新文件：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114234615.html。未重新识别或入库。

2026-11-14：C/D都关闭时B行上下padding缩为2px、行高1.25，金色徽章上下padding/margin归零；字号不变，开启任一详情恢复原样。14项HTML专项测试通过。最新文件：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114234918.html。未重新识别或入库。

2026-11-14：命中金色徽章移除前置✓及空格，保留名称/Subject链接及其他样式。14项专项测试通过。最新文件：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114235116.html。未重新识别或入库。

2026-11-14：修正阶段名称18px加粗后原7em列宽不足导致分隔符与右侧文字重叠；名称列增至10em并增加0.25em列间距，——左右各保留一个半角空格，仍右对齐。同步样式断言，未运行测试。最新文件：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1114235323.html。未重新识别或入库。

## 人工核对表规范集中归档（2026-11-15）

人工核对表技术契约统一见[人工核对表格式与交互规范](docs/review-format.md)，覆盖文件名/日期、HTML布局字号/色彩/对齐、D阶段证据、交互/导出、最后MD格式、实现归属和兼容限制。源码已交叉核对，本轮不修改实现。

2026-11-15：D行实际命中阶段名称使用对应背景色并设黑字，未命中/歧义保持原样。规范docs/review-format.md已同步。15项HTML专项测试通过。最新文件：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1115000820.html。未重新识别或入库。

2026-11-15：增加D行别名未命中后的拟新增alias→目标GPC名称预览，采用Karl选择的低对比灰蓝code；只有后续已命中时显示，不代表入库。16项专项测试通过。最新HTML：outputs/note-review/人工核对表_出价日2026-11-03_11.3｜Ps好价光盘_1115002605.html。同步文档为docs/review-format.md、_CURRENT.md、_TDD.md、_DEVLOG.md；后续回复明确列出实际同步文档。未重新识别或入库。

## GameFAQs链接字段（2026-11-15）

modou_test当前版本0007，在0006基础上仅增加game_product_config.gamefaqs_link（TEXT、可空、无默认值），保存完整GameFAQs URL。0007迁移在线校验库名为modou_test，锁等待10秒，不支持自动删除字段降级。ORM同步增加字段；目录读取与审核导入门禁接受0006/0007，以兼容新增可空列。正式库仍不在此次范围内。

## GPC类型字段（2026-11-15，0008）

GPC新增type：可空TEXT、无默认值，CHECK ck_gpc_type限制Base/rebase/Expansion/母子集/合集，定义见_DB.md。仅modou_test迁移，执行前检查current_database并设10秒锁等待。downgrade禁止自动删除字段。

名称及报价审核final.type默认为null，人工确认合法枚举后导入新GPC；不从Bangumi或版本名称自动生成类型。旧审核载荷不填时兼容；复用Subject或指定gpc_id时，显式类型须与既有值一致，不自动覆盖。版本门禁兼容0006/0007/0008，但非空type要求0008。别名查询原样保留目录信息，既有CatalogEntry匹配不以type改变识别结果。type不替代bangumi_main，不代表合集成员关系。


## GameFAQs兜底（2026-11-15，e63b9a20）

resolve增加gamefaqs_suggestion、stage_hits.gamefaqs及第五阶段stage_trace，AI上下文task=gamefaqs使用独立提示词。仅无前序命中时调用；校验HTTPS、精确域名及产品根路径，不能证明页面存在或内容正确。final.gamefaqs_link在两种审核入口中保留待核实建议；导入再次校验并要求0007/0008，可新建或补充已有GPC空链接，冲突拒绝覆盖。所有写操作仍在调用方事务中，门禁仅modou_test。共享STAGES扩为五段，HTML/MD、日志汇总、别名预览同步；HTML不承担直接审批。

## 单篇统计实现（2026-11-15，e5a19d63）

logging_setup.NoteStatistics由ContextVar关联四个CLI解析作用域，event的条目最终结果驱动计数；note_total记录实际规则范围总数。note_phase以monotonic切换并暂停父阶段，logged_request嵌套计入联网识别，四类耗时互斥。最后输出3行，使用SafeFormatter专用note_block分支逐行脱敏，允许仅受控行分隔和上下两行空白；保留run_id。捕获异常记录失败阶段，未获总数标未知，已完成与未处理不混淆。

memory_cli预读逐篇保存时刻与耗时，再恢复该篇统计，排除预读后等待其他文件和共享初始化的耗时；共享准备和批次输出单独记录。note_review关闭初步规则解析重复条目日志；import分支不生成解析统计。直接调用库函数不自动启用单篇摘要，需显式note_statistics作用域。


## 单行AI识别与11.3A测试（2026-11-15，7c2e4a91）

note_review.build_review将item.raw_line传入resolve的note参数，审核载荷note随之变为当前行。两个AI分支均使用ai_candidate白名单：id/bangumi_id、name/name_cn/name_zh/name_en、edition、summary；infobox只留中文名、英文名、别名、版本、内容版本、平台，兼容结构化和wiki多行别名块。删除请求中的图片、标签、评分、收藏等无关资料；完整candidates仍在本地审核证据保留，命中和平台判断继续使用原候选。两阶段系统提示词统一指向当前条目原始行。


## PS光盘候选及平台规则（2026-11-15）

build_review识别文件名/首行标题的PS+光盘条件，置ps_disc_filter；别名预筛后计算本地预读需求，resolve在各阶段唯一命中判断及AI发送前再次过滤。ps_platforms统一读取结构化/wiki infobox平台、platform/platforms和合规GameFAQs链接路径，仅匹配PS4/PS5及PlayStation 4/5，不使用名称、简介或报价默认平台作为证据。GameFAQs链接须为ps4/ps5产品，提示词要求返回同名同内容版本platforms并按选择平台给链接；stage_trace保留platforms。quote_platform在该模式按单平台/双平台及原文PS4规则决定quote.platform；非PS光盘模式保留原规则。未命中时的默认报价平台不构成候选证据，也不代表确认GPC。


## 审核HTML改版编号（2026-11-15，a47c9e12）

review_html.write_html新增parsed_at与revision_of关键字参数。生成HTML内嵌review-metadata JSON，含batch_id/content_hash/parsed_at/revision；哈希覆盖rows/source/title。revision_of校验内容一致，沿用解析时刻并扫描输出目录相同批次最高版本后递增。原解析时刻保存到秒和时区，标题/文件名展示到分钟。旧文件按MMDDHHMMSS尾缀校验显式parsed_at后按第1版基线生成第2版。不同批次同分钟命名冲突仍拒绝覆盖。不更改识别载荷或数据库结构。


## B行命中色与平台展示（2026-11-15）

review_html的阶段背景移到B1(hit-name)，B3仅PS4与未知平台使用platform样式，PS5普通td。旧载荷无stage_hits即将B3显示为？，并以platform=None生成问题提示，不修改源载荷。quote_platform对无任何命中返回None，新解析quote.platform为空、人工确认前不能入库。原解析批次使用revision_of生成新版，内容哈希不变。

## DeepSeek候选及交互记录接口（2026-11-16）

ai_candidate输出完整infobox的单行字段文本，保留字段顺序、重复字段及空值，多值转换为紧凑JSON，特殊字符转义。本地资料记录_ai_source=BGM本地，API=BGM-API，同Subject沿用API覆盖本地；分来源编号。请求candidates为带完整标识的字符串数组；每项经ai_candidate_line按UTF-8限制为最多200字节（含标识、冒号与末尾…）。超过200时取前197字节并丢弃末尾不完整UTF-8字符，再追加3字节省略号；未超限保持原文。两个AI阶段复用同一受限列表，原始候选、候选标识映射和命中证据不截断；返回candidate/edition/reason，程序校验candidate并映射回bangumi_id用于既有审核。GameFAQs沿用产品建议返回结构，候选与前次建议不携带内部ID映射。

ai_client.interactions在请求边界累计白名单记录：call_id/system/user/raw_response/content/status/error。读取正文先于响应解析；HTTPError正文及IncompleteRead.partial保留。错误仅保存类型和有无正文，不保存异常原始信息或请求头。resolve在finally中提取本次新增记录并标注DeepSeek或GameFAQs阶段，输出ai_interactions，失败也不丢弃。system/user是实际payload中的字符串，不由渲染器重建。

HTML将各条各阶段记录HTML转义后放入独立template；textContent呈现，禁止innerHTML插入记录。独立浮窗限制视口、内部滚动，mouseleave延迟200ms关闭，mouseenter取消；支持焦点触发、Esc和关闭按钮。JSON格式化为另行阅读视图，原始保存值不修改；再次悬停恢复原文。全部资源内嵌，无外部请求。

## 浮窗显示切换（2026-11-16，c8a41e7b）

浮窗以formatted=true/wrapped=false初始化，render仅改变展示文本和pre的white-space/overflow-wrap，JSON格式化与折行独立；保留原始记录，每次show重置。按钮文案显示下一步操作。

## 浮窗烟粉卡片布局（2026-11-16）

详情模板按调用编号生成四个section.ai-block，模型content增加ai-reply类（#34252f背景、#493440标题、#8a6277边框）。template内容逐字段escape；show克隆模板节点，将每个pre的原始textContent保存在节点属性，render分别格式化JSON或恢复原文。formatted/wrapped默认false且每次打开重置。pre不设高度上限，overflow-x:auto/overflow-y:hidden；浮窗max-height:70vh、overflow-y:auto。

## 浮窗深色滚动条（2026-11-16，b6d28f40）

浮窗与pre局部声明color-scheme:dark/scrollbar-color；WebKit滚动条宽高12px，深灰轨道#2b2b2b、圆角灰滑块#9e9e9e及hover #b5b5b5。平台可能使用原生叠加滚动条，形状由浏览器决定；不采用自绘滚动逻辑。

## 浮窗全局及逐块换行（2026-11-16）

每个pre维护wrapped属性，标题内ai-block-wrap按钮仅修改对应pre；render根据各自wrapped设置white-space/overflow-wrap并更新内嵌SVG、aria-label/title/aria-pressed。All按钮检查所有pre：全true时全部设false，否则全部设true；JSON格式化不修改wrapped。关闭内嵌SVG及图标路径为固定程序常量，不依赖网络；原始交互仍通过escape和textContent安全显示。

## 三行交互概要（2026-11-16）

interaction_summary从当前条目stage_trace读取最近API候选证据（否则本地），stage_hits按DeepSeek/GameFAQs独立取选择。全部动态值转义并压平原文换行；概要三行nowrap及横向滚动。共享ai-summary-badge定义14px字体，selected仅覆盖颜色边框及字重，不改变字号；原文徽章16px。概要不含pre，不参与详情格式化/折行。

## 概要排版与A行斜体（2026-11-16，d74e2a91）

interaction_summary将后两项拆为ai-summary-label和ai-summary-value；两列CSS grid采用max-content/minmax(0,1fr)，内容min-width:0与overflow-wrap:anywhere，徽章max-width:100%及box-sizing:border-box避免溢出。概要与ai-call同12px/1.5 system-ui及#a6b5cb；首项14px斜体，徽章font:inherit，selected保留字重和底边框。页面.original统一font-style:italic。


## 取消Bangumi主版本外键（2026-11-16）

按Karl快马加鞭授权，modou_test已执行0009迁移，移除game_product_config.bangumi_main的数据库外键；字段保留可空TEXT及主版本Subject ID语义，允许对应主版本尚未入库。ORM同步移除外键，目录读取及审核导入版本门禁兼容0009；相关测试代码已更新。按Karl要求，未运行测试或迁移后验证。正式库未连接或修改。


## B行GPC字段与问题集中展示（2026-11-16）

review_html的B行与表头采用18/32/10/10/7/6/6/11百分比8列；C行对任何非空问题列表生成colspan=8。BGM_main/type从final非空值或命中目标已保存字段读取；final的gpc_id/bangumi_id改选其他目标时不复用原目标字段。type复用models.GPC_TYPES生成disabled select，空值为待确认，不补造主版本或分类。平台样式列位改为索引4，D行缩进跟随首列18%；JS导出固定选择索引0/1/4/5/6/7，避开select.textContent中的全部选项。生成器不读取数据库、不更改载荷及导入契约。34项HTML专项测试通过；MD生成逻辑不变。


2026-11-16修正：type仅使用final或带gpc_id的命中GPC中的合法产品类型，隔离Bangumi同名type（4为游戏条目类别）；未知或非法值显示待确认，不追加下拉选项。灰化禁用下拉内容通过text-align及text-align-last水平居中。34项HTML专项测试通过；当前8条离线页面11160004(12).html均为待确认，原载荷、解析时刻和旧版本保留；未重新识别或入库，浏览器人工验收待进行。


## main表头与主游戏链接（2026-11-16）

review_html.HEADERS第三列改为main，B行使用main_subject_link渲染bangumi_main；ASCII数字ID生成https://bgm.tv/subject/{id}链接，target=_blank、rel=noopener noreferrer。缺失值继续待确认，非数字值只进行HTML转义。字段来源和导出顺序不变，36项HTML专项测试通过。未重新解析、请求API、连接数据库、入库、运行全量测试或Git写入；未进行浏览器人工验收。


## DeepSeek候选200字节限制（2026-11-16）

新增ai_candidate_line，使用UTF-8编码长度判定，超限encoded[:197].decode(utf-8,errors=ignore)+…，确保总长不超过200字节且不截断字符。resolve在构造candidate_lines时统一调用，candidate_map保存原候选；候选选择及GameFAQs共用限制后列表。34项相关测试通过、7项跳过。真实运行d6df66e4d059的5次AI请求共22条候选文本逐项比对完整候选验证，18条截短、最大200字节，原始infobox保留；回执.tmp/candidate-200-byte-verification.json。


## D行歧义候选紧凑展示（2026-11-16）

review_html的D行阶段事件在result=歧义且存在candidates时隐藏重复reason，用冒号直接连接候选列表，候选仍用分号连接、HTML转义及现有subject_label链接；无候选明细及非歧义事件沿用原规则。按Karl要求未运行测试；未重新解析、调用API、入库或Git写入。


## 实体游戏候选分类过滤（2026-11-16，c8e42b17）

LocalDump.lookup_many在names(item)前执行item.type==4且item.platform==4001；AnonymousAPI.search保留搜索type=[4]及摘要type门禁，每项详情返回后执行item.type==4且item.platform==游戏，只有通过者才能返回resolve。使用严格值比较，不将字符串4/4001转换为数字，缺失字段不放行。API仍保留前10项搜索及请求缓存。PS4/PS5、候选200字节、别名、GameFAQs、审批导入契约保持。36项专项测试通过、7项跳过，无真实重解析。


## 0010测试库结构修订（2026-11-16）

modou_test已升级0010；仅允许目标库，锁表后要求GPC及报价为空再变更，拒绝隐式转换非空业务数据。移除uq_gpc_bangumi_id，增加(bangumi_id,platform,gamefaqs_link)联合唯一约束；NULL按PostgreSQL默认语义允许重复。ORM与_DB.md同步。

本轮仅结构层交付。catalog_memory及bangumi_cli版本门禁尚不接受0010；save_observation仍向报价写platform，目录导入仍以bangumi_id单独定位GPC。现有目录及报价导入不可直接用于0010，须后续按三字段身份适配，不自动补平台、不运行导入。


## DeepSeek输出额度配置（2026-11-16）

DeepSeek输出额度由项目根目录config.toml的[deepseek].max_output_tokens提供，要求严格正整数（拒绝布尔、字符串、浮点及非正值）；客户端创建时读取，映射到Chat Completions请求max_tokens，包含推理和最终正文。配置错误不静默回退，不包含密钥。


## 统一报价日期识别（2026-11-16）

日期统一由publication_date.infer_publication_date识别。优先显式published参数，其次本地文件名，再次笔记标题；URL路径不参与日期推导。无年份取Asia/Shanghai当前年；非法日期不采纳，继续尝试标题。parse_note接收统一published_date，正文合法日期可覆盖单条lowprice_date。HTML以quote.published_at为准，缺字段的旧载荷才推导；无法识别时保持NULL及待确认，不用解析当天冒充出价日。

## 主游戏归属建议（实施中，f4a83d19）
审核载荷新增main_resolution，包含status、subject_id、main_id、source及evidence。self表示自身为主版本，main_id等于subject_id；parent表示指向其他主版本；unknown/conflict/failed均不产生ID。main建议与人工final隔离。导入允许bangumi_main等于bangumi_id，旧的主版本自身留空约定由此修订：确认自身为主版本时保存自身ID，未知仍为NULL。其余未完成边界见_CURRENT.md。


### 主版本默认自身规则（a61d9e32）
已识别Subject且本地/API正常查询后无主版本时，默认main_id为自身，status=default_self；与证据确认的self区分。查询失败、关系冲突及无Subject保留待确认。HTML自身main以（ID）暗灰色#64748B纯文本显示，其他主版本保留新标签页链接。仍须人工确认后保存到GPC，既有结果不回填。


2026-11-16：main未确定时显示红底#F53535、黑字#000、字重700的全角问号？；自身主版本仍显示暗灰色无链接（ID），其他主版本保留链接。


2026-11-16：main未知时红底#F53535作用于整个td单元格（含padding），黑字加粗？；替代仅文字底色。其他main显示规则不变。


## DeepSeek候选完整JSON（2026-11-16）
按Karl快马加鞭授权，两个DeepSeek任务的candidates改为候选标识到资料的JSON映射；资料包含顶层name/name_cn及infobox别名、平台、游戏类型、发行日期，缺失null。不再限制单候选字节数，其他infobox字段不发送；本地原始wiki字段完整保留为字符串，API数组保留结构。模型仍返回候选标识并映射回Subject，不改变审核门禁。26项相关专项测试通过，覆盖两个真实请求边界结构、超过200字节内容不截断、原证据不变。真实重解析运行c9f85b0a5f47已启动，结果待核验。


2026-11-16：按Karl快马加鞭授权，DeepSeek用户提示改为原始名称、当前报价原始行、候选逐行文本；每行“候选标识：name=…｜name_cn=…｜别名=…｜平台=…｜游戏类型=…｜发行日期=…”，取消限长，数组紧凑JSON显示，仅v的数组项转为值，字符串换行转义。内部候选映射和返回标识契约保持不变，实际请求正文浮窗原样保存。26项相关专项测试通过；11.3A真实重解析416f60dae6c7已启动。替代前版用户消息JSON格式。



## 局域网在线审核架构（6f2c9a84，2026-11-17）
本节为在线审核与0010导入的当前设计，优先于历史未适配说明，不代表pricing搜索完成。FastAPI边界位于src/modou/web/app.py；service.py编排串行后台解析、审核和事务，links.py限制规范域名并记录主版本建议，store.py以原子JSON替换、单进程RLock及revision维护草稿。页面复用review_html.render_html及独立在线编辑资源。HTTP同源检查和自定义请求头阻止跨站写入；面向受信局域网单管理员，暂不提供账号权限。
原始证据与人工final/quote隔离，selected绑定保存版本；服务端再次校验全部勾选条目后，同一事务维护GPC、别名、来源与报价。0010导入复用catalog_import，按三字段NULL安全匹配；存在多个相同身份时要求指定GPC。platform仅写GPC，报价校验关联平台并按来源/GPC/地区/金额/日期/优惠复用。自身main归一NULL，note/display_name为空合法。数据库表级事务锁保护并发写入；草稿不支持多实例共享。
GameFAQs主版本使用独立main_subject AI任务，输入产品资料，返回main_subject_id和reason，详情type=4校验失败时保留未知。不填当前产品bangumi_id；自动和人工URL请求结果保留。GameFAQs限时、限大小并禁止重定向。不变更业务表结构或自动迁移，正式库仍禁止连接。接口、恢复和部署约定见docs/web-review.md。


## 审核交互完善（9b17c4e2，2026-11-17）
在线审核新增POST /api/batches/{key}/rows/{index}/restore与/reparse、GET /api/preview/{sid}。草稿增加parse_baseline、manual_fields、manual_target、previous_parse；旧草稿兼容重建基线。重解析先在单线程解析池计算替代行，再以原revision原子更新，仅替换目标索引，失败/冲突不覆盖。build_review新增only_line关键字参数，在完整笔记规则提取后、识别前筛选原始行号。前端串行mutation队列处理revision，字段change即时保存；所有审核门禁保留。


## Bangumi专用代理（c6e93a12，2026-11-17）
HTTP传输位于src/modou/http_transport.py。bangumi_urlopen仅允许HTTPS api.bgm.tv（默认或443端口），从项目根config.toml读取HTTP代理；专用ProxyHandler不应用proxy_bypass，防止NO_PROXY/Windows绕过。隔离opener拒绝跨主机及降级重定向，不安装全局opener，不回退直连。direct_opener显式ProxyHandler({})供DeepSeek两个客户端及GameFAQs使用。local_config.read_bangumi_proxy_url校验配置并独立于cwd；地址不支持凭据。AnonymousAPI缓存策略和transport注入接口保留。浏览器图片请求不经过服务端。

## 三表首次入库时间（0011，已被0012替代）

按e4b8a031及Karl排除data_source的执行澄清，GPC、别名、报价增加created_at，TIMESTAMPTZ NOT NULL DEFAULT now()；ORM使用server_default，无onupdate。数据库默认取事务开始时刻，更新/复用不覆盖。data_source及recorded_at不变。0011校验目标库、10秒锁等待、锁定三表并确认空表后增加字段，非空拒绝迁移，不支持自动降级。目录读取、CLI新结构分支及网页提交门禁接受0011；沿用0010导入原语，不改变产品身份或报价去重。完整结构见_DB.md。


## 日期栏与审核标记修正（e8a24c71，2026-11-17）
service.refresh_review_state基于parse_baseline计算manual_fields及manual_target，金额按Decimal值比较、ID按字符串归一；人工命中按外部身份（无外部身份时GPC）比较，不由点击动作强制置真。red_columns合并已有记录、解析基线和当前eligibility_errors对应列，独立于审核资格。public_batch仅在副本补齐旧草稿状态；edit_row前后累计红底并持久化，restore_row保留该记录，prepare_row新建空记录后按新解析计算。前端candidateSelection对相同身份不覆盖其他字段；日期统计使用独立web-summary避免更新文本销毁按钮，页面内日期编辑显式收起/展开。

## 来源关联与时间（0012，2026-11-17）

本节取代0011三表时间设计：删除GPC、别名、报价的created_at；GPC和别名增加必填BIGINT sources_id外键，报价沿用原有来源外键；data_source结构不变。GPC/别名来源记录首次创建来源，复用及资料更新不覆盖，新别名记录自身来源。来源recorded_at不是每条业务记录的独立新增时刻。

共享get_or_create_source负责创建/复用来源，保留原有来源时间和发布日期冲突门禁；目录写入先取得来源，再建GPC/别名，报价复用相同来源。无来源的手动目录录入使用source_path="手动插入"。source_path唯一意味着手动记录共用来源时间，不承诺逐次手动操作审计；直接SQL插入须显式提供来源ID。

0012校验库名、10秒锁等待、锁定四业务表后确认目标三表为空才变更，不转换已有数据，不自动降级。CLI写入和HTTP提交要求0012来源结构；只读别名门禁增加0012。网页服务重载加载新模型，批次草稿无需改写。


## 审核批次与勾选锁定（b8c14f62，2026-11-17）
Store在单进程RLock内创建批次并分配upload_index及batch_order，原filename/source_path不变；display_filename用于标题与列表。启动时仅为缺失编号的旧草稿补齐并原子持久化，不改业务行和revision。新批次created_at是本地草稿元数据，不是业务表字段；解析任务记录UTC parse_started_at/parse_finished_at及perf_counter计算的parse_elapsed_seconds，前端上海时区格式化，解析中更新已耗时。旧批次不推断解析时间。服务端edit_row/restore_row/reparse_one与重解析HTTP边界拒绝已勾选条目；批次日期修改遇到未入库且已勾选条目拒绝。前端将A行多选框放在inert范围外，保存控件禁用状态和C/D可见状态，选中后内容转灰压暗、历史红底保留、C/D强制隐藏，解锁恢复。历史红底下拉独立于edit状态，note文本固定；web-titlebar实现标题及日期右侧换行。

## 来源提交、判重与类型证据（0013，2026-11-17）

0013保留source_path可重复、跨来源报价判重及事务锁定的设计；来源归组已由0015取代：get_or_create_source按review_batch_id复用，recorded_at为审核批次创建时间，不再使用两小时窗口。CLI无审核批次时只在单次提交内共享来源；网页写入要求0015。0013本身仅删除source_path唯一约束并更新recorded_at注释，历史数据由后续迁移保留。

web.duplicates按完整身份唯一定位GPC，字段齐全才自动标记already_imported；解析结束、保存、读取恢复、重新解析及提交前检查。历史红底和人工修改标记独立。准备新GPC时按bangumi_id/platform查询相似项；HTTP409返回展示表及包含拟入库字段/现有完整记录的摘要token。用户确认后在同一数据库锁内重算，变化重新确认；原唯一约束保留。GameFAQs人工显示名同时更新name_zh并保存在草稿。

ProductTypes用于名称CLI及报价流程，已审核类型优先复用。取得Bangumi详情及主关系，必要时让DeepSeek提出GameFAQs检索URL并实际读取；检索URL须进一步核对同一内容版本。资料带E编号、URL、文本，确定规则命中停止，否则product_type任务返回type/reason/evidence_ids/candidates，校验枚举与证据引用；失败或证据不足返回null，Expansion不自动分类。GameFAQs拒绝重定向、限制2MB，/data只取首个Title Data避免其他版本混入。主关系的default_self不作为Base依据。

草稿type_resolution保存状态、类型、备选、理由、证据及AI交互；final.type仍需审核门禁。页面问号使用红底黑字，原生下拉备选通过CSS金色加粗并附文本标记；类型依据可展开，Restore恢复解析基线，重解析建立新基线。


## 动态审核与逐条入库（7d3a90c2，2026-11-17）
已实现在线筛选按钮调整、D行命中/拟增双模块、Restore与重解析位置调整、单条入库及已入库展开按钮、批量数量确认、每10条发布与页面轮询追加、全部完成特效。公开URL正文入口与TXT共用解析流程，登录或正文提取失败明确报错。拟增预览不持久化、不改变审核revision；解析发布在草稿锁内追加，不覆盖人工结果，修改日期沿用于后续条目。沿用0013，无数据库迁移。

专项85通过、10跳过（未启用数据库专项或历史样本缺失），未运行全量测试或写入真实业务数据。隔离浏览器已观察单条入库成功、自动勾选锁定及展开类切换；顶部布局和展开CSS随后修正，尚未完成最终浏览器复验；动态追加、相似确认与全部完成特效的完整浏览器验收仍待完成。4001尚待重载。不得将此状态等同于全部验收完成。


## 审核展示与数据语义修正（f3a82c19，2026-11-17）

0014对m_low_record.lowprice_method增加ck_price_method_nonempty（length(trim(lowprice_method))>0），将旧空字符串转为“直接购买”；ORM和迁移一致，前端选项、解析、校验及判重统一新语义，旧草稿读取时转换。后续0015保留该购买方式语义；当前网页提交要求0015，目录读取及CLI接受0015。
prepare_row严格隔离Bangumi subject.type与GPC type。english_name同时支持dump字符串和API结构化infobox，严格采用三步：优先Bangumi明确英文名/英文标签别名，否则检查原名是否仅含英文字母、可带变音符号的拉丁字母、数字/空格/符号，仍未知则留空并显示红底黑问号。字符检查兼容预组合及组合变音符号，至少含一个拉丁字母；不使用未标注英文的别名或候选自身name_en兜底，已有GPC非空英文名继续复用。name_en_unknown保留未知红底历史，manual_fields.final.name_en驱动斜纹，人工编辑经现有字段保存接口持久化。
proposed_inserts为只读衍生数据，不持久化；未入库别名隐藏gpc_id及空可选字段。已入库按receipt.record_id关联实际GPC/别名/报价，返回stored与operation标记；新回执added记录本次新增表清单，旧回执标注新增/复用未记录。显示读取当前数据库记录，不声称是不可变入库时快照。


## type按main简化判定（93a7c2e8，2026-11-17）

已按93a7c2e8简化type：保留已审核GPC类型复用；新识别条目的有效main与bangumi_id相同取Base，不同取母子集，其他情况留NULL，动态表显示问号。default_self同样参与比较。取消type专用Bangumi详情/GameFAQs资料检索、内容规则及DeepSeek判断；名称识别和main流程保持原逻辑。已有数据库记录及历史草稿不批量改写。本节取代此前type资料检索及AI分类流程说明；五种合法类型枚举及人工审核门禁保留。


## 动态表布局与明暗（7b29d4a1，2026-11-17）

动态表底部不再追加type判定依据，审核载荷/API仍保留type_resolution。Restore与重新解析在D区右上角上下排列；取消整行顶部留白，仅首个内容块为按钮预留空间，窄屏改在命中区域预留。顶部勾选/入库统计与筛选控件同行。拟增（非已增）标题、字段名及数据值统一使用适中文字#98a5b7，表头#1b2636，边框#354154；未知字段红底黑字及按钮/命中区亮度保留。配色集中在src/modou/web/static/review.css的--proposal-text/--proposal-head/--proposal-border，旁附轻/中/深三档颜色。


## 动态表统计口径与已增表名（2026-11-17）

重新解析与Restore在D区右上角横排，重新解析在前。已增模块逐表显示“别名表（game_alias）”“GPC表（Game Product Configuration）”“报价表（m_low_record）”，并沿用回执的新增/复用状态；旧回执明确显示新增/复用未记录。顶部三个详情按钮按工具栏中心对齐，窄屏独立一行居中。统计精简为“已勾选S/U条 · 已入库I/T条”：T为全部、I含本次及早已入库、U=T-I、S仅含未入库且勾选；仅看未选只筛除未入库且已勾选条目，不改变已入库条目显隐，后者由仅看未入库控制。本节取代此前按钮竖排及将已入库计入已勾选的展示约定，拟增明暗设置保持不变。


## 首页批次展示契约（2026-11-17）
/api/batches增加created_at/error；URL草稿新增source_kind=url及source_title，旧草稿通过HTTP source_path及去掉.txt的filename兼容。display_filename只提供名称，重复次数追加在完整名称后，首页添加书名号及状态。日期使用created_at优先、parse_started_at兜底，上海时区自然日比较，每秒刷新跨日样式。首页提交后单次刷新与固定轮询分开，避免提交增加轮询链。A行和AI原文共用original_with_section，读取extracted.section剥离边界装饰并转义输出；不修改raw_line和解析身份。无数据库结构变化。
