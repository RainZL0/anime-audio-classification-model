import { tr } from "../language";

export function Help({ onClose }: { onClose: () => void }) {
  const rows = [
    [tr("J / ↓，K / ↑", "J / ↓, K / ↑"), tr("下一句，上一句", "Next line, previous line")],
    [
      tr("空格", "Space"),
      tr(
        "从头重播这一句；再点一下选中的那句也一样",
        "Replay this line from the start; clicking the selected line again does the same",
      ),
    ],
    ["Enter", tr("接受机器猜的第一个", "Accept the machine's top guess")],
    [
      "1 – 9",
      tr(
        "标成底部角色栏里对应的目标角色",
        "Label as the matching target character in the bottom bar",
      ),
    ],
    [
      "Shift + 1 – 9",
      tr(
        "同一个目标角色，但质量低：背景音太重或有人同时出声。不拿来认人，导出时跳过",
        "The same target character, but low quality: too much background sound or someone talking at the same time. Not used to recognize anyone, skipped on export",
      ),
    ],
    ["Q", tr("其他：不是任何一个目标角色", "Other: not any of the target characters")],
    [
      "N",
      tr(
        "标成一个新的目标角色，名字以后再起；有画面时接着截头像",
        "Label as a new target character, to be named later; with video, crop an avatar next",
      ),
    ],
    [
      "Backspace",
      tr(
        "清掉这句的标签，回到机器的猜测（Z 是撤回上一步，不一定是清掉）",
        "Clear this line's label and go back to the machine's guess (Z undoes the last step, which is not always the same)",
      ),
    ],
    ["R", tr("听机器最像的那个角色的参考音", "Hear a reference line of the machine's top guess")],
    [
      "L",
      tr(
        "多放前后文：在不多放、前后各 5 秒、15 秒之间切换，换一句也保持",
        "More context: step through none, 5 seconds on each side, and 15. It stays when you move to another line",
      ),
    ],
    ["Z", tr("撤销上一步（可以一直往回撤）", "Undo the last step (you can keep going back)")],
    ["F", tr("场景视图里只看要处理的", "In the Scenes view, show only what needs work")],
    [
      tr("角色视图里 Shift+Enter", "Shift+Enter in Characters"),
      tr(
        "确认机器归给这个角色、还没人确认的全部句子",
        "Confirm all lines the machine gave this character that no one has confirmed yet",
      ),
    ],
    [
      tr("角色视图里 P", "P in Characters"),
      tr("从最没把握的开始连着播", "Play one after another, least sure first"),
    ],
    [
      "G / S / O / E",
      tr("切到起步分组 / 场景 / 角色 / 导出", "Go to Groups / Scenes / Characters / Export"),
    ],
    [tr("截头像时 Enter / Esc", "Enter / Esc when cropping"), tr("保存 / 放弃", "Save / cancel")],
  ];
  return (
    <div className="overlay" onClick={onClose}>
      <div className="help" onClick={(e) => e.stopPropagation()}>
        <h2>{tr("快捷键", "Keyboard shortcuts")}</h2>
        <table>
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}>
                <td>
                  <kbd>{k}</kbd>
                </td>
                <td>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="note" style={{ marginTop: "12px" }}>
          {tr(
            "每次标注都立刻保存，并让机器重新学一次。标注、新建、改名和合并角色都能撤销；头像和设不设目标角色不算标注，直接改回去就行。",
            "Every label is saved at once and retrains the machine. Labeling, making, renaming and merging characters can all be undone; avatars and target settings are not labels, just change them back.",
          )}
        </p>
      </div>
    </div>
  );
}
