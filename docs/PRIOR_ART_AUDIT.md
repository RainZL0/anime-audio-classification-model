# anime-audio-classification-model 重构与升级计划

> 版本：v1 草案　　日期：2026-09-05
> 适用对象：本仓库当前 `main`（commit `4f76cdd`）

## 1. 现状快照（实测数据，非估计）

| 项目 | 现状 |
| --- | --- |
| 代码文件 | 5 个 `.py`，共约 620 行，其中 `a002_网络基类.py` 文件名含中文 |
| 训练数据 | `训练集/钉宫语音` 95 条、`训练集/其他语音` 215 条 |
| 测试数据 | `测试集` 24 条，**无标签** |
| 音频规格 | 全部 44100 Hz / 立体声 / 16-bit PCM |
| 时长 | 目标类 294 s（中位 2.80 s），其他类 420 s（中位 1.71 s），共约 12 分钟 |
| 仓库体积 | 工作区 141 MB，`.git` 91 MB（wav 全部进了 git 历史） |
| 依赖管理 | `requirements.txt`，UTF-16 编码，包含失效包 |
| 测试 / CI / lint | 无 |

一句话总结：**这是一个用 12 分钟音频、40 维 MFCC 均值向量做二分类的单集实验脚本**，工程规范和方法论都需要重做，而不是修补。

## 2. 问题清单

### 2.1 会直接报错或导致错误结果的 bug

| 位置 | 问题 | 后果 |
| --- | --- | --- |
| `a002_网络基类.py` 类属性 | `save_model_per_epochs = SAVE_MODEL_FOLDER`（应为 `SAVE_MODEL_PER_EPOCHS`） | `current_epoch % "./saved_model"` 抛 `TypeError`，ANN 训练路径实际从未跑通 |
| `a002_网络基类.py` `initialize_nn()` | 先对**全量数据**做 z-score，再 `random_split` | 验证集统计量泄漏进训练，验证准确率虚高。文件顶部 TODO 自己也写了这一条 |
| `a001_preprocess.py` `unify_dim_t()` | 样本比 `dim_t` 长时 `zeros_length` 为负 | `torch.zeros(..., -n)` 抛 `RuntimeError`，且没有截断逻辑 |
| `a002_ANN.py` `__main__` | 函数体只有 `pass` | ANN 没有入口，README 承诺的三个模型只有 SVM 可用 |
| `a001_preprocess.py` `load_wav_data()` | `os.listdir` 不过滤扩展名 | 目录下任何非音频文件（`.DS_Store`、`desktop.ini`）都会让 `torchaudio.load` 崩 |
| `a002_SVM.py` `output_prediction()` | 对配置里的 `RESULT_FOLDER` 无条件 `shutil.rmtree` | 配错一次路径就是不可逆删除 |
| `requirements.txt` | `sklearn==0.0.post4` 是废弃占位包，安装时会主动报错；`torch~=2.0.0+cu118` 带 local version，PyPI 解析不到；还混入了教程遗留的 `mnist` | 依赖装不上 |

### 2.2 工程规范问题

1. **配置即全局变量 + `import *`**：`from a000_configuration import *` 把常量散播到所有模块，无法在一次进程里跑两组参数，无法做超参搜索，IDE 无法追踪来源。
2. **中文文件名 / 中文目录名**：`a002_网络基类.py`、`训练集/`、`分类结果/` 在 CI、Docker、非 UTF-8 locale 下都是雷区。
3. **`a00x_` 前缀假装依赖顺序**：这是脚本思维，不是模块划分。没有包结构，根目录一个空 `__init__.py` 但没有任何包。
4. **状态挂在类属性上**：`MyNN` 把 `criterion`、`optimizer`、三个 dataloader 都定义成**类变量**，多实例会互相污染。
5. **硬编码 `MY_DEVICE = 'cuda'`**，并且在数据函数 `preprocess_training_set()` 里调用 `torch.set_default_device()` 这种全局副作用。
6. **模型不可持久化**：SVM 的 `model`、`mean`、`std` 全在内存，训练和推理必须同一进程跑完；下次分类新一集还得重训。
7. 无日志（全 `print`）、无随机种子、无 CLI、无类型标注、无测试、无 CI。
8. **数据进了 git**：121 MB wav 让 clone 变成 91 MB 下载，且 `分类结果/`（程序输出）也被提交。

