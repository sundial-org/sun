const response = await fetch('data.json');
const data = await response.json();
document.getElementById('count').textContent = `${data.prs.length} review requests`;
for (const [i, pr] of data.prs.entries()) {
  const row = document.createElement('tr');
  const title = document.createElement('td');
  const link = document.createElement('a');
  link.textContent = `${pr.repository.nameWithOwner} #${pr.number} · ${pr.title}`;
  link.href = pr.error ? pr.url : `prs/${i}/index.html`;
  title.append(link);
  row.append(title);
  const c = pr.coverage;
  const cells = [pr.author?.login || 'Unknown',
    c?.turns == null ? 'Unknown' : `${c.checked_turns} / ${c.turns}`,
    c?.covered_files == null ? 'Unknown' : `${c.covered_files} / ${c.files} files`,
    pr.error || c?.warning || (c.files - c.covered_files ? `${c.files-c.covered_files} files need review` : 'Covered; awaiting your review')];
  for (const text of cells) {
    const cell = document.createElement('td');
    cell.textContent = text;
    row.append(cell);
  }
  document.getElementById('requests').append(row);
}
if (!data.prs.length) document.getElementById('error').textContent = 'No open PRs requesting your review.';
