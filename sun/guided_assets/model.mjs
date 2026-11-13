export const pageSize = 5;
export function queue(prs, mode, query = '', done = new Set()) {
  const available = prs.filter(p => !done.has(p.id));
  if (query.trim()) return available.filter(p => `${p.id} ${p.title}`.toLowerCase().includes(query.trim().toLowerCase()));
  const waiting = p => Boolean(p.error || p.analysis?.waiting);
  if (mode === 'waiting') return available.filter(waiting);
  const ready = available.filter(p => !waiting(p));
  return mode === 'later' ? ready.slice(pageSize) : ready.slice(0, pageSize);
}
export function requiredChecks(pr) {
  const results = [...(pr.review?.check_results || []), ...(pr.review?.github_checks || [])];
  for (const name of pr.analysis?.required_checks || []) {
    if (!results.some(c => c.name === name)) results.push({name, status: 'Not recorded', files: [], checks: []});
  }
  return results;
}
export function githubUrl(pr) {
  // The canonical server URL is checked again at the DOM boundary.
  try {
    const url = new URL(pr.url);
    if (url.protocol !== 'https:' || url.hostname !== 'github.com' || url.port || url.username || url.password ||
        !/^\/[\w-]+\/[\w.-]+\/pull\/[1-9]\d*$/.test(url.pathname)) return null;
    return url.origin + url.pathname + '/files';
  } catch { return null; }
}
