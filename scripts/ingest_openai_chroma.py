"""Resumable OpenAI question/PDF ingestion into the app's configured local Chroma.
No app model switch, old collection deletion, answer generation or secret logging.
"""
import os,json,csv,re,time,math,hashlib,shutil,datetime,threading,collections,email.utils
from pathlib import Path
import numpy as np
import tiktoken,pymupdf,psutil
from dotenv import dotenv_values
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
from chromadb.config import Settings
from openai import OpenAI
ROOT=Path(r'C:\Users\Playdata\Desktop\dograg');MODEL='text-embedding-3-small';DIM=1536;APP_TPM=1000000
ENC=tiktoken.get_encoding('cl100k_base')
def sha(data):return hashlib.sha256(data).hexdigest()
def file_sha(p):return sha(p.read_bytes())
def atomic(path,value):
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def normalize(text):
    text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]',' ',text)
    return '\n'.join(l for raw in text.splitlines() if (l:=re.sub(r'[ \t]{2,}',' ',raw).strip()))
def input_records():
    source=ROOT/'data/df.csv';health_hash=file_sha(source)
    with source.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    health=[]
    for n,row in enumerate(rows):
        text=row['qa.input'];assert text.strip()
        metadata={k:v or '' for k,v in row.items() if k and k!='qa.input'}
        metadata.update(source='data/df.csv',source_sha256=health_hash,source_row=n,source_id=row.get('',str(n)),source_record_json=json.dumps(row,ensure_ascii=False,sort_keys=True),embedding_model=MODEL,embedding_dimension=DIM,text_sha256=sha(text.encode('utf-8')),document_kind='health_question')
        health.append({'id':f'h_{health_hash[:12]}_{n:05d}','text':text,'metadata':metadata})
    splitter=RecursiveCharacterTextSplitter(chunk_size=1000,chunk_overlap=200,separators=['\n\n','\n','. ','다. ','; ',' ',''])
    pdfs=[];inventory=[];seen=set();raw_tokens=0
    years={'반려동물 복지실태와 개선과제.pdf':2024,'반려동물 산업 조사체계 진단 및 실태조사.pdf':2024,'반려동물+의료보험서비스+시장+진단+및+개선방안+연구_고은희_강하영.pdf':2025,'반려동물+장묘서비스+이용+실태조사_온라인거래조사팀.pdf':2022,'2025 한국 반려동물 보고서.pdf':2025}
    for path in sorted((ROOT/'data').rglob('*.pdf')):
        digest=file_sha(path);relative=str(path.relative_to(ROOT)).replace('\\','/')
        if digest in seen:inventory.append({'path':relative,'sha256':digest,'duplicate_file':True});continue
        seen.add(digest);start=len(pdfs)
        with pymupdf.open(path) as doc:
            for page_no,page in enumerate(doc,1):
                text=normalize(page.get_text('text',sort=True));raw_tokens+=len(ENC.encode(text))
                for ci,chunk in enumerate(splitter.split_text(text)):
                    chunk=chunk.strip();meta={'source':relative,'source_sha256':digest,'title':path.stem,'report_year':years.get(path.name,0),'year_provenance':'report identity checked in prior source review' if path.name in years else 'unknown','page':page_no,'page_start':page_no,'page_end':page_no,'chunk_index':ci,'chunk_size_chars':1000,'chunk_overlap_chars':200,'text_sha256':sha(chunk.encode('utf-8')),'embedding_model':MODEL,'embedding_dimension':DIM,'document_kind':'report_chunk'}
                    pdfs.append({'id':f'p_{digest[:12]}_{page_no:04d}_{ci:03d}','text':chunk,'metadata':meta})
            inventory.append({'path':relative,'sha256':digest,'pages':len(doc),'chunks':len(pdfs)-start,'duplicate_file':False})
    corpus_hash=sha(json.dumps([(r['path'],r['sha256']) for r in inventory],sort_keys=True,ensure_ascii=False).encode('utf-8'))
    return health,pdfs,health_hash,corpus_hash,inventory,raw_tokens
