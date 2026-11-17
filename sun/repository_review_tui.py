"""Deterministic curses view. Deliberately never reads agent explanations."""
import curses
from pathlib import Path
import sys
from .repository_review import load,review_turn,NEGATIVE


def unreviewed(model,t):
    return not all(c['id'] in model.get('reviewed',[]) for c in t['changes'])


def sessions(model,mode='unreviewed'):
    groups={}
    for t in model['turns']:
        if mode!='all' and not unreviewed(model,t):continue
        if mode=='failed' and not t['failed']:continue
        if mode=='unchecked' and not t['unchecked']:continue
        groups.setdefault(t['session'],[]).append(t)
    return sorted(groups.values(),key=lambda ts:-sum(t['failed'] for t in ts))


def plain(model,width=90):
    s=model['summary'];bar=round(48*s['percent']/100)
    lines=['sun / repository                         all recorded branches','',
           '┌─ edits '+'─'*(width-10)+'┐',f"│ {s['edits']:,} agent edits",f"│ {'█'*bar}{'░'*(48-bar)} {s['percent']}%",
           f"│ {s['checked']:,} checked       {s['unchecked']:,} unchecked",'└'+'─'*(width-2)+'┘','', '┌─ rules '+'─'*(width-10)+'┐']
    for r in model['rules']:
        checks=[c for c in model['checks'].values() if c['rule']==r['name']]
        lines.append(f"│ {r['name']:<22} {sum(c['verdict'].lower() in NEGATIVE for c in checks):>4} failed")
    lines+=['└'+'─'*(width-2)+'┘','','┌─ turns '+'─'*(width-10)+'┐']
    chars=['×' if t['failed'] else '+' if t['passed'] else '·' for t in model['turns']]
    for i in range(0,len(chars),36):lines.append('│ '+' '.join(chars[i:i+36]))
    lines+=['└'+'─'*(width-2)+'┘','  × failed  + passed  · no checks','','sessions · unreviewed']
    for group in sessions(model):
        lines.append(f"  {group[0]['session'][:8]}  {sum(t['failed'] for t in group):>3} failed  {group[0]['title'][:50]}")
    return '\n'.join(lines)


class Browser:
    def __init__(self,workspace):
        self.workspace=Path(workspace);self.model=load(workspace);self.page=('overview',None);self.stack=[];self.selected=0;self.mode='unreviewed';self.grid=False;self.tile=0;self.x=0
    def rows(self):
        kind,key=self.page;m=self.model
        if kind=='overview':
            return [(f"{g[0]['session'][:8]}  {sum(t['failed'] for t in g):>3} failed  {len(g):>3} turns  {g[0]['title']}",('session',g[0]['session'])) for g in sessions(m,self.mode)] or [('No sessions in this group.',None)]
        if kind=='session':
            return [(f"turn {t['label']:<5} {t['failed']:>3} failed  {t['passed']:>3} passed  {t['title']}",('turn',t['id'])) for t in m['turns'] if t['session']==key]
        t=next(t for t in m['turns'] if t['id']==key)
        rows=[('task  '+(t['request'] or t['title']).replace('\n',' '),None),('',None)]
        rows += [(f"{'×' if c['verdict'].lower() in NEGATIVE else '✓'} {c['rule']}  {c.get('note') or c['verdict']}",None) for c in t['checks']]
        if not t['checks']:rows.append(('— no checks recorded',None))
        for c in t['changes']:
            rows += [('',None),(f"┌─ {c['file']} · {c['at'][:7]}",None)]
            patch=(self.workspace/'patches'/f"{c['id']}.patch").read_text()
            rows += [(line,None) for line in patch.splitlines()]
        return rows
    def open(self):
        target=('turn',self.model['turns'][self.tile]['id']) if self.grid and self.model['turns'] else self.rows()[self.selected][1]
        if target:
            self.stack.append((self.page,self.selected));self.page=target;self.selected=0;self.grid=False;self.x=0
    def back(self):
        if self.stack:self.page,self.selected=self.stack.pop();self.grid=False;self.x=0
    def mark(self):
        if self.page[0]=='turn':
            review_turn(self.workspace,self.model,self.page[1]);self.model=load(self.workspace)


