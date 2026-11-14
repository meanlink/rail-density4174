from fastapi import HTTPException
from sqlalchemy import select
from src.models import Dataset, DatasetSupplement, DefectRevision
from src.services.revisions import RevisionConflict, normalize, content_hash, record_of
from src.utils.serialization import checksum
import time


def _validate(records):
    """解析并校验整次投递；任何一行不合法都会拒绝整次投递。"""
    entries = [normalize(row, index) for index, row in enumerate(records)]
    seen = {}
    for index, entry in enumerate(entries):
        key = (entry['defect_id'], entry['revision'])
        if key in seen:
            first = seen[key]
            if entries[first] != entry:
                raise RevisionConflict(
                    f'第 {index+1} 行与第 {first+1} 行缺陷编号 {entry["defect_id"]} 的修订号 {entry["revision"]} 内容冲突')
        else:
            seen[key] = index
    return entries


def _ledger(db, dataset_id):
    pairs, latest = {}, {}
    for row in db.scalars(select(DefectRevision).where(DefectRevision.dataset_id == dataset_id)):
        pairs[(row.defect_id, row.revision)] = row
        held = latest.get(row.defect_id)
        if held is None or (row.revision, row.id) > (held.revision, held.id):
            latest[row.defect_id] = row
    return pairs, latest


def _plan(entries, pairs, latest):
    """无副作用地模拟整次补发，返回每条记录的处理动作。

    动作：added=新增、corrected=更正、revoked=撤销、ignored=重复或晚到旧记录。
    """
    pair_hashes = {key: row.content_hash for key, row in pairs.items()}
    latest_state = {key: (row.revision, row.state, row.content_hash) for key, row in latest.items()}
    # 同一次投递内同一缺陷出现多个修订时，只有最高修订生效，其余按晚到旧记录忽略。
    highest = {}
    for entry in entries:
        held = highest.get(entry['defect_id'])
        if held is None or entry['revision'] > held:
            highest[entry['defect_id']] = entry['revision']
    actions = []
    for entry in entries:
        key = (entry['defect_id'], entry['revision'])
        digest = content_hash(entry)
        state = 'revoked' if entry['revoked'] else 'active'
        if key in pair_hashes:
            if pair_hashes[key] != digest:
                raise RevisionConflict(
                    f'缺陷编号 {entry["defect_id"]} 的修订号 {entry["revision"]} 与已接收内容冲突')
            actions.append('ignored')
            continue
        if entry['revision'] < highest[entry['defect_id']]:
            actions.append('ignored')
            continue
        held = latest_state.get(entry['defect_id'])
        if held is None:
            pair_hashes[key] = digest
            latest_state[entry['defect_id']] = (entry['revision'], state, digest)
            actions.append('revoked' if entry['revoked'] else 'added')
            continue
        revision, previous_state, _ = held
        if entry['revision'] < revision:
            # 晚到的旧记录：不新增、不复活撤销点，原批次保持不变
            actions.append('ignored')
            continue
        if entry['revision'] == revision:
            # 同号只有在内容完全一致时才走到这里，按重复投递忽略
            actions.append('ignored')
            continue
        pair_hashes[key] = digest
        latest_state[entry['defect_id']] = (entry['revision'], state, digest)
        if entry['revoked']:
            actions.append('revoked')
        elif previous_state == 'revoked':
            actions.append('added')
        else:
            actions.append('corrected')
    return actions


def _counts(actions):
    counts = {'added': 0, 'corrected': 0, 'revoked': 0, 'ignored': 0}
    for action in actions:
        counts[action] += 1
    return counts


def create(db, data):
    name=data.name.strip()
    if len(name)<2: raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    if db.scalar(select(Dataset).where(Dataset.name==name)):
        raise HTTPException(409, '该数据批次名已存在，请修改名称')
    try:
        entries = _validate(data.records)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    now = time.time()
    actions = _plan(entries, {}, {})
    d=Dataset(name=name, source=data.source, records=[], checksum=checksum([]), created_at=now, updated_at=now)
    db.add(d); db.flush()
    log = DatasetSupplement(dataset_id=d.id, kind='intake', source=data.source,
                            checksum=checksum(data.records), received=len(entries), actor='', created_at=now)
    db.add(log); db.flush()
    for entry, action in zip(entries, actions):
        if action == 'ignored':
            continue
        db.add(DefectRevision(dataset_id=d.id, supplement_id=log.id, defect_id=entry['defect_id'],
                              revision=entry['revision'], state='revoked' if entry['revoked'] else 'active',
                              payload=entry, content_hash=content_hash(entry), created_at=now))
    counts = _counts(actions)
    log.added, log.corrected, log.revoked, log.ignored = counts['added'], counts['corrected'], counts['revoked'], counts['ignored']
    records, _ = _active_records(db, d.id)
    d.records = records
    d.checksum = checksum(records)
    db.flush()
    return d


