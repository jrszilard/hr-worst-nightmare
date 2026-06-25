import type { Indicator } from "../lib/api";

const colorMap: Record<Indicator, string> = {
  green: "bg-green-600 text-green-50",
  yellow: "bg-yellow-500 text-yellow-950",
  red: "bg-red-600 text-red-50",
};

interface ROIBadgeProps {
  indicator: Indicator;
  score: number | null;
}

export default function ROIBadge({ indicator, score }: ROIBadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold ${colorMap[indicator]}`}
    >
      {score !== null ? score.toFixed(1) : "--"}
    </span>
  );
}
