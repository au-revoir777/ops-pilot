import { redact, redactValue } from "@/lib/redact";

describe("redact", () => {
  it.each([
    ["password=hunter2 user=bob", "password=[REDACTED] user=bob"],
    ['{"api_key": "abc123def"}', '{"api_key": "[REDACTED]"}'],
    ["Authorization: Bearer abcdefghijklmnop", "Authorization: [REDACTED] abcdefghijklmnop"],
    ["postgresql://opspilot:s3cret@db:5432/x", "postgresql://opspilot:[REDACTED]@db:5432/x"],
    ["key sk-abcdefghijklmnopqrstuvwx used", "key [REDACTED] used"],
    ["AKIAABCDEFGHIJKLMNOP", "[REDACTED]"],
  ])("redacts %s", (input, expected) => {
    expect(redact(input)).toBe(expected);
  });

  it("leaves ordinary log lines alone", () => {
    const line = "slow_query_detected operation=cart query_time_ms=950 request_id=req-1";
    expect(redact(line)).toBe(line);
  });

  it("redacts nested values and secret-named keys", () => {
    expect(redactValue({ a: ["token=xyz123"], password: "plain", n: 3 })).toEqual({
      a: ["token=[REDACTED]"],
      password: "[REDACTED]",
      n: 3,
    });
  });
});
