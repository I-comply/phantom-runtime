import { NextResponse } from 'next/server';
import { runAllActive } from '@/lib/scraper/engine';

export const dynamic = 'force-dynamic';
export const maxDuration = 300;

export async function GET() {
  const results = await runAllActive();
  return NextResponse.json({
    total: results.length,
    changed: results.filter((r) => r.ok && r.changed).length,
    failed: results.filter((r) => !r.ok).length,
    results,
  });
}
