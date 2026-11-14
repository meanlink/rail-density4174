import time
from copy import deepcopy
from fastapi import HTTPException
from redis import Redis
from sqlalchemy import select
from src.config.settings import REDIS_URL
from src.models import Dataset, Job, JobSnapshot, DatasetSupplement
from src.services.business import metadata
from src.utils.serialization import checksum


def create(db, data, user):
    d=db.get(Dataset,data.dataset_id)
    if not d: raise HTTPException(404,'数据批次不存在')
    allowed={p['key']:p for p in metadata().get('parameters',[])}
    if set(data.params)-set(allowed): raise HTTPException(422,'包含未知分析参数')
    params={k:p['default'] for k,p in allowed.items()}
    params.update(data.params)
    for key,p in allowed.items():
        v=params[key]
        if p['type']=='number':
            try:
                v=float(v)
                if not (p.get('min',-1e9)<=v<=p.get('max',1e9)): raise ValueError()
                params[key]=v
            except (ValueError,TypeError): raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options',[])]:
            raise HTTPException(422,f'{p["label"]} 不是有效选项')
    now=time.time()
    j=Job(name=data.name, dataset_id=data.dataset_id, params=params, created_by=user.id, created_at=now, status='queued')
    db.add(j); db.flush()
    latest=db.scalar(select(DatasetSupplement).where(DatasetSupplement.dataset_id==d.id).order_by(DatasetSupplement.id.desc()))
    frozen=deepcopy(d.records)
    db.add(JobSnapshot(job_id=j.id, dataset_id=d.id, supplement_id=latest.id if latest else None,
                       records=frozen, checksum=checksum(frozen), created_at=now))
    db.flush()
    return j

def enqueue(job_id):
    try:
        r=Redis.from_url(REDIS_URL); r.rpush('analysis:queue',job_id); r.close()
    except Exception:
        pass # SQL queued status is the durable fallback


def snapshot_dict(snapshot):
    return {'id':snapshot.id,'job_id':snapshot.job_id,'dataset_id':snapshot.dataset_id,
            'supplement_id':snapshot.supplement_id,'rows':len(snapshot.records),
            'checksum':snapshot.checksum,'created_at':snapshot.created_at}