### 2.3 方法论问题（比前两类更致命）

1. **特征选择过时**：对 MFCC 在时间轴取均值得到 40 维向量，丢掉了全部动态信息（基频轨迹、共振峰变化、韵律），而这些恰恰是说话人身份的主要载体。2026 年做说话人识别，起手就应该是预训练说话人嵌入（ECAPA-TDNN / ResNet / CAM++），不是手工 MFCC。
2. **没有做任何音频前处理**：44.1 kHz 立体声直接喂进去，没有重采样到 16 kHz、没有单声道下混、没有响度归一、没有 VAD 去静音。字幕时轴切出来的片段前后必然带空白，还叠着 BGM 和音效。**动画音轨里的 BGM 是当前最大的噪声源**，而流程里完全没有处理。
3. **评估不可信**：
   - 划分是按片段随机划分，而所有片段来自同一集。相邻台词共享同一场景的混响、BGM、编码，模型可以靠「信道指纹」而不是「音色」拿分。
   - 类别不平衡 215 : 95（69% / 31%），却只报 accuracy。全预测为负类就有 69% 的 accuracy。
   - 验证集只有约 62 条，单次划分，没有交叉验证、没有固定种子，两次运行的数字不可比。
   - `测试集/` 没有标签，也就是说**这个项目从头到尾没有一个诚实的泛化指标**。
4. **问题被建模错了**：真实需求是「从一集动画里挑出角色 A 的台词」，这是**开集（open-set）说话人验证**问题：非目标类是无穷开放的（新角色、旁白、路人），不是一个可枚举的「其他」类。当前建模成闭集二分类，换一集就会大面积误判。
5. **数据量与模型容量不匹配**：250 条训练样本配 6 层 MLP、`lr=0.01`、`TOTAL_EPOCHS = 100000`，没有早停、没有学习率调度、没有类别权重。

## 3. 目标形态

重构后的项目应该能做到：

1. **输入一集动画的音频 + 字幕文件**，输出「哪些台词属于角色 A」的带置信度结果（CSV / JSON），并可选地导出音频片段。
2. **注册（enrollment）式使用**：给 5 到 20 条角色 A 的干净样本，就能在新一集上工作，不需要为每一集重新准备「其他语音」。
3. **可复现**：一条命令跑完 `prepare → embed → train → eval`，指标写入 `runs/<run_id>/metrics.json`，随机种子固定。
4. **诚实的指标**：按集（而非按片段）分组的交叉验证，报告 PR-AUC、EER、以及「在召回 0.9 时的精确率」这类贴合使用场景的工作点。
5. **可扩展到多角色**：从二分类改成多说话人 + 拒识，不需要重写流水线。

## 4. 技术栈选型

### 4.1 工程侧

| 方面 | 现状 | 目标 | 理由 |
| --- | --- | --- | --- |
| 包管理 | `requirements.txt`(UTF-16) | **uv** + `pyproject.toml` + `uv.lock` | 本机已装 uv；锁文件保证可复现；解决 torch index 的问题 |
| 布局 | 根目录平铺脚本 | `src/avs/` 布局 + 真包 | 避免 import 路径玄学，可 `pip install -e .` |
| 配置 | 全局常量 + `import *` | **pydantic-settings** + YAML profile | 类型校验、多组配置共存、可被 CLI 覆盖 |
| CLI | `if __name__ == '__main__'` | **typer** | 子命令、`--help`、参数校验 |
| 日志 | `print` | `logging` + `rich` handler | 可分级、可落盘 |
| 实验记录 | 无 | `runs/<timestamp>/` 写 `config.yaml` + `metrics.json`（规模够用，不上 MLflow） | 轻量、可 diff、可进 git |
| 质量 | 无 | **ruff**（lint + format）+ **mypy** + **pytest** + pre-commit | |
| CI | 无 | GitHub Actions：lint + mypy + pytest（CPU，用仓库内几条小样本） | |
| 数据 | 进 git | `data/` 进 `.gitignore`，仓库只留 `data/manifest.csv`（路径 + sha256 + 标签）与 `tests/fixtures/` 里几条 <1 MB 的短样本 | |
| Python | 未声明 | 3.12 | |

