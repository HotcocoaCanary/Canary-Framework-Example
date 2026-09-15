"""Repositories — stateless query objects.

A repository never opens a session: the caller passes the one it must run in, so
a service can span several repositories inside a single transaction (see
``app/infra/db.py``).
"""
