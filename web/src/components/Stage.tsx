import { useEffect, useRef, useState, type RefObject, type SyntheticEvent } from "react";
import { media, mediaProblem, type Clip, type Roles } from "../api";
import { lowTip, OTHER, type LabelText } from "../clips";
import { pct, stamp } from "../format";
import { tr } from "../language";
import { needsText } from "../purpose";
import { CONTEXTS, SPEEDS, VIDEO_PAD, type Sound } from "../playback";
import { Avatar } from "./Avatar";
import { RoleName } from "./RoleName";

/* The text that export writes for this line, in the language spoken, when it differs from the subtitles shown
   above. For a target character's line that cannot be exported with text, the reason, unless only the sound is
   collected (see purpose.ts). */
function SpokenLine({ clip }: { clip: Clip }) {
  if (needsText() && clip.role && clip.spoken_problem)
    return (
      <div className="spoken-line warn">
        {tr("导出时没有文字：", "No text on export: ")}
        {clip.spoken_problem}
        {clip.spoken && <span className="spoken-text">{clip.spoken}</span>}
      </div>
    );
  if (!clip.spoken || clip.spoken === clip.text) return null;
  return (
    <div
      className="spoken-line"
      title={tr(
        "导出时写的文字，用说话的语言",
        "The text written on export, in the language spoken",
      )}
    >
      {clip.spoken}
    </div>
  );
}

interface StageProps {
  clip: Clip | null;
  roles: Roles;
  labelText: LabelText;
  sound: Sound;
  setSound: (sound: Sound) => void;
  speed: number;
  setSpeed: (speed: number) => void;
  onAssign: (name: string, low?: boolean) => void;
  onAccept: () => void;
  onPlayRef: (name: string) => void;
  hasVideo: boolean;
  /* The player on the stage: the video, or the vocals when there is no video. */
  videoRef: RefObject<HTMLMediaElement | null>;
  onAvatar: (name: string) => void;
  onNewRole: () => void;
  onClear: () => void;
  context: number;
  setContext: (context: number) => void;
  dock: string[];
}

/* ───────────── Stage: picture, line, who is it ───────────── */

