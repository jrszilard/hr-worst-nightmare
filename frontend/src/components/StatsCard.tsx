interface StatsCardProps {
  label: string;
  value: string | number;
  subtext?: string;
}

export default function StatsCard({ label, value, subtext }: StatsCardProps) {
  return (
    <div className="rounded border border-gray-700 bg-gray-800 p-4">
      <p className="text-xs font-medium text-gray-400">{label}</p>
      <p className="mt-1 text-2xl font-bold text-gray-100">{value}</p>
      {subtext && (
        <p className="mt-1 text-xs text-gray-500">{subtext}</p>
      )}
    </div>
  );
}