### 4.2 算法侧

**说话人嵌入模型（核心替换项）**，以下为候选，最终**用你自己的数据测 EER 来选**，不要凭品牌名拍板：

| 候选 | 获取方式 | 备注 |
| --- | --- | --- |
| ECAPA-TDNN (VoxCeleb) | `speechbrain/spkrec-ecapa-voxceleb` | 192 维，生态最成熟，CPU 上跑 310 条只要几秒，**建议作为默认基线** |
| WavLM-base-plus-sv | `microsoft/wavlm-base-plus-sv` | 自监督底座，对非英语 / 演绎腔通常更稳，但更重 |
| CAM++ / ERes2Net | ModelScope `iic/speech_campplus_sv_*` | 3D-Speaker 系列，中文与多语版本可选 |
| WeSpeaker ResNet34 | `wespeaker` pip 包 | 与 pyannote 3.x 内部同源 |

注意：这些模型都在真人语音（多为 VoxCeleb 类数据）上训练，而动画配音是**演绎腔 + 高动态 + 重后期**，域偏移真实存在。所以流程里必须留一个「用自有数据微调 / 训练轻量分类头」的位置（见阶段 P4）。

**其余组件**：

- **VAD**：`silero-vad`，切掉字幕时轴带来的前后静音与纯 BGM 段。
- **人声分离**：`demucs`（`--two-stems=vocals`）或 MDX / BS-Roformer 系列。这一步大概率是**除换嵌入模型之外收益第二大的改动**，因为它直接消掉 BGM 与音效。
- **分类头**：先用「注册中心向量 + 余弦相似度 + 阈值」，再用 `LogisticRegression`（带 `class_weight='balanced'` 与概率校准）做对比。250 条样本上，任何深层网络都不会赢过这两个。
- **字幕解析**：`pysubs2`，直接吃 `.ass` / `.srt`，把「切片」这一步纳入仓库，而不是靠外部手工操作。
- **说话人分离（终局形态）**：`pyannote/speaker-diarization-3.1` 对整集做分离，再把每个 cluster 与注册向量比对；字幕时轴只用来对齐文本，不再用来定义样本边界。

**保留 MFCC + SVM 作为 legacy baseline**，不是为了用它，而是为了在同一套评估协议下量化「新方案到底赢了多少」。

## 5. 目标仓库结构

```
anime-voice-sorter/
├─ pyproject.toml            # uv + ruff + mypy + pytest 配置集中于此
├─ uv.lock
├─ README.md                 # 中英双语，含 30 秒上手
├─ configs/
│  ├─ default.yaml
│  ├─ baseline_mfcc.yaml     # 复现旧方案，用于对照
│  └─ ecapa.yaml
├─ src/avs/
│  ├─ config.py              # pydantic-settings 模型
│  ├─ logging.py
│  ├─ audio/
│  │  ├─ io.py               # load → mono / 16k / float32 / 响度归一
│  │  ├─ vad.py              # silero-vad 裁剪
│  │  └─ separate.py         # demucs 人声分离（可选，带缓存）
│  ├─ subtitles.py           # .ass/.srt → Segment(start, end, text, style)
│  ├─ embeddings/
│  │  ├─ base.py             # Embedder Protocol
│  │  ├─ ecapa.py
│  │  ├─ wavlm.py
│  │  ├─ mfcc.py             # legacy
│  │  └─ cache.py            # 按 (模型 id, 音频 sha256) 缓存到 .npy
│  ├─ models/
│  │  ├─ centroid.py         # 注册式余弦打分
│  │  └─ linear.py           # LogisticRegression + CalibratedClassifierCV
│  ├─ evaluation/
│  │  ├─ metrics.py          # PR-AUC / EER / P@R / 混淆矩阵
│  │  ├─ splits.py           # GroupKFold（按集分组）
│  │  └─ report.py           # 生成 markdown + 图
│  ├─ pipeline/
│  │  ├─ enroll.py
│  │  ├─ classify.py
│  │  └─ diarize.py
│  └─ cli.py                 # avs prepare|enroll|train|eval|predict|diarize
├─ data/                     # .gitignore；只有 manifest.csv 进版本库
│  ├─ manifest.csv
│  └─ raw/  interim/  processed/
├─ runs/                     # 每次实验一个目录
├─ tests/
│  ├─ fixtures/              # 3~5 条 <1MB 短音频
│  └─ test_*.py
└─ .github/workflows/ci.yml
```

