import os,re,sys,hashlib,json
P=sys.argv[1]
ALLOW=[r'\.ai-workflow/state\.yaml', r'\.ai-workflow/discovery-notes\.md',
 r'\.ai-workflow/backup/0[1-5]-(discovery|prd|user-stories|user-flows|acceptance-criteria)\.md',
 r'docs/planning/0[1-5]-(discovery|prd|user-stories|user-flows|acceptance-criteria)\.md']
SENT=json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'sentinels.json')))
bad=[]
for root,dirs,files in os.walk(P):
  dirs[:]=[d for d in dirs if not (root==P and d in ('.git','.claude'))]
  for f in files:
    rel=os.path.relpath(os.path.join(root,f),P)
    if rel in SENT or rel=='.gitignore': continue
    if not any(re.fullmatch(a,rel) for a in ALLOW): bad.append(rel)
sent_bad=[k for k,v in SENT.items() if not os.path.exists(os.path.join(P,k)) or hashlib.sha256(open(os.path.join(P,k),'rb').read()).hexdigest()!=v]
print('ALLOWLIST', 'OK' if not bad else 'VIOLATION '+str(bad), '| SENTINELS', 'OK' if not sent_bad else 'CHANGED '+str(sent_bad))
st=os.path.join(P,'.ai-workflow/state.yaml')
if os.path.exists(st):
  t=open(st).read()
  for stage in ('discovery','planning','design'):
    m=re.search(r'\n  '+stage+r':\n(.*?)(?=\n  [a-z]+:\n|\nhistory:|\Z)',t,re.S)
    if m:
      b=m.group(1); s=re.search(r'status: (\w+)',b); r=re.search(r'\n    revision: (\d+)',b); ar=re.search(r'approved:\n\s+revision: (\S+)',b)
      print(f"  {stage}: status={s and s.group(1)} rev={r and r.group(1)} approved_rev={ar and ar.group(1)}")
  for path,h in re.findall(r'(docs/planning/[\w.-]+): "?([0-9a-f]{64})"?',t):
    fp=os.path.join(P,path); real=hashlib.sha256(open(fp,'rb').read()).hexdigest() if os.path.exists(fp) else None
    print(f"  hash {path}: {'MATCH' if real==h else 'MISMATCH'}")
  d=os.path.join(P,'docs/planning')
  for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
    m=re.search(r'^revision: (\d+)',open(os.path.join(d,f)).read(),re.M); print(f"  fm {f}: revision={m and m.group(1)}")
