"""Two interchangeable voiceprint extractors.

Input is a 16 kHz analysis copy. Output is unit-length vectors (each vector is scaled to length 1).

ReDimNet2 and WeSpeaker are both kept for comparing identity grouping. Differences between
models cannot replace human identity evaluation.
WeSpeaker uses the CPU on the current Windows setup.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

FRONTIER = "redimnet2-b6"
BASELINE = "wespeaker-resnet293"
ANIME_CHAR = "anime-char"
ANIME_VA = "anime-va"
MODELS = (FRONTIER, BASELINE, ANIME_CHAR, ANIME_VA)

DEFAULT_THRESHOLDS = {FRONTIER: 0.50, BASELINE: 0.60, ANIME_CHAR: 0.53, ANIME_VA: 0.70}
"""Each model's own starting distance threshold.

The similarity scale differs between models, so using another model's threshold would scan over
a meaningless range.

These values were chosen on the labels of the first two episodes, **and they drift as the clip
pool grows**. At the same threshold, a bigger pool makes merging more conservative. This is
because average linkage (merging two groups by the average distance between all their clips)
requires the average distance across the whole cluster to reach the threshold. For anime-va at
0.70, episode ep03 had 2613 same-person pairs linked with 76 wrong merges in a 372-clip pool.
In a 1176-clip pool, it has 2095 pairs linked with 21 wrong merges.

**Note that these two numbers move together. So the grouping has not gotten worse. The fixed
number has slid to the conservative end of the trade-off curve.** Holding wrong merges fixed and
moving the threshold again, a bigger pool can link even more pairs (at the 76-wrong-merges level,
2613 pairs become 3278 pairs). The approach that does not change with pool size is pool_threshold
in stages/cluster.py. The command line option is `avs group --relative`. It has no independent
test yet, so the default here is still the fixed one. As more episodes are added, re-check with
`avs drift`, and do not treat the number as a constant."""

ANIME_VARIANTS = {ANIME_CHAR: "char", ANIME_VA: "va"}
"""The two variants of litagin02/anime_speaker_embedding.

"char" is trained by character, so different characters voiced by the same voice actor are also
kept apart. "va" groups by voice actor. Our labels are characters, so "char" is the matching one.
Both are kept for comparison anyway. If "va" turns out better, it means that in this series few
voice actors play several characters, and a voice-actor-level target is easier to learn.

The author warns that this model "tends to actively tell speakers apart". Its similarity between
the same character is generally lower than with other models. So the distance threshold cannot be
copied over from ReDimNet, and it must be scanned again."""

SAMPLE_RATE = 16_000
"""Voiceprint models all need 16 kHz, which is the sample rate of the analysis copy. Do not feed
them the vocals track at its original sample rate."""

MIN_SECONDS = 0.5
"""Clips shorter than this length do not get a voiceprint, so they cannot enter grouping.

This value was measured, not guessed. After episode 3 was labeled, clips shorter than 0.5 seconds
got human identities for the first time. Measured, their similarity to the same character and to
different characters was almost impossible to tell apart. When the "same character" and
"different character" pairs were put side by side, the ranking accuracy (how often a same-character
pair scores higher than a different-character pair) for clips under 0.5 seconds was only 0.61.
Pure random guessing gives 0.50. So these clips mostly bring in noise. Clips from 0.5 to 1 second
get 0.81, which is marginally useful, so they are kept for now."""

MIN_WINDOW = 0.0
"""Smallest audio window fed to the model.

When a clip is shorter than this, neighboring audio is taken from the original track symmetrically
from both sides to fill it up. The clip's own time range does not change. The model just hears a
little more context. 0 means it only hears the clip itself.

