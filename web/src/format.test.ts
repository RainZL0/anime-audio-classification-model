import { describe, expect, test } from "vitest";
import { howLong, minutes, pct, stamp } from "./format";

describe("stamp", () => {
  test("writes minutes and seconds with tenths", () => {
    expect(stamp(0)).toBe("00:00.0");
    expect(stamp(83.24)).toBe("01:23.2");
  });

  test("carries the minute when the seconds round up to 60", () => {
    expect(stamp(59.96)).toBe("01:00.0");
  });
});

test("pct rounds to a whole percent", () => {
  expect(pct(0.256)).toBe("26%");
});

test("howLong picks seconds, minutes or hours", () => {
  expect(howLong(42)).toBe("42 秒");
  expect(howLong(125)).toBe("2 分 5 秒");
  expect(howLong(3 * 3600 + 7 * 60)).toBe("3 小时 7 分");
});

test("minutes pads the seconds", () => {
  expect(minutes(187.9)).toBe("3:07");
});