def fingerprints(client,names):
    result={}
    for name in names:
        c=client.get_collection(name,embedding_function=None);data=c.get(include=['documents','metadatas','embeddings']);h=hashlib.sha256()
        for i in sorted(range(len(data['ids'])),key=lambda n:data['ids'][n]):
            h.update(json.dumps([data['ids'][i],data['documents'][i],data['metadatas'][i]],sort_keys=True,ensure_ascii=False).encode('utf-8'));h.update(np.asarray(data['embeddings'][i],dtype=np.float32).tobytes())
        result[name]={'count':c.count(),'content_vector_sha256':h.hexdigest()}
    return result
class RateLimiter:
    def __init__(self):self.tpm=APP_TPM;self.rpm=3000;self.events=collections.deque();self.last_headers={};self.cool_until=0;self.remaining_tokens=None;self.remaining_requests=None;self.tokens_reset=0;self.requests_reset=0
    def headers(self,headers):
        for kind,attr in [('tokens','tpm'),('requests','rpm')]:
            value=headers.get('x-ratelimit-limit-'+kind)
            if value and value.isdigit():setattr(self,attr,min(APP_TPM,int(value)) if kind=='tokens' else int(value))
        self.last_headers={k:headers[k] for k in ['x-ratelimit-limit-tokens','x-ratelimit-remaining-tokens','x-ratelimit-reset-tokens','x-ratelimit-limit-requests','x-ratelimit-remaining-requests','x-ratelimit-reset-requests'] if k in headers}
        for kind in ['tokens','requests']:
            left=headers.get('x-ratelimit-remaining-'+kind);reset=headers.get('x-ratelimit-reset-'+kind)
            if left and left.isdigit():setattr(self,'remaining_'+kind,int(left))
            if reset:
                seconds=sum(float(number)*{'ms':.001,'s':1,'m':60,'h':3600}[unit] for number,unit in re.findall(r'(\d+(?:\.\d+)?)(ms|s|m|h)',reset))
                setattr(self,kind+'_reset',time.monotonic()+seconds)
    def acquire(self,tokens):
        while True:
            t=time.monotonic()
            while self.events and self.events[0][0]<=t-60:self.events.popleft()
            used=sum(x[1] for x in self.events)
            wait=max(0,self.cool_until-t)
            if self.remaining_tokens is not None and self.remaining_tokens<tokens and self.tokens_reset>t:wait=max(wait,self.tokens_reset-t)
            if self.remaining_requests is not None and self.remaining_requests<1 and self.requests_reset>t:wait=max(wait,self.requests_reset-t)
            if self.events and (used+tokens>self.tpm or len(self.events)>=self.rpm):wait=max(wait,self.events[0][0]+60.1-t)
            if tokens>self.tpm:raise RuntimeError('Batch exceeds detected token rate limit; resume with adaptive smaller batch')
            if wait<=0:self.events.append((t,tokens));return
            time.sleep(min(wait,5))
