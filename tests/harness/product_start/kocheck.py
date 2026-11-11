import sys,os,re
P=sys.argv[1]; exp={'01-discovery.md':['## 2. 문제 정의','## 11. 가정','## 12. 미결 질문'],'02-prd.md':['## 4. 기능 요구사항','## 7. 가정','## 9. 릴리스 기준'],
 '03-user-stories.md':['## 스토리 목록'],'04-user-flows.md':['## UI 플로우가 없는 스토리'],'05-acceptance-criteria.md':['## 추적 매트릭스','## 커버리지 점검']}
out=[]
for f,hs in exp.items():
  p=os.path.join(P,'docs/planning',f)
  if not os.path.exists(p): continue
  t=open(p).read(); miss=[h for h in hs if h not in t]
  eng=re.findall(r'^## (?:\d+\. )?(Problem|Assumptions|Open Questions|Functional Requirements|Traceability Matrix|Coverage Check|Stories)\s*$',t,re.M)
  out.append(f"{f}:{'OK' if not miss and not eng and len(re.findall(r'[가-힣]',t))>50 else 'NG miss='+str(miss)+' eng='+str(eng)}")
print('KOREAN',' '.join(out))
