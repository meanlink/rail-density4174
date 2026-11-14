from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.config.database import get_db
from src.models import Dataset, DatasetSupplement, DefectRevision
from src.schemas.dataset import DatasetInput, SupplementInput
from src.middlewares.auth import current_user, can_write
from src.services import datasets
from src.services.audit import record
from src.utils.serialization import dataset_dict, supplement_dict
router=APIRouter(prefix='/datasets')
@router.get('')
def listing(db=Depends(get_db),u=Depends(current_user)):
    return [dataset_dict(d) for d in db.scalars(select(Dataset).order_by(Dataset.id.desc()))]
@router.post('',status_code=201)
def create(data:DatasetInput,db=Depends(get_db),u=Depends(can_write)):
    d=datasets.create(db,data); record(db,u.email,'dataset.create',{'id':d.id,'rows':len(d.records)})
    db.commit(); return dataset_dict(d)
@router.get('/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    d=db.get(Dataset,id)
    if not d:raise HTTPException(404,'数据批次不存在')
    intake=db.scalar(select(DatasetSupplement).where(DatasetSupplement.dataset_id==id,DatasetSupplement.kind=='intake').order_by(DatasetSupplement.id))
    supplements=[supplement_dict(s) for s in db.scalars(select(DatasetSupplement).where(DatasetSupplement.dataset_id==id).order_by(DatasetSupplement.id.desc()))]
    return {**dataset_dict(d),'records':d.records,'intake':supplement_dict(intake) if intake else None,'supplements':supplements}
@router.post('/{id}/supplements',status_code=201)
def supplement(id:int,data:SupplementInput,db=Depends(get_db),u=Depends(can_write)):
    try:
        d,log=datasets.supplement(db,id,data,actor=u.email)
        record(db,u.email,'dataset.supplement',{'id':d.id,'supplement':log.id,'received':log.received,'added':log.added,'corrected':log.corrected,'revoked':log.revoked,'ignored':log.ignored})
        db.commit()
    except IntegrityError:
        # 并发投递同一编号同修订：数据库唯一约束兜底，整次回滚，原批次不变
        db.rollback()
        raise HTTPException(409,'该次补发与并发接收的修订冲突，请刷新后重试')
    return {**dataset_dict(d),'supplement':supplement_dict(log)}
@router.get('/{id}/revisions')
def revisions(id:int,db=Depends(get_db),u=Depends(current_user)):
    if not db.get(Dataset,id):raise HTTPException(404,'数据批次不存在')
    rows=db.scalars(select(DefectRevision).where(DefectRevision.dataset_id==id).order_by(DefectRevision.defect_id,DefectRevision.revision))
    return [{'defect_id':r.defect_id,'revision':r.revision,'state':r.state,'payload':r.payload,'content_hash':r.content_hash,'supplement_id':r.supplement_id,'created_at':r.created_at} for r in rows]