def main():
    start=time.perf_counter();cfg=dotenv_values(ROOT/'.env')
    if any(v for k,v in {**os.environ,**cfg}.items() if k.upper().startswith('CHROMA')):raise RuntimeError('Unexpected Chroma configuration; no alternate database fallback')
    key=cfg.get('OPENAI_API_KEY') or os.environ.get('OPENAI_API_KEY')
    if not key:raise RuntimeError('Existing OpenAI authentication missing')
    # The actual Streamlit code explicitly configures this persistence directory.
    db=ROOT/'data/chroma_db'
    if not db.exists():raise RuntimeError('Configured application Chroma directory missing; no fallback')
    health,pdfs,hh,ph,inventory,raw_tokens=input_records();records=health+pdfs
    assert len({r['id'] for r in records})==len(records)
    secrets=[v for k,v in cfg.items() if v and len(v)>=16 and ('KEY' in k or 'PASSWORD' in k)]
    pii=re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)\d{6}-[1-4]\d{6}(?!\d)|(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)')
    if any(pii.search(r['text']) or any(v in r['text'] for v in secrets) for r in health):raise RuntimeError('Health input privacy preflight found a candidate identifier; nothing sent')
    if any(any(v in r['text'] for v in secrets) for r in pdfs):raise RuntimeError('Report input credential preflight failed; nothing sent')
    for r in records:r['tokens']=len(ENC.encode(r['text']));assert 0<r['tokens']<=8192
    total_tokens=sum(r['tokens'] for r in records)
    if total_tokens*.02/1e6>1:raise RuntimeError('Cost exceeds authorized1USD review threshold')
    out=ROOT/'output'/f'openai_chroma_ingest_20261003_{hh[:8]}_{ph[:8]}';out.mkdir(parents=True,exist_ok=True);cache=out/'vector_batches';cache.mkdir(exist_ok=True)
    lock=ROOT/'output/.openai_chroma_ingest.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise RuntimeError('Another ingestion lock exists; refusing duplicate execution')
    os.write(fd,json.dumps({'pid':os.getpid(),'task':'authorized_openai_chroma_ingest','started':now()}).encode());os.close(fd)
    try:
        names={'health':f'pet_care_openai3small_1536_{hh[:12]}','reports':f'pet_reports_openai3small_1536_{ph[:12]}'}
        manifest_path=out/'manifest.json'
        manifest=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {'started_utc':now(),'model':MODEL,'dimension':DIM,'target_type':'local_persistent','target_path':str(db),'health_source_hash':hh,'pdf_corpus_hash':ph,'collections':names,'health_records':len(health),'pdf_chunks':len(pdfs),'pdf_inventory':inventory,'pdf_raw_tokens':raw_tokens,'health_question_tokens':sum(r['tokens'] for r in health),'pdf_chunk_tokens':sum(r['tokens'] for r in pdfs),'total_input_tokens_with_duplicates':total_tokens,'estimated_all_standard_usd':total_tokens*.02/1e6,'api_usage':[],'retries':[],'status':'prepared','app_tpm_cap':APP_TPM}
        atomic(manifest_path,manifest)
        index_path=out/'cache_index.json';index=json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {}
        old=ROOT/'eval/report_embedding_comparison_20261003';reused=0
        if not index:
            stats=json.loads((old/'openai_stats.json').read_text(encoding='utf-8'));chunks=list(map(json.loads,(old/'shared_chunks.jsonl').read_text(encoding='utf-8').splitlines()));vec=np.load(old/'openai_vectors.npy')
            assert stats['model']==MODEL and vec.shape==(len(chunks),DIM) and np.isfinite(vec).all()
            assert np.max(np.abs(np.linalg.norm(vec,axis=1)-1))<.001
            lookup={sha(c['text'].encode('utf-8')):n for n,c in enumerate(chunks)}
            chosen=[(r,lookup[r['metadata']['text_sha256']]) for r in pdfs if r['metadata']['text_sha256'] in lookup]
            selected=np.asarray([vec[n] for r,n in chosen],dtype=np.float32);np.save(cache/'reused_pdf.npy',selected)
            for n,(r,old_n) in enumerate(chosen):
                assert r['text']==chunks[old_n]['text']
                index[r['metadata']['text_sha256']]={'file':'reused_pdf.npy','row':n,'provenance':'verified_previous_same_model_dimension_exact_text'}
            reused=len(chosen);manifest['pdf_reused_records']=reused;manifest['pdf_reuse_source_vector_sha256']=file_sha(old/'openai_vectors.npy');atomic(index_path,index)
        unique={r['metadata']['text_sha256']:r for r in records}
        pending=[(h,r) for h,r in unique.items() if h not in index]
        expected=sum(r['tokens'] for _,r in pending)
        manifest.update(unique_embedding_inputs=len(unique),pending_api_inputs_at_start=len(pending),pending_api_tokens_at_start=expected,estimated_additional_standard_usd=expected*.02/1e6,health_duplicate_question_extra_rows=len(health)-len({r['text'] for r in health}))
        atomic(manifest_path,manifest)
        print(json.dumps({'stage':'prepared','health':len(health),'pdf_chunks':len(pdfs),'pdf_reused':manifest.get('pdf_reused_records',0),'new_api_inputs':len(pending),'new_api_tokens':expected,'estimated_new_usd':expected*.02/1e6,'target_type':'local_persistent','collections':names},ensure_ascii=False),flush=True)
        backup=out/'pre_ingest_chroma_backup'
        if not backup.exists():shutil.copytree(db,backup)
        client=chromadb.PersistentClient(path=str(db),settings=Settings(anonymized_telemetry=False))
        if 'old_collection_fingerprints' not in manifest:
            prior_names=[c.name for c in client.list_collections() if c.name not in names.values()];manifest['old_collection_fingerprints']=fingerprints(client,prior_names);atomic(manifest_path,manifest)
        cols={}
        for kind,name in names.items():
            cols[kind]=client.get_or_create_collection(name,embedding_function=None,metadata={'hnsw:space':'cosine','embedding_model':MODEL,'embedding_dimension':DIM,'source_sha256':hh if kind=='health' else ph,'ingest_schema':'question_only_and_page_local1000_200_v1'})
            assert cols[kind].metadata['embedding_model']==MODEL and cols[kind].metadata['source_sha256']==(hh if kind=='health' else ph)
        api=OpenAI(api_key=key,base_url='https://api.openai.com/v1',max_retries=0,timeout=120);limiter=RateLimiter();done=0
        while pending:
            batch=[];tokens=0;cap=min(100000,300000,max(8192,limiter.tpm//2))
            while pending and len(batch)<128 and tokens+pending[0][1]['tokens']<=cap:
                item=pending.pop(0);batch.append(item);tokens+=item[1]['tokens']
            assert batch and len(batch)<=2048 and tokens<=300000
            for attempt in range(6):
                limiter.acquire(tokens);t=time.perf_counter()
                try:
                    raw=api.embeddings.with_raw_response.create(model=MODEL,input=[r['text'] for h,r in batch],encoding_format='float');limiter.headers(raw.headers);res=raw.parse();break
                except Exception as error:
                    status=getattr(error,'status_code',None);headers=getattr(getattr(error,'response',None),'headers',{}) or {};limiter.headers(headers)
                    manifest['retries'].append({'class':type(error).__name__,'status_code':status,'attempt':attempt+1,'estimated_request_tokens':tokens,'timestamp':now()});atomic(manifest_path,manifest)
                    if status==429 and tokens>limiter.tpm:
                        pending=batch+pending;batch=[];break
                    if attempt==5 or (status is not None and status!=429 and status<500):raise RuntimeError(f'Embedding request failed: {type(error).__name__}, status={status}') from None
                    delay=min(60,2**(attempt+1));retry=headers.get('retry-after')
                    if retry:
                        try:delay=max(delay,float(retry))
                        except ValueError:
                            try:delay=max(delay,(email.utils.parsedate_to_datetime(retry)-datetime.datetime.now(datetime.timezone.utc)).total_seconds())
                            except Exception:pass
                    limiter.cool_until=time.monotonic()+max(delay,0)
                    print(json.dumps({'stage':'retry_wait','status_code':status,'wait_seconds':round(delay,2)}),flush=True)
            if not batch:continue
            assert len(res.data)==len(batch) and res.model==MODEL
            vectors=np.asarray([d.embedding for d in sorted(res.data,key=lambda d:d.index)],dtype=np.float32)
            assert vectors.shape==(len(batch),DIM) and np.isfinite(vectors).all() and np.max(np.abs(np.linalg.norm(vectors,axis=1)-1))<.001
            filename=f'api_{len(manifest["api_usage"]):04d}_{sha("".join(h for h,r in batch).encode())[:12]}.npy';np.save(cache/filename,vectors)
            for n,(h,r) in enumerate(batch):index[h]={'file':filename,'row':n,'provenance':'new_openai_api'}
            atomic(index_path,index)
            manifest['api_usage'].append({'inputs':len(batch),'predicted_tokens':tokens,'actual_prompt_tokens':res.usage.prompt_tokens,'actual_total_tokens':res.usage.total_tokens,'seconds':time.perf_counter()-t,'rate_limit_headers':limiter.last_headers,'model':res.model})
            done+=len(batch);manifest.update(status='embedding',completed_new_inputs=done,actual_api_tokens=sum(u['actual_prompt_tokens'] for u in manifest['api_usage']),actual_standard_usd=sum(u['actual_prompt_tokens'] for u in manifest['api_usage'])*.02/1e6,effective_token_cap=limiter.tpm,effective_request_cap=limiter.rpm)
            atomic(manifest_path,manifest)
            if len(manifest['api_usage'])%4==0 or not pending:print(json.dumps({'stage':'embedding','completed_new_inputs':done,'remaining':len(pending),'actual_tokens':manifest['actual_api_tokens'],'effective_TPM':limiter.tpm,'effective_RPM':limiter.rpm}),flush=True)
        def cached_vector(record):
            ref=index[record['metadata']['text_sha256']];return np.load(cache/ref['file'],mmap_mode='r')[ref['row']]
        for kind,rr in [('reports',pdfs),('health',health)]:
            for offset in range(0,len(rr),256):
                block=rr[offset:offset+256];v=np.stack([cached_vector(r) for r in block]);assert v.shape==(len(block),DIM) and np.isfinite(v).all()
                cols[kind].upsert(ids=[r['id'] for r in block],documents=[r['text'] for r in block],metadatas=[r['metadata'] for r in block],embeddings=v)
                manifest.update(status='persisting',**{kind+'_upserted':offset+len(block)});atomic(manifest_path,manifest)
            assert cols[kind].count()==len(rr)
            print(json.dumps({'stage':'persisted','collection':names[kind],'count':cols[kind].count()}),flush=True)
        # Fresh client handle and explicit vector queries; no default embedding model/API calls.
        reconnect=chromadb.PersistentClient(path=str(db),settings=Settings(anonymized_telemetry=False));qa={'reconnected':True,'collections':{},'old_collections_unchanged':False}
        for kind,rr in [('health',health),('reports',pdfs)]:
            c=reconnect.get_collection(names[kind],embedding_function=None);assert c.count()==len(rr);seen_ids=set();checked=0
            for offset in range(0,len(rr),256):
                block=rr[offset:offset+256];got=c.get(ids=[r['id'] for r in block],include=['documents','metadatas','embeddings']);mapping={id_:n for n,id_ in enumerate(got['ids'])}
                assert len(mapping)==len(block)
                for record in block:
                    n=mapping[record['id']];assert record['id'] not in seen_ids;seen_ids.add(record['id']);assert got['documents'][n]==record['text'] and got['metadatas'][n]==record['metadata'];v=np.asarray(got['embeddings'][n]);assert v.shape==(DIM,) and np.isfinite(v).all();assert np.allclose(v,cached_vector(record),atol=1e-7);checked+=1
            query_checks=[]
            for n in [0,len(rr)//2,len(rr)-1]:
                r=rr[n];ret=c.query(query_embeddings=np.asarray([cached_vector(r)]),n_results=3,include=['distances','metadatas']);assert r['id'] in ret['ids'][0] and min(ret['distances'][0])<1e-5;query_checks.append({'source_row_or_page':r['metadata'].get('source_row',r['metadata'].get('page')),'expected_id_found':True,'nearest_distance':float(min(ret['distances'][0]))})
            qa['collections'][kind]={'name':names[kind],'count':c.count(),'all_records_verified':checked,'dimension':DIM,'finite':True,'ids_unique':True,'documents_metadata_preserved':True,'vector_queries':query_checks}
        assert fingerprints(reconnect,list(manifest['old_collection_fingerprints']))==manifest['old_collection_fingerprints'];qa['old_collections_unchanged']=True
        assert file_sha(ROOT/'data/df.csv')==hh
        assert all(file_sha(ROOT/r['path'])==r['sha256'] for r in inventory)
        qa.update(source_hashes_unchanged=True,pdf_page_mapping_preserved=True,failed_records=0,retries=len(manifest['retries']),actual_api_tokens=sum(u['actual_prompt_tokens'] for u in manifest['api_usage']),elapsed_seconds=time.perf_counter()-start)
        atomic(out/'QA.json',qa);manifest.update(status='complete',completed_utc=now(),elapsed_seconds=time.perf_counter()-start,failed_records=0,actual_api_tokens=qa['actual_api_tokens'],actual_standard_usd=qa['actual_api_tokens']*.02/1e6,query_API_calls=0);atomic(manifest_path,manifest)
        print(json.dumps({'stage':'complete','collections':names,'counts':{k:v['count'] for k,v in qa['collections'].items()},'actual_tokens':qa['actual_api_tokens'],'actual_usd':manifest['actual_standard_usd'],'retries':qa['retries'],'old_collections_unchanged':True,'output_path':str(out)},ensure_ascii=False),flush=True)
    except Exception as error:
        if 'manifest' in locals():manifest.update(status='failed_resumable',error_class=type(error).__name__,error_status_code=getattr(error,'status_code',None),error_message='Sanitized; inspect checkpoint counts, no raw authentication/response/document logged');atomic(manifest_path,manifest)
        raise
    finally:
        try:
            if json.loads(lock.read_text())['pid']==os.getpid():lock.unlink()
        except FileNotFoundError:pass
if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'stage':'failed','error_class':type(error).__name__,'status_code':getattr(error,'status_code',None),'message':'Sanitized failure. No secrets or raw response emitted; resume from manifest.'}),flush=True);raise SystemExit(2)
