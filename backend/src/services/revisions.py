"""缺陷补发的修订号解析与内容规范化。

补发按「缺陷编号 + 修订号」定位：修订号更大者替换旧版；同一修订号内容不一致
视为投递冲突，整次补发拒绝。撤销作为一条修订状态保存，撤销点不进入分析。
"""
import math

from src.utils.serialization import checksum


class RevisionInvalid(ValueError):
    """投递记录字段不合法。"""


class RevisionConflict(ValueError):
    """同一缺陷编号与修订号出现不同内容，或同一补发内自相矛盾。"""


TRUE_WORDS = {'true', '1', 'yes', 'y', '是', '撤销', '已撤销', 'revoked', 'revoke'}
FALSE_WORDS = {'false', '0', 'no', 'n', '否', '正常', '有效', 'active', 'normal'}


def _flag_from_status(value, index):
    text = str(value).strip().lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    raise RevisionInvalid(f'第 {index+1} 行撤销标记无法识别')


def _bool(value, index):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value in (0, 1):
            return bool(value)
        raise RevisionInvalid(f'第 {index+1} 行撤销标记必须为布尔值')
    if isinstance(value, str):
        text = value.strip().lower()
        if text in TRUE_WORDS:
            return True
        if text in FALSE_WORDS:
            return False
    raise RevisionInvalid(f'第 {index+1} 行撤销标记必须为布尔值')


def _number(value, label, index):
    if isinstance(value, bool) or value is None or value == '':
        raise RevisionInvalid(f'第 {index+1} 行 {label} 必须为有限数值')
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RevisionInvalid(f'第 {index+1} 行 {label} 必须为有限数值') from exc
    if not math.isfinite(number):
        raise RevisionInvalid(f'第 {index+1} 行 {label} 必须为有限数值')
    return number


def normalize(row, index=0):
    """把一行投递记录规范成可比较、可入库的修订条目。"""
    if not isinstance(row, dict):
        raise RevisionInvalid(f'第 {index+1} 行必须是 JSON 对象')
    raw_id = row.get('defect_id')
    if raw_id is None or isinstance(raw_id, (dict, list, bool)):
        raise RevisionInvalid(f'第 {index+1} 行缺少缺陷编号 defect_id')
    defect_id = str(raw_id).strip()
    if not defect_id:
        raise RevisionInvalid(f'第 {index+1} 行缺少缺陷编号 defect_id')
    if len(defect_id) > 80:
        raise RevisionInvalid(f'第 {index+1} 行缺陷编号不得超过 80 个字符')

    raw_revision = row.get('revision', 1)
    if isinstance(raw_revision, bool):
        raise RevisionInvalid(f'第 {index+1} 行修订号必须为不小于 1 的整数')
    try:
        revision_value = float(raw_revision)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RevisionInvalid(f'第 {index+1} 行修订号必须为不小于 1 的整数') from exc
    if not math.isfinite(revision_value) or revision_value != int(revision_value) or revision_value < 1:
        raise RevisionInvalid(f'第 {index+1} 行修订号必须为不小于 1 的整数')
    revision = int(revision_value)

    if 'revoked' in row and row.get('revoked') is not None:
        revoked = _bool(row.get('revoked'), index)
    elif row.get('status') is not None:
        revoked = _flag_from_status(row.get('status'), index)
    elif row.get('action') is not None:
        revoked = _flag_from_status(row.get('action'), index)
    else:
        revoked = False

    entry = {'defect_id': defect_id, 'revision': revision, 'revoked': revoked}
    if revoked:
        return entry

    mileage = _number(row.get('mileage_km'), '线路里程(km)', index)
    if mileage < 0:
        raise RevisionInvalid(f'第 {index+1} 行线路里程不得为负数')
    lateral = _number(row.get('lateral_mm'), '横向偏差(mm)', index)
    severity_value = _number(row.get('severity'), '复核等级(1~5)', index)
    if severity_value != int(severity_value) or not 1 <= severity_value <= 5:
        raise RevisionInvalid(f'第 {index+1} 行复核等级须为 1~5 的整数')
    entry.update({'mileage_km': mileage, 'lateral_mm': lateral, 'severity': int(severity_value)})
    return entry


def content_hash(entry):
    return checksum(entry)


def record_of(entry):
    """修订条目中参与分析的字段，不包含修订号与撤销标记。"""
    return {key: entry[key] for key in ('defect_id', 'mileage_km', 'lateral_mm', 'severity')}