**Why it may help or hurt.** Short clips have poor voiceprints. One explanation is that the model
hears too little audio, and adding neighboring audio gives it more material. But the neighboring
audio may not still be the same person speaking. Padding too much mixes in the voices of the
neighbors. Whether the benefit outweighs the harm, or the reverse, can only be measured on human
labels. Do not decide it by intuition."""

REDIMNET2_REPO = "PalabraAI/redimnet2"
REDIMNET2_SIZE = "b6"
WESPEAKER_REPO = "Wespeaker/wespeaker-voxceleb-resnet293-LM"
WESPEAKER_ONNX = "voxceleb_resnet293_LM.onnx"
"""pyannote's loader looks for the file name `speaker-embedding.onnx` by default, but this
repository uses a different name. So the file has to be downloaded first, and its local path
passed to the loader."""


@dataclass(frozen=True)
class Embedded:
    """The voiceprint of one clip.

    The vector is stored separately as .npy. Only the readable metadata is kept here.
    """

    speaker: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


class Extractor(Protocol):
    """Takes a 16 kHz mono waveform and returns a sequence of numbers."""

    def __call__(self, mono: Any) -> Any: ...


def _load_redimnet2(device: str) -> Extractor:
    import numpy as np
    import torch

    # torch.hub.load has no type annotations of its own, so the type checker would block it.
    # Let it through here.
    model = torch.hub.load(  # type: ignore[no-untyped-call]
        REDIMNET2_REPO,
        "redimnet2",
        model_name=REDIMNET2_SIZE,
        train_type="lm",
        pretrained=True,
        trust_repo=True,
    )
    model = model.to(device).eval()

    def extract(mono: Any) -> Any:
        wave = torch.from_numpy(np.ascontiguousarray(mono)).unsqueeze(0).to(device)
        with torch.no_grad():
            return model(wave).squeeze(0).cpu().numpy()

    return extract


def _load_wespeaker(device: str) -> Extractor:
    import numpy as np
    import torch
    from huggingface_hub import hf_hub_download
    from pyannote.audio.pipelines.speaker_verification import PretrainedSpeakerEmbedding

    onnx = hf_hub_download(repo_id=WESPEAKER_REPO, filename=WESPEAKER_ONNX)
    # onnxruntime-gpu is broken on this machine, so do not pass cuda in.
    # See the notes at the top of this module.
    model = PretrainedSpeakerEmbedding(onnx, device=torch.device("cpu"))

    def extract(mono: Any) -> Any:
        # pyannote needs a 3-D shape: (batch, channel, samples)
        wave = torch.from_numpy(np.ascontiguousarray(mono))[None, None, :]
        return np.asarray(model(wave)).squeeze(0)

    return extract


def load_extractor(model: str, device: str = "cuda") -> Extractor:
    """Load a voiceprint model by its code name.

    device has no effect for wespeaker. The reason is at the top of this module.
    """
    if model == FRONTIER:
        return _load_redimnet2(device)
    if model == BASELINE:
        return _load_wespeaker(device)
    if model in ANIME_VARIANTS:
        return _load_anime(ANIME_VARIANTS[model], device)
    raise ValueError(f"Unknown model {model!r}, must be one of {' or '.join(MODELS)}")


def _load_anime(variant: str, device: str) -> Extractor:
    """The ECAPA-TDNN (a speaker-embedding neural network) for the anime domain.

    The package's get_embedding only accepts file paths. So this follows its method and feeds the
    array in directly, saving a temporary file for each clip. The input is also 16 kHz mono, which
    is exactly the analysis copy.
    """
    import numpy as np
    import torch
    from anime_speaker_embedding import AnimeSpeakerEmbedding

    model = AnimeSpeakerEmbedding(variant=variant, device=device)

    def extract(mono: Any) -> Any:
        wave = torch.from_numpy(np.ascontiguousarray(mono)).float().unsqueeze(0).to(device)
        with torch.inference_mode():
            vector = model(wave).squeeze(0).squeeze(0)
            return torch.nn.functional.normalize(vector, dim=0).cpu().numpy()

    return extract


def embed_segments(
    wav: Path,
    segments: list[Any],
    model: str = FRONTIER,
    device: str = "cuda",
    window: float = MIN_WINDOW,
) -> tuple[list[Embedded], Any]:
    """Compute a voiceprint for each clip. wav must be 16 kHz mono, which is the analysis copy.

    `window` is the smallest listening window. Short clips borrow neighboring audio from both sides
    to fill this length. The recorded metadata still holds the clip's own time range. The borrowed
    part only affects what the model hears, not what the clip is.

    Returns (list of metadata, voiceprint matrix). The matrix has one row per clip, and row numbers
    line up with the list. The rows are already length-normalized, so the dot product of two rows
    is their cosine similarity.
    """
    import numpy as np
    import soundfile as sf

    extract = load_extractor(model, device)
    samples, sample_rate = sf.read(str(wav), dtype="float32", always_2d=True)
    if sample_rate != SAMPLE_RATE:
        raise ValueError(
            f"{wav} is {sample_rate} Hz, but the voiceprint model needs a "
            f"{SAMPLE_RATE} Hz analysis copy"
        )
    mono = samples[:, 0]

    meta: list[Embedded] = []
    vectors: list[Any] = []
    for seg in segments:
        start, end = float(seg["start"]), float(seg["end"])
        if end - start < MIN_SECONDS:
            continue
        heard = _window(start, end, window, len(mono) / sample_rate)
        chunk = mono[int(heard[0] * sample_rate) : int(heard[1] * sample_rate)]
        vector = np.asarray(extract(chunk), dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            continue
        meta.append(Embedded(speaker=str(seg.get("speaker", "")), start=start, end=end))
        vectors.append(vector / norm)

    if not vectors:
        raise RuntimeError(
            "No voiceprint was computed at all. Check clip durations and the analysis copy"
        )
    return meta, np.stack(vectors)


def _window(start: float, end: float, window: float, duration: float) -> tuple[float, float]:
    """Symmetrically widen a clip shorter than `window` to `window`.

    If it hits either end of the track, take the extra from the other side.
    """
    if window <= 0 or end - start >= window:
        return start, end
    room = (window - (end - start)) / 2
    low, high = start - room, end + room
    if low < 0:
        low, high = 0.0, min(duration, high - low)
    if high > duration:
        low, high = max(0.0, low - (high - duration)), duration
    return low, high
