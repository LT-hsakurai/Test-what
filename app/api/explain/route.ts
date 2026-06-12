// Claude explanation is now handled by the Python backend (/explain endpoint).
// This file is kept as a placeholder in case a Next.js-side fallback is needed.
export const dynamic = 'force-dynamic';

export async function GET() {
  return new Response(JSON.stringify({ info: 'Use the Python backend /explain endpoint' }), {
    headers: { 'Content-Type': 'application/json' },
  });
}
