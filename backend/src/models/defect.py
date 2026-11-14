from sqlalchemy import String, Double, JSON, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class DatasetSupplement(Base):
    """一次数据接入或补发投递的接收记录，保存本次四类处理结果数量。"""
    __tablename__ = 'dataset_supplements'
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'), index=True)
    kind: Mapped[str] = mapped_column(String(20), default='supplement')
    source: Mapped[str] = mapped_column(String(200), default='supplement.json')
    checksum: Mapped[str] = mapped_column(String(64), default='')
    received: Mapped[int] = mapped_column(Integer, default=0)
    added: Mapped[int] = mapped_column(Integer, default=0)
    corrected: Mapped[int] = mapped_column(Integer, default=0)
    revoked: Mapped[int] = mapped_column(Integer, default=0)
    ignored: Mapped[int] = mapped_column(Integer, default=0)
    actor: Mapped[str] = mapped_column(String(150), default='')
    created_at: Mapped[float] = mapped_column(Double)


class DefectRevision(Base):
    """缺陷点的修订台账；同一数据批次内缺陷编号 + 修订号唯一。"""
    __tablename__ = 'defect_revisions'
    __table_args__ = (
        UniqueConstraint('dataset_id', 'defect_id', 'revision', name='uq_defect_revision'),
        Index('ix_defect_revisions_dataset_defect', 'dataset_id', 'defect_id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'), index=True)
    supplement_id: Mapped[int | None] = mapped_column(ForeignKey('dataset_supplements.id'), nullable=True)
    defect_id: Mapped[str] = mapped_column(String(80))
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(12), default='active')
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[float] = mapped_column(Double)
