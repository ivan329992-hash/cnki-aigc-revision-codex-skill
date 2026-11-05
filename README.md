# 知网 AIGC 对照修订 Skill for Codex

面向中文学术论文的 **报告驱动修订工作流**。先确认稿件与报告对应，再比较不同版本的标记范围，以事实、引用和技术边界为约束完成局部改写，而不是对整篇文章机械换词。

**不保证检测分数，不预测“AI率”，不替代作者的原创研究与人工审读。** AIGC特征值与普通文字重复率不是同一个指标。使用AI辅助写作时，仍须遵守期刊或机构的相关披露要求。

## 适用场景

- 已有中文论文和知网AIGC全文报告，需要定位并修订具体段落。
- 多轮改写后分数反升，需要对照旧稿、新稿及各自报告。
- 需要保留数字、文献、专业术语、适用条件和Word排版。

本项目不是检测器、查重平台、自动投稿工具，也不是通过隐藏字符、图片化文字或拼凑引用规避检查的工具。

## 安装到 Codex

将 `skills/cnki-aigc-revision` 文件夹放入用户级 `$HOME/.agents/skills/`，或当前项目的 `.agents/skills/`。目录位置与调用方式参见 [Codex官方技能文档](https://learn.chatgpt.com/docs/build-skills)。不要覆盖已有同名技能，也不要同时安装多个同名副本。

也可以直接使用指令词
 `帮我安装https://github.com/ivan329992-hash/cnki-aigc-revision-codex-skill.git这个skill`

### Windows PowerShell

在一个新的工作目录中执行：

```powershell
git clone https://github.com/ivan329992-hash/cnki-aigc-revision-codex-skill.git
$dest = Join-Path $HOME '.agents/skills/cnki-aigc-revision'
if (Test-Path -LiteralPath $dest) { throw '目标技能已存在，请先人工核对。' }
New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
Copy-Item -LiteralPath './cnki-aigc-revision-codex-skill/skills/cnki-aigc-revision' -Destination $dest -Recurse
```

### macOS / Linux

```bash
git clone https://github.com/ivan329992-hash/cnki-aigc-revision-codex-skill.git
mkdir -p "$HOME/.agents/skills"
test ! -e "$HOME/.agents/skills/cnki-aigc-revision" && \
  cp -R ./cnki-aigc-revision-codex-skill/skills/cnki-aigc-revision "$HOME/.agents/skills/"
```

安装后开启新会话；若技能尚未出现，重新打开Codex。显式输入 `$cnki-aigc-revision` 调用。

## 使用方法

### 单稿与报告

```text
使用 $cnki-aigc-revision。
稿件：./private-work/draft-a.docx
报告：./private-work/report-a.pdf
请先核对正文是否对应，再按报告定位局部修订。
保留事实、数值、引用和适用条件，另存Word，不覆盖原稿。
以20%以下为后续复检目标，但不要预测或承诺检测结果。
不要上传任何资料或调用收费服务。
```

### 两稿、两报告，且新稿分数反升

```text
使用 $cnki-aigc-revision 对照两轮稿件和报告。
先列出实际改动、新增标记、仍标记及不再标记的范围。
选择有依据的基准版，解释各区域是保留、参考还是重写。
不要将未改段落的新标记归因于某个同义词，也不要直接重写全文。
完成数字、引用、技术边界和逐页排版检查后，交付一个独立新版。
```

如果只有报告、没有对应Word，技能会先要求补充或确认版本，不会默认取“最近修改”的文件。

输出JSON包含私有正文和本地路径，只能留在私人工作目录。工具拒绝覆盖已有输出。`inspect`会报告规范化段落匹配情况、首页指标和启发式字体颜色定位；`compare`会报告插入/删除/替换、数值与引用变化、表格及参考文献变化。

这些结果**不是**AIGC分数估计、普通查重率或作者身份鉴定。规范化匹配不等于文件哈希一致；“未标记”不等于证明人类创作。扫描PDF、背景色标记、修订痕迹、内容控件、浮动文本框及复杂版式均需人工复核，短表格数值也不能脱离上下文判定匹配。脚本不修改Word；由Codex结合当前可用的文档工具另存修改稿并渲染检查。

## 本次匿名修改历程

已核验的知网检测节点为 **92.0% → 51.1% → 39.5% → 33.1% → 42.0% → 14.7%**，不是只修改了最后三次，也不是一路单调下降。早期进行了较大范围的表达修订，随后逐步改为按报告定位、复核论据和限定范围编辑。中间还穿插其他平台反馈及多次未直接复检的改稿，不能把六个检测节点理解为全部修改轮次。

后期一次按照通用提示词改写多个段落，复检反而升高；最终回到较低分版本，以两份实际报告重新划定修改范围，保留较稳定的后文，参考摘要的标记变化，修正重复字、数据总量歧义及持续标记区域的表述，再完成证据和排版核验。最终送检前仍存在少量人工修改。旧版说明只概括了最后三个节点，现已补齐前期报告记录。

最终报告低于当次20%的目标，详细过程见 [匿名案例](docs/anonymized-case.md)。

## 隐私和发布

仓库不包含真实论文、检测报告、截图、作者、单位、项目名称、实际正文或原始文件路径。示例和测试均为合成数据。技能不会自动调用检测平台或第三方改写接口；收费检测、对外上传与公开发布都须另行获得用户授权。

不要把真实输入、运行JSON或修订稿放进本仓库。`.gitignore`只是辅助措施，发布前仍需人工检查文件清单和版本历史。

## 许可与说明

MIT License。