def tui(screen,b):
    try:curses.curs_set(0)
    except curses.error:pass
    screen.keypad(True);colored=curses.has_colors()
    if colored:
        curses.start_color()
        try:curses.use_default_colors()
        except curses.error:pass
        palette=[(1,250),(2,151),(3,108),(4,65),(5,181),(6,131),(7,88)] if curses.COLORS>=256 else [(1,curses.COLOR_WHITE),(2,curses.COLOR_GREEN),(3,curses.COLOR_GREEN),(4,curses.COLOR_GREEN),(5,curses.COLOR_RED),(6,curses.COLOR_RED),(7,curses.COLOR_RED)]
        for pair,color in palette:
            try:curses.init_pair(pair,color,-1)
            except curses.error:curses.init_pair(pair,color,curses.COLOR_BLACK)
    def put(y,x,text,width,attr=0):
        clean=''.join(c if c.isprintable() else ' ' for c in str(text))
        try:screen.addnstr(y,x,clean,max(0,width),attr)
        except curses.error:pass
    while True:
        screen.erase();height,width=screen.getmaxyx()
        if height<12 or width<45:
            put(0,0,'Resize terminal to at least 45 × 12. q to quit',width-1);screen.refresh()
            if screen.getch()==ord('q'):return
            continue
        m=b.model;s=m['summary'];put(0,1,'sun / repository  / '+b.page[0],width-2,curses.A_BOLD);start=2
        if b.page[0]=='overview':
            put(2,1,'┌─ edits '+'─'*(width-12)+'┐',width-2);put(3,3,f"{s['edits']:,} agent edits",width-6,curses.A_BOLD)
            barwidth=min(50,width-16);filled=round(barwidth*s['percent']/100)
            put(4,3,'█'*filled+'░'*(barwidth-filled)+f" {s['percent']}%",width-6)
            put(5,3,f"{s['checked']:,} checked    {s['unchecked']:,} unchecked",width-6);put(6,1,'└'+'─'*(width-4)+'┘',width-2)
            start=8
            for r in m['rules']:
                n=sum(c['verdict'].lower() in NEGATIVE for c in m['checks'].values() if c['rule']==r['name'])
                put(start,3,f"{r['name']:<20} {n:>3} failed",width-6,curses.color_pair(6) if n and colored else 0);start+=1
            start+=1;put(start,1,'┌─ turns · g to select '+'─'*max(0,width-25)+'┐',width-2);start+=1
            columns=max(1,(width-6)//3)
            for index,t in enumerate(m['turns']):
                y=start+index//columns
                if y>=height-7:break
                pair=(4+t['intensity'] if t['failed'] else 1+t['intensity'] if t['passed'] else 1)
                attr=curses.color_pair(pair) if colored else 0
                if b.grid and index==b.tile:attr|=curses.A_REVERSE
                put(y,3+(index%columns)*3,'██',2,attr)
            start=min(start+(len(m['turns'])+columns-1)//columns,height-7)+1
            put(start,2,('turn '+m['turns'][b.tile]['label']+' · '+m['turns'][b.tile]['title']) if b.grid and m['turns'] else 'sessions · '+b.mode+'    [u unreviewed / f failed / n unchecked / a all]',width-4);start+=2
        rows=b.rows();b.selected=min(b.selected,max(0,len(rows)-1));size=max(1,height-start-2);offset=max(0,min(b.selected-size//2,len(rows)-size))
        for n,(text,target) in enumerate(rows[offset:offset+size]):
            attr=curses.A_REVERSE if not b.grid and offset+n==b.selected else 0
            if colored and text.startswith('+'):attr|=curses.color_pair(3)
            elif colored and text.startswith('-'):attr|=curses.color_pair(6)
            put(start+n,2,('› ' if target else '  ')+text[b.x:],width-4,attr)
        put(height-1,1,'j/k move  Enter open  Esc back  g grid  r reviewed  q quit',width-2);screen.refresh();key=screen.getch()
        if key==ord('q'):return
        if key==ord('g') and b.page[0]=='overview':b.grid=not b.grid
        elif key in (10,13,curses.KEY_ENTER):b.open()
        elif key in (27,ord('h')):b.back()
        elif key==ord('r'):b.mark()
        elif b.page[0]=='overview' and key in map(ord,'ufna'):
            b.mode={ord('u'):'unreviewed',ord('f'):'failed',ord('n'):'unchecked',ord('a'):'all'}[key];b.selected=0;b.grid=False
        elif b.grid and m['turns']:
            delta={curses.KEY_RIGHT:1,curses.KEY_LEFT:-1,curses.KEY_DOWN:columns,curses.KEY_UP:-columns,ord('j'):columns,ord('k'):-columns}.get(key,0)
            b.tile=max(0,min(len(m['turns'])-1,b.tile+delta))
        elif key in (ord('j'),curses.KEY_DOWN):b.selected=min(len(rows)-1,b.selected+1)
        elif key in (ord('k'),curses.KEY_UP):b.selected=max(0,b.selected-1)
        elif key==curses.KEY_NPAGE:b.selected=min(len(rows)-1,b.selected+size)
        elif key==curses.KEY_PPAGE:b.selected=max(0,b.selected-size)
        elif key==curses.KEY_RIGHT:b.x+=8
        elif key==curses.KEY_LEFT:b.x=max(0,b.x-8)


def run(workspace):
    if not sys.stdin.isatty() or not sys.stdout.isatty():raise SystemExit('Use --tui in a terminal, or --print for plain output.')
    curses.wrapper(tui,Browser(workspace))
