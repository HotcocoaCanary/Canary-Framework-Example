-- 容器首次初始化时执行；alembic 迁移里也有同样的语句，两条路径都能保证扩展就绪。
CREATE EXTENSION IF NOT EXISTS vector;
