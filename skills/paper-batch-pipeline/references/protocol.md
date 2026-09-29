# 执行协议

## 运行条件与职责

本skill提供可直接调用的代理工作流及三个标准库脚本入口；它不自带论文生成模型或MATLAB许可证。Python 3.10+即可运行目录、提示词和台账工具。正式生成时还需要可实际运行的MATLAB及项目所需工具箱，以及可生成、渲染和检查DOCX的工具。先检测现有环境，不自动购买、安装或声称具备缺失能力。

Windows下临时编写的中文Python核验命令建议使用`python -X utf8`，文件读写显式指定`encoding="utf-8"`，避免终端编码导致乱码；本skill三个CLI入口已设置UTF-8输出。

`pipeline.py`只检查路径、身份、状态结构和文件哈希；科学有效性、图源真实性、作者确认及签署真实性由执行者和指定审稿人核查。任何`pass`都须有审稿证据，不能根据脚本退出码填写。

用户请求只演示、扫描或优化提示词时，遵守该范围。完整生成时以各项目目录为工作目录启动实验和文档命令；工具的`--workspace`仍指批次工作区。

## 1. 扫描与提示合成

以下`<SKILL_DIR>`为本skill绝对目录，`<WORKSPACE>`为工作区，`<PROJECT>`为扫描返回的项目绝对路径。将`python`换成本机已有解释器路径即可。

```text
python "<SKILL_DIR>/scripts/pipeline.py" scan --workspace "<WORKSPACE>"
python "<SKILL_DIR>/scripts/pipeline.py" scan --workspace "<WORKSPACE>" --output ".paper-pipeline/scan-001.json"
python "<SKILL_DIR>/scripts/pipeline.py" compose --workspace "<WORKSPACE>" --project "<PROJECT>"
```

- 默认根为`gen/artifacts`，范围`all`；不会按ID或版本去重，也不受Git忽略规则影响。项目存在资产子目录仍会被发现。上下级均含提示词时只处理最深提示词目录，父目录列入`shadowed`。
- 显式限定当前台账路径时，给`scan`和`update-goal`都加`--scope goal-paths`；`compose`指定扫描选中的一个目录。保持整批使用同一范围，保存被排除列表。
- 台账候选为`goal.md`、`src/goal.md`、`goal/进度表.md`。多个候选须显式`--goal "src/goal.md"`。表格须含ID、标题、作者、进度列；兼容本仓库`稿件ID/auth/标题/进度`列名。
- 审稿规则优先`test/README.md`，不存在才回退`test/script/README.md`；两份内容不同会报错，须明确`--review`。显式选择不意味着可以规避用户的实验有效性红线。
- 输入文件采用UTF-8，可带BOM。链接和junction不作为项目遍历，以免越出工作区。
- `scan --output`仅能写一个**不存在的新路径**，避免覆盖历史证据；复扫使用新编号或省略`--output`。
- `compose`将全部原文附在总提示后，写入并完整输出`final_prompt.md`；同内容不重复写，不同内容会备份至项目`.paper-pipeline/history/`。调用时给输出足够长度；界面截断则分段继续回显文件剩余内容，不能只说“已保存”。
- 已完成项目先核规则/输入/证据是否仍有效。不要为无变动的完成项目无条件重合成提示，产生无意义的新审稿版本。

`scan`中的`goal_match`必须为`matched`才可自动更新该行。匹配ID、标题和作者；空作者可由唯一匹配台账行继承，返回`authors_source=goal`。非空作者冲突不覆盖。仅靠标题相似不算匹配。

## 2. 项目状态

完整批处理开始时，为全部身份匹配的项目建立`.paper-pipeline/status.json`；已存在的有效状态应保留并核验。新项目填`待处理`，不要由旧台账“已完成”直接生成全门禁通过。初始化全清单后再串行运行，保证每完成一个目录都可准确聚合台账。

以下是**待处理模板**。身份取自扫描结果，哈希取当前真实文件；字符串说明须替换。未运行的门禁必须是`pending`，不得批量置为`pass`。

```json
{
  "schema_version": 1,
  "project_id": "扫描返回的稿件ID",
  "title": "扫描返回的标题",
  "authors": ["扫描确认的作者"],
  "phase": "queued",
  "progress": "待处理",
  "prompt_sha256": "合成后填写final_prompt.md的SHA-256",
  "inputs_sha256": {"src": "真实SHA-256", "speek": "真实SHA-256", "review": "真实SHA-256"},
  "gates": {
    "design": "pending", "experiment": "pending", "independent_v2": "pending",
    "manuscript": "pending", "matlab_assets": "pending", "review": "pending"
  },
  "artifacts": [],
  "review": {},
  "signature": {"required": true, "signer": "", "evidence_path": "", "evidence_sha256": ""},
  "reason": "待执行先导审查",
  "updated_at": "当前ISO-8601时间"
}
```

