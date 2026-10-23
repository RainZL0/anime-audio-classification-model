import { expect, test } from "vitest";
import type { Clip } from "./api";
import { bestTarget, maybeListOf, OTHER, otherName, pendingOf, whoOf } from "./clips";

const clip = (id: string, extra: Partial<Clip> = {}): Clip => ({
  id,
  episode: "ep1",
  start: 0,
  end: 1,
  duration: 1,
  gap: null,
  text: "",
  scene: 0,
  voiced: true,
  label: null,
  rejects: [],
  unusable: false,
  guess: [],
  familiar: null,
  status: "review",
  ...extra,
});

test("whoOf takes the person's label before the machine's guess", () => {
  const guess = [{ name: "A", p: 0.9 }];
  expect(whoOf(clip("1", { guess }))).toEqual({ name: "A", human: false, p: 0.9 });
  expect(whoOf(clip("1", { guess, label: "B" }))).toEqual({ name: "B", human: true });
  expect(whoOf(clip("1"))).toBeNull();
});

test("bestTarget skips other", () => {
  const guess = [
    { name: OTHER, p: 0.7 },
    { name: "A", p: 0.2 },
  ];
  expect(bestTarget(clip("1", { guess }))?.name).toBe("A");
});

test("pendingOf lists unconfirmed lines, least sure first, and leaves out maybe missed", () => {
  const sure = clip("sure", { guess: [{ name: "A", p: 0.9 }] });
  const unsure = clip("unsure", { guess: [{ name: "A", p: 0.4 }] });
  const done = clip("done", { label: "A" });
  const maybe = clip("maybe", { maybe: true });
  const list = [sure, unsure, done, maybe];
  expect(pendingOf(list).map((c) => c.id)).toEqual(["unsure", "sure"]);
  expect(maybeListOf(list).map((c) => c.id)).toEqual(["maybe"]);
});

test("other typed as a name in either language means the other label", () => {
  expect(otherName(" Other ")).toBe(true);
  expect(otherName("其他")).toBe(true);
  expect(otherName("Others")).toBe(false);
});
