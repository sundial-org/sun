// UI preferences only. These settings never enter the agent's review prompt.
export const settingsKey = 'sun-review-inbox.action.v1';

export function githubReviewUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.hostname !== 'github.com' ||
        url.port || url.username || url.password) return null;
    const match = url.pathname.match(/^\/([\w-]+)\/([\w.-]+)\/pull\/([1-9]\d*)(?:\/files)?\/?$/);
    return match ? `https://github.com/${match[1]}/${match[2]}/pull/${match[3]}/files` : null;
  } catch { return null; }
}

export function readSettings(storage) {
  try {
    const value = JSON.parse(storage.getItem(settingsKey));
    const links = Object.fromEntries(Object.entries(value?.links || {})
      .filter(([id, url]) => /^\d+$/.test(id) && typeof url === 'string' && githubReviewUrl(url))
      .map(([id, url]) => [id, githubReviewUrl(url)]));
    return {action: value?.action === 'github' ? 'github' : 'local', links};
  } catch { return {action: 'local', links: {}}; }
}

export function reviewAction(settings, id) {
  if (settings.action !== 'github') return {label: 'Mark reviewed', url: null, local: true};
  const url = githubReviewUrl(settings.links?.[id]);
  return {label: url ? 'Review on GitHub' : 'Link GitHub PR', url, local: false};
}
