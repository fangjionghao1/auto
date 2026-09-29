---
name: paper-batch-pipeline
description: 按目录中的src.md和speek.md串行生成、续作或复审论文，前置实验有效性审查，失败时重设计实验，交付MATLAB图源与可复现资产，并按标题和作者更新goal.md。适用于批量论文项目，不用于只润色现有段落。
---

# 批量论文生成与实验闭环

以含 `src.md`、`speek.md` 的每个项目目录为执行单元，串行完成；真实有效的研究结果、MATLAB资产和审稿证据全部满足后才更新完成状态。

## 开始

先读 [总提示词](references/master-prompt.md)，用它统筹流程；脚本接口及状态格式见 [执行协议](references/protocol.md)。用户只要求优化提示词、演示或扫描时，只做该范围，不启动真实论文生成。

将 `<SKILL_DIR>` 替换为本技能所在目录，`<WORKSPACE>` 为用户工作区。优先使用已有Python 3.10+，无须安装第三方Python包。

```text
python "<SKILL_DIR>/scripts/pipeline.py" scan --workspace "<WORKSPACE>" --output "<WORKSPACE>/.paper-pipeline/scan.json"
python "<SKILL_DIR>/scripts/pipeline.py" compose --workspace "<WORKSPACE>" --project "<PROJECT>"
```

`scan`只读盘点；`compose`保存并完整回显最终提示。**回显完成后才运行该项目实验或生成论文。** 脚本负责清单、提示合成和台账一致性，论文研究、科学判断、真实MATLAB执行及文档审校由执行代理完成。

## 必守门禁

- 默认遍历所有符合条件的项目版本，不按同标题或ID偷偷合并；已有仿真、图片子目录不使项目失去资格。只有明确选择 `--scope goal-paths` 才只处理台账当前路径。每个排除项目都留原因。
- 优先使用 `test/README.md`，不存在则回退 `test/script/README.md`；两份并存且不同须明确选择。记录规则路径/哈希；执行期间规则或输入变化会使旧放行失效，按影响范围复验。
- **实验过分理想化、关键现象未覆盖、方法无有效贡献、实验不能支撑题目中的核心承诺，均不可交付。** 先查数量级、物理约束、类别覆盖、数据泄漏和强基线，再跑独立先导。未过门禁不得提前写有结果的摘要或终稿。
- 失败后必须形成根因及修订设计，保留失败版本与所有结果，按新方案重新实验；不能靠改文字、换指标、挑种子、删困难样本或降低原任务目标过关。重新设计不保证产生有利结果。
- Python可用于数量级计算、先导、预处理、独立复算；最终图必须由真实MATLAB运行生成可编辑 `.fig` 和同源 `.png`。根据项目要求决定是否完整MATLAB复现；不能把Python结果改扩展名或伪造MATLAB执行记录。
- 正文、数据、代码、图源、数值复核和审稿链缺任一关键环节，不能填“已完成”。要求正式签署而尚未签署时填“待签署”，不得代签。

## 执行节奏

每项目依次执行：合成并回显提示 → 目标配置/实验设计 → 数量级与先导门禁 → 主实验及独立验证 → MATLAB资产 → 论文/Word/逐页检查 → 审稿与修订 → 台账。仅同一项目内可并行检索或独立复核，不并行启动第二篇。

批量任务已授权完整生成时，保存框架并自检后自动继续；不沿用通用src里的“框架后等继续”造成无谓暂停。确有目标硬限冲突、关键数据/运行环境缺失、签署等待时，记录真实阻断并处理下一项目，完成整批遍历；依审稿规程的返修轮次上限结束无效循环，默认最多3轮完整重设计。

已完成旧稿也要对照当前实验有效性红线；“数据真实但方法无增益”的旧报告不自动满足新门禁。本次仅安装skill时不追改现有论文或台账。

## 工具衔接与交付

实际需要时使用已安装的 `matlab-simfit-accel`、`md-to-docx-omml`、文档渲染能力；技能不可用时用等效可运行工具完成相同检查，不能仅因别的skill缺失跳过要求。MATLAB不可用时可继续Python先导和正文草稿，最终交付保持阻断。

完成科学审查后按协议写项目 `.paper-pipeline/status.json`，先预览台账更新，再执行：

```text
python "<SKILL_DIR>/scripts/pipeline.py" update-goal --workspace "<WORKSPACE>"
python "<SKILL_DIR>/scripts/pipeline.py" update-goal --workspace "<WORKSPACE>" --apply
```

不得把脚本验证成功当成科学门禁通过。整批结束再次扫描，报告完成、待签署、需重设计、阻断和待定位的数量及路径。

## 案例

[功角预测案例](references/example-power-angle.md)给出可执行的隔离演练：发现单类先导 → 禁止交付 → 保存重设计方案 → 更新示例台账。运行入口为 `scripts/demo_case.py`；它不改真实项目，不生成虚假的“成功论文”。
