"""refactor: rename kb_nodes to kb_files, merge kb_file_records, remove parse_tasks, add collection_items

Revision ID: b1c2d3e4f5a6
Revises: a27a6902544b
Create Date: 2026-05-26 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'a27a6902544b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop parse_tasks table (no business value)
    op.drop_index(op.f('ix_parse_tasks_kb_id'), table_name='parse_tasks')
    op.drop_table('parse_tasks')

    # 2. Drop kb_file_records table (merged into kb_files)
    op.drop_table('kb_file_records')

    # 3. Rename kb_nodes → kb_files
    op.rename_table('kb_nodes', 'kb_files')
    op.execute(sa.text("ALTER INDEX ix_kb_nodes_kb_id RENAME TO ix_kb_files_kb_id"))

    # 4. Rename columns: node_type → file_type, size → file_size
    op.alter_column('kb_files', 'node_type', new_column_name='file_type')
    op.alter_column('kb_files', 'size', new_column_name='file_size',
                    existing_type=sa.BigInteger(), existing_nullable=True)

    # 5. Drop oss_key and full_path columns
    op.drop_column('kb_files', 'oss_key')
    op.drop_column('kb_files', 'full_path')

    # 6. Add status, parsed_text, error_msg columns
    op.add_column('kb_files', sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=True))
    op.add_column('kb_files', sa.Column('parsed_text', sa.Text(), nullable=True))
    op.add_column('kb_files', sa.Column('error_msg', sa.Text(), nullable=True))

    # 7. Drop page column from kb_chunks
    op.drop_column('kb_chunks', 'page')

    # 8. Add indexes to kb_chunks
    op.create_index('idx_chunks_kb', 'kb_chunks', ['kb_id'])
    op.create_index('idx_chunks_file', 'kb_chunks', ['file_id'])

    # 9. Create collection_items table
    op.create_table('collection_items',
                    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
                    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
                    sa.Column('url', sa.Text(), nullable=False),
                    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
                    sa.Column('content', sa.Text(), nullable=True),
                    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False,
                              server_default='pending'),
                    sa.Column('is_imported', sa.Boolean(), nullable=False, server_default=sa.text('false')),
                    sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
                    sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
                    sa.PrimaryKeyConstraint('id')
                    )
    op.create_index('idx_ci_user', 'collection_items', ['user_id', sa.text('created_at DESC')])
    op.create_index('idx_ci_status', 'collection_items', ['status'])
    op.create_index('idx_ci_imported', 'collection_items', ['user_id', 'is_imported'])


def downgrade() -> None:
    # 9. Drop collection_items table
    op.drop_index('idx_ci_imported', table_name='collection_items')
    op.drop_index('idx_ci_status', table_name='collection_items')
    op.drop_index('idx_ci_user', table_name='collection_items')
    op.drop_table('collection_items')

    # 8. Drop indexes from kb_chunks
    op.drop_index('idx_chunks_file', table_name='kb_chunks')
    op.drop_index('idx_chunks_kb', table_name='kb_chunks')

    # 7. Re-add page column to kb_chunks
    op.add_column('kb_chunks', sa.Column('page', sa.Integer(), nullable=True))

    # 6. Drop status, parsed_text, error_msg columns
    op.drop_column('kb_files', 'error_msg')
    op.drop_column('kb_files', 'parsed_text')
    op.drop_column('kb_files', 'status')

    # 5. Re-add oss_key and full_path
    op.add_column('kb_files', sa.Column('full_path', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=False,
                                        server_default=''))
    op.add_column('kb_files', sa.Column('oss_key', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True))

    # 4. Rename columns back
    op.alter_column('kb_files', 'file_size', new_column_name='size',
                    existing_type=sa.BigInteger(), existing_nullable=True)
    op.alter_column('kb_files', 'file_type', new_column_name='node_type')

    # 3. Rename kb_files back to kb_nodes
    op.execute(sa.text("ALTER INDEX ix_kb_files_kb_id RENAME TO ix_kb_nodes_kb_id"))
    op.rename_table('kb_files', 'kb_nodes')

    # 2. Re-create kb_file_records table
    op.create_table('kb_file_records',
                    sa.Column('file_id', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
                    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
                    sa.Column('parsed_text', sa.Text(), nullable=True),
                    sa.Column('error_msg', sa.Text(), nullable=True),
                    sa.Column('parse_task_id', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False),
                    sa.PrimaryKeyConstraint('file_id')
                    )

    # 1. Re-create parse_tasks table
    op.create_table('parse_tasks',
                    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
                    sa.Column('kb_id', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
                    sa.Column('created_by', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False),
                    sa.PrimaryKeyConstraint('id')
                    )
    op.create_index(op.f('ix_parse_tasks_kb_id'), 'parse_tasks', ['kb_id'], unique=False)
