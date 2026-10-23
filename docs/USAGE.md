# 命令

全部命令只写在这里。每一步内部怎么运转见 [HOW_IT_WORKS.md](HOW_IT_WORKS.md)。`uv run avs --help` 列出全部命令，`uv run avs <命令> --help` 列出参数。

| 小节 | 做什么 |
| --- | --- |
| [装好](#装好) | 第一次运行前 |
| [处理新的一集](#处理新的一集) | 分离人声、切片段、算声纹、核对覆盖 |
| [补片段](#补片段) | 把漏掉的对白行补进旧的片段表 |
| [标注与修正界面](#标注与修正界面) | 日常主流程：标几句、让机器猜、改它猜错的、导出 |
| [标注](#标注) | 盲标检验集用的旧页面 |
| [分组、打分、导出](#分组打分导出) | 不经界面，按机器分组打分、导出；留作对照 |
| [对照实验](#对照实验) | 扫分界线、量漂移、比分不分得开、近邻诊断 |
| [检查](#检查) | 提交前跑的检查 |

## 装好

需要 FFmpeg 在 PATH 里。GPU 环境和各模型说明见 [TOOLS.md](TOOLS.md)。

```powershell
uv sync --locked
uv run avs doctor
```

## 处理新的一集

```powershell
uv run avs prepare "D:/_search/ani/uma/[DHR][Uma Musume S2][04][BIG5][1080P][HEVC_AAC].mp4" --subs "data/ass/uma/[FLsnow][UmamusumeS2][04][HEVC_FLAC][BDRIP].chs.ass" --name ep04 --out runs/episodes/ep04 --offset -0.96
uv run avs embed runs/episodes/ep04 --model anime-va
uv run avs embed runs/episodes/ep04 --model anime-char
uv run avs embed runs/episodes/ep04 --model redimnet2-b6
uv run avs coverage runs/episodes/ep04 --subtitle "data/ass/uma/[FLsnow][UmamusumeS2][04][HEVC_FLAC][BDRIP].chs.ass" --out runs/coverage/ep04
```

视频和字幕都必需。音轨默认从视频里抽；另有同一时间线的无损音轨就用 `--audio` 给，时长和视频差超过 0.5 秒会拒绝。界面默认把三个声纹模型拼在一起用，所以三个都要算。

**建议直接给 `--offset`。** 同一片源同一字幕组的偏移是稳定的（第 1 至 3 集实测 -0.95、-0.96、-0.96），给了就完全不跑语音检测。

`coverage` 验收切得对不对：「有片段的对白行」应该等于对白行总数（第 3 集是 375/375）。它顺便把没有片段的台词切成音频，放在 `below_floor`（行本身太短）和 `no_speech_found`（行够长却没切出）两个目录，另出 `lines.txt` 和 `report.json`。

## 补片段

```powershell
uv run avs extend runs/episodes/ep02 --subtitle "data/ass/uma/[FLsnow][UmamusumeS2][02][HEVC_FLAC][BDRIP].chs.ass"
uv run avs embed runs/episodes/ep02
```

把字幕里没有对应片段的对白行补进片段表。只增不改，已有标签照旧有效。片段表变了声纹缓存就失效，所以要重跑 `embed`。补进来的解说、欢呼不在这里挑，标注时由人打标签。

## 标注与修正界面

工作区是一个目录，下面的 `episodes/` 放各集（`prepare` 的输出），标签自动存在 `labels/`。本仓库用 `runs/` 当工作区。

```powershell
uv run avs app runs
```

在浏览器打开 `http://127.0.0.1:8765`。`--port` 换端口，`--no-open` 不自动开浏览器，`--model` 可重复，只用指定的声纹模型。网址 `#` 后面记着当前的视图、集、角色和选中的句子，刷新后回到原处。

只给要收集的人（目标角色）起名字，别的人一律按 Q 标「其他」，拿不准是不是目标角色的也标「其他」。几个人同时说话、里面没有目标角色的，欢呼、音效这类不是说话的，也标「其他」。目标角色自己的笑声、叹气算 TA 的声音，标成 TA。每个目标角色有两个选项，一次选好：数字键是干净的 TA，Shift + 同一个数字是「TA·质量低」，给背景音太重或有人同时出声的，不拿来认人，导出时跳过、写进 `rejected.tsv`。两个目标角色时底部一共 5 个选项（再加「其他」）。改标成干净的 TA 或「其他」时，「质量低」自动去掉。目标角色可以有好几个，在「角色」视图里随时加减，加减时已有的标签怎么算见 [HOW_IT_WORKS.md](HOW_IT_WORKS.md#标注与修正界面)。

- **起步分组**（G）：没有标签时先来这里。机器把听起来像同一个人的片段归成一组，一次标一整组：点目标角色的头像，定成一个新的目标角色，或者「都是其他」。名字可以不填。也可以用按键只标选中的那一句；标过的句子留在组里、显示标成了什么，组按钮只管还没标的，按 Z 撤销后原样回来。
- **场景**（S）：按集、按场景列出全部台词。左边放画面和机器猜的名次，「只听人声」时画面照放、换成分离出的人声；空格或再点一下选中的那句会重播。看不出是谁时按 L，这句临时前后各多放 5 秒，再按 15 秒，再按回到平常，换一句自动回到平常。目标角色附一条参考音，Enter 接受第一名，数字键选底部的目标角色，Q 标「其他」，`/` 搜索或新建角色。F 只看要人处理的。短于 1 秒、前后 0.5 秒内没有别的台词的短句标成「太短，默认跳过」，不算要处理的，「整集」里也默认不显示，点「显示短句」才列出来，想标也能标。
- **角色**（O）：左边上面是目标角色，下面是不再作为目标、但还有标签的角色，最后一行是「其他」的句数。点开一个角色，先列机器归给 TA 的，从最没把握的开始，可以连着播；X 标出「不是这个角色」，Shift+Enter 确认其余。再往下是「可能漏掉的」：机器没归给 TA、但听起来有可能是的，从最像的开始，和别处一样标。这里也能改名、合并角色、设头像、设为或不再作为目标角色。
- **导出**（E）：选角色和格式（GPT-SoVITS、Style-Bert-VITS2 或按角色分文件夹），可以只导人确认过的，也可以带上机器有把握的。切片段的字幕是中文译文、要训练日语模型时，「台词文字从哪来」选「每集另配的台词字幕」，在下面每集贴上日文字幕的路径，点「对齐并配上」；也可以用下面的 `set-text-subtitles` 命令配。配不上台词的片段不导出，明细在导出目录的 `rejected.tsv`。

认人主要靠头像，名字可以不起：

- N 把当前这句标成一个新角色，先叫「角色 1」「角色 2」这样的临时名字，以后在「角色」视图里点「起名字」再补。
- 没截头像的角色显示一张按编号生成的图（底色、形状、花纹三样一起变），不同角色一眼分得开。
- 截头像：新建角色时有画面就会直接弹出来；以后在舞台上点已确认角色的头像，或在「角色」视图点「截取头像」。拖方框挪位置，拖右下角或滚轮缩放，滑块换一帧，Enter 保存。

每次标注立刻落盘、立刻重训；Z 一直往回撤销。全部快捷键按 `?` 查看。页面默认白天配色，顶栏右上角可以切到夜间，选择记在浏览器里。

旧的集补信息用的命令：

```powershell
uv run avs set-video runs/episodes/ep01 "D:/_search/ani/uma/[DHR][Uma Musume S2][01][BIG5][1080P][HEVC_AAC].mp4"
uv run avs set-subtitles runs/episodes/ep01 "data/ass/uma/[FLsnow][UmamusumeS2][01][HEVC_FLAC][BDRIP].chs.ass"
uv run avs set-text-subtitles runs/episodes/ep01 "data/subtitles/uma_s2/ja/Netflix/ウマ娘.プリティーダービー.S02E01.トウカイテイオー.WEBRip.Netflix.ja[cc].srt"
uv run avs import-labels runs --annotation annotations/ep01-full.json --annotation annotations/ep02-full.json --annotation annotations/ep03-full.json --target teo
uv run avs migrate-targets runs --target teo
```

- `set-video`：给 `prepare` 改成必需视频之前处理的集记上视频。时长和音轨对不上就拒绝。
- `set-subtitles`：给没记字幕的集补上字幕，偏移从已有片段推出来，按时间重叠找台词文字。
- `set-text-subtitles`：给一集另配一份字幕（ASS 或 SRT），导出时台词文字从它取。偏移自动量，和切片段的字幕对不上就拒绝。来源以 Netflix、Amazon 的为好，电视台录的字幕带 🎤 之类的符号，不会被去掉。
- `import-labels`：把旧的人工归档一次导进标签记录，只在记录还空着时可用，导入不能撤销。给了 `--target` 就接着做下面的 `migrate-targets`。
- `migrate-targets`：只留下给定的目标角色（可重复给），其余角色的标签都改成「其他」。改之前把 `labels/` 里的标签记录和角色表原样复制到 `labels/archive-日期-时间/`。迁移不能用 Z 撤回，要找回原来的名字就看归档。

## 标注

第 1 至 3 集是用这个旧页面盲标的，它不显示机器的猜测。独立检验取消后，新的集改在修正界面里标，这个页面留着备用。标注的规矩（为什么只认画面、为什么页面不给机器答案）见 [HISTORY.md](HISTORY.md#标注)，归档文件见 [annotations/README.md](../annotations/README.md)。

```powershell
uv run avs label runs/episodes/ep04 --archive annotations/ep04-full.json --all --known annotations/ep03-full.json --known annotations/names.json --video "D:/_search/ani/uma/[DHR][Uma Musume S2][04][BIG5][1080P][HEVC_AAC].mp4"
```

对照画面报名字，每条按下就存进人工归档。

- `--all`：标这一集全部片段，按时间顺序连着走。不给就随机抽 `--count` 条。片段表后来补进新片段时，再跑一次 `--all` 会把它们以空标签追加到已有归档，已标的不动。
- `--known`：页面上可点的角色名从哪来，可以重复给。给人工归档时，里面的片段还能在页面上回放；给 `annotations/names.json` 这种只有名字的词表就只有名字。名字按出现条数排序，数字键 1 至 9 对应前九个。
- `--video`：放当前片段对应的画面，前后各多给 0.5 秒。翻到哪条才用 ffmpeg 切哪条（一段两三秒实测不到半秒），同时预热下一条。统一转成 360p 的 H.264，一集约 46 MB。

  **视频和音轨必须是同一条时间线。** `data/raw/*.flac` 就是从这些 mp4 里抽的，时长精确一致、波形对齐位移 0 毫秒。换片源前先核对，否则画面会对错人。

页面操作：

- 角色名排成小块，点一下给当前片段打标。特殊标签也成块显示，否则标成「不止一个人」的片段就再也翻不出来复核。
- 名字右边的数字打开面板，按集和时间列出这个名字下的全部片段：本轮的点一下跳过去，旧归档里的点一下就地试听（用单独的播放器，不打断正在标的那条）。面板里可以改名、整批撤掉标签，也可以把某一条直接拖到另一个名字上改归属。
- 在筛名字框里敲一个新名字，点「＋ 建这个名字」先建出来再往上拖。没用到的名字和从列表里删掉的名字只影响当前页面，不落盘。

## 分组、打分、导出

```powershell
uv run avs group runs/episodes/ep01 runs/episodes/ep02 runs/episodes/ep03 --out runs/groups/uma-next.json
uv run avs evaluate runs/groups/uma-next.json --annotation annotations/ep01-full.json --annotation annotations/ep02-full.json --annotation annotations/ep03-full.json --out runs/groups/uma-next-evaluation.json
uv run avs export runs/groups/uma-next.json --out out/uma-next
```

`group` 的参数：

- `--threshold`：不给就用这个模型自己的默认分界线，并把它打印出来。
- `--relative`：按池子自己的距离定分界线（见[名词表](HOW_IT_WORKS.md#名词表)）。没有经过独立检验，默认不开，现状见 [STATUS.md](STATUS.md)。
- `--model`：`anime-va`（默认）、`redimnet2-b6`、`anime-char`、`wespeaker-resnet293`。换模型要重新扫分界线。
- `--method`：默认 `average`。另有 `single`、`complete`、`mutual_knn`、`two_stage`，都已排除，留着只为复算。

分组文件和导出目录每次用新名字，免得旧音频混进新结果。

## 对照实验

用人工标签挑出来的数字只能算探索，要另找一份没参与过的数据检验。

**扫分界线，比模型和合并规则：**

```powershell
uv run avs compare runs/episodes/ep01 runs/episodes/ep02 runs/episodes/ep03 --annotation annotations/ep03-full.json --model anime-va --model redimnet2-b6 --method average --low 0.25 --high 1.15 --out runs/comparison-next.json
```

会先核验各模型覆盖同一批片段。`--low` / `--high` 要按模型的相似度刻度给，默认的 0.20 至 0.90 是给 `redimnet2-b6` 定的，对 `anime-va` 几乎全无意义。

**量成绩随片段池变大怎么变：**

```powershell
uv run avs drift runs/episodes/ep01 runs/episodes/ep02 runs/episodes/ep03 --scored ep03 --annotation annotations/ep03-full.json --out runs/drift-next.json --steps 9 --seeds 8
```

被打分的那一集始终整集在池子里，只往池子里加别的集的片段。`--steps` 分几档，`--seeds` 每档随机抽几遍。报告并排给固定分界线和按池子定分界线两条线，`--multiplier` 可以试别的松紧。

**按集留出，把片段直接分到角色名下：**

```powershell
uv run avs classify-check runs/episodes/ep01 runs/episodes/ep02 runs/episodes/ep03 --test ep03 --annotation annotations/ep01-full.json --annotation annotations/ep02-full.json --annotation annotations/ep03-full.json --model anime-va --model anime-char --model redimnet2-b6 --out runs/classify/next.json
```

`--test` 那一集的标签不进训练，只用来打分，其余各集的标签都拿来训练。`--model` 可重复，多个时把声纹拼在一起，各模型的缓存要先用 `avs embed` 算好。报告并排给「最像的一条」「角色平均」「小分类器」三种做法，每份带逐条预测。

**只比同一角色和不同角色分不分得开，不做分组：**

```powershell
uv run avs scores runs/episodes/ep03 --annotation annotations/ep03-full.json --model anime-va --norm none --out runs/score-next.json
```

报告给排序正确率和相等错误率，按片段时长和是否跨集分层。`--norm` 可重复（`none` / `snorm` / `asnorm`），后两个是分数归一化，已排除。`--window` 读用别的最小音频长度算出的声纹。

**近邻检索与距离分布：**

```powershell
uv run avs diagnose runs/episodes/ep01 runs/episodes/ep02 runs/episodes/ep03 --annotation annotations/ep01-full.json --annotation annotations/ep02-full.json --annotation annotations/ep03-full.json --groups runs/groups/uma3.json --out runs/diagnosis-next
```

输出报告、全部标签配对的距离，以及 `examples/` 下可试听的错误实例。

**已排除路线留下的命令**，只为复算：`avs embed --window`（给短片段补相邻音频，存在 `embeddings/<模型>@w<秒数>`）、`avs references`（少量身份参考）、`avs label-plan`（只标候选改动过的片段）。

## 检查

```powershell
uv run ruff check .
uv run ruff format --check .
ty check src
uv run pytest -q
```

类型检查用 [ty](https://github.com/astral-sh/ty)，不在项目依赖里，装在本机：`uv tool install ty`。CI 里固定用 0.0.91。
