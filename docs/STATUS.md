# 当前状态与下一步

更新：2026-10-18。眼前的计划只写在这里，到初版发布为止的路线见 [ROADMAP.md](ROADMAP.md)。已经定下的做法见 [DECISIONS.md](DECISIONS.md)，实验数字见 [EXPERIMENTS.md](EXPERIMENTS.md)。

## 到哪一步了

| 环节 | 状态 |
| --- | --- |
| 素材 | 整季 13 集的音轨和字幕都在 `data/` 下，已处理第 1 至 3 集 |
| 片段 | 三集共 1184 条，其中 8 条短于 0.5 秒，没有声纹 |
| 声纹 | 三集在 `anime-va` 和 `redimnet2-b6` 下都算好了 |
| 分组 | `anime-va`、按整组平均距离合并、分界线 0.70。分成 258 组，98 个单条组 |
| 人工标签 | 第 3 集全部标完（375 条）。第 1、2 集标完原有的 242 和 243 条，后来补进的 324 条待标。合计 860 条有人工名字，34 个角色 |
| 打分 | 751 条能精确对上的标签：连上 12521 对，错误合并 146 对，该合没合 16712 对，连上的比例 42.8% |
| 导出 | 换了模型和分界线之后还没重跑 |

## 正在检验的问题

**按名字分类能不能比分组好。** 分组只连上了 42.8% 的同角色配对。新的做法是声纹模型不动，在已有人工标签上训练一个小分类器，把片段直接分到已知角色名下，拿不准的标成待确认。理由和整体设计见 [ROADMAP.md](ROADMAP.md#方向)。

分界线随池子漂移的问题（固定 0.70 在池子变大时会滑，对策是 `avs group --relative`）先放下：如果分类成立，分组只在起步时用来让人给整组起名字。数字留在 [EXPERIMENTS.md](EXPERIMENTS.md#分界线漂移)。

## 下一步

1. **按集留出检验。** 用第 1、2 集的标签训练，只在第 3 集上测。
   - 对照做法：每条片段跟第 1、2 集里最像的那一条已标片段同名。这就是分组所依赖的「一条比一条」。
   - 报两样数字：按片段时长分档的正确率；按把握从高到低排序后，前 50%、前 80% 和全部片段各自的正确率。
   - 第 3 集当初被用来挑 `anime-va`，所以这次只决定方向值不值得做下去，不算独立检验（见 [HISTORY.md](HISTORY.md#打分) 第 2 条）。
2. **第 4 集做独立检验。** 标注前不看任何机器结果，把第 4 集整集标完；再用第 1 至 3 集的标签训练，只在第 4 集上测。口径与第 1 步相同，而且在标注之前写死。
3. **补标第 1、2 集的 324 条。** 训练数据更多，也能顺便看 0.5 到 1 秒这一档在更多数据上是不是同样勉强（见[证据的边界](EXPERIMENTS.md#证据的边界)）。
4. 第 1 步通过后，按 [ROADMAP.md](ROADMAP.md#标注界面) 开始做标注界面。

## 文件在哪

| 内容 | 位置 |
| --- | --- |
| 三集的片段、音轨、声纹缓存 | `runs/episodes/ep01/`、`ep02/`、`ep03/` |
| 当前分组与打分 | `runs/groups/uma3.json`、`uma3-evaluation.json`、`uma3-ep03-evaluation.json` |
| 第 3 集独立检验 | `runs/groups/blind-redimnet*.json`、`blind-animeva*.json`、`runs/comparison-ep03.json`、`runs/score-ep03.json` |
| 分界线随池子漂移 | `runs/drift-ep01.json`、`drift-ep02.json`、`drift-ep03.json` |
| 模型对照 | `runs/score-models.json`、`runs/comparison-anime.json` |
| 对白覆盖核对 | `runs/coverage/ep01/`、`ep02/`、`ep03/` |
| 人工标签 | `annotations/`，见那里的 [README](../annotations/README.md) |
| 已被取代的旧报告 | `runs/superseded/`，见那里的 `README.txt` |
