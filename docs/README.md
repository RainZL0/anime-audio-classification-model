# 文档索引

| 想知道什么 | 读哪份 | 主要小节 |
| --- | --- | --- |
| 现在到哪了、下一步做什么 | [STATUS.md](STATUS.md) | [正在检验的问题](STATUS.md#正在检验的问题)、[下一步](STATUS.md#下一步)、[文件在哪](STATUS.md#文件在哪) |
| 命令怎么敲 | [USAGE.md](USAGE.md) | [处理新的一集](USAGE.md#处理新的一集)、[标注](USAGE.md#标注)、[分组、打分、导出](USAGE.md#分组打分导出)、[对照实验](USAGE.md#对照实验) |
| 东西怎么运转、名词什么意思 | [HOW_IT_WORKS.md](HOW_IT_WORKS.md) | [名词表](HOW_IT_WORKS.md#名词表)、[五步流程](HOW_IT_WORKS.md#五步流程)、[打分怎么算](HOW_IT_WORKS.md#打分怎么算)、[数据文件](HOW_IT_WORKS.md#数据文件) |
| 哪些做法已经定了、哪些路已经排除 | [DECISIONS.md](DECISIONS.md) | [已经定下的](DECISIONS.md#已经定下的)、[已经排除的](DECISIONS.md#已经排除的) |
| 做事的规矩，以及每条吃过什么亏 | [HISTORY.md](HISTORY.md) | [打分](HISTORY.md#打分)、[调参数](HISTORY.md#调参数)、[标注](HISTORY.md#标注)、[保留与删除](HISTORY.md#保留与删除) |
| 实验做了什么、数字是多少 | [EXPERIMENTS.md](EXPERIMENTS.md) | 开头有按结论排的目录 |
| 依赖、模型、运行环境 | [TOOLS.md](TOOLS.md) | |
| 人工标签文件 | [annotations/README.md](../annotations/README.md) | |

## 每份管什么

一件事只写在一处，别处只放链接。

| 文档 | 只写 | 不写 |
| --- | --- | --- |
| STATUS | 当前数字、正在检验的问题、下一步、当前有效的文件 | 已定下的做法、实验过程 |
| USAGE | 命令和参数 | 为什么这样选 |
| HOW_IT_WORKS | 名词、流程、数据格式、打分的算法 | 规矩、实验数字 |
| DECISIONS | 已定下和已排除的技术选择，各一句理由加链接 | 数字细节、还没检验完的做法 |
| HISTORY | 做事的规矩，以及定下它的那次教训；清理记录 | 具体选了哪个模型、哪种切法 |
| EXPERIMENTS | 做完的实验和数字 | 计划、规矩 |
| TOOLS | 依赖和模型是什么、怎么接进来 | 谁好谁坏 |

维护时：计划变了改 STATUS；做完一个实验，数字进 EXPERIMENTS，由此定下的做法进 DECISIONS；被推翻的做法直接改掉或移进「已经排除的」，不留成流水账。

## 怎么写

用朴素易懂的话，不自造简称、不用行话。借来的指标名第一次出现时用一句话说清它衡量什么，统一收在[名词表](HOW_IT_WORKS.md#名词表)。已测事实、解释性猜想和还没做的计划要分开写。
