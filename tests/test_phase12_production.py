import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock
from app.database.models import Item, ItemStatus, ItemAnalysis, AnalysisStatus, CategoryEnum, Source
from app.services.digest_service import DigestService, SECTION_MAP, AI_KEYWORDS

BASE = Path(__file__).resolve().parent.parent

def _load_yaml(p):
    with open(p) as f:
        lines = [l for l in f if l.strip() and not l.strip().startswith('#')]
    r = {'sources': []}; cs = None
    for l in lines:
        s = l.strip()
        if s.startswith('- id:'):
            if cs: r['sources'].append(cs)
            cs = {'id': s.split(':',1)[1].strip()}
        elif cs and ':' in s:
            k,_,v = s.partition(':'); k=k.strip(); v=v.strip()
            if v.startswith('[') and v.endswith(']'):
                v = [x.strip().strip(chr(39)+chr(34)) for x in v[1:-1].split(',') if x.strip()]
            elif v=='true': v=True
            elif v=='false': v=False
            elif v.isdigit(): v=int(v)
            else: v=v.strip(chr(39)+chr(34))
            cs[k]=v
    if cs: r['sources'].append(cs)
    return r

def test_yaml_exists():
    assert (BASE/'config'/'news_sources.yaml').exists()
def test_yaml_structure():
    d=_load_yaml(BASE/'config'/'news_sources.yaml')
    for s in d['sources']:
        for f in ['id','name','feed_url','language','source_type','enabled']:
            assert f in s
def test_international():
    d=_load_yaml(BASE/'config'/'news_sources.yaml')
    assert len([s for s in d['sources'] if s.get('language')=='en'])>=5
def test_russian():
    d=_load_yaml(BASE/'config'/'news_sources.yaml')
    assert len([s for s in d['sources'] if s.get('language')=='ru'])>=2
def test_build():
    svc=DigestService(MagicMock())
    svc.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value=[]
    r=svc.build_digest(limit=10)
    assert 'sections' in r and 'stats' in r
def test_render():
    svc=DigestService(MagicMock())
    d={'sections':{'main':[{'title':'T','url':'http://x','source':'S','published_at':'2026','summary_ru':'Sum','what_is_new':'N','why_important':'W','tags':['ai']}]},'stats':{'total_analyzed':10,'total_in_digest':1}}
    md=svc.render_markdown(d)
    assert '# AI Radar' in md
def test_section_map():
    for c in CategoryEnum: assert c.value in SECTION_MAP
def test_keywords():
    assert len(AI_KEYWORDS)>10
def test_dedup():
    from app.pipeline.url_normalizer import canonicalize_url
    assert 'utm_source' not in canonicalize_url('https://x.com/a?utm_source=t')
def test_cli():
    assert (BASE/'scripts'/'latest_digest.py').exists()
def test_readonly():
    import inspect
    src=inspect.getsource(DigestService)
    assert '.add(' not in src and '.commit(' not in src
