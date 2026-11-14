from sqlalchemy import String, Double, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class JobSnapshot(Base):
    """试验创建时的输入冻结快照；之后补发、更正或撤销都不会改动此快照。"""
    __tablename__ = 'job_snapshots'
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'), unique=True, index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    supplement_id: Mapped[int | None] = mapped_column(ForeignKey('dataset_supplements.id'), nullable=True)
    records: Mapped[list] = mapped_column(JSON, default=list)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[float] = mapped_column(Double)