## 6. 分阶段路线图

每个阶段都有**可验证的验收标准**，不满足就不进下一阶段。

### P0　仓库与数据治理（约 0.5 天）

动作：

1. 打 tag `v1-archive` 保住旧代码，然后用 `git-filter-repo` 从历史中剥离所有 `*.wav` 与 `分类结果/`，`.git` 应从 91 MB 降到 1 MB 量级。
2. 写 `.gitignore`（`data/`、`runs/`、`*.wav`、`__pycache__/`、`.venv/`）。
3. 目录与文件名全部改为 ASCII：`训练集/钉宫语音` → `data/raw/kugimiya/`，`训练集/其他语音` → `data/raw/others/`，`测试集` → `data/raw/unlabeled/`。
4. 生成 `data/manifest.csv`：`path, sha256, speaker, episode, duration, split`。**`episode` 这一列是后面做分组评估的前提**，现在就要补上。
5. 数据本体移出仓库，放本地 `data/` 或 git-lfs / 网盘，README 写明获取方式。

风险提醒：仓库是公开的，`filter-repo` + 强推会改写所有历史 commit 的 hash，已有的 fork 和 PR 引用会失效。如果不接受，替代方案是**新建 v2 仓库，旧仓库归档只读**。这个选择需要你来定。

验收：`git clone` 体积 < 5 MB；`ls` 在任何 locale 下不乱码。

### P1　工程骨架（约 1 天）

动作：

1. `uv init` + `pyproject.toml`，声明 Python 3.12；torch 走 `[[tool.uv.index]]` 指定 CPU 或 CUDA index，不再写 `torch~=2.0.0+cu118` 这种非法约束。
2. 建 `src/avs/` 包结构（先只放空模块与 Protocol）。
3. `config.py`：把 `a000_configuration.py` 的每个常量映射成 pydantic 字段，带默认值、类型、取值范围校验。设备字段默认 `auto`，按 `torch.cuda.is_available()` 决定。
4. `cli.py` 骨架 + `logging.py`。
5. ruff / mypy / pytest / pre-commit / CI 全部接上，先让空项目通过。

验收：`uv run avs --help` 可用；`uv run ruff check`、`uv run mypy src`、`uv run pytest` 三绿。

### P2　建立诚实的评估基线（约 1 天）

**这是整个计划里最重要的一步。没有可信的尺子，后面所有「升级」都无法证明。**

动作：

1. 实现 `audio/io.py`：统一重采样到 16 kHz、单声道下混、float32、响度归一。
2. 移植 legacy MFCC 特征（修好 `unify_dim_t` 的负长度与截断，MFCC transform 只构造一次并复用）。
3. 实现 `evaluation/`：`GroupKFold`（按 `episode` 分组）、PR-AUC、EER、`P@R=0.9`、混淆矩阵、固定 `seed`。
4. 归一化统计量**只在训练折上计算**，用 `sklearn.pipeline.Pipeline` 把 `StandardScaler` 和分类器绑在一起，从结构上杜绝泄漏。
5. 跑一遍 `baseline_mfcc.yaml`，把数字写进 `runs/`，作为**旧方案的真实水平**（预期会明显低于原来打印的 accuracy）。

**同时必须做的一件数据工作**：现在所有数据来自同一集，分组交叉验证会退化成单组，测不出泛化。**请标注第二集（哪怕只标 50 条目标 + 100 条其他）作为独立测试集**，否则 P3 之后的所有对比都只是在测同一集的信道特征。这件事没有技术替代方案。

验收：`uv run avs eval --config configs/baseline_mfcc.yaml` 输出一份 `report.md`，含上述全部指标与 95% 置信区间。

### P3　换成预训练说话人嵌入（约 1 天）