def _active_records(db, dataset_id):
    _, latest = _ledger(db, dataset_id)
    records = [record_of(row.payload) for row in latest.values() if row.state == 'active']
    return sorted(records, key=lambda row: (row['mileage_km'], row['defect_id'])), latest


def ensure_ledger(db, dataset):
    """为功能上线前已存在的批次补齐修订台账，避免首次补发把旧点重复计入。"""
    if db.scalar(select(DefectRevision.id).where(DefectRevision.dataset_id == dataset.id).limit(1)):
        return
    if not dataset.records:
        return
    now = time.time()
    log = DatasetSupplement(dataset_id=dataset.id, kind='intake', source=dataset.source,
                            checksum=dataset.checksum, received=len(dataset.records),
                            added=0, actor='system', created_at=dataset.created_at or now)
    db.add(log); db.flush()
    seen = set()
    count = 0
    for row in dataset.records:
        try:
            entry = normalize(row)
        except ValueError:
            continue
        if entry['defect_id'] in seen:
            continue
        seen.add(entry['defect_id'])
        db.add(DefectRevision(dataset_id=dataset.id, supplement_id=log.id, defect_id=entry['defect_id'],
                              revision=entry['revision'], state='revoked' if entry['revoked'] else 'active',
                              payload=entry, content_hash=content_hash(entry), created_at=log.created_at))
        if not entry['revoked']:
            count += 1
    log.added = count
    log.revoked = len(seen) - count
    db.flush()


def freeze_dataset(db, dataset, supplement_id=None):
    """为补发前已创建的试验冻结输入快照；重复调用是幂等的。"""
    from src.models import Job, JobSnapshot
    from copy import deepcopy
    current = list(dataset.records)
    digest = checksum(current)
    frozen = {row.job_id for row in db.scalars(select(JobSnapshot).where(JobSnapshot.dataset_id == dataset.id))}
    for job in db.scalars(select(Job).where(Job.dataset_id == dataset.id)):
        if job.id in frozen:
            continue
        db.add(JobSnapshot(job_id=job.id, dataset_id=dataset.id, supplement_id=supplement_id,
                           records=deepcopy(current), checksum=digest, created_at=time.time()))


def supplement(db, dataset_id, data, actor=''):
    """按缺陷编号与修订号接收补发。

    更高修订号替换旧版；撤销点退出分析；重复投递不新增；
    晚到旧记录不能复活撤销点；同编号同修订内容冲突时整次拒绝且原批次不变。
    """
    d = db.get(Dataset, dataset_id)
    if not d:
        raise HTTPException(404, '数据批次不存在')
    try:
        entries = _validate(data.records)
    except RevisionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    pairs, latest = _ledger(db, dataset_id)
    if not pairs:
        ensure_ledger(db, d)
        pairs, latest = _ledger(db, dataset_id)
    try:
        actions = _plan(entries, pairs, latest)
    except RevisionConflict as exc:
        raise HTTPException(409, str(exc)) from exc

    # 任何写入之前，先冻结已有试验的输入；补发不会影响它们的计算数据。
    previous_log = db.scalar(select(DatasetSupplement).where(DatasetSupplement.dataset_id == d.id).order_by(DatasetSupplement.id.desc()))
    freeze_dataset(db, d, previous_log.id if previous_log else None)

    now = time.time()
    log = DatasetSupplement(dataset_id=d.id, kind='supplement', source=data.source,
                            checksum=checksum(data.records), received=len(entries),
                            actor=actor, created_at=now)
    db.add(log); db.flush()
    for entry, action in zip(entries, actions):
        if action == 'ignored':
            continue
        db.add(DefectRevision(dataset_id=d.id, supplement_id=log.id, defect_id=entry['defect_id'],
                              revision=entry['revision'], state='revoked' if entry['revoked'] else 'active',
                              payload=entry, content_hash=content_hash(entry), created_at=now))
    counts = _counts(actions)
    log.added, log.corrected, log.revoked, log.ignored = counts['added'], counts['corrected'], counts['revoked'], counts['ignored']
    db.flush()
    records, _ = _active_records(db, d.id)
    d.records = records
    d.checksum = checksum(records)
    d.updated_at = now
    db.flush()
    return d, log
