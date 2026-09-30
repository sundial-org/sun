"""Claim parsing, coverage checks, and rendering without automatic approval."""
import hashlib
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
REFERENCES={}

def blocks(text):
    for m in re.finditer(r'\\claim\{([A-Z]\d+)\}\{',text):
        depth,end=1,m.end()
        while depth:
            assert end<len(text),'Unclosed claim'
            if text[end-1]!='\\':
                depth+=(text[end]=='{')-(text[end]=='}')
            end+=1
        yield m[1],text[m.end():end-1],m.start(),end

def parse(text):
    result={}
    for cid,claim,_,_ in blocks(text):
        assert cid not in result,'Duplicate '+cid
        result[cid]=claim
    return result

def coverage(text):
    body=text.split('\\begin{abstract}',1)[1].split('\\begin{thebibliography}',1)[0]
    for _,_,a,b in reversed(list(blocks(body))):
        body=body[:a]+body[b:]
    body=re.sub(r'\\begin\{(?:table|figure)\*?\}.*?\\end\{(?:table|figure)\*?\}','',body,flags=re.S)
    body=re.sub(r'\\(?:subsection|section)\{[^{}]*\}','',body)
    body=body.replace('\\end{abstract}','').replace('\\small','').replace('{','').replace('}','')
    assert not body.strip(),'Untracked prose: '+body.strip()[:200]

def plain(text):
    text=re.sub(r'\\cite\{([^}]+)\}',lambda m:'['+m[1]+']',text)
    text=re.sub(r'\\ref\{([^}]+)\}',lambda m:REFERENCES.get(m[1],m[1]),text)
    text=re.sub(r'\\href\{([^{}]+)\}\{([^{}]+)\}',r'[\2](\1)',text)
    text=re.sub(r'\\(?:texttt|textit|textbf|emph)\{([^}]+)\}',r'\1',text)
    return text.replace('\\%','%').replace('~',' ').replace('``','"').replace("''",'"')

def notes_coverage(text):
    body=text.split('\\begin{document}',1)[1].split('\\end{document}',1)[0]
    for _,_,a,b in reversed(list(blocks(body))):
        body=body[:a]+body[b:]
    body=re.sub(r'\\begin\{center\}.*?\\end\{center\}','',body,flags=re.S)
    body=re.sub(r'^\\InputIfFileExists.*$','',body,flags=re.M)
    body=re.sub(r'\\textbf\{[^{}]*\}','',body)
    body=re.sub(r'\\(?:begin|end)\{itemize\}|\\item','',body)
    assert not body.strip(),'Untracked submission-note prose: '+body.strip()[:200]

def main():
    text=(HERE/'paper.tex').read_text()
    coverage(text)
    for kind in ['figure','table']:
        for number,match in enumerate(re.finditer(r'\\begin\{'+kind+r'\*?\}.*?\\end\{'+kind+r'\*?\}',text,re.S),1):
            for label in re.findall(r'\\label\{([^}]+)\}',match[0]):
                REFERENCES[label]=str(number)
    claims=parse(text)
    paper_ids=set(parse(text.split('\\begin{thebibliography}',1)[0]))
    notes=(HERE/'submission-notes.tex').read_text()
    notes_coverage(notes)
    note_claims=parse(notes)
    assert not claims.keys() & note_claims.keys()
    claims.update(note_claims)
    ledger=json.loads((HERE/'claim-checks.json').read_text())
    assert claims.keys()==ledger.keys()
    lines=['# Claim-by-claim justification','',
           'Every substantive assertion in the paper and appended submission notes has a stable ID. Measured claims are checked '
           'against saved responses and independently recomputed summaries; method claims are '
           'checked against the frozen code and manifests; literature claims are checked in primary '
           'sources. Inferences and limitations are identified separately. Hashes detect changes to '
           'reviewed text; they do not prove a claim true. No human quality review is implied.','']
    for cid,claim in claims.items():
        check=ledger[cid]
        assert check['reviewed'] is True and check['text_sha256']==hashlib.sha256(claim.encode()).hexdigest(),cid
        assert check['sources'] and check['justification'] and check['status']!='pending',cid
        assert 'pending' not in check.get('verification_status','').lower(),cid
        for source in check['sources']:
            if source.startswith(('https://','http://','git commit ')):
                continue
            path=source.split(': ',1)[0]
            if path not in ['CLAIMS.md','evidence/build-check.json']:
                assert (HERE/path).exists(),(cid,'Missing evidence locator',path)
        for path, expected in check.get('artifact_sha256',{}).items():
            assert hashlib.sha256((HERE/path).read_bytes()).hexdigest()==expected,(cid,path)
        lines += [f'## {cid}: {check["status"]}','',plain(claim),'',
                  '**Evidence:** '+'; '.join(check['sources']),
                  '', '**Check and justification:** '+check['justification'],'']
        if check.get('artifact_sha256'):
            lines += ['**Reviewed artifact hashes:** '+json.dumps(check['artifact_sha256'],sort_keys=True),'']
    (HERE/'CLAIMS.md').write_text('\n'.join(lines))
    prose='\n'.join(plain(c) for cid,c in claims.items() if cid in paper_ids)
    prose=re.sub(r'\$[^$]*\$',' MATH ',prose)
    prose=re.sub(r'\[[a-z,]+\]','',prose)
    count=len(re.findall(r"\b\w+(?:[-']\w+)*\b",prose))
    tables='\n'.join(p.read_text() for p in (HERE/'evidence').glob('*-table.tex'))
    tables=re.sub(r'\\(?:begin|end)\{[^}]+\}(?:\{[^}]+\})?','',tables)
    tables=re.sub(r'\\[A-Za-z]+','',tables)
    count+=len(re.findall(r'\b\w+\b',tables))
    result=dict(count=count,target=[2000,2500],within_target=2000<=count<=2500,
                method='Claim prose and captions plus table entries; math expressions count once; excludes title, headings, bibliography, audit, and submission notes.')
    (HERE/'evidence/word-count.json').write_text(json.dumps(result,indent=2)+'\n')
    assert result['within_target'],result
    print(f'{len(claims)} reviewed claim blocks; {count} body words')

if __name__=='__main__':
    main()
