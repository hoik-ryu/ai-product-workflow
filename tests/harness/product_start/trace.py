import re,glob,sys,os
P=sys.argv[1];D={os.path.basename(f):open(f).read() for f in glob.glob(P+'/docs/planning/0[2-5]*.md')}
def ids(f,p): return set(re.findall(r'(?:^#+ *|^\| *)('+p+r'-\d{3})\b',D[f],re.M))
fr=ids('02-prd.md','FR');us=ids('03-user-stories.md','US');fl=ids('04-user-flows.md','FLOW');ac=ids('05-acceptance-criteria.md','AC')
allt=''.join(D.values())
print(f"FR {len(fr)} US {len(us)} FLOW {len(fl)} AC {len(ac)}",'| FR w/o US:',sorted(x for x in fr if x not in D['03-user-stories.md']),
 '| US w/o AC:',sorted(x for x in us if x not in D['05-acceptance-criteria.md']),'| US w/o FLOW:',sorted(x for x in us if x not in D['04-user-flows.md']),
 '| undefined:',sorted(set(re.findall(r'\b(?:FR|US|AC)-\d{3}\b',allt))-fr-us-ac | (set(re.findall(r'\bFLOW-\d{3}(?!-)\b',allt))-fl)))
