import { NextResponse } from 'next/server';

export async function GET() {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8080';
  try {
    const res = await fetch(`${backendUrl}/api/analytics`, { cache: 'no-store' });
    if (res.ok) {
      const data = await res.json();
      return NextResponse.json(data);
    }
  } catch {
    // Return empty default state if backend server is not running
  }

  return NextResponse.json({
    total_calls: 0,
    successful_calls: 0,
    failed_calls: 0,
    success_rate: 0,
    average_duration_seconds: 0,
    average_duration_formatted: '0s',
    human_escalations: 0,
    emergency_cases: 0,
    recent_calls: [],
  });
}
