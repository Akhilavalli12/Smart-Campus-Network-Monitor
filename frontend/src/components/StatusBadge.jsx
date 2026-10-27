import { statusColor, statusLabel } from "../status.js";
import StatusDot from "./StatusDot.jsx";

export default function StatusBadge({ status }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs font-semibold tracking-wide">
      <StatusDot color={statusColor(status)} />
      {statusLabel(status)}
    </span>
  );
}
