import { useState } from "react";
import { calculateSubnet } from "../services/api.js";
import Row from "./Row.jsx";

export default function SubnetCalculator() {
  const [cidr, setCidr] = useState("192.168.10.77/24");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    try {
      setResult(await calculateSubnet(cidr.trim()));
      setError(null);
    } catch (err) {
      setResult(null);
      setError(err.message);
    }
  }

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wider text-slate-400">Subnet calculator</h2>
      <p className="mb-3 text-xs text-slate-500">Computed by the backend with Python&apos;s ipaddress module.</p>
      <form onSubmit={submit} className="mb-3 flex gap-2">
        <input
          value={cidr}
          onChange={(e) => setCidr(e.target.value)}
          className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-sm"
          aria-label="CIDR"
        />
        <button className="rounded bg-sky-600 px-3 py-1 text-sm font-medium hover:bg-sky-500">Calculate</button>
      </form>
      {error && <p className="text-sm text-red-300">{error}</p>}
      {result && (
        <div>
          <Row label="Network">{result.cidr}</Row>
          <Row label="Subnet mask">{result.netmask}</Row>
          <Row label="Wildcard">{result.wildcard_mask}</Row>
          <Row label="Broadcast">{result.broadcast_address ?? "n/a"}</Row>
          <Row label="Usable hosts">{result.usable_hosts}</Row>
          <Row label="Host range">{result.first_host} - {result.last_host}</Row>
          <Row label="RFC 1918 private">{result.is_private_rfc1918 ? "yes" : "no"}</Row>
        </div>
      )}
    </section>
  );
}
