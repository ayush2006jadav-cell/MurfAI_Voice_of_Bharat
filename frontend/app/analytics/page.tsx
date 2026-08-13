'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';

interface RecentCall {
  call_id: string;
  user_id_masked: string;
  started_at: string;
  duration_seconds: number;
  duration_formatted: string;
  outcome: 'successful' | 'failed';
  human_escalation: boolean;
  emergency_case: boolean;
}

interface AnalyticsData {
  total_calls: number;
  successful_calls: number;
  failed_calls: number;
  success_rate: number;
  average_duration_seconds: number;
  average_duration_formatted: string;
  human_escalations: number;
  emergency_cases: number;
  recent_calls: RecentCall[];
}

export default function AnalyticsPage() {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAnalytics = async () => {
    try {
      const res = await fetch('/api/analytics');
      if (!res.ok) throw new Error('Failed to load analytics data');
      const json = await res.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAnalytics();
    const interval = setInterval(fetchAnalytics, 5000); // Auto-refresh every 5s
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 px-6 pt-24 pb-12 font-sans text-slate-100 md:px-10 md:pt-28">
      <div className="mx-auto max-w-6xl space-y-8">
        {/* Header */}
        <div className="flex flex-col gap-4 border-b border-slate-800 pb-6 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <Link
                href="/"
                className="flex items-center gap-1 text-xs font-medium text-sky-400 hover:underline"
              >
                ← Back to Agent
              </Link>
            </div>
            <h1 className="mt-1 text-2xl font-bold tracking-tight text-sky-400 md:text-3xl">
              Swasthya Bharat — Call Analytics
            </h1>
            <p className="mt-1 text-sm text-slate-400">
              Real-time analytics and safe call metrics powered by Swasthya Bharat SQLite database
            </p>
          </div>
          <button
            onClick={fetchAnalytics}
            className="flex items-center gap-2 self-start rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-200 transition hover:bg-slate-700 md:self-auto"
          >
            <span>🔄</span> Refresh Data
          </button>
        </div>

        {loading && !data && (
          <div className="p-12 text-center text-slate-400">Loading call analytics...</div>
        )}

        {error && (
          <div className="rounded-xl border border-red-800 bg-red-950/60 p-4 text-sm text-red-300">
            {error}
          </div>
        )}

        {data && (
          <>
            {/* TOP METRICS */}
            <div>
              <h2 className="mb-3 text-xs font-bold tracking-wider text-slate-400 uppercase">
                Top Metrics
              </h2>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                {/* Total Calls */}
                <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 shadow-lg">
                  <div className="text-xs font-semibold text-slate-400 uppercase">Total Calls</div>
                  <div className="mt-2 text-4xl font-extrabold text-white">{data.total_calls}</div>
                </div>

                {/* Successful Calls */}
                <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 shadow-lg">
                  <div className="text-xs font-semibold text-slate-400 uppercase">
                    Successful Calls
                  </div>
                  <div className="mt-2 text-4xl font-extrabold text-emerald-400">
                    {data.successful_calls}
                  </div>
                </div>

                {/* Failed Calls */}
                <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 shadow-lg">
                  <div className="text-xs font-semibold text-slate-400 uppercase">Failed Calls</div>
                  <div className="mt-2 text-4xl font-extrabold text-rose-400">
                    {data.failed_calls}
                  </div>
                </div>
              </div>
            </div>

            {/* SECONDARY METRICS */}
            <div>
              <h2 className="mb-3 text-xs font-bold tracking-wider text-slate-400 uppercase">
                Secondary Metrics
              </h2>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                {/* Success Rate */}
                <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 shadow-lg">
                  <div className="text-xs font-semibold text-slate-400 uppercase">Success Rate</div>
                  <div className="mt-2 text-4xl font-extrabold text-sky-400">
                    {data.success_rate}%
                  </div>
                </div>

                {/* Human Escalations */}
                <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 shadow-lg">
                  <div className="text-xs font-semibold text-slate-400 uppercase">
                    Human Escalations
                  </div>
                  <div className="mt-2 text-4xl font-extrabold text-amber-400">
                    {data.human_escalations}
                  </div>
                </div>

                {/* Emergency Cases */}
                <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 shadow-lg">
                  <div className="text-xs font-semibold text-slate-400 uppercase">
                    Emergency Cases
                  </div>
                  <div className="mt-2 text-4xl font-extrabold text-rose-500">
                    {data.emergency_cases}
                  </div>
                </div>
              </div>
            </div>

            {/* AVERAGE CALL DURATION */}
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 shadow-lg">
              <div className="text-xs font-semibold text-slate-400 uppercase">
                Average Call Duration
              </div>
              <div className="mt-1 text-3xl font-extrabold text-sky-400">
                {data.average_duration_formatted}
              </div>
            </div>

            {/* RECENT CALLS */}
            <div>
              <h2 className="mb-3 text-xs font-bold tracking-wider text-slate-400 uppercase">
                Recent Calls
              </h2>
              <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900 shadow-lg">
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm text-slate-300">
                    <thead className="border-b border-slate-800 bg-slate-950 text-xs text-slate-400 uppercase">
                      <tr>
                        <th className="px-4 py-3 font-semibold">Call ID</th>
                        <th className="px-4 py-3 font-semibold">Date / Time</th>
                        <th className="px-4 py-3 font-semibold">Duration</th>
                        <th className="px-4 py-3 font-semibold">Outcome</th>
                        <th className="px-4 py-3 font-semibold">Escalation</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800">
                      {data.recent_calls.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="py-8 text-center text-slate-500">
                            No call records available yet.
                          </td>
                        </tr>
                      ) : (
                        data.recent_calls.map((call) => (
                          <tr key={call.call_id} className="transition hover:bg-slate-800/50">
                            <td className="px-4 py-3 font-mono font-medium text-sky-400">
                              {call.call_id}
                            </td>
                            <td className="px-4 py-3 text-xs text-slate-400">
                              {call.started_at.slice(0, 19).replace('T', ' ')}
                            </td>
                            <td className="px-4 py-3 font-mono text-xs">
                              {call.duration_formatted}
                            </td>
                            <td className="px-4 py-3">
                              <span
                                className={`rounded-full px-2.5 py-1 text-xs font-bold ${
                                  call.outcome === 'successful'
                                    ? 'border border-emerald-800 bg-emerald-950 text-emerald-400'
                                    : 'border border-rose-800 bg-rose-950 text-rose-400'
                                }`}
                              >
                                {call.outcome.toUpperCase()}
                              </span>
                            </td>
                            <td className="px-4 py-3">
                              {call.human_escalation ? (
                                <span className="rounded-md border border-amber-800 bg-amber-950 px-2 py-0.5 text-xs font-semibold text-amber-400">
                                  Yes
                                </span>
                              ) : (
                                <span className="text-xs text-slate-500">No</span>
                              )}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