状态使用：`待处理`、`执行中`、`需重设计`、`阻断`、`待签署`、`已完成`。`phase`描述实际阶段，如`preflight`、`redesign-1`、`matlab`、`review`、`done`。门禁值使用`pending/fail/pass`。

| 门禁 | 判据与证据 |
| --- | --- |
| design | 目标配置、物理/数学依据、先验有效性判据、强基线、划分和预先冻结的实验设计 |
| experiment | 先导及最终独立保留测试满足核心问题的有效性要求；覆盖所有预定结果及失败 |
| independent_v2 | 按当前规程进行独立重算，记录与主结果差异、容差和复现范围 |
| manuscript | 结论与证据一致，引用核实、DOCX结构/OMML/逐页渲染检查满足要求 |
| matlab_assets | 真实MATLAB运行、数值核对、全部图源配对及一键复现包通过 |
| review | 当前版本审稿完成，Blocker/Major均为0；签署另记录 |

`artifacts`逐项填写`{"path":"相对项目的路径","sha256":"真实SHA-256","role":"角色"}`。完成或待签署至少要求下列角色：

| role | 文件 |
| --- | --- |
| manuscript_md / manuscript_docx | 当前论文.md / .docx |
| raw_mat / raw_csv | 原始.mat / .csv |
| matlab_entry / matlab_params | MATLAB入口.m / 参数.m或.mat |
| matlab_env / matlab_run_log | 实际环境记录 / 执行日志 |
| figure_fig / figure_png | 全部交付图逐项列入，.fig与同目录同名.png成对 |
| package | 可复现.zip |

数量与额外类型仍以项目要求为准，不是每种一份便必然合格。额外源码、证据也应加入清单，可用自定义role；打包哈希另外保存。最终核验前不可仅更新文件哈希掩盖已变更的内容。

当前审稿报告的`review`对象要求：`path`、`sha256`、`rule_sha256`、`prompt_sha256`、`blocker_count: 0`、`major_count: 0`。报告正文也须绑定相同输入、数据和资产版本，给出科学门禁证据。

签署要求由当前规则决定，扫描输出`signature_requirement`供人工复核；自动提取不是身份认证。规则未明确免签时按需签署处理。`signature.required=false`不能覆盖规则。只缺签署时用`待签署`；真实签署取得后填写`signer/evidence_path/evidence_sha256`，核对指定守门人，才可用`已完成`。签署证据和审稿报告可在工作区内，其他资产须在项目内。

## 3. 台账更新与结束

```text
python "<SKILL_DIR>/scripts/pipeline.py" update-goal --workspace "<WORKSPACE>"
python "<SKILL_DIR>/scripts/pipeline.py" update-goal --workspace "<WORKSPACE>" --apply
```

第一条预览；检查`changes/skipped/unresolved`后执行第二条。整批必须沿用所选`--goal/--review/--scope`。更新只改进度单元格，保留其余列、行、BOM和换行，原文件备份至台账旁`.paper-pipeline/history/`；检测到读取后台账变化则拒绝写入，重新扫描。

同一台账行聚合本次范围所有对应项目，优先级为：`阻断 > 需重设计 > 执行中 > 待处理 > 待签署 > 已完成`。每目录细节仍在独立状态文件和批次报告中；同一行只有所有项目均完成才显示完成。状态缺失、身份不明或歧义会使对应整行保持不动，并在报告解释，不能忽略警告后宣称成功。请求完成/待签署但哈希、门禁或资产不齐时，脚本将可匹配行聚合为阻断。

发生阻断先处理可解决的原因：修正路径、补生成资产、重算、重设计及复审。真实外部依赖或达到规程轮次上限才保留阻断并继续下一项目。最后复扫，汇总各目录状态、证据及剩余动作；不得将“清单遍历结束”写成“所有论文交付完成”。

## 4. 自检与演练

```text
python "<SKILL_DIR>/scripts/test_pipeline.py"
python "<SKILL_DIR>/scripts/demo_case.py" --output "<新的隔离目录>"
```

测试只使用临时工作区。演练拒绝覆盖已有输出目录，复制自带案例，完整回显提示，再执行真实Python先导并更新示例台账。它展示红线失败与重设计记录，不冒充已经通过实验或MATLAB交付的论文。