export function Stage({
  clip,
  roles,
  labelText,
  sound,
  setSound,
  speed,
  setSpeed,
  onAssign,
  onAccept,
  onPlayRef,
  hasVideo,
  videoRef,
  onAvatar,
  onNewRole,
  onClear,
  context,
  setContext,
  dock,
}: StageProps) {
  /* Which player can play, named by what it plays. "Loading" is worked out from it while drawing. It used to be
     switched on when the line changed, but a clip already cut could be ready before that ran, and then the
     spinner covered the picture for good. */
  const line = `${clip?.id}-${sound}-${context}`;
  /* How many times "Cut again" was pressed on this line. Only this line asks for a fresh cut. */
  const [retry, setRetry] = useState<{ for: string; times: number } | null>(null);
  const fresh = retry?.for === line ? retry.times : 0;
  const shown = `${line}-${fresh}`;
  /* `problem` is set when a player failed: "" until the reason comes back from the server. */
  const [status, setStatus] = useState<{ for: string; problem?: string } | null>(null);
  const problem = status?.for === shown ? status.problem : undefined;
  const loading = status?.for !== shown;
  const ready = () =>
    setStatus((s) => (s?.for === shown && s.problem !== undefined ? s : { for: shown }));
  const fail = (kind: "video" | "audio") => {
    const at = shown;
    setStatus({ for: at, problem: "" });
    mediaProblem(media(kind, clip!.id, context))
      .catch(() => null)
      .then((reason) =>
        setStatus((s) =>
          s?.for === at
            ? {
                for: at,
                problem:
                  reason ??
                  tr(
                    "切好的文件坏了，浏览器放不了",
                    "The cut file is broken, so the browser cannot play it",
                  ),
              }
            : s,
        ),
      );
  };
  /* Which line's player is playing, so a new line starts out shown as paused. */
  const [playingFor, setPlayingFor] = useState<string | null>(null);
  const playing = playingFor === shown;
  /* The number key of each of the first 9 characters in the bottom bar; Shift + it is that character, low quality. */
  const slot = (name: string) => {
    const i = dock.indexOf(name);
    return i >= 0 && i < 9 ? i + 1 : null;
  };
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const startVoice = useRef(0);
  useEffect(() => () => clearTimeout(startVoice.current), [shown]);
  /* On a new clip the player resets its speed to defaultPlaybackRate, so set both. */
  useEffect(() => {
    for (const el of [videoRef.current, audioRef.current]) {
      if (el) {
        el.defaultPlaybackRate = speed;
        el.playbackRate = speed;
      }
    }
  }, [speed, shown, videoRef]);

  if (!clip) {
    return (
      <aside className="stage">
        <div className="screen">
          <div className="wait">{tr("在右边选一句台词", "Pick a line on the right")}</div>
        </div>
      </aside>
    );
  }
  const vocals = hasVideo && sound === "vocals";
  /* With vocals only, the picture plays muted and the separated vocals play instead, following the picture's
     play, pause and seek. The video clip starts VIDEO_PAD seconds before the line (less at the very start of an
     episode), so the vocals wait until the picture reaches the line. With extra context the vocals were cut
     with the same extra seconds, so both start at the same moment. */
  const follow = (e: SyntheticEvent<HTMLVideoElement>) => {
    const voice = audioRef.current;
    if (!vocals || !voice) return;
    clearTimeout(startVoice.current);
    const at = e.currentTarget.currentTime - (context ? 0 : Math.min(VIDEO_PAD, clip.start));
    voice.currentTime = Math.max(0, at);
    if (e.currentTarget.paused) voice.pause();
    else if (at >= 0) voice.play().catch(() => {});
    else {
      voice.pause();
      startVoice.current = setTimeout(() => voice.play().catch(() => {}), (-at * 1000) / speed);
    }
  };
  const isOther = !!clip.label && !!labelText[clip.label];
  const label = clip.label;
  return (
    <aside className="stage">
      <div className="screen">
        {hasVideo ? (
          <>
            <video
              ref={(el) => {
                videoRef.current = el;
              }}
              key={shown}
              src={media("video", clip.id, context, fresh)}
              autoPlay
              playsInline
              muted={vocals}
              onCanPlay={ready}
              onError={() => fail("video")}
              onClick={(e) => {
                if (e.currentTarget.paused) e.currentTarget.play().catch(() => {});
                else e.currentTarget.pause();
              }}
              onPlay={(e) => {
                setPlayingFor(shown);
                follow(e);
              }}
              onPause={(e) => {
                setPlayingFor(null);
                follow(e);
              }}
              onSeeked={follow}
            ></video>
            {vocals && (
              <audio
                ref={audioRef}
                key={`v-${shown}`}
                src={media("audio", clip.id, context, fresh)}
                preload="auto"
                onError={() => fail("audio")}
              ></audio>
            )}
            {!loading && problem === undefined && (
              <div className={`play-state ${playing ? "playing" : ""}`} aria-hidden="true">
                {playing ? (
                  <svg viewBox="0 0 24 24">
                    <rect x="6" y="5" width="4" height="14" rx="1" />
                    <rect x="14" y="5" width="4" height="14" rx="1" />
                  </svg>
                ) : (
                  <svg viewBox="0 0 24 24">
                    <path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z" />
                  </svg>
                )}
              </div>
            )}
          </>
        ) : (
          <>
            <div className="wait">
              {tr("这一集没有视频，只有人声", "This episode has no video, only vocals")}
            </div>
            <audio
              ref={(el) => {
                audioRef.current = el;
                videoRef.current = el;
              }}
              key={shown}
              src={media("audio", clip.id, context, fresh)}
              autoPlay
              onCanPlay={ready}
              onError={() => fail("audio")}
            ></audio>
          </>
        )}
        <div className={`wait ${!hasVideo || !loading ? "hide" : ""}`}>
          <div className="spinner"></div>
        </div>
        {problem !== undefined && (
          <div className="wait failed">
            <div>
              <div>{tr("这一句放不了", "This line cannot play")}</div>
              <div className="reason">{problem || tr("正在查原因…", "Finding out why…")}</div>
              <button
                onClick={() => setRetry({ for: line, times: fresh + 1 })}
                title={tr(
                  "丢掉存好的片段，从原视频重新切",
                  "Throw away the saved clip and cut it again from the original",
                )}
              >
                {tr("重新切一次", "Cut again")}
              </button>
            </div>
          </div>
        )}
      </div>
      <div className="player">
        {hasVideo && (
          <span className="seg">
            <button className={sound === "vocals" ? "on" : ""} onClick={() => setSound("vocals")}>
              {tr("只听人声", "Vocals only")}
            </button>
            <button
              className={sound === "original" ? "on" : ""}
              onClick={() => setSound("original")}
            >
              {tr("画面原声", "Original sound")}
            </button>
          </span>
        )}
        <span
          className="seg"
          title={tr("播放速度，参考音也一样快", "Playback speed, also used for reference clips")}
        >
          {SPEEDS.map((s) => (
            <button key={s} className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>
              {s}×
            </button>
          ))}
        </span>
      </div>
      <div className="line-text">
        {clip.text || (
          <span style={{ color: "var(--text-3)" }}>
            {tr("（字幕里没有这句的文字）", "(no text for this line in the subtitles)")}
          </span>
        )}
      </div>
      <SpokenLine clip={clip} />
      <div className="line-meta">
        <span>{clip.episode}</span>
        <span>{stamp(clip.start)}</span>
        <span>{tr(`${clip.duration.toFixed(2)} 秒`, `${clip.duration.toFixed(2)} s`)}</span>
        <span
          className="context"
          title={tr(
            "看不出是谁时，前后各多放一些。选好的会一直用到你改回来；L 键依次切换",
            "When you can't tell who it is, play more on each side. Your choice stays until you change it; L steps through them",
          )}
        >
          {tr("多放前后文", "More context")}
          <span className="seg">
            {CONTEXTS.map((c) => (
              <button key={c} className={context === c ? "on" : ""} onClick={() => setContext(c)}>
                {c ? tr(`±${c} 秒`, `±${c} s`) : tr("不多放", "None")}
              </button>
            ))}
          </span>
          <kbd>L</kbd>
        </span>
      </div>

      {label ? (
        <>
          <div className="ask">{tr("已经确认", "Confirmed")}</div>
          <div className="confirmed-box">
            <Avatar
              role={roles[label]}
              name={label}
              blank={isOther}
              size="lg"
              onClick={!isOther && hasVideo ? () => onAvatar(label) : null}
              title={tr("从画面里截一块当头像", "Crop an avatar from the picture")}
            />
            <div>
              <div className="who">
                {isOther ? labelText[label] : <RoleName role={roles[label]} name={label} />}
                {clip.unusable && !labelText[label] && (
                  <>
                    {" "}
                    <span className="pill unusable" title={lowTip()}>
                      {tr("质量低", "Low quality")}
                    </span>
                  </>
                )}
              </div>
              <div style={{ fontSize: "12px" }}>
                {tr(
                  "要改的话，直接按别的数字键或在下面选；Shift + 数字是质量低",
                  "To change it, press another number key or pick below. Shift + number means low quality",
                )}
              </div>
            </div>
            <span className="actions">
              <button
                className="ghost"
                title={tr(
                  "清掉这句的标签，回到机器的猜测",
                  "Clear this line's label and go back to the machine's guess",
                )}
                onClick={onClear}
              >
                {tr("清掉标签", "Clear label")} <kbd>Backspace</kbd>
              </button>
            </span>
          </div>
        </>
      ) : (
        <>
          <div className="ask">
            {clip.guess.length
              ? tr("这是谁？机器的猜测", "Who is this? The machine's guesses")
              : clip.voiced
                ? tr("这是谁？", "Who is this?")
                : tr(
                    "这句太短，机器听不出来，请直接选人",
                    "Too short for the machine to tell. Pick the character yourself",
                  )}
          </div>
          {clip.familiar === false && (
            <div className="stranger">
              {tr(
                <>
                  跟已经确认过的角色都不太像，可能是还没标过的人。是新角色就按 <kbd>N</kbd>{" "}
                  新建，名字以后再起也行。
                </>,
                <>
                  Not much like any confirmed character, so it may be someone not labeled yet. If it
                  is a new character, press <kbd>N</kbd>; you can name it later.
                </>,
              )}
            </div>
          )}
          {clip.familiar === null && clip.guess.length > 0 && (
            <div className="stranger early">
              {tr(
                <>
                  机器现在只会在底部这几个角色里挑。都不是就按 <kbd>N</kbd> 新建；确认满 20
                  句后，它会自己提醒你哪句像新面孔。
                </>,
                <>
                  For now the machine only picks among the characters at the bottom. If it is none
                  of them, press <kbd>N</kbd>. After 20 confirmed lines it will point out lines that
                  sound like someone new.
                </>,
              )}
            </div>
          )}
          <div className="cands">
            {clip.guess
              .filter((g) => g.p >= 0.02 || g === clip.guess[0])
              .map((g, i) => {
                const k = slot(g.name);
                return (
                  <div
                    key={g.name}
                    className={`cand ${i === 0 ? "top" : ""}`}
                    onClick={() => onAssign(g.name)}
                  >
                    <Avatar role={roles[g.name]} name={g.name} blank={g.name === OTHER} size="md" />
                    <div className="name">
                      {g.name === OTHER ? (
                        labelText[OTHER]
                      ) : (
                        <RoleName role={roles[g.name]} name={g.name} />
                      )}
                    </div>
                    {g.name !== OTHER && (
                      <button
                        className="ref"
                        title={tr(
                          "听这个角色确认过的一句",
                          "Hear a confirmed line of this character",
                        )}
                        onClick={(e) => {
                          e.stopPropagation();
                          onPlayRef(g.name);
                        }}
                      >
                        {tr("参考音", "Reference")}
                        {i === 0 ? (
                          <>
                            {" "}
                            <kbd>R</kbd>
                          </>
                        ) : (
                          ""
                        )}
                      </button>
                    )}
                    {g.name !== OTHER && (
                      <button
                        className="low"
                        title={
                          tr(`标成 ${g.name}·质量低：`, `Label as ${g.name}, low quality: `) +
                          lowTip()
                        }
                        onClick={(e) => {
                          e.stopPropagation();
                          onAssign(g.name, true);
                        }}
                      >
                        {tr("质量低", "Low quality")}
                        {k ? (
                          <>
                            {" "}
                            <span className="k">⇧{k}</span>
                          </>
                        ) : (
                          ""
                        )}
                      </button>
                    )}
                    <span className="pct">{pct(g.p)}</span>
                    <div className="meter">
                      <i style={{ width: pct(g.p) }}></i>
                    </div>
                  </div>
                );
              })}
          </div>
          <div
            style={{
              marginTop: "10px",
              display: "flex",
              gap: "8px",
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            {clip.guess.length > 0 && (
              <button className="primary" onClick={onAccept}>
                {tr("是", "It's")} {labelText[clip.guess[0].name] || clip.guess[0].name}
                <kbd style={{ marginLeft: "4px" }}>Enter</kbd>
              </button>
            )}
            <button
              onClick={onNewRole}
              title={tr(
                "新建一个目标角色，名字可以以后再起；有画面时接着截头像",
                "Make a new target character; you can name it later. With video, crop an avatar next",
              )}
            >
              {tr("新角色", "New character")} <kbd style={{ marginLeft: "4px" }}>N</kbd>
            </button>
            <span style={{ fontSize: "12px", color: "var(--text-3)" }}>
              {tr(
                "已有的人按数字键，或点底部的头像",
                "Existing characters: number keys, or click an avatar at the bottom",
              )}
            </span>
          </div>
        </>
      )}

      <div className="hint">
        {tr(
          <>
            <kbd>J</kbd> <kbd>K</kbd> 上下一句 · <kbd>空格</kbd> 重播 · <kbd>1</kbd>–<kbd>9</kbd>{" "}
            选下面的角色 ·<kbd>N</kbd> 新角色 · <kbd>Z</kbd> 撤销 · <kbd>?</kbd> 全部快捷键
          </>,
          <>
            <kbd>J</kbd> <kbd>K</kbd> next / previous · <kbd>Space</kbd> replay · <kbd>1</kbd>–
            <kbd>9</kbd> pick a character below ·<kbd>N</kbd> new character · <kbd>Z</kbd> undo ·{" "}
            <kbd>?</kbd> all shortcuts
          </>,
        )}
      </div>
    </aside>
  );
}
