import ast,hashlib,json,sys
from pathlib import Path
from types import SimpleNamespace
from lab.search_campaign import _single_factor_change
from lab.bounded_strategy import analyze_bounded_causal_strategy
r=Path(__file__).resolve().parent
n=int(sys.argv[1]);g=json.loads((r/f'r{n}-generation-current.json').read_text())['body'];c=g['candidate']
assert g['status']=='COMPLETED' and g['source']=='CODEX' and g['returned_strategy_count']==1
assert c['class_name']==f'DogeBidirectionalSmaR{n}'
reference=(r/'proposed-r1-template-reference.py').read_text()
if n==2: reference=reference.replace('DogeBidirectionalSmaR1','DogeBidirectionalSmaR2').replace('-0.20','-0.10')
code=c['code_text'];tree=ast.parse(code)
assert ast.dump(tree,include_attributes=False)==ast.dump(ast.parse(reference),include_attributes=False),'frozen AST mismatch'
assert len([x for x in tree.body if isinstance(x,ast.ClassDef)])==1
sha=hashlib.sha256(code.encode()).hexdigest();assert sha==c['code_sha256']
analysis=analyze_bounded_causal_strategy(code,c['class_name'],expected_timeframe='1d')
assert analysis.startup_candle_count==90 and analysis.max_lookback==30
if n==2:
 p=json.loads((r/'r1-generation-current.json').read_text())['body']['candidate']
 assert g['input']['parent_candidate_id']==p['id']
 assert _single_factor_change(SimpleNamespace(code_text=p['code_text'],class_name=p['class_name']),SimpleNamespace(code_text=code,class_name=c['class_name']),'stoploss')
report={'status':'FROZEN_CODE_REVIEW_PASS','round':n,'generation_id':g['id'],'candidate_id':c['id'],'class_name':c['class_name'],'code_sha256':sha,'reference_sha256':hashlib.sha256(reference.encode()).hexdigest(),'exact_ast':True,'unique_class':True,'startup_candle_count':90,'maximum_lookback':30,'single_factor': 'stoploss' if n==2 else None,'parent_candidate_id':g['input']['parent_candidate_id']}
(r/f'r{n}-code-review.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
