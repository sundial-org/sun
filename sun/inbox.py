"""GitHub review requests and immutable, isolated PR snapshots."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace

from . import checks, git_store, history, review, review_web


def command(*args, cwd=None):
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f'{args[0]} timed out after 120 seconds') from None
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"{args[0]} failed")
    return result.stdout


def gh(*args):
    if not shutil.which('gh'):
        raise RuntimeError('GitHub CLI is required. Install gh and run gh auth login.')
    return json.loads(command('gh', *args))


def repo_name(value):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value):
        raise ValueError('Invalid GitHub repository name')
    return value


def send(a):
    if not a.reviewer:
        sys.exit('sun: send needs --reviewer USER (repeatable)')
    if a.json or a.update or a.pr:
        sys.exit('sun: send cannot use --json, --update, or --pr')
    try:
        # Resolve the actual push destination, not an unrelated upstream PR.
        origin = git_store.git('remote', 'get-url', '--push', 'origin').strip()
        match = re.fullmatch(r'(?:https://github.com/|git@github.com:)(.+?)(?:\.git)?', origin)
        if not match:
            raise RuntimeError('sun pr send currently requires a github.com origin remote')
        repo = repo_name(match[1])
        branch = git_store.git('symbolic-ref', '--short', 'HEAD').strip()
        base = a.base or gh('repo', 'view', repo, '--json', 'defaultBranchRef')['defaultBranchRef']['name']
        if branch == base:
            raise RuntimeError('Switch to a feature branch before sending a PR')
        existing = gh('pr', 'list', '--repo', repo, '--head', branch, '--state', 'open',
                      '--json', 'url')
        if len(existing) > 1:
            raise RuntimeError('Multiple open PRs for this branch; choose a unique branch')
        if git_store.git('status', '--porcelain').strip():
            raise RuntimeError('Commit or stash working changes before sending a PR')
        with git_store.lock():
            history.maybe_sync()
            tip = git_store.history_head()
            head = git_store.git('rev-parse', 'HEAD').strip()
            if git_store.git('diff', '--name-only', head, tip).strip():
                raise RuntimeError('Sun snapshot differs from Git HEAD; sync committed work before sending')
        # Publish normal code through normal hooks. Sun history honors existing sharing settings.
        command('git', 'push', '-u', 'origin', branch)
        history.cmd_push(SimpleNamespace(branch=branch, remote='origin'))
        if git_store.refs('refs/sun/checks/'):
            command('git', 'push', '--no-verify', 'origin', 'refs/sun/checks/*:refs/sun/checks/*')
        command('git', 'push', '--no-verify', 'origin', f'{tip}:refs/sun/reviews/{head}')
        if existing:
            url = existing[0]['url']
            for reviewer in a.reviewer:
                command('gh', 'pr', 'edit', url, '--add-reviewer', reviewer)
        else:
            args = ['gh', 'pr', 'create', '--repo', repo, '--head', branch, '--base', base,
                    '--title', a.title or git_store.git('log', '-1', '--format=%s').strip(),
                    '--body', 'Review requested through Sun.']
            for reviewer in a.reviewer:
                args += ['--reviewer', reviewer]
            url = command(*args).strip()
        if checks.read_rules()[1]:
            checks.cmd_pr(SimpleNamespace(base=base, json=False, update=True, pr=url, automatic=True))
        print(url)
    except (RuntimeError, ValueError, OSError) as exc:
        sys.exit(f'sun: {exc}')


def snapshot(pr, directory):
    """Fetch objects only: never check out or execute code supplied by a PR."""
    repo = repo_name(pr['repository']['nameWithOwner'])
    number = int(pr['number'])
    info = gh('pr', 'view', str(number), '--repo', repo, '--json',
              'headRefOid,baseRefOid,headRepository,headRepositoryOwner,statusCheckRollup')
    head, base = info['headRefOid'], info['baseRefOid']
    if not all(re.fullmatch(r'[0-9a-f]{40,64}', x) for x in (head, base)):
        raise ValueError('Invalid PR revision')
    directory = Path(directory)
    directory.mkdir()
    command('git', 'init', '-q', str(directory))
    # Disable hooks in this disposable repository only.
    command('git', 'config', 'core.hooksPath', '/dev/null', cwd=directory)
    url = f'https://github.com/{repo}.git'
    command('git', 'fetch', '-q', '--no-tags', url, base, head, cwd=directory)
    merge_base = command('git', 'merge-base', base, head, cwd=directory).strip()
    warning = None
    source = info.get('headRepository')
    owner = info.get('headRepositoryOwner')
    if source and owner:
        source_repo = repo_name(owner['login'] + '/' + source['name'])
        try:
            command('git', 'fetch', '-q', '--no-tags', f'https://github.com/{source_repo}.git',
                    f'+refs/sun/reviews/{head}:refs/sun/inbox/head',
                    'refs/sun/events/*:refs/sun/events/*', 'refs/sun/ops/*:refs/sun/ops/*',
                    'refs/sun/checks/*:refs/sun/checks/*', cwd=directory)
        except RuntimeError:
            warning = 'No shared Sun evidence for this revision'
    else:
        warning = 'Source repository is unavailable'
    old = os.getcwd()
    try:
        os.chdir(directory)
        evidence = git_store.ref_oid('refs/sun/inbox/head') if not warning else ''
        if evidence and git_store.git('rev-parse', evidence + '^{tree}').strip() != git_store.git('rev-parse', head + '^{tree}').strip():
            evidence, warning = '', 'Shared Sun snapshot does not match this revision'
        # Scope events to the published snapshot; no dependency on local branch state.
        if evidence:
            git_store.git('update-ref', 'refs/sun/heads/inbox', evidence)
        data = review.review_data(merge_base, head=head, evidence_head=evidence or head, use_checks=bool(evidence))
        events = history.events(scope=[evidence]) if evidence else []
        def turn(e):
            return (e.get('actor'), e.get('session_id'), e.get('turn'))
        turns = {turn(e) for e in events if e.get('type') == 'edit' and e.get('session_id') and e.get('turn') and
                 git_store.quiet('git', 'merge-base', '--is-ancestor', e['commit'], merge_base).returncode != 0}
        stored = checks.checks() if evidence else {}
        checked = set()
        for c in stored.values():
            cites = {x['at'] for x in review.citations(c, stored)}
            checked.update(turn(e) for e in events
                           if e['commit'] in cites or e.get('snapshot') in cites)
        data['github_checks'] = []
        for check in info.get('statusCheckRollup') or []:
            state = (check.get('conclusion') or check.get('state') or check.get('status') or '').upper()
            status = ('Passed' if state == 'SUCCESS' else
                      'Running' if state in ('PENDING', 'QUEUED', 'IN_PROGRESS', 'WAITING', 'REQUESTED') else
                      'Skipped' if state in ('SKIPPED', 'NEUTRAL') else
                      'Nonpassing' if state in ('FAILURE', 'ERROR', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED', 'STARTUP_FAILURE') else 'Unknown')
            data['github_checks'].append({'name': check.get('name') or check.get('context') or 'GitHub check',
                                          'status': status, 'detail': 'GitHub CI at ' + head})
        data['coverage'] = {'turns': len(turns) if evidence else None,
                            'checked_turns': len(turns & checked) if evidence else None,
                            'covered_files': len(data['hidden_files']) if evidence else None,
                            'files': data['files'], 'warning': warning}
        return data
    finally:
        os.chdir(old)


def collect(limit, directory):
    prs = gh('search', 'prs', '--review-requested=@me', '--state=open',
             '--limit', str(limit), '--json', 'number,title,url,repository,author,updatedAt')
    rows = []
    for index, pr in enumerate(prs):
        row = dict(pr)
        print(f"sun: preparing {index + 1}/{len(prs)} {pr['url']}", file=sys.stderr)
        root = str(Path(directory) / str(index))
        try:
            row['review'] = snapshot(pr, root)
            row['root'] = root
        except (RuntimeError, ValueError, OSError, SystemExit) as exc:
            row['error'] = str(exc)
        rows.append(row)
    return rows


def run(a):
    try:
        with tempfile.TemporaryDirectory(prefix='sun-inbox-') as directory:
            rows = collect(a.limit, directory)
            if a.json:
                return print(json.dumps({'prs': [{k: v for k, v in r.items() if k != 'root'} for r in rows]}))
            review_web.run({'prs': rows})
    except (RuntimeError, ValueError, OSError) as exc:
        sys.exit(f'sun: {exc}')