动作：

1. 定义 `Embedder` Protocol：`encode(wav, sr) -> np.ndarray`。
2. 实现 ECAPA embedder（`speechbrain`），加 `(model_id, audio_sha256)` 级别的磁盘缓存，避免重复推理。
3. 两种分类头都实现：注册中心向量余弦打分、`LogisticRegression(class_weight='balanced')` + 概率校准。
4. 在 P2 的同一评估协议下与 MFCC 基线对比，产出对比表。
5. 顺带把 VAD 接进来，做「开 / 关 VAD」的消融。

验收：ECAPA + 逻辑回归在跨集测试上的 PR-AUC 显著优于 MFCC 基线；若不显著，先查前处理（采样率、声道、静音）而不是急着换模型。

### P4　前处理增强与域适配（约 1 到 2 天）

动作：

1. 接入 Demucs 人声分离（带缓存，因为它很慢），做「分离 / 不分离」的消融。按动画音轨的特点，这一项应当有可观增益。
2. 数据增强：加噪、变速（speed perturb 0.9 / 1.0 / 1.1）、随机 RIR 混响、SpecAugment，缓解 250 条样本的过拟合。
3. 若域偏移确实明显，训练一个轻量投影头（嵌入 → 128 维，AAM-softmax），或对嵌入模型最后几层做低秩微调。**这一步只有在 P3 的数字证明有必要时才做。**
4. 阈值选择：在验证折上按「精确率优先」选工作点，并显式输出一个 `uncertain` 中间带交给人工复核，这比强行二分更贴合实际使用。

验收：每一项改动都有消融表；`runs/` 里能追溯到具体是哪个开关带来的增益。

### P5　产品化：整集流水线（约 1 到 2 天）

动作：

1. `subtitles.py` 解析 `.ass` / `.srt`，把「从整集音频按时轴切片」纳入仓库。
2. `pipeline/diarize.py`：pyannote 分离整集 → 每段取嵌入 → 与注册中心向量比对 → 与字幕时轴求交并分配说话人。这条路不依赖字幕边界的准确性，鲁棒性明显更好。
3. 输出改为 `predictions.csv`（`file, start, end, score, label, bucket`），文件复制变成 `--export copy|symlink|none` 的可选行为，**绝不再对配置路径做 `rmtree`**，改为要求目标目录为空或显式 `--force`。
4. README 重写：中英双语，含真实的用法步骤（现在的 README 里 1. 2. 3. 是空的）。

验收：`uv run avs predict --episode ep05.mkv --subs ep05.ass --enroll kugimiya/ -o out/` 一条命令跑通。

### 可选后续

- 多角色多标签（把二分类换成「注册 N 个角色 + 拒识」）。
- 结合 `faster-whisper` 做强制对齐，修正字幕时轴偏移。
- 一个最小 Web UI（Gradio）用于人工复核 `uncertain` 桶并回流标注，形成数据飞轮。

## 7. 关键设计细节

### 7.1 配置

```python
# src/avs/config.py
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AudioConfig(BaseModel):
    sample_rate: int = 16_000
    mono: bool = True
    peak_normalize: bool = True
    vad: bool = True
    separate_vocals: bool = False


class EmbedderConfig(BaseModel):
    kind: Literal["ecapa", "wavlm", "campp", "mfcc"] = "ecapa"
    model_id: str = "speechbrain/spkrec-ecapa-voxceleb"
    cache_dir: Path = Path(".cache/embeddings")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AVS_", yaml_file="configs/default.yaml")

    seed: int = 42
    device: Literal["auto", "cpu", "cuda"] = "auto"
    data_dir: Path = Path("data")
    audio: AudioConfig = Field(default_factory=AudioConfig)
    embedder: EmbedderConfig = Field(default_factory=EmbedderConfig)
```

对比原来的 `MY_DEVICE = 'cuda'` + `from a000_configuration import *`：现在可以在一个进程里跑多组配置，CLI 可以覆盖任意字段，错误配置在启动时就报错而不是在第 3 小时的训练中途。

### 7.2 嵌入接口

