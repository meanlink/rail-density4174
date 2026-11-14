from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models


def _columns(connection, table):
    return {column['name'] for column in inspect(connection).get_columns(table)}


def _additive_columns():
    """已有部署只做加法迁移：新增缺陷修订台账相关字段，不改动既有数据。"""
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        if 'datasets' not in tables:
            return
        columns = _columns(connection, 'datasets')
        if 'updated_at' not in columns:
            numeric = 'DOUBLE' if engine.dialect.name == 'sqlite' else 'DOUBLE PRECISION'
            connection.execute(text(f'ALTER TABLE datasets ADD COLUMN updated_at {numeric} NULL'))


def migrate():
    Base.metadata.create_all(engine)
    _additive_columns()


if __name__ == '__main__':
    migrate()
