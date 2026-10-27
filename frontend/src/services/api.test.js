import { afterEach, describe, expect, it, vi } from "vitest";
import { apiGet, calculateSubnet, extractDetail } from "./api.js";

afterEach(() => vi.unstubAllGlobals());

describe("apiGet", () => {
  it("returns parsed JSON on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) }));
    await expect(apiGet("/api/health")).resolves.toEqual({ status: "ok" });
  });

  it("throws a readable error on HTTP failure even without a JSON body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => { throw new Error("no json"); } }));
    await expect(apiGet("/api/health")).rejects.toThrow("HTTP 503");
  });

  it("includes the server's validation detail in the error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: "CIDR prefix length must be between 0 and 32" }) }));
    await expect(apiGet("/x")).rejects.toThrow("CIDR prefix length must be between 0 and 32");
  });
});

describe("extractDetail", () => {
  it("handles string, list and missing details", () => {
    expect(extractDetail({ detail: "boom" })).toBe("boom");
    expect(extractDetail({ detail: [{ msg: "a" }, { msg: "b" }] })).toBe("a; b");
    expect(extractDetail({})).toBeNull();
    expect(extractDetail(null)).toBeNull();
  });
});

describe("calculateSubnet", () => {
  it("URL-encodes the slash in the CIDR", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    await calculateSubnet("192.168.10.0/24");
    expect(fetchMock.mock.calls[0][0]).toContain("cidr=192.168.10.0%2F24");
  });
});
