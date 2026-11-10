import { neon } from "@neondatabase/serverless";

/** Optional Neon access. App pages primarily read committed artifacts; DB is the weekly sync target. */
export function getSql() {
  const url =
    process.env.DATABASE_URL ||
    process.env.DATABASE_URL_UNPOOLED ||
    process.env.POSTGRES_URL ||
    process.env.POSTGRES_URL_NON_POOLING;
  if (!url) return null;
  return neon(url);
}

export async function fetchForecastsFromDb() {
  const sql = getSql();
  if (!sql) return null;
  try {
    const rows = await sql`select payload from forecasts order by kickoff asc`;
    return rows.map((r) => r.payload);
  } catch {
    return null;
  }
}
