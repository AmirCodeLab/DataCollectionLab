import { useQuery } from "@tanstack/react-query";

async function fetchHealth() {
  const response = await fetch("/api/../health");
  if (!response.ok) throw new Error("API unreachable");
  return response.json() as Promise<{ status: string; environment: string }>;
}

export function App() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
  });

  return (
    <main className="p-8 font-sans">
      <h1 className="text-2xl font-semibold">DCP Console</h1>
      <p className="mt-2 text-sm opacity-70">Phase 0 — architecture proof</p>
      <div className="mt-6 rounded border p-4">
        <span className="font-medium">API: </span>
        {isLoading && <span>checking…</span>}
        {isError && <span className="text-red-600">unreachable</span>}
        {data && <span className="text-green-600">{data.status} ({data.environment})</span>}
      </div>
    </main>
  );
}