```python
# src/avs/embeddings/base.py
from typing import Protocol
import numpy as np
import torch


class Embedder(Protocol):
    dim: int

    def encode(self, wav: torch.Tensor, sr: int) -> np.ndarray: ...

    @property
    def signature(self) -> str: ...  # 进缓存 key，模型换了缓存自动失效
```

换模型 = 换一个实现类，评估代码、CLI、缓存层完全不动。这正是现在 `a002_SVM.py` 里 SVM 与特征提取纠缠在一起所做不到的。

### 7.3 防泄漏的训练管道

```python
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

clf = make_pipeline(
    StandardScaler(),
    LogisticRegression(class_weight="balanced", max_iter=1000),
)
scores = cross_val_predict(
    clf, X, y, groups=episodes,
    cv=GroupKFold(n_splits=5), method="predict_proba",
)[:, 1]
```

`StandardScaler` 在 pipeline 内部，`cross_val_predict` 只在训练折上 `fit`。这从结构上消除了 `initialize_nn()` 里那个泄漏，不需要靠人记得「先划分再归一化」。

### 7.4 评估指标

二分类阈值 $\tau$ 下，定义

$$\text{Precision} = \frac{TP}{TP+FP}, \qquad \text{Recall} = \frac{TP}{TP+FN}$$

主指标用 PR-AUC 而非 accuracy 或 ROC-AUC，因为正类占比只有 31%，且在真实整集场景里会更低（一集里单个角色的台词往往不到 20%）。等错误率 EER 定义为使

$$\mathrm{FAR}(\tau) = \mathrm{FRR}(\tau)$$

成立时的错误率，用于跨模型比较且与阈值选择解耦。实际交付的工作点用 $P@R{=}0.9$：保证漏掉的目标台词不超过 10%，看此时要人工剔除多少误检。

## 8. 数据与标注建议

1. **补第二集标注**（P2 的硬前提）。没有跨集数据，一切指标都不可信。
2. **注册样本挑干净的**：5 到 20 条无 BGM、无重叠说话、时长 2 到 5 秒的片段。注册质量对最终效果的影响可能大于模型选择。
3. **「其他类」要多样**：当前的负样本全部来自同一集，模型学不到「没见过的说话人也该拒识」。可以引入外部语料（日语语音语料、其他动画）扩充负类，或者干脆改用开集验证的建模方式（推荐后者）。
4. **记录元数据**：每条样本的来源集数、时间码、是否重叠、是否带 BGM。后续做误差分析时，这些列比模型本身更有用。

## 9. 风险与取舍

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 改写 git 历史 | 公开仓库的 fork / PR 引用失效 | 或接受，或新建 v2 仓库并归档旧仓库（需你决策） |
| 预训练模型的域偏移（真人语音 → 动画配音） | 增益可能不如预期 | P3 先量化，不达标再走 P4 的微调；保留 MFCC 基线做对照 |
| Demucs / pyannote 推理慢 | 迭代变慢 | 全部加磁盘缓存；分离结果落盘复用 |
| pyannote 与部分 ModelScope 模型需要接受协议 / token | 首次运行受阻 | README 写明步骤；CI 只跑不需 token 的路径 |
| 数据量太小（12 分钟） | 任何复杂模型都会过拟合 | 坚持「预训练嵌入 + 线性头」，把复杂度留给数据而非模型 |

## 10. 如果你想保留「练手」属性

上面的路线以「做出好用的工具」为目标，会大量使用现成模型。如果这个项目对你的价值是**学习实现本身**，建议拆成两条线：

- `src/avs/`：工程化的实用线，按上面的路线走。
- `experiments/from_scratch/`：教学线，自己实现 x-vector / ECAPA / AAM-softmax，**在同一套评估协议下**与实用线对比。

关键是两条线共用 `evaluation/` 和数据管道，这样「自己写的能到什么水平」才有明确答案。

## 11. 建议的第一步

按依赖顺序，前三件事：

1. 决定 git 历史处理方式（改写 vs 新仓库）。
2. 执行 P0 + P1，得到一个干净、可 lint、可测试的空骨架。
3. 执行 P2，得到旧方案的**真实**指标，同时开始标注第二集。

拿到 P2 的数字之后，再决定 P3 到 P5 各投入多少。
